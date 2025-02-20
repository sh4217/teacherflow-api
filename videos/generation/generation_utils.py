from pathlib import Path
from typing import Tuple, List, Dict, Any
from uuid import uuid4
import tempfile
import subprocess
import shutil
import os
from dotenv import load_dotenv
from fastapi import HTTPException
import multiprocessing
from itertools import cycle
import asyncio
from concurrent.futures import ProcessPoolExecutor

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

def analyze_parallel_distribution(scenes):
    """
    Analyze and log how scenes would be distributed across available CPU cores.
    """
    total_cores = multiprocessing.cpu_count()
    # Use N-1 workers to leave one core free for system processes
    num_workers = max(1, total_cores - 1)
    
    print(f"\n=== Parallel Processing Analysis ===")
    print(f"Total CPU cores available: {total_cores}")
    print(f"Number of worker processes: {num_workers}")
    print(f"Total scenes to process: {len(scenes)}")
    
    # Simulate distribution of scenes to workers
    workers = list(range(num_workers))
    scene_distribution = {i: [] for i in workers}
    
    for scene_idx, worker in zip(range(len(scenes)), cycle(workers)):
        scene_distribution[worker].append(scene_idx + 1)
    
    print("\nProjected scene distribution:")
    for worker_id, scene_list in scene_distribution.items():
        print(f"Worker {worker_id + 1}: Scenes {scene_list} ({len(scene_list)} scenes)")
    print("===================================\n")

def render_single_scene(scene_data: Dict[str, Any]) -> List[Path]:
    """
    Worker function to render a single scene in a separate process.
    Returns list of paths to rendered video files.
    """
    scene_idx = scene_data['scene_idx']
    scene_code = scene_data['scene_code']
    temp_dir_path = Path(scene_data['temp_dir'])
    video_id = scene_data['video_id']
    max_retries = scene_data['max_retries']
    debug_mode = scene_data['debug_mode']
    
    # Create scene-specific directory
    worker_dir = temp_dir_path / f"worker_{scene_idx + 1}"
    worker_dir.mkdir(exist_ok=True)
    
    scene_attempt = 0
    current_code = scene_code
    
    while scene_attempt <= max_retries:
        try:
            print(f"=== DEBUG: Rendering scene {scene_idx + 1} (attempt {scene_attempt + 1}) ===")
            
            # Write current scene code to file
            scene_file = worker_dir / f"scene_{scene_idx + 1}.py"
            with open(scene_file, "w") as f:
                f.write(current_code)
            
            # Render individual scene
            cmd = ["manim", "-qm", "-a", str(scene_file)]
            try:
                process = subprocess.Popen(
                    cmd,
                    cwd=worker_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    start_new_session=True
                )
                stdout, stderr = process.communicate()
                if process.returncode != 0:
                    error_msg = f"Command output (stdout):\n{stdout}\nCommand output (stderr):\n{stderr}"
                    print(f"=== ERROR: Scene {scene_idx + 1} rendering failed on attempt {scene_attempt + 1} ===")
                    print(error_msg)
                    
                    if debug_mode:
                        save_debug_files(Path(scene_data['generation_dir']), video_id, scene_data['json_content'], 
                                      scene_code, scene_idx + 1, scene_attempt + 1, error_msg)
                    
                    raise subprocess.CalledProcessError(process.returncode, cmd, stdout, stderr)
            except subprocess.CalledProcessError as e:
                if scene_attempt == max_retries:
                    raise
                
                # Try to fix just this scene
                fixed_code = retry_manim_scene_generation(current_code, e.stderr)
                if not fixed_code:
                    raise HTTPException(status_code=500, detail=f"Failed to fix scene {scene_idx + 1} after error")
                
                current_code = fixed_code
                scene_attempt += 1
                continue
            
            # Find rendered video for this scene
            scene_dir = worker_dir / "media" / "videos" / f"scene_{scene_idx + 1}" / "720p30"
            scene_videos = sorted(list(scene_dir.glob("Scene_*.mp4")))
            
            if not scene_videos:
                print(f"=== ERROR: No video file found for scene {scene_idx + 1} after successful render ===")
                if scene_attempt == max_retries:
                    raise HTTPException(status_code=500, detail=f"Scene {scene_idx + 1} rendered without errors but no video file was created")
                scene_attempt += 1
                continue
            
            print(f"=== DEBUG: Successfully rendered scene {scene_idx + 1} ===")
            
            if debug_mode:
                save_debug_files(Path(scene_data['generation_dir']), video_id, scene_data['json_content'], 
                               current_code, scene_idx + 1, scene_attempt + 1)
            
            return [(v, scene_idx) for v in scene_videos]
            
        except Exception as e:
            print(f"=== ERROR: Unexpected error rendering scene {scene_idx + 1}: {str(e)} ===")
            if scene_attempt == max_retries:
                raise
            scene_attempt += 1
            continue
    
    raise Exception(f"Failed to render scene {scene_idx + 1} after all attempts")

async def render_scenes_in_parallel(video_code, temp_dir_path: Path, video_id: str, 
                                  generation_dir: Path, json_content: str, max_retries: int, 
                                  debug_mode: bool) -> List[Path]:
    """
    Render all scenes in parallel using a process pool.
    Returns ordered list of rendered video paths.
    """
    # Prepare scene data for parallel processing
    scene_data_list = []
    for i, scene in enumerate(video_code.scenes):
        scene_data = {
            'scene_idx': i,
            'scene_code': scene.code,
            'temp_dir': str(temp_dir_path),
            'video_id': video_id,
            'max_retries': max_retries,
            'debug_mode': debug_mode,
            'generation_dir': str(generation_dir) if generation_dir else None,
            'json_content': json_content if debug_mode else None
        }
        scene_data_list.append(scene_data)
    
    # Create process pool and run scenes in parallel
    num_workers = max(1, multiprocessing.cpu_count() - 1)
    print(f"\n=== Starting parallel rendering with {num_workers} workers ===")
    
    loop = asyncio.get_running_loop()
    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        # Submit all scenes for processing
        futures = [
            loop.run_in_executor(executor, render_single_scene, scene_data)
            for scene_data in scene_data_list
        ]
        
        # Wait for all scenes to complete
        results = await asyncio.gather(*futures, return_exceptions=True)
    
    # Check for any errors and flatten results
    rendered_videos = []
    for result in results:
        if isinstance(result, Exception):
            raise result
        rendered_videos.extend(result)
    
    # Sort by scene index and extract just the video paths
    rendered_videos.sort(key=lambda x: x[1])
    return [video[0] for video in rendered_videos]

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

        # Analyze potential parallel processing distribution
        analyze_parallel_distribution(video_code.scenes)
        
        # Render all scenes in parallel
        rendered_videos = await render_scenes_in_parallel(
            video_code, temp_dir_path, video_id, generation_dir,
            json_content if DEBUG_MODE else None, max_retries, DEBUG_MODE
        )
        
        # Update progress after all scenes are rendered
        await update_progress(90)
        
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
