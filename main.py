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
from videos.video_utils import (
    prepare_video_prerequisites,
    generate_and_render_video
)

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
    is_pro: bool
):
    """Background task to process the video generation job"""
    audio_file_path = None
    
    async def update_progress(progress: int, status: JobStatus = JobStatus.IN_PROGRESS):
        """Helper function to update job progress with sufficient sleep time"""
        jobs[job_id].status = status
        jobs[job_id].progress = progress
        await asyncio.sleep(0.5)
    
    try:
        print(f"=== DEBUG: Starting system design video job {job_id} ===")
        
        # Prepare all prerequisites (content, audio, paths)
        json_content, audio_file_path, audio_duration, output_path, generation_dir = await prepare_video_prerequisites(
            job_id, user_query, is_pro, update_progress
        )
        
        # Generate and render the video
        video_filename = await generate_and_render_video(
            job_id, user_query, json_content, audio_file_path, audio_duration,
            output_path, generation_dir, update_progress
        )
        
        # Update job status
        jobs[job_id].status = JobStatus.COMPLETED
        jobs[job_id].progress = 100
        jobs[job_id].videoUrl = video_filename
        
        # Clean up audio file after successful video generation
        if audio_file_path:
            try:
                if audio_file_path.exists():
                    audio_file_path.unlink()
                    print(f"=== DEBUG: Cleaned up audio file: {audio_file_path} ===")
            except Exception as cleanup_error:
                print(f"=== ERROR: Failed to clean up audio file: {cleanup_error} ===")
        
    except Exception as e:
        print(f"=== ERROR: Exception in system design video job {job_id}: {str(e)} ===")
        jobs[job_id].status = JobStatus.FAILED
        jobs[job_id].progress = 0
        # Clean up audio file on any unexpected error
        if audio_file_path:
            try:
                if audio_file_path.exists():
                    audio_file_path.unlink()
                    print(f"=== DEBUG: Cleaned up audio file after error: {audio_file_path} ===")
            except Exception as cleanup_error:
                print(f"=== ERROR: Failed to clean up audio file: {cleanup_error} ===")
        raise

@app.post("/generate-video")
async def generate_video(
    background_tasks: BackgroundTasks,
    request: ConceptRequest
):
    """Start a video generation job, immediately return a job ID so the frontend can poll for status"""
    try:
        job_id = str(uuid4())
        jobs[job_id] = JobMetadata(
            job_id=job_id,
            status=JobStatus.PENDING,
            progress=0
        )

        print(f"=== DEBUG: Starting system design video generation for query: {request.query} ===")

        background_tasks.add_task(
            process_video_job,
            job_id=job_id,
            user_query=request.query,
            is_pro=request.is_pro
        )
        
        return {"job_id": job_id}
        
    except Exception as e:
        print(f"=== ERROR: Exception in generate_system_design_video: {str(e)} ===")
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
