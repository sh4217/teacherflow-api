from audio.audio_utils import generate_and_prepare_audio_files, get_audio_duration
from fastapi import FastAPI, HTTPException, UploadFile, BackgroundTasks, Body
from fastapi.middleware.cors import CORSMiddleware
from uuid import uuid4
from typing import List, Dict, Optional
from pathlib import Path
from manim import *
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from enum import Enum
from pydantic import BaseModel
import asyncio
from ai.ai_utils import generate_concepts, generate_system_design, generate_text
import os
from dotenv import load_dotenv
import subprocess
import re
import tempfile
import shutil

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

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.get("/job-status/{job_id}")
async def get_job_status(job_id: str):
    """Endpoint to get job status"""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs[job_id]

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
    user_query: str,
    json_content: str,
    is_pro: bool,
    audio_file_path: str = None,
    audio_duration: float = None
):
    """Background task to process the system design video generation job"""
    temp_files = []
    
    async def update_progress(progress: int, status: JobStatus = JobStatus.IN_PROGRESS):
        """Helper function to update job progress with sufficient sleep time"""
        jobs[job_id].status = status
        jobs[job_id].progress = progress
        await asyncio.sleep(0.5)
    
    try:
        print(f"=== DEBUG: Starting system design video job {job_id} ===")
        await update_progress(20)
        
        # Step 2: Generate Manim code using generate_system_design
        print("=== DEBUG: Starting Manim code generation and video rendering ===")
        max_retries = 2
        attempt = 0
        last_error = None
        last_code = None
        video_id = str(uuid4())
        video_filename = f"{video_id}.mp4"
        
        if DEBUG_MODE:
            code_dir = Path("code")
            code_dir.mkdir(exist_ok=True)
            generation_dir = code_dir / video_id
            generation_dir.mkdir(exist_ok=True)
            output_path = generation_dir / video_filename
            print(f"=== DEBUG: Debug mode ON - Using code directory: {generation_dir} ===")
        else:
            output_path = VIDEOS_DIR / video_filename
            print("=== DEBUG: Debug mode OFF - Using direct video output ===")
        
        await update_progress(40)
        
        while attempt <= max_retries:
            try:
                print(f"=== DEBUG: Attempt {attempt + 1}/{max_retries + 1} to generate and render video ===")
                # Generate the system design Manim code
                manim_code = generate_system_design(
                    user_query, 
                    json_content, 
                    previous_code=last_code, 
                    error_message=last_error,
                    audio_file_path=audio_file_path,
                    audio_duration=audio_duration
                )
                if not manim_code:
                    raise HTTPException(status_code=500, detail="Failed to generate system design Manim code")
                
                await update_progress(60)
                
                # Extract the Scene class name
                class_match = re.search(r'class\s+(\w+)\s*\(\s*Scene\s*\)', manim_code)
                if not class_match:
                    raise HTTPException(status_code=500, detail="Could not find Scene class in generated code")
                scene_class_name = class_match.group(1)
                print(f"=== DEBUG: Found scene class name: {scene_class_name} ===")
                
                # Create a temporary directory to render the video
                with tempfile.TemporaryDirectory() as temp_dir:
                    temp_dir_path = Path(temp_dir)
                    temp_file_path = temp_dir_path / "scene.py"
                    print(f"=== DEBUG: Created temporary directory: {temp_dir} ===")
                    
                    with open(temp_file_path, "w") as f:
                        f.write(manim_code)
                    print(f"=== DEBUG: Written Manim code to: {temp_file_path} ===")
                    
                    await update_progress(70)
                    
                    # Run Manim command
                    cmd = ["manim", "-qm", str(temp_file_path), scene_class_name, "-o", video_filename]
                    print(f"=== DEBUG: Running Manim command: {' '.join(cmd)} ===")
                    subprocess.run(cmd, cwd=temp_dir, capture_output=True, text=True, check=True)
                    print("=== DEBUG: Manim command completed successfully ===")
                    
                    await update_progress(80)
                    
                    # Locate the rendered video
                    video_pattern = f"media/videos/**/720p30/{video_filename}"
                    print(f"=== DEBUG: Searching for video with pattern: {video_pattern} ===")
                    rendered_videos = list(Path(temp_dir).glob(video_pattern))
                    print(f"=== DEBUG: Found {len(rendered_videos)} matching videos ===")
                    
                    if not rendered_videos:
                        raise Exception(f"Could not find rendered video with pattern: {video_pattern}")
                    
                    rendered_video = rendered_videos[0]
                    print(f"=== DEBUG: Moving video from {rendered_video} to {output_path} ===")
                    shutil.move(str(rendered_video), str(output_path))
                    
                    await update_progress(90)
                    
                    if DEBUG_MODE:
                        success_file = generation_dir / f"success-{attempt + 1}.py"
                        with open(success_file, "w") as f:
                            f.write(manim_code)
                        print(f"=== DEBUG: Saved successful code to: {success_file} ===")
                        video_copy = VIDEOS_DIR / video_filename
                        shutil.copy2(output_path, video_copy)
                        print(f"=== DEBUG: Copied video to: {video_copy} ===")
                    else:
                        shutil.copy2(output_path, VIDEOS_DIR / video_filename)
                        print(f"=== DEBUG: Copied video to videos directory ===")
                    
                    print("=== DEBUG: Video generation completed successfully ===")
                    jobs[job_id].status = JobStatus.COMPLETED
                    jobs[job_id].progress = 100
                    jobs[job_id].videoUrl = video_filename
                    
                    # Clean up audio file after successful video generation
                    if audio_file_path:
                        try:
                            audio_path = Path(audio_file_path)
                            if audio_path.exists():
                                audio_path.unlink()
                                print(f"=== DEBUG: Cleaned up audio file: {audio_path} ===")
                        except Exception as cleanup_error:
                            print(f"=== ERROR: Failed to clean up audio file: {cleanup_error} ===")
                    
                    return
                    
            except subprocess.CalledProcessError as e:
                print(f"=== ERROR: Manim rendering failed on attempt {attempt + 1} ===")
                print(f"=== Command output (stdout) ===\n{e.stdout}")
                print(f"=== Command output (stderr) ===\n{e.stderr}")
                
                if DEBUG_MODE:
                    fail_file = generation_dir / f"fail-{attempt + 1}.py"
                    with open(fail_file, "w") as f:
                        f.write(manim_code)
                        f.write("\n\n# Error details from Manim rendering:\n")
                        f.write(f'error_message = """{e.stderr}"""')
                    print(f"=== DEBUG: Saved failed code to: {fail_file} ===")
                
                if attempt == max_retries:
                    jobs[job_id].status = JobStatus.FAILED
                    jobs[job_id].progress = 0
                    # Clean up audio file on final failure
                    if audio_file_path:
                        try:
                            audio_path = Path(audio_file_path)
                            if audio_path.exists():
                                audio_path.unlink()
                                print(f"=== DEBUG: Cleaned up audio file after failure: {audio_path} ===")
                        except Exception as cleanup_error:
                            print(f"=== ERROR: Failed to clean up audio file: {cleanup_error} ===")
                    raise HTTPException(status_code=500, detail=f"Failed to render video after {max_retries + 1} attempts: {e.stderr}")
                
                last_error = e.stderr
                last_code = manim_code
                attempt += 1
                continue
                
            except Exception as e:
                print(f"=== ERROR: Failed to process video on attempt {attempt + 1} ===")
                print(f"=== Error type: {type(e)} ===")
                print(f"=== Error details: {str(e)} ===")
                
                if DEBUG_MODE:
                    fail_file = generation_dir / f"fail-{attempt + 1}.py"
                    with open(fail_file, "w") as f:
                        f.write(manim_code)
                        f.write("\n\n# Error details from execution:\n")
                        f.write(f'error_message = """{str(e)}"""')
                    print(f"=== DEBUG: Saved failed code to: {fail_file} ===")
                
                if attempt == max_retries:
                    jobs[job_id].status = JobStatus.FAILED
                    jobs[job_id].progress = 0
                    # Clean up audio file on final failure
                    if audio_file_path:
                        try:
                            audio_path = Path(audio_file_path)
                            if audio_path.exists():
                                audio_path.unlink()
                                print(f"=== DEBUG: Cleaned up audio file after failure: {audio_path} ===")
                        except Exception as cleanup_error:
                            print(f"=== ERROR: Failed to clean up audio file: {cleanup_error} ===")
                    raise HTTPException(status_code=500, detail=f"Failed to process video after {max_retries + 1} attempts: {str(e)}")
                
                last_error = str(e)
                last_code = manim_code
                attempt += 1
                continue
                
    except Exception as e:
        print(f"=== ERROR: Exception in system design video job {job_id}: {str(e)} ===")
        jobs[job_id].status = JobStatus.FAILED
        jobs[job_id].progress = 0
        # Clean up audio file on any unexpected error
        if audio_file_path:
            try:
                audio_path = Path(audio_file_path)
                if audio_path.exists():
                    audio_path.unlink()
                    print(f"=== DEBUG: Cleaned up audio file after error: {audio_path} ===")
            except Exception as cleanup_error:
                print(f"=== ERROR: Failed to clean up audio file: {cleanup_error} ===")
        raise

