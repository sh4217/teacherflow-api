from audio_utils import process_audio_files
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Body, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from uuid import uuid4
from typing import List, Dict, Optional, Set
from pathlib import Path
from manim import *
import tempfile
import shutil
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from manim_utils import SceneSegment, CombinedScript
from enum import Enum
from pydantic import BaseModel
import asyncio

print("=== DEBUG: Entering main.py file ===")

class ConnectionManager:
    def __init__(self):
        # job_id -> Set[WebSocket]
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        print("=== DEBUG: Initialized WebSocket connection manager ===")
    
    async def connect(self, websocket: WebSocket, job_id: str):
        await websocket.accept()
        if job_id not in self.active_connections:
            self.active_connections[job_id] = set()
        self.active_connections[job_id].add(websocket)
        print(f"=== DEBUG: New WebSocket connection for job {job_id} ===")
    
    def disconnect(self, websocket: WebSocket, job_id: str):
        if job_id in self.active_connections:
            self.active_connections[job_id].discard(websocket)
            if not self.active_connections[job_id]:
                del self.active_connections[job_id]
        print(f"=== DEBUG: WebSocket disconnected for job {job_id} ===")
    
    async def broadcast_job_update(self, job_id: str, data: dict):
        if job_id in self.active_connections:
            dead_connections = set()
            for connection in self.active_connections[job_id]:
                try:
                    await connection.send_json(data)
                except WebSocketDisconnect:
                    dead_connections.add(connection)
                except Exception as e:
                    print(f"=== ERROR: Failed to send WebSocket message: {e} ===")
                    dead_connections.add(connection)
            
            # Clean up dead connections
            for dead in dead_connections:
                self.disconnect(dead, job_id)

# Create a connection manager instance
manager = ConnectionManager()

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

# In-memory job store
jobs: Dict[str, JobMetadata] = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("=== DEBUG: FastAPI startup event triggered ===")
    yield
    print("=== DEBUG: FastAPI shutdown event triggered ===")

app = FastAPI(lifespan=lifespan)

print("=== DEBUG: Configuring CORS middleware ===")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://teacherflow.ai", "https://www.teacherflow.ai"],
    allow_credentials=True,
    allow_methods=["POST", "GET", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)

VIDEOS_DIR = Path("videos")
print(f"=== DEBUG: VIDEOS_DIR is set to: {VIDEOS_DIR.resolve()} ===")
VIDEOS_DIR.mkdir(exist_ok=True)

print("=== DEBUG: Mounting /videos static files ===")
app.mount("/videos", StaticFiles(directory="videos"), name="videos")

print("=== DEBUG: Defining health-check endpoint ===")

@app.get("/health")
async def health_check():
    print("=== DEBUG: /health endpoint was hit ===")
    return {"status": "healthy"}

@app.get("/debug/jobs/{job_id}")
async def get_job_status(job_id: str):
    """Debug endpoint to get job status"""
    print(f"=== DEBUG: Getting status for job {job_id} ===")
    print(f"=== DEBUG: Current jobs in store: {jobs} ===")
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs[job_id]

@app.post("/debug/jobs")
async def create_test_job():
    """Debug endpoint to create a test job"""
    job_id = str(uuid4())
    jobs[job_id] = JobMetadata(
        job_id=job_id,
        status=JobStatus.PENDING,
        progress=0.0
    )
    print(f"=== DEBUG: Created test job {job_id} ===")
    print(f"=== DEBUG: Current jobs in store: {jobs} ===")
    return {"job_id": job_id}

print("=== DEBUG: Defining /generate-video endpoint ===")

async def validate_request(texts: List[str], audio_files: List[UploadFile]):
    """Validate the incoming request data"""
    if len(texts) != len(audio_files):
        print("=== DEBUG: Mismatched number of texts and audio files ===")
        raise HTTPException(status_code=400, detail="Number of texts must match number of audio files")

def create_scene_segments(texts: List[str], audio_paths: List[str]) -> List[SceneSegment]:
    """Create scene segments from texts and audio paths"""
    return [
        SceneSegment(text, audio_path)
        for text, audio_path in zip(texts, audio_paths)
    ]

async def render_video(segments: List[SceneSegment], video_path: Path) -> None:
    """Render the video using Manim and copy to final destination"""
    with tempfile.TemporaryDirectory() as temp_dir:
        config.media_dir = temp_dir
        config.quality = "medium_quality"
        config.output_file = "animation"
        
        print("=== DEBUG: Rendering Manim scene ===")
        scene = CombinedScript(segments)
        scene.render()
        
        generated_video = Path(temp_dir) / "videos" / "720p30" / "animation.mp4"
        if not generated_video.exists():
            print("=== ERROR: Video file not generated by Manim ===")
            raise Exception("Video file not generated")
        
        # Copy the file while we're still in the context
        shutil.copy(generated_video, video_path)
        print(f"=== DEBUG: Copied generated video to final path {video_path} ===")

def cleanup_temp_files(temp_files: List[str]):
    """Clean up temporary files"""
    for temp_file in temp_files:
        try:
            Path(temp_file).unlink()
        except Exception:
            pass

@app.api_route("/delete/videos", methods=["POST", "DELETE"])
async def delete_videos(filenames: List[str] = Body(...)):
    print(f"=== DEBUG: Bulk delete request for {len(filenames)} videos ===")
    
    results = []
    for filename in filenames:
        if "/" in filename or "\\" in filename:
            print(f"=== DEBUG: Skipping invalid filename: {filename} ===")
            results.append({"filename": filename, "status": "error", "message": "Invalid filename"})
            continue
            
        video_path = VIDEOS_DIR / filename
        try:
            if not video_path.exists():
                print(f"=== DEBUG: Video file not found: {video_path} ===")
                results.append({"filename": filename, "status": "error", "message": "File not found"})
                continue
                
            video_path.unlink()
            print(f"=== DEBUG: Successfully deleted video: {video_path} ===")
            results.append({"filename": filename, "status": "success", "message": "Deleted"})
            
        except Exception as e:
            print(f"=== ERROR: Failed to delete video {filename}: {e} ===")
            results.append({"filename": filename, "status": "error", "message": str(e)})
    
    return {"results": results}

