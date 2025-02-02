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
from ai.ai_utils import generate_text, parse_scenes, generate_speech

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

# In-memory job store
jobs: Dict[str, JobMetadata] = {}

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