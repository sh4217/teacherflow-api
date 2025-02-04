from audio.audio_utils import process_audio_files, generate_and_prepare_audio_files
from fastapi import FastAPI, HTTPException, UploadFile, Body, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from uuid import uuid4
from typing import List, Dict, Optional
from pathlib import Path
from manim import *
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from videos.video_utils import create_scene_segments, render_video
from enum import Enum
from pydantic import BaseModel
import asyncio
from ai.ai_utils import generate_text, parse_scenes, generate_manim, generate_concepts
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Debug mode setting
DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"

# Job status enum
class JobStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"

# Job metadata model
class JobMetadata(BaseModel):
    job_id: str
    status: JobStatus
    progress: float = 0.0
    videoUrl: Optional[str] = None

# Text request model
class TextRequest(BaseModel):
    query: str
    is_pro: Optional[bool] = False

class ConceptRequest(BaseModel):
    query: str
    is_pro: Optional[bool] = False

class ManimRequest(BaseModel):
    query: str

# In-memory job store
jobs: Dict[str, JobMetadata] = {}

# Add this near other directory constants
JSON_DIR = Path("json")
JSON_DIR.mkdir(exist_ok=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://teacherflow.ai", "https://www.teacherflow.ai"],
    allow_credentials=True,
    allow_methods=["POST", "GET", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)

VIDEOS_DIR = Path("videos")
VIDEOS_DIR.mkdir(exist_ok=True)

AUDIO_DIR = Path("audio")
AUDIO_DIR.mkdir(exist_ok=True)

app.mount("/videos", StaticFiles(directory="videos"), name="videos")
app.mount("/json", StaticFiles(directory="json"), name="json")

async def validate_request(texts: List[str], audio_files: List[UploadFile]):
    """Validate the incoming request data"""
    if len(texts) != len(audio_files):
        raise HTTPException(status_code=400, detail="Number of texts must match number of audio files")

def cleanup_temp_files(temp_files: List[str]):
    """Clean up temporary files"""
    for temp_file in temp_files:
        try:
            Path(temp_file).unlink()
        except Exception:
            pass

async def process_video_job(
    job_id: str,
    texts: List[str],
    audio_files: List[UploadFile]
):
    """Background task to process the video generation job"""
    temp_files = []
    audio_paths = []  # Track audio paths for cleanup
    
    async def update_progress(progress: int, status: JobStatus = JobStatus.IN_PROGRESS):
        """Helper function to update job progress with sufficient sleep time"""
        jobs[job_id].status = status
        jobs[job_id].progress = progress
        await asyncio.sleep(0.5)
    
    try:
        await update_progress(50)
        
        await validate_request(texts, audio_files)
        
        VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
        
        video_filename = f"{uuid4()}.mp4"
        video_path = VIDEOS_DIR / video_filename
        
        audio_paths, new_temp_files = await process_audio_files(audio_files)
        temp_files.extend(new_temp_files)
        
        try:
            segments = create_scene_segments(texts, audio_paths)
            await update_progress(80)
            
            await render_video(segments, video_path)
            await update_progress(90)
            
            jobs[job_id].status = JobStatus.COMPLETED
            jobs[job_id].progress = 100
            jobs[job_id].videoUrl = video_filename
            
        finally:
            cleanup_temp_files(temp_files)
            for audio_file in audio_files:
                try:
                    audio_file.file.close()
                    if hasattr(audio_file, 'filename') and isinstance(audio_file.filename, str):
                        audio_path = AUDIO_DIR / audio_file.filename
                        if audio_path.exists():
                            audio_path.unlink()
                except Exception as e:
                    print(f"=== ERROR: Failed to clean up audio file: {e} ===")
            
    except Exception as e:
        print(f"=== ERROR: Exception in video processing job {job_id}: {e} ===")
        jobs[job_id].status = JobStatus.FAILED
        jobs[job_id].progress = 0
        raise

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.get("/job-status/{job_id}")
async def get_job_status(job_id: str):
    """Endpoint to get job status"""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs[job_id]

@app.post("/generate-video")
async def generate_video(
    background_tasks: BackgroundTasks,
    request: TextRequest
):
    """Start a video generation job using AI-generated text and audio"""
    job_id = str(uuid4())
    jobs[job_id] = JobMetadata(
        job_id=job_id,
        status=JobStatus.PENDING,
        progress=0
    )
    
    try:
        messages = [{"role": "user", "content": request.query}]
        text_response = generate_text(messages, is_pro=request.is_pro)
        scenes = parse_scenes(text_response["message"]["content"])
        
        saved_audio_files = await generate_and_prepare_audio_files(scenes)
    
        background_tasks.add_task(
            process_video_job,
            job_id=job_id,
            texts=scenes,
            audio_files=saved_audio_files
        )
        
        return {"job_id": job_id}
        
    except Exception as e:
        print(f"=== ERROR: Exception in generate_video: {str(e)} ===")
        raise

@app.post("/generate-manim")
async def generate_manim_video(request: ManimRequest):
    """Generate and render Manim video for a given query"""
    try:
        import tempfile
        import subprocess
        import shutil
        import os
        import re

        print("=== DEBUG: Starting Manim video generation process ===")

        # Generate a unique ID for this video
        video_id = str(uuid4())
        video_filename = f"{video_id}.mp4"
        
        # Set up paths based on debug mode
        if DEBUG_MODE:
            # Create code directory and generation directory for debugging
            code_dir = Path("code")
            code_dir.mkdir(exist_ok=True)
            generation_dir = code_dir / video_id
            generation_dir.mkdir(exist_ok=True)
            output_path = generation_dir / video_filename
        else:
            # In production, save directly to videos directory
            output_path = VIDEOS_DIR / video_filename
            
        print(f"=== DEBUG: Target output path: {output_path} ===")

        max_retries = 2
        attempt = 0
        last_error = None
        last_code = None

        while attempt <= max_retries:
            try:
                # Generate the Manim code
                manim_code = generate_manim(
                    request.query,
                    previous_code=last_code,
                    error_message=last_error
                )
                if not manim_code:
                    raise HTTPException(status_code=500, detail="Failed to generate Manim code")

                # Extract the scene class name from the code
                class_match = re.search(r'class\s+(\w+)\s*\(\s*Scene\s*\)', manim_code)
                if not class_match:
                    raise HTTPException(status_code=500, detail="Could not find Scene class in generated code")
                scene_class_name = class_match.group(1)
                print(f"=== DEBUG: Extracted scene class name: {scene_class_name} ===")

                # Create a temporary directory for our work
                with tempfile.TemporaryDirectory() as temp_dir:
                    print(f"=== DEBUG: Created temporary directory: {temp_dir} ===")
                    
                    # Create a Python file with the generated code
                    temp_file_path = Path(temp_dir) / "scene.py"
                    with open(temp_file_path, "w") as f:
                        f.write(manim_code)
                    print(f"=== DEBUG: Written scene code to: {temp_file_path} ===")

                    # Run manim command to render the video
                    cmd = [
                        "manim",
                        "-qm",  # medium quality
                        str(temp_file_path),
                        scene_class_name,  # use the extracted class name
                        "-o",
                        video_filename,
                    ]
                    print(f"=== DEBUG: Running command: {' '.join(cmd)} ===")
                    print(f"=== DEBUG: Working directory: {temp_dir} ===")

                    result = subprocess.run(
                        cmd,
                        cwd=temp_dir,
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                    print("=== DEBUG: Manim command completed successfully ===")

                    # List all files in media directory for debugging
                    media_dir = Path(temp_dir) / "media" / "videos"
                    print(f"=== DEBUG: Contents of media directory {media_dir}: ===")
                    for path in media_dir.rglob("*"):
                        print(f"  {path.relative_to(media_dir)}")

                    # Find and move the rendered video to our videos directory
                    video_pattern = f"media/videos/**/720p30/{video_filename}"
                    print(f"=== DEBUG: Searching for video with pattern: {video_pattern} ===")
                    rendered_videos = list(Path(temp_dir).glob(video_pattern))
                    print(f"=== DEBUG: Found {len(rendered_videos)} matching videos: {rendered_videos} ===")
                    
                    if not rendered_videos:
                        raise Exception(f"Could not find rendered video with pattern: {video_pattern}")
                    
                    rendered_video = rendered_videos[0]
                    print(f"=== DEBUG: Moving video from {rendered_video} to {output_path} ===")
                    shutil.move(str(rendered_video), str(output_path))

                    if DEBUG_MODE:
                        # Save the successful code only in debug mode
                        success_file = generation_dir / f"success-{attempt + 1}.py"
                        with open(success_file, "w") as f:
                            f.write(manim_code)
                        print(f"=== DEBUG: Saved successful code to: {success_file} ===")
                        
                        # Copy the video to the videos directory (don't use symlink)
                        video_copy = VIDEOS_DIR / video_filename
                        shutil.copy2(output_path, video_copy)
                        print(f"=== DEBUG: Copied video to: {video_copy} ===")
                    else:
                        # In production, copy to videos directory directly
                        shutil.copy2(output_path, VIDEOS_DIR / video_filename)

                    return {
                        "videoUrl": video_filename,
                        "message": "Video generated successfully",
                        "attempts": attempt + 1
                    }

            except subprocess.CalledProcessError as e:
                print(f"=== ERROR: Manim rendering failed on attempt {attempt + 1} ===")
                print(f"=== Command output (stdout) ===\n{e.stdout}")
                print(f"=== Command output (stderr) ===\n{e.stderr}")
                
                if DEBUG_MODE:
                    # Save the failed code only in debug mode
                    fail_file = generation_dir / f"fail-{attempt + 1}.py"
                    with open(fail_file, "w") as f:
                        f.write(manim_code)
                        f.write("\n\n# Error details from Manim rendering:\n")
                        f.write(f'error_message = """{e.stderr}"""')
                    print(f"=== DEBUG: Saved failed code to: {fail_file} ===")
                
                if attempt == max_retries:
                    raise HTTPException(
                        status_code=500,
                        detail=f"Failed to render video after {max_retries + 1} attempts: {e.stderr}"
                    )
                    
                last_error = e.stderr
                last_code = manim_code
                attempt += 1
                continue

            except Exception as e:
                print(f"=== ERROR: Failed to process video on attempt {attempt + 1}: {str(e)} ===")
                print(f"=== Error type: {type(e)} ===")
                print(f"=== Error details: {str(e)} ===")
                
                if DEBUG_MODE:
                    # Save the failed code only in debug mode
                    fail_file = generation_dir / f"fail-{attempt + 1}.py"
                    with open(fail_file, "w") as f:
                        f.write(manim_code)
                        f.write("\n\n# Error details from execution:\n")
                        f.write(f'error_message = """{str(e)}"""')
                    print(f"=== DEBUG: Saved failed code to: {fail_file} ===")
                
                if attempt == max_retries:
                    raise HTTPException(
                        status_code=500,
                        detail=f"Failed to process video after {max_retries + 1} attempts: {str(e)}"
                    )
                    
                last_error = str(e)
                last_code = manim_code
                attempt += 1
                continue

    except Exception as e:
        print(f"=== ERROR: Exception in generate_manim_video: {str(e)} ===")
        print(f"=== Error type: {type(e)} ===")
        print(f"=== Error details: {str(e)} ===")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/create-conceptual-graph")
async def create_conceptual_graph(request: ConceptRequest):
    """Generate a conceptual graph for a given technical topic and save to JSON file"""
    try:
        messages = [{"role": "user", "content": request.query}]
        response = generate_concepts(messages, is_pro=request.is_pro)
        
        # Generate unique filename and save JSON
        json_filename = f"{uuid4()}.json"
        json_path = JSON_DIR / json_filename
        
        with open(json_path, 'w') as f:
            f.write(response["message"]["content"])
        
        return {
            "message": response["message"],
            "jsonPath": json_filename
        }
    except Exception as e:
        print(f"=== ERROR: Exception in create_conceptual_graph: {str(e)} ===")
        raise HTTPException(status_code=500, detail=str(e))
