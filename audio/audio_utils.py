from fastapi import UploadFile
from typing import Optional, Tuple, List
from pathlib import Path
import tempfile
import mutagen
import shutil
from ai.ai_utils import generate_speech
from models import AudioFile

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

async def generate_audio(audio_dir: Path, script_contents: List[str]) -> List[AudioFile]:
    """
    Generate audio files for each scene and return their paths and durations.
    
    Args:
        audio_dir: Directory where audio files will be saved
        script_contents: List of scene text content
        
    Returns:
        List of AudioFile objects containing path and duration
        
    Raises:
        Exception: If audio generation fails for any scene
    """
    audio_files = []
    for i, scene_content in enumerate(script_contents):
        audio_filename = f"scene_{i + 1}.mp3"
        audio_path = audio_dir / audio_filename
        
        try:
            success = await generate_speech(scene_content, audio_path)
            if success:
                duration = get_audio_duration(str(audio_path))
                audio_files.append(AudioFile(
                    path=str(audio_path),
                    duration=duration
                ))
                print(f"=== DEBUG: Generated audio file: {audio_filename} with duration {duration}s ===")
            else:
                raise Exception(f"Failed to generate audio for scene {i + 1}")
        except Exception as e:
            print(f"=== ERROR: Audio generation failed for scene {i + 1}: {str(e)} ===")
            raise
    
    return audio_files
