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
from ai.ai_utils import generate_concepts, generate_manim_code, generate_text

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
    concept_response = generate_concepts(messages)
    json_content = concept_response["message"]["content"]
    
    # Step 2: Generate voiceover script
    print("=== DEBUG: Step 2 - Generating voiceover script ===")
    await update_progress(20)
    script_response = generate_text(messages)
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
    
    # Set up directories
    videos_dir_path, generation_dir, temp_dir_path = setup_directories(video_id, DEBUG_MODE)
    
    try:
        # Save initial debug files if in debug mode
        if DEBUG_MODE:
            save_debug_files(generation_dir, video_id, json_content, "", 0)
        
        # Generate audio
        print("=== DEBUG: Step 3 - Generating audio from script ===")
        await update_progress(40)
        audio_dir = temp_dir_path / "media" / "audio"
        audio_files = await generate_audio(audio_dir, script_contents)
        await update_progress(60)
        
        while attempt <= max_retries:
            try:
                print(f"=== DEBUG: Attempt {attempt + 1}/{max_retries + 1} to generate and render video ===")
                
                # Generate Manim code
                manim_code = generate_manim_code(
                    user_query, 
                    json_content, 
                    previous_code=last_code, 
                    error_message=last_error,
                    audio_files=audio_files
                )
                if not manim_code:
                    raise HTTPException(status_code=500, detail="Failed to generate system design Manim code")
                
                await update_progress(80)
                
                # Render individual scenes
                rendered_videos = render_manim_scenes(temp_dir_path, manim_code)
                await update_progress(90)
                
                # Process videos to get a single output video
                rendered_video = concatenate_scenes(rendered_videos, temp_dir_path, video_filename)
                
                # Save the final video
                save_final_video(rendered_video, videos_dir_path, generation_dir)
                
                # Save successful debug files
                if DEBUG_MODE:
                    save_debug_files(generation_dir, video_id, json_content, manim_code, attempt + 1)
                
                await update_progress(100)
                return video_filename
                    
            except subprocess.CalledProcessError as e:
                print(f"=== ERROR: Manim rendering failed on attempt {attempt + 1} ===")
                print(f"=== Command output (stdout) ===\n{e.stdout}")
                print(f"=== Command output (stderr) ===\n{e.stderr}")
                
                if DEBUG_MODE:
                    save_debug_files(generation_dir, video_id, json_content, manim_code, attempt + 1, e.stderr)
                
                if attempt == max_retries:
                    raise
                
                last_error = e.stderr
                last_code = manim_code
                attempt += 1
                continue
    finally:
        # Clean up temporary directory
        shutil.rmtree(temp_dir_path, ignore_errors=True)
                
    raise Exception("Failed to generate video after all attempts")

def setup_directories(video_id: str, debug_mode: bool) -> Tuple[Path, Path, Path]:
    """
    Set up necessary directories for video generation.
    Returns tuple of (videos_dir_path, generation_dir, temp_dir_path).
    videos_dir_path is always VIDEOS_DIR/video_id.mp4 for serving.
    generation_dir is only set in debug mode for additional debug copy.
    """
    # Set up the main video path that will be used for serving
    videos_dir_path = VIDEOS_DIR / f"{video_id}.mp4"
    
    # Set up debug directory if needed
    generation_dir = None
    if debug_mode:
        DEBUG_DIR.mkdir(exist_ok=True)
        generation_dir = DEBUG_DIR / video_id
        generation_dir.mkdir(exist_ok=True)

    # Create temporary directory
    temp_dir = tempfile.mkdtemp()
    temp_dir_path = Path(temp_dir)
    
    # Create media directory structure
    media_dir = temp_dir_path / "media"
    media_dir.mkdir(exist_ok=True)
    audio_dir = media_dir / "audio"
    audio_dir.mkdir(exist_ok=True)
    
    return videos_dir_path, generation_dir, temp_dir_path

def save_debug_files(generation_dir: Path, video_id: str, json_content: str, manim_code: str, attempt: int, error: str = None):
    """
    Save debug files when in debug mode.
    """
    # Save JSON content
    json_path = generation_dir / f"{video_id}.json"
    with open(json_path, 'w') as f:
        f.write(json_content)

    # Save Manim code
    if error:
        fail_file = generation_dir / f"fail-{attempt}.py"
        with open(fail_file, "w") as f:
            f.write(manim_code)
            f.write("\n\n# Error details from Manim rendering:\n")
            f.write(f'error_message = """{error}"""')
    else:
        success_file = generation_dir / f"success-{attempt}.py"
        with open(success_file, "w") as f:
            f.write(manim_code)

def render_manim_scenes(temp_dir_path: Path, manim_code: str) -> List[Path]:
    """
    Run Manim to render the video scenes.
    Returns list of rendered video paths.
    """
    # Write Manim code
    temp_file_path = temp_dir_path / "scene.py"
    with open(temp_file_path, "w") as f:
        f.write(manim_code)

    # Run Manim command
    cmd = ["manim", "-qm", "-a", str(temp_file_path)]
    result = subprocess.run(cmd, cwd=temp_dir_path, capture_output=True, text=True)
    result.check_returncode()

    # Locate rendered videos
    video_pattern = "media/videos/**/720p30/*.mp4"
    rendered_videos = sorted(list(Path(temp_dir_path).glob(video_pattern)))
    
    if not rendered_videos:
        raise Exception(f"Could not find any rendered videos with pattern: {video_pattern}")
    
    return rendered_videos

def save_final_video(rendered_video: Path, videos_dir_path: Path, generation_dir: Path):
    """
    Save the final video to appropriate locations.
    Always saves to videos_dir_path for serving, and optionally saves to generation_dir/video_filename in debug mode.
    """
    # In debug mode, also save a copy to debug directory
    if generation_dir:
        debug_path = generation_dir / videos_dir_path.name
        shutil.copy2(str(rendered_video), str(debug_path))
    
    # Always save to videos directory for serving
    shutil.move(str(rendered_video), str(videos_dir_path))

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
    result = subprocess.run(concat_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"=== ERROR: ffmpeg concat failed ===\nStdout:\n{result.stdout}\nStderr:\n{result.stderr}")
        result.check_returncode()
    
    return combined_video
