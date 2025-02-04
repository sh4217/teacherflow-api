from pathlib import Path
from typing import Optional, Tuple
from uuid import uuid4
import tempfile
import subprocess
import shutil
import re
import os
from dotenv import load_dotenv
from fastapi import HTTPException

from audio.audio_utils import generate_and_prepare_audio_files, get_audio_duration
from ai.ai_utils import generate_concepts, generate_system_design, generate_text

# Load environment variables
load_dotenv()

# Debug mode setting
DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"

# Constants
VIDEOS_DIR = Path("videos")
AUDIO_DIR = Path("audio")
DEBUG_DIR = Path("debug")  # Changed from code to debug

async def prepare_video_prerequisites(
    job_id: str,
    user_query: str,
    is_pro: bool,
    update_progress: callable
) -> Tuple[str, Path, float, Path, Optional[Path]]:
    """
    Prepare all prerequisites for video generation including content, audio, and paths.
    Returns tuple of (json_content, audio_file_path, audio_duration, output_path, generation_dir)
    """
    # Generate a single UUID for all related files
    video_id = str(uuid4())
    video_filename = f"{video_id}.mp4"
    
    # Step 1: Generate system design JSON
    print("=== DEBUG: Step 1 - Generating system design JSON ===")
    await update_progress(10)
    messages = [{"role": "user", "content": user_query}]
    concept_response = generate_concepts(messages, is_pro=is_pro)
    json_content = concept_response["message"]["content"]
    
    # Step 2: Generate voiceover script
    print("=== DEBUG: Step 2 - Generating voiceover script ===")
    await update_progress(20)
    script_response = generate_text(messages, is_pro=is_pro)
    script_content = script_response["message"]["content"]
    
    # Step 3: Generate audio from script
    print("=== DEBUG: Step 3 - Generating audio from script ===")
    await update_progress(30)
    scenes = [script_content]  # Wrap in list since the method expects multiple scenes
    audio_files = await generate_and_prepare_audio_files(scenes)
    
    if not audio_files:
        raise Exception("Failed to generate audio files")
        
    # Get the audio file path and duration
    audio_file = audio_files[0]  # We only have one audio file
    audio_file_path = Path.cwd() / AUDIO_DIR / audio_file.filename
    audio_duration = get_audio_duration(str(audio_file_path))
    
    print(f"=== DEBUG: Generated audio file: {audio_file_path} with duration {audio_duration}s ===")
    
    # Setup paths
    generation_dir = None
    
    if DEBUG_MODE:
        # Create debug directory structure
        DEBUG_DIR.mkdir(exist_ok=True)
        generation_dir = DEBUG_DIR / video_id
        generation_dir.mkdir(exist_ok=True)
        
        # Save JSON to debug directory
        json_filename = f"{video_id}.json"
        json_path = generation_dir / json_filename
        print(f"=== DEBUG: Saving JSON to {json_path} ===")
        with open(json_path, 'w') as f:
            f.write(json_content)
        print("=== DEBUG: JSON saved successfully ===")
        
        # Set video output path
        output_path = generation_dir / video_filename
        print(f"=== DEBUG: Debug mode ON - Using debug directory: {generation_dir} ===")
    else:
        output_path = VIDEOS_DIR / video_filename
        print("=== DEBUG: Debug mode OFF - Using direct video output ===")
    
    await update_progress(40)
    
    return json_content, audio_file_path, audio_duration, output_path, generation_dir

