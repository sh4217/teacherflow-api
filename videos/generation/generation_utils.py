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
from ai.ai_utils import generate_video_plan, generate_manim_scenes, retry_manim_scene_generation
from models import VideoPlan

# Load environment variables
load_dotenv()

# Debug mode setting
DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"

# Constants
VIDEOS_DIR = Path("videos")
AUDIO_DIR = Path("audio")
DEBUG_DIR = Path("debug")

async def prepare_video_prerequisites(
    user_query: str,
    update_progress: callable
) -> VideoPlan:
    """
    Prepare initial prerequisites for video generation including content and script.
    Returns VideoPlan object (without audio information at this stage).
    """
    print("=== DEBUG: Step 1 - Generating video plan ===")
    await update_progress(10)
    messages = [{"role": "user", "content": user_query}]
    video_plan_response = generate_video_plan(messages)
    json_content = video_plan_response["message"]["content"]
    
    print("=== DEBUG: Step 2 - Parsing video plan ===")
    await update_progress(20)
    video_plan = VideoPlan.model_validate_json(json_content)
    
    await update_progress(30)
    return video_plan

async def generate_and_render_video(
    video_plan: VideoPlan,
    update_progress: callable
) -> str:
    """
    Generate and render the video using Manim.
    Returns the filename of the generated video.
    """
    video_id = str(uuid4())
    video_filename = f"{video_id}.mp4"
    max_retries = 2
    
    videos_dir_path, generation_dir, temp_dir_path = setup_directories(video_id, DEBUG_MODE)
    
    try:
        if DEBUG_MODE:
            json_content = video_plan.model_dump_json(indent=2)
            # Save just the JSON file for debugging
            json_path = generation_dir / f"{video_id}.json"
            with open(json_path, 'w') as f:
                f.write(json_content)
        
        print("=== DEBUG: Step 3 - Generating audio from script ===")
        await update_progress(40)
        audio_dir = temp_dir_path / "media" / "audio"
        script_contents = [scene.script for scene in video_plan.plan]
        audio_files = await generate_audio(audio_dir, script_contents)
        await update_progress(60)
        
        # Update audio information in the video plan
        for scene, audio_file in zip(video_plan.plan, audio_files):
            scene.audio_path = audio_file.path
            scene.audio_duration = audio_file.duration
        
        print("=== DEBUG: Step 4 - Generating Manim scenes ===")
        video_code = generate_manim_scenes(video_plan)
        if not video_code or not video_code.scenes:
            raise HTTPException(status_code=500, detail="Failed to generate Manim scenes")
        
        rendered_videos = []
        for i, scene in enumerate(video_code.scenes):
            scene_attempt = 0
            current_code = scene.code
            
            while scene_attempt <= max_retries:
                try:
                    print(f"=== DEBUG: Rendering scene {i + 1}/{len(video_code.scenes)} (attempt {scene_attempt + 1}) ===")
                    
                    # Write current scene code to file
                    scene_file = temp_dir_path / f"scene_{i + 1}.py"
                    with open(scene_file, "w") as f:
                        f.write(current_code)
                    
                    # Render individual scene with proper resource cleanup
                    cmd = ["manim", "-qm", "-a", str(scene_file)]
                    try:
                        # Use a separate process group to prevent affecting the main server
                        process = subprocess.Popen(
                            cmd,
                            cwd=temp_dir_path,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            start_new_session=True  # This prevents the subprocess from sharing signal handlers
                        )
                        stdout, stderr = process.communicate()
                        if process.returncode != 0:
                            error_msg = f"Command output (stdout):\n{stdout}\nCommand output (stderr):\n{stderr}"
                            print(f"=== ERROR: Scene {i + 1} rendering failed on attempt {scene_attempt + 1} ===")
                            print(error_msg)
                            
                            if DEBUG_MODE:
                                save_debug_files(generation_dir, video_id, json_content, scene.code, i + 1, scene_attempt + 1, error_msg)
                            
                            raise subprocess.CalledProcessError(process.returncode, cmd, stdout, stderr)
                    except subprocess.CalledProcessError as e:
                        if scene_attempt == max_retries:
                            raise
                        
                        # Try to fix just this scene
                        scene.code = retry_manim_scene_generation(scene.code, e.stderr)
                        if not scene.code:
                            raise HTTPException(status_code=500, detail=f"Failed to fix scene {i + 1} after error")
                        
                        current_code = scene.code  # Update current_code to match the retried scene code
                        scene_attempt += 1
                        continue
                    
                    # Find rendered video for this scene
                    scene_dir = temp_dir_path / "media" / "videos" / f"scene_{i + 1}" / "720p30"
                    print(f"=== DEBUG: Contents of {scene_dir}: ===")
                    if scene_dir.exists():
                        print(f"=== DEBUG: Contents of {scene_dir}: ===")
                        for file in sorted(scene_dir.glob("Scene_*.mp4")):
                            print(f"Found video: {file.name}")
                    else:
                        print(f"=== DEBUG: Scene directory does not exist: {scene_dir} ===")
                    
                    # Match any scene number, but sort them to get in correct order
                    scene_videos = sorted(list(scene_dir.glob("Scene_*.mp4")))
                    print(f"=== DEBUG: Found {len(scene_videos)} matching videos for scene {i + 1} ===")
                    if scene_videos:
                        print(f"=== DEBUG: Matched videos: {[v.name for v in scene_videos]} ===")
                    
                    if not scene_videos:
                        print(f"=== ERROR: No video file found for scene {i + 1} after successful render ===")
                        if scene_attempt == max_retries:
                            raise HTTPException(status_code=500, detail=f"Scene {i + 1} rendered without errors but no video file was created")
                        scene_attempt += 1
                        continue
                    
                    # Add all videos in correct order
                    rendered_videos.extend(scene_videos)
                    print(f"=== DEBUG: Added {len(scene_videos)} videos to rendered_videos (total: {len(rendered_videos)}) ===")
                    
                    if DEBUG_MODE:
                        save_debug_files(generation_dir, video_id, json_content, scene.code, i + 1, scene_attempt + 1)
                    
                    break  # Success, move to next scene
                    
                except Exception as e:
                    print(f"=== ERROR: Unexpected error rendering scene {i + 1}: {str(e)} ===")
                    if scene_attempt == max_retries:
                        raise
                    scene_attempt += 1
                    continue
            
            # Update progress as each scene is rendered
            progress = 60 + (30 * (i + 1) // len(video_code.scenes))
            await update_progress(progress)
        
        # Concatenate all rendered scenes
        rendered_video = concatenate_scenes(rendered_videos, temp_dir_path, video_filename)
        save_final_video(rendered_video, videos_dir_path, generation_dir)
        
        await update_progress(100)
        return video_filename
                
    finally:
        shutil.rmtree(temp_dir_path, ignore_errors=True)

def setup_directories(video_id: str, debug_mode: bool) -> Tuple[Path, Path, Path]:
    """
    Set up necessary directories for video generation.
    Returns tuple of (videos_dir_path, generation_dir, temp_dir_path).
    videos_dir_path is always VIDEOS_DIR/video_id.mp4 for serving.
    generation_dir is only set in debug mode for additional debug copy.
    """
    videos_dir_path = VIDEOS_DIR / f"{video_id}.mp4"
    
    generation_dir = None
    if debug_mode:
        DEBUG_DIR.mkdir(exist_ok=True)
        generation_dir = DEBUG_DIR / video_id
        generation_dir.mkdir(exist_ok=True)

    temp_dir = tempfile.mkdtemp()
    temp_dir_path = Path(temp_dir)
    
    media_dir = temp_dir_path / "media"
    media_dir.mkdir(exist_ok=True)
    audio_dir = media_dir / "audio"
    audio_dir.mkdir(exist_ok=True)
    
    return videos_dir_path, generation_dir, temp_dir_path

def save_debug_files(generation_dir: Path, video_id: str, json_content: str, manim_code: str, scene_num: int, attempt: int, error: str = None):
    """
    Save debug files when in debug mode.
    """
    json_path = generation_dir / f"{video_id}.json"
    with open(json_path, 'w') as f:
        f.write(json_content)

    if error:
        fail_file = generation_dir / f"fail-{scene_num}-{attempt}.py"
        with open(fail_file, "w") as f:
            f.write(manim_code)
            f.write("\n\n# Error details from Manim rendering:\n")
            f.write(f'error_message = """{error}"""')
    else:
        success_file = generation_dir / f"success-{scene_num}-{attempt}.py"
        with open(success_file, "w") as f:
            f.write(manim_code)

def render_manim_scenes(temp_dir_path: Path, manim_code: str) -> List[Path]:
    """
    Run Manim to render the video scenes.
    Returns list of rendered video paths.
    """
    temp_file_path = temp_dir_path / "scene.py"
    with open(temp_file_path, "w") as f:
        f.write(manim_code)

    cmd = ["manim", "-qm", "-a", str(temp_file_path)]
    result = subprocess.run(cmd, cwd=temp_dir_path, capture_output=True, text=True)
    result.check_returncode()

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
    if generation_dir:
        debug_path = generation_dir / videos_dir_path.name
        shutil.copy2(str(rendered_video), str(debug_path))
    
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
    """
    print(f"=== DEBUG: Concatenating {len(rendered_videos)} videos ===")
    for i, video in enumerate(rendered_videos):
        print(f"Video {i + 1}: {video.name}")
    
    concat_file = temp_dir_path / "concat.txt"
    print(f"=== DEBUG: Writing concat file to: {concat_file} ===")
    with open(concat_file, "w") as f:
        for video in rendered_videos:
            line = f"file '{video.absolute()}'"
            print(f"=== DEBUG: Adding to concat file: {line} ===")
            f.write(f"{line}\n")
    
    combined_video = temp_dir_path / video_filename
    concat_cmd = [
        "ffmpeg",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_file),
        "-c", "copy",
        str(combined_video)
    ]
    print(f"=== DEBUG: Running ffmpeg command: {' '.join(concat_cmd)} ===")
    
    try:
        # Use a separate process group to prevent affecting the main server
        process = subprocess.Popen(
            concat_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True  # This prevents the subprocess from sharing signal handlers
        )
        stdout, stderr = process.communicate()
        if process.returncode != 0:
            print(f"=== ERROR: ffmpeg concat failed ===\nStdout:\n{stdout}\nStderr:\n{stderr}")
            raise subprocess.CalledProcessError(process.returncode, concat_cmd, stdout, stderr)
        print(f"=== DEBUG: Successfully created combined video: {combined_video} ===")
    except subprocess.CalledProcessError as e:
        print(f"=== ERROR: ffmpeg concat failed ===\nStdout:\n{e.stdout}\nStderr:\n{e.stderr}")
        raise
    
    return combined_video