async def process_video_job(
    job_id: str,
    texts: List[str],
    audio_files: List[UploadFile]
):
    """Background task to process the video generation job"""
    temp_files = []
    
    try:
        # Update job status to in_progress
        jobs[job_id].status = JobStatus.IN_PROGRESS
        jobs[job_id].progress = 10
        await manager.broadcast_job_update(job_id, jobs[job_id].dict())
        await asyncio.sleep(0.1)
        
        # Validate request
        await validate_request(texts, audio_files)
        jobs[job_id].progress = 20
        await manager.broadcast_job_update(job_id, jobs[job_id].dict())
        await asyncio.sleep(0.1)
        
        # Ensure videos directory exists
        VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
        
        # Generate unique filename for the video
        video_filename = f"{uuid4()}.mp4"
        video_path = VIDEOS_DIR / video_filename
        
        # Process audio files
        audio_paths, new_temp_files = await process_audio_files(audio_files)
        temp_files.extend(new_temp_files)
        jobs[job_id].progress = 40
        await manager.broadcast_job_update(job_id, jobs[job_id].dict())
        await asyncio.sleep(0.1)
        
        try:
            # Create scene segments
            segments = create_scene_segments(texts, audio_paths)
            jobs[job_id].progress = 60
            await manager.broadcast_job_update(job_id, jobs[job_id].dict())
            await asyncio.sleep(0.1)
            
            # Render video
            await render_video(segments, video_path)
            jobs[job_id].progress = 90
            await manager.broadcast_job_update(job_id, jobs[job_id].dict())
            await asyncio.sleep(0.1)
            
            # Update job with success
            jobs[job_id].status = JobStatus.COMPLETED
            jobs[job_id].progress = 100
            jobs[job_id].videoUrl = video_filename
            await manager.broadcast_job_update(job_id, jobs[job_id].dict())
            
        finally:
            # Clean up all temporary files
            cleanup_temp_files(temp_files)
            # Clean up the uploaded files
            for audio_file in audio_files:
                try:
                    audio_file.file.close()
                    if hasattr(audio_file, 'filename') and isinstance(audio_file.filename, str):
                        try:
                            Path(audio_file.filename).unlink()
                        except:
                            pass
                except:
                    pass
            
    except Exception as e:
        print(f"=== ERROR: Exception in video processing job {job_id}: {e}")
        jobs[job_id].status = JobStatus.FAILED
        jobs[job_id].progress = 0
        await manager.broadcast_job_update(job_id, jobs[job_id].dict())
        raise

@app.post("/generate-video")
async def generate_video(
    background_tasks: BackgroundTasks,
    texts: List[str] = Form(...),
    audio_files: List[UploadFile] = File(...)
):
    """Start a video generation job and return immediately with a job ID"""
    print("=== DEBUG: /start-generate-video endpoint called ===")
    
    # Create a new job
    job_id = str(uuid4())
    jobs[job_id] = JobMetadata(
        job_id=job_id,
        status=JobStatus.PENDING,
        progress=0
    )
    
    # Save audio files to temporary files
    temp_audio_files = []
    saved_audio_files = []
    
    try:
        for audio_file in audio_files:
            # Create a temporary file with the audio content
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
            temp_audio_files.append(temp_file.name)
            
            # Read content and save to temp file
            content = await audio_file.read()
            temp_file.write(content)
            temp_file.close()
            
            # Reopen the file for reading
            file_handle = open(temp_file.name, 'rb')
            
            # Create a SpooledTemporaryFile for the UploadFile
            spooled_file = tempfile.SpooledTemporaryFile()
            shutil.copyfileobj(file_handle, spooled_file)
            spooled_file.seek(0)
            file_handle.close()
            
            # Create the UploadFile with the spooled content
            saved_file = UploadFile(
                file=spooled_file,
                filename=audio_file.filename or "audio.mp3",
                headers={"content-type": "audio/mpeg"}
            )
            saved_audio_files.append(saved_file)
    
        # Schedule the background task with saved files
        background_tasks.add_task(
            process_video_job,
            job_id=job_id,
            texts=texts,
            audio_files=saved_audio_files
        )
        
        return {"job_id": job_id}
        
    except Exception as e:
        # Clean up temp files if there's an error
        for temp_file in temp_audio_files:
            try:
                Path(temp_file).unlink()
            except:
                pass
        print(f"=== ERROR: Exception in start_generate_video: {str(e)} ===")
        raise

@app.websocket("/ws/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    """WebSocket endpoint for real-time job updates"""
    try:
        await manager.connect(websocket, job_id)
        
        # Send initial job status if job exists
        if job_id in jobs:
            await websocket.send_json(jobs[job_id].dict())
        
        try:
            # Keep the connection alive and handle any incoming messages
            while True:
                data = await websocket.receive_text()
                # For now, we just echo back any received messages
                await websocket.send_json({"message": f"Received: {data}"})
        except WebSocketDisconnect:
            manager.disconnect(websocket, job_id)
    except Exception as e:
        print(f"=== ERROR: WebSocket error for job {job_id}: {e} ===")
        try:
            manager.disconnect(websocket, job_id)
        except:
            pass

print("=== DEBUG: Finished loading main.py ===")