async def generate_and_render_video(
    job_id: str,
    user_query: str,
    json_content: str,
    audio_file_path: Path,
    audio_duration: float,
    output_path: Path,
    generation_dir: Optional[Path],
    update_progress: callable
) -> str:
    """
    Generate and render the video using Manim.
    Returns the filename of the generated video.
    """
    max_retries = 2
    attempt = 0
    last_error = None
    last_code = None
    video_filename = output_path.name
    
    await update_progress(60)
    
    while attempt <= max_retries:
        try:
            print(f"=== DEBUG: Attempt {attempt + 1}/{max_retries + 1} to generate and render video ===")
            # Generate the system design Manim code
            manim_code = generate_system_design(
                user_query, 
                json_content, 
                previous_code=last_code, 
                error_message=last_error,
                audio_file_path=str(audio_file_path),
                audio_duration=audio_duration
            )
            if not manim_code:
                raise HTTPException(status_code=500, detail="Failed to generate system design Manim code")
            
            await update_progress(80)
            
            # Extract the Scene class name
            class_match = re.search(r'class\s+(\w+)\s*\(\s*Scene\s*\)', manim_code)
            if not class_match:
                raise HTTPException(status_code=500, detail="Could not find Scene class in generated code")
            scene_class_name = class_match.group(1)
            print(f"=== DEBUG: Found scene class name: {scene_class_name} ===")
            
            # Run the Manim code
            return await run_manim_code(
                manim_code,
                scene_class_name,
                video_filename,
                output_path,
                generation_dir,
                update_progress,
                attempt
            )
                
        except subprocess.CalledProcessError as e:
            print(f"=== ERROR: Manim rendering failed on attempt {attempt + 1} ===")
            print(f"=== Command output (stdout) ===\n{e.stdout}")
            print(f"=== Command output (stderr) ===\n{e.stderr}")
            
            if DEBUG_MODE and generation_dir:
                fail_file = generation_dir / f"fail-{attempt + 1}.py"
                with open(fail_file, "w") as f:
                    f.write(manim_code)
                    f.write("\n\n# Error details from Manim rendering:\n")
                    f.write(f'error_message = """{e.stderr}"""')
                print(f"=== DEBUG: Saved failed code to: {fail_file} ===")
            
            if attempt == max_retries:
                raise
            
            last_error = e.stderr
            last_code = manim_code
            attempt += 1
            continue
            
    raise Exception("Failed to generate video after all attempts")

async def run_manim_code(
    manim_code: str,
    scene_class_name: str,
    video_filename: str,
    output_path: Path,
    generation_dir: Optional[Path],
    update_progress: callable,
    attempt: int
) -> str:
    """
    Run Manim code in a temporary directory and save the generated video to the appropriate locations.
    Returns the filename of the generated video.
    """
    # Create a temporary directory to render the video
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)
        temp_file_path = temp_dir_path / "scene.py"
        print(f"=== DEBUG: Created temporary directory: {temp_dir} ===")
        
        with open(temp_file_path, "w") as f:
            f.write(manim_code)
        print(f"=== DEBUG: Written Manim code to: {temp_file_path} ===")
        
        await update_progress(90)
        
        # Run Manim command
        cmd = ["manim", "-qm", str(temp_file_path), scene_class_name, "-o", video_filename]
        print(f"=== DEBUG: Running Manim command: {' '.join(cmd)} ===")
        subprocess.run(cmd, cwd=temp_dir, capture_output=True, text=True, check=True)
        print("=== DEBUG: Manim command completed successfully ===")
        
        await update_progress(100)
        
        # Locate the rendered video
        video_pattern = f"media/videos/**/720p30/{video_filename}"
        print(f"=== DEBUG: Searching for video with pattern: {video_pattern} ===")
        rendered_videos = list(Path(temp_dir).glob(video_pattern))
        print(f"=== DEBUG: Found {len(rendered_videos)} matching videos ===")
        
        if not rendered_videos:
            raise Exception(f"Could not find rendered video with pattern: {video_pattern}")
        
        rendered_video = rendered_videos[0]
        
        # In debug mode, save to both locations
        if DEBUG_MODE:
            print(f"=== DEBUG: Moving video from {rendered_video} to {output_path} ===")
            shutil.copy2(str(rendered_video), str(output_path))
            
            # Also save to videos directory for serving
            videos_path = VIDEOS_DIR / video_filename
            print(f"=== DEBUG: Copying video to serving location: {videos_path} ===")
            shutil.copy2(str(rendered_video), str(videos_path))
            
            # Save successful code
            if generation_dir:
                success_file = generation_dir / f"success-{attempt + 1}.py"
                with open(success_file, "w") as f:
                    f.write(manim_code)
                print(f"=== DEBUG: Saved successful code to: {success_file} ===")
        else:
            # In production, just move to videos directory
            print(f"=== DEBUG: Moving video from {rendered_video} to {output_path} ===")
            shutil.move(str(rendered_video), str(output_path))
        
        return video_filename