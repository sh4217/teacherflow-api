from audio_utils import validate_audio_file, get_audio_duration
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Body
from fastapi.middleware.cors import CORSMiddleware
from uuid import uuid4
from typing import Optional, List
from pathlib import Path
from manim import *
import tempfile
import shutil
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

print("=== DEBUG: Entering main.py file ===")

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

print("=== DEBUG: Defining /generate-video endpoint ===")

class SceneSegment:
    def __init__(self, text: str, audio_path: Optional[str] = None):
        self.text = text
        self.audio_path = audio_path
        self.has_audio = audio_path is not None
        self.duration = get_audio_duration(audio_path) if audio_path else 5.0

class CombinedScript(Scene):
    def __init__(self, segments: List[SceneSegment]):
        super().__init__()
        self.segments = segments
        self.MIN_FONT_SIZE = 40
        self.INITIAL_FONT_SIZE = 72
        
    def create_text(self, content: str, font_size: float) -> MarkupText:
        return MarkupText(
            content,
            line_spacing=1.2,
            font_size=font_size,
            width=config.frame_width * 0.8
        )

    def construct(self):
        frame_height = config.frame_height
        
        for i, segment in enumerate(self.segments):
            self.remove(*self.mobjects)
            text = self.create_text(segment.text, self.INITIAL_FONT_SIZE)
            while text.height > frame_height * 0.85 and text.font_size > self.MIN_FONT_SIZE:
                new_size = max(self.MIN_FONT_SIZE, text.font_size * 0.95)
                text = self.create_text(segment.text, new_size)
            text.move_to(ORIGIN)
            self.add(text)
            
            if segment.has_audio:
                try:
                    self.add_sound(segment.audio_path)
                    self.wait(segment.duration)
                except Exception as e:
                    print(f"Audio playback failed for scene {i}: {e}")
                    self.wait(5)
            else:
                self.wait(5)
            
            if i < len(self.segments) - 1:
                self.wait(0.25)

@app.post("/generate-video")
async def generate_video(
    texts: List[str] = Form(...),
    audio_files: List[UploadFile] = File(...)
):
    print("=== DEBUG: /generate-video endpoint called ===")
    if len(texts) != len(audio_files):
        print("=== DEBUG: Mismatched number of texts and audio files ===")
        raise HTTPException(status_code=400, detail="Number of texts must match number of audio files")

    temp_files = []
    try:
        VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
        
        video_filename = f"{uuid4()}.mp4"
        video_path = VIDEOS_DIR / video_filename
        print(f"=== DEBUG: Generated video filename: {video_filename} ===")

        audio_paths = []
        for audio in audio_files:
            is_valid, error_message = validate_audio_file(audio)
            if not is_valid:
                print(f"=== DEBUG: Audio file invalid: {error_message} ===")
                raise HTTPException(status_code=400, detail=error_message)
            
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_audio:
                shutil.copyfileobj(audio.file, temp_audio)
                audio_paths.append(temp_audio.name)
                temp_files.append(temp_audio.name)
                print(f"=== DEBUG: Wrote temp audio file to {temp_audio.name} ===")

        segments = [
            SceneSegment(text, audio_path)
            for text, audio_path in zip(texts, audio_paths)
        ]

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
                
            shutil.copy(generated_video, video_path)
            print(f"=== DEBUG: Copied generated video to final path {video_path} ===")
        
        return {"videoUrl": video_filename}
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"=== ERROR: Exception in /generate-video: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        for temp_file in temp_files:
            try:
                Path(temp_file).unlink()
            except Exception:
                pass

@app.delete("/delete/videos")
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

print("=== DEBUG: Finished loading main.py ===")