@app.post("/generate-video")
async def generate_video(
    background_tasks: BackgroundTasks,
    request: ConceptRequest
):
    """Start a system design video generation job"""
    audio_files = []  # Track audio files for cleanup
    try:
        # Create a new job
        job_id = str(uuid4())
        jobs[job_id] = JobMetadata(
            job_id=job_id,
            status=JobStatus.PENDING,
            progress=0
        )

        print(f"=== DEBUG: Starting system design video generation for query: {request.query} ===")
        
        # Step 1: Generate system design JSON
        print("=== DEBUG: Step 1 - Generating system design JSON ===")
        messages = [{"role": "user", "content": request.query}]
        concept_response = generate_concepts(messages, is_pro=request.is_pro)
        json_content = concept_response["message"]["content"]
        
        # Step 2: Generate voiceover script
        print("=== DEBUG: Step 2 - Generating voiceover script ===")
        script_response = generate_text(messages, is_pro=request.is_pro)
        script_content = script_response["message"]["content"]
        
        # Step 3: Generate audio from script
        print("=== DEBUG: Step 3 - Generating audio from script ===")
        scenes = [script_content]  # Wrap in list since the method expects multiple scenes
        audio_files = await generate_and_prepare_audio_files(scenes)
        
        if not audio_files:
            raise Exception("Failed to generate audio files")
            
        # Get the audio file path and duration
        audio_file = audio_files[0]  # We only have one audio file
        audio_file_path = str(Path.cwd() / AUDIO_DIR / audio_file.filename)  # Use absolute path
        audio_duration = get_audio_duration(audio_file_path)
        
        print(f"=== DEBUG: Generated audio file: {audio_file_path} with duration {audio_duration}s ===")
        
        # Save JSON to file only in debug mode
        if DEBUG_MODE:
            json_filename = f"{uuid4()}.json"
            json_path = JSON_DIR / json_filename
            print(f"=== DEBUG: Saving JSON to {json_path} ===")
            with open(json_path, 'w') as f:
                f.write(json_content)
            print("=== DEBUG: JSON saved successfully ===")
        
        # Start the background task
        background_tasks.add_task(
            process_video_job,
            job_id=job_id,
            user_query=request.query,
            json_content=json_content,
            is_pro=request.is_pro,
            audio_file_path=audio_file_path,
            audio_duration=audio_duration
        )
        
        return {"job_id": job_id}
        
    except Exception as e:
        print(f"=== ERROR: Exception in generate_system_design_video: {str(e)} ===")
        # Clean up audio files if there's an error
        for audio_file in audio_files:
            try:
                if hasattr(audio_file, 'file'):
                    audio_file.file.close()
                audio_path = AUDIO_DIR / audio_file.filename
                if audio_path.exists():
                    audio_path.unlink()
                    print(f"=== DEBUG: Cleaned up audio file: {audio_path} ===")
            except Exception as cleanup_error:
                print(f"=== ERROR: Failed to clean up audio file: {cleanup_error} ===")
        raise HTTPException(status_code=500, detail=str(e))

@app.api_route("/delete/videos", methods=["POST", "DELETE"])
async def delete_videos(filenames: List[str] = Body(...)):
    results = []
    for filename in filenames:
        if "/" in filename or "\\" in filename:
            results.append({"filename": filename, "status": "error", "message": "Invalid filename"})
            continue
            
        video_path = VIDEOS_DIR / filename
        try:
            if not video_path.exists():
                results.append({"filename": filename, "status": "error", "message": "File not found"})
                continue
                
            video_path.unlink()
            results.append({"filename": filename, "status": "success", "message": "Deleted"})
            
        except Exception as e:
            print(f"=== ERROR: Failed to delete video {filename}: {e} ===")
            results.append({"filename": filename, "status": "error", "message": str(e)})
    
    return {"results": results}
