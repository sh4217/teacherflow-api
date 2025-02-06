from pathlib import Path
from typing import Tuple, List
from uuid import uuid4
import tempfile
import subprocess
import shutil
import os
from dotenv import load_dotenv
from fastapi import HTTPException

from audio.audio_utils import generate_audio
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
    user_query: str,
    is_pro: bool,
    update_progress: callable
) -> Tuple[str, str, List[str]]:
    """
    Prepare initial prerequisites for video generation including content and script.
    Returns tuple of (json_content, video_id, script_contents)
    """
    # Generate a single UUID for all related files
    video_id = str(uuid4())
    
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
    script_contents = script_response["message"]["content"]  # Now a list of scene content
    
    await update_progress(30)
    
    return json_content, video_id, script_contents

async def generate_and_render_video(
    user_query: str,
    json_content: str,
    video_id: str,
    script_contents: List[str],
    update_progress: callable
) -> str:
    """
    Generate and render the video using Manim.
    Returns the filename of the generated video.
    """
    video_filename = f"{video_id}.mp4"
    max_retries = 2
    attempt = 0
    last_error = None
    last_code = None
    
    # Create debug directory if needed
    generation_dir = None
    if DEBUG_MODE:
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
    
    # Create a temporary directory for all file operations
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)
        print(f"=== DEBUG: Created temporary directory: {temp_dir} ===")
        
        # Set output paths
        if DEBUG_MODE:
            output_path = generation_dir / video_filename
            print(f"=== DEBUG: Debug mode ON - Using debug directory: {generation_dir} ===")
        else:
            output_path = VIDEOS_DIR / video_filename
            print("=== DEBUG: Debug mode OFF - Using direct video output ===")
        
        # Create media directory structure
        media_dir = temp_dir_path / "media"
        media_dir.mkdir(exist_ok=True)
        audio_dir = media_dir / "audio"
        audio_dir.mkdir(exist_ok=True)
        
        # Step 3: Generate audio from script
        print("=== DEBUG: Step 3 - Generating audio from script ===")
        await update_progress(40)
        
        # Generate audio files for each scene
        audio_files = await generate_audio(audio_dir, script_contents)
        
        await update_progress(60)
        
        while attempt <= max_retries:
            try:
                print(f"=== DEBUG: Attempt {attempt + 1}/{max_retries + 1} to generate and render video ===")
                
                # Generate the system design Manim code with audio paths and durations
                manim_code = generate_system_design(
                    user_query, 
                    json_content, 
                    previous_code=last_code, 
                    error_message=last_error,
                    audio_files=audio_files
                )
                if not manim_code:
                    raise HTTPException(status_code=500, detail="Failed to generate system design Manim code")
                
                await update_progress(80)
                
                # Write and run the Manim code
                temp_file_path = temp_dir_path / "scene.py"
                with open(temp_file_path, "w") as f:
                    f.write(manim_code)
                print(f"=== DEBUG: Written Manim code to: {temp_file_path} ===")
                
                await update_progress(90)

                # Run Manim command
                cmd = ["manim", "-qm", "-a", str(temp_file_path)]
                print(f"=== DEBUG: Running Manim command: {' '.join(cmd)} ===")

                result = subprocess.run(cmd, cwd=temp_dir, capture_output=True, text=True)
                if result.returncode == 0:
                    print("=== DEBUG: Manim command completed successfully ===")
                else:
                    print(f"=== ERROR: Manim command failed with return code {result.returncode} ===")
                    result.check_returncode()  # This will raise CalledProcessError
                
                # Locate all rendered videos
                video_pattern = "media/videos/**/720p30/*.mp4"
                print(f"=== DEBUG: Searching for videos with pattern: {video_pattern} ===")
                rendered_videos = sorted(list(Path(temp_dir).glob(video_pattern)))
                print(f"=== DEBUG: Found {len(rendered_videos)} scene videos ===")
                
                if not rendered_videos:
                    raise Exception(f"Could not find any rendered videos with pattern: {video_pattern}")
                    
                # Process videos to get a single output video
                rendered_video = concatenate_scenes(rendered_videos, temp_dir_path, video_filename)
                
                await update_progress(100)
                
                # Save the video to appropriate locations
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

def concatenate_scenes(
    rendered_videos: list[Path],
    temp_dir_path: Path,
    video_filename: str
) -> Path:
    """
    Process rendered videos and return a single video file.
    If multiple videos exist, they will be concatenated using ffmpeg.
    If only one video exists, it will be renamed to the desired filename.
    
    Args:
        rendered_videos: List of rendered video file paths (sorted alphabetically)
        temp_dir_path: Path to temporary directory
        video_filename: Desired filename for the output video
        
    Returns:
        Path to the final video file
    """
    # Create a file listing of all videos to concatenate in order
    concat_file = temp_dir_path / "concat.txt"
    with open(concat_file, "w") as f:
        for video in rendered_videos:
            f.write(f"file '{video.absolute()}'\n")
    
    print(f"=== DEBUG: Created concat file at {concat_file} ===")
    print("=== DEBUG: Concat file contents ===")
    with open(concat_file, "r") as f:
        print(f.read())
    
    # Use ffmpeg concat demuxer to concatenate the videos
    combined_video = temp_dir_path / video_filename
    concat_cmd = [
        "ffmpeg",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_file),
        "-c", "copy",  # Stream copy without re-encoding
        str(combined_video)
    ]
    print(f"\n=== DEBUG: Running ffmpeg concat command: {' '.join(concat_cmd)} ===")
    result = subprocess.run(concat_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"=== ERROR: ffmpeg concat failed ===\nStdout:\n{result.stdout}\nStderr:\n{result.stderr}")
        result.check_returncode()
    
    # Verify the output
    print(f"\n=== DEBUG: Verifying concatenated output ===")
    
    return combined_video
