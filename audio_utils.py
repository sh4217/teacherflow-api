from fastapi import UploadFile, HTTPException
from typing import Optional, Tuple, List
from pathlib import Path
import tempfile
import mutagen
import shutil

# Constants
MAX_AUDIO_SIZE_BYTES = 10 * 1024 * 1024  # 10MB
ALLOWED_AUDIO_TYPES = {'audio/mpeg', 'audio/mp3'}
MAX_DURATION_SECONDS = 300  # 5 minutes

def get_audio_duration(file_path: str) -> float:
    """Get the duration of an audio file in seconds.
    
    Args:
        file_path (str): Path to the audio file
        
    Returns:
        float: Duration in seconds, or 5.0 if duration cannot be determined
    """
    try:
        audio = mutagen.File(file_path)
        if audio is None:
            return 5.0  # Default duration if file can't be read
        return float(audio.info.length)
    except Exception:
        return 5.0  # Default duration if there's an error

def validate_audio_file(file: UploadFile) -> Tuple[bool, Optional[str]]:
    """Validate audio file format, size, and integrity.
    
    Args:
        file (UploadFile): The uploaded audio file to validate
        
    Returns:
        Tuple containing:
        - bool: True if file is valid, False otherwise
        - Optional[str]: Error message if validation fails, None if successful
    """
    try:
        # Check content type
        if file.content_type not in ALLOWED_AUDIO_TYPES:
            return False, f"Invalid audio format. Allowed types: {', '.join(ALLOWED_AUDIO_TYPES)}"
        
        # Check file size using chunks to avoid loading entire file
        total_size = 0
        chunk_size = 8192  # 8KB chunks
        
        while True:
            chunk = file.file.read(chunk_size)
            if not chunk:
                break
            total_size += len(chunk)
            if total_size > MAX_AUDIO_SIZE_BYTES:
                file.file.seek(0)
                return False, f"Audio file too large. Maximum size: {MAX_AUDIO_SIZE_BYTES/1024/1024}MB"
        
        file.file.seek(0)  # Reset file pointer
        
        # Stream to temporary file for format validation
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_file:
            file.file.seek(0)
            shutil.copyfileobj(file.file, temp_file)
            temp_path = temp_file.name
        
        try:
            # Validate audio file integrity
            audio = mutagen.File(temp_path)
            if audio is None:
                return False, "Invalid audio file format or corrupted file"
            
            # Get duration if available
            duration = getattr(audio.info, 'length', None)
            if duration and duration > MAX_DURATION_SECONDS:
                return False, f"Audio file too long. Maximum duration: {MAX_DURATION_SECONDS/60} minutes"
                
            return True, None
        finally:
            Path(temp_path).unlink()
            file.file.seek(0)  # Reset file pointer again
            
    except Exception as e:
        return False, f"Error validating audio: {str(e)}" 

async def process_audio_files(audio_files: List[UploadFile]) -> Tuple[List[str], List[str]]:
    """Process uploaded audio files and return paths to temp files
    
    Args:
        audio_files: List of uploaded audio files
        
    Returns:
        Tuple containing:
        - List of paths to processed audio files
        - List of temporary files to clean up
        
    Raises:
        HTTPException: If any audio file is invalid
    """
    audio_paths = []
    temp_files = []
    
    for audio in audio_files:
        is_valid, error_message = validate_audio_file(audio)
        if not is_valid:
            print(f"=== DEBUG: Audio file invalid: {error_message} ===")
            raise HTTPException(status_code=400, detail=error_message)
        
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_audio:
            shutil.copyfileobj(audio.file, temp_audio)
            audio_paths.append(temp_audio.name)
            temp_files.append(temp_audio.name)
            print(f"=== DEBUG: Wrote temp audio file to {temp_audio.name} ===")
    
    return audio_paths, temp_files 