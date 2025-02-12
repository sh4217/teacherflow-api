from fastapi import FastAPI, HTTPException, UploadFile, BackgroundTasks, Body, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from uuid import uuid4
from typing import List, Dict
from pathlib import Path
from manim import *
from contextlib import asynccontextmanager
import asyncio
from videos.generation.generation_utils import (
    prepare_video_prerequisites,
    generate_and_render_video
)
from videos.streaming.streaming_utils import (
    get_video_file_response,
    read_video_chunk
)
from models import JobStatus, JobMetadata, VideoRequest

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
    allow_headers=["Content-Type", "Range"],
)

# Constants
VIDEOS_DIR = Path("videos")
VIDEOS_DIR.mkdir(exist_ok=True)

# Remove StaticFiles mount and add streaming endpoint
@app.get("/videos/{video_filename}")
async def stream_video(video_filename: str, request: Request):
    """Stream video with support for range requests"""
    video_path = VIDEOS_DIR / video_filename
    
    range_header = request.headers.get("range")
    response_data = get_video_file_response(video_path, range_header)
    
    # Prepare headers
    headers = {
        "accept-ranges": response_data.accept_ranges,
        "content-type": response_data.content_type,
        "content-length": str(response_data.content_length)
    }
    
    if response_data.content_range:
        headers["content-range"] = response_data.content_range
        
        # Parse start and chunk size from content range
        start = int(response_data.content_range.split(" ")[1].split("-")[0])
        chunk_size = response_data.content_length
        content = read_video_chunk(video_path, start, chunk_size)
    else:
        content = read_video_chunk(video_path)
    
    return Response(
        content=content,
        status_code=response_data.status_code,
        headers=headers
    )

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.get("/job-status/{job_id}")
async def get_job_status(job_id: str):
    """Endpoint to get job status"""
    print(f"=== DEBUG: Checking status for job {job_id} ===")
    if job_id not in jobs:
        print(f"=== ERROR: Job {job_id} not found in jobs dictionary ===")
        print(f"=== DEBUG: Current jobs: {list(jobs.keys())} ===")
        raise HTTPException(status_code=404, detail="Job not found")
    job_status = jobs[job_id]
    print(f"=== DEBUG: Returning status for job {job_id}: {job_status} ===")
    return job_status

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

    # Keeping isPro in the method signature; will be used later when o3-mini designs a full video plan.
    async def update_progress(progress: int, status: JobStatus = JobStatus.IN_PROGRESS):
        """Helper function to update job progress with sufficient sleep time"""
        jobs[job_id].status = status
        jobs[job_id].progress = progress
        await asyncio.sleep(0.5)
    
    try:
        print(f"=== DEBUG: Starting system design video job {job_id} ===")
        
        # Prepare initial prerequisites (content and script)
        video_plan = await prepare_video_prerequisites(
            user_query, update_progress
        )
        
        # Generate and render the video
        video_filename = await generate_and_render_video(
            video_plan,
            update_progress
        )
        
        # Update job status
        print(f"=== DEBUG: Video generation complete, updating job status for {job_id} ===")
        jobs[job_id].status = JobStatus.COMPLETED
        jobs[job_id].progress = 100
        jobs[job_id].videoUrl = video_filename
        print(f"=== DEBUG: Job {job_id} completed successfully with video: {video_filename} ===")
        
    except Exception as e:
        print(f"=== ERROR: Exception in system design video job {job_id}: {str(e)} ===")
        if job_id in jobs:  # Check if job still exists
            jobs[job_id].status = JobStatus.FAILED
            jobs[job_id].progress = 0
        raise
    finally:
        print(f"=== DEBUG: Video generation process complete for job {job_id} ===")
        # Add a small delay to ensure the job status is updated before any potential cleanup
        await asyncio.sleep(1)

@app.post("/generate-video")
async def generate_video(
    background_tasks: BackgroundTasks,
    request: VideoRequest
):
    """Start a video generation job, immediately return a job ID so the frontend can poll for status"""
    try:
        job_id = str(uuid4())
        print(f"=== DEBUG: Creating new video generation job {job_id} ===")
        jobs[job_id] = JobMetadata(
            job_id=job_id,
            status=JobStatus.PENDING,
            progress=0
        )

        print(f"=== DEBUG: Starting video generation for query: {request.query} ===")

        background_tasks.add_task(
            process_video_job,
            job_id=job_id,
            user_query=request.query,
            is_pro=request.is_pro
        )
        
        return {"job_id": job_id}
        
    except Exception as e:
        print(f"=== ERROR: Exception in generate_video: {str(e)} ===")
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
