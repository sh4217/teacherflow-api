import os
import sys

print("=== DEBUG: Entering main.py file ===")

try:
    from audio_utils import validate_audio_file, get_audio_duration
    print("=== DEBUG: Imported audio_utils successfully ===")
except Exception as e:
    print(f"=== ERROR: Failed to import audio_utils: {e}")
    sys.exit(1)  # Exit early so we see the error in logs

try:
    from fastapi import FastAPI, HTTPException, UploadFile, File, Form
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse
    print("=== DEBUG: Imported FastAPI and related modules successfully ===")
except Exception as e:
    print(f"=== ERROR: Failed to import FastAPI or related modules: {e}")
    sys.exit(1)

try:
    from uuid import uuid4
    from typing import Optional, List
    from pathlib import Path
    from manim import *
    import tempfile
    import shutil
    from fastapi.staticfiles import StaticFiles
    print("=== DEBUG: Imported other dependencies (uuid, manim, etc.) successfully ===")
except Exception as e:
    print(f"=== ERROR: Failed to import one of the dependencies (manim, etc.): {e}")
    sys.exit(1)

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("=== DEBUG: FastAPI startup event triggered ===")
    yield
    print("=== DEBUG: FastAPI shutdown event triggered ===")

app = FastAPI(lifespan=lifespan)

print("=== DEBUG: Configuring CORS middleware ===")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
        
        from uuid import uuid4
        video_filename = f"{uuid4()}.mp4"
        video_path = VIDEOS_DIR / video_filename
        print(f"=== DEBUG: Generated video filename: {video_filename} ===")

        audio_paths = []
        for audio in audio_files:
            is_valid, error_message = validate_audio_file(audio)
            if not is_valid:
                print(f"=== DEBUG: Audio file invalid: {error_message} ===")
                raise HTTPException(status_code=400, detail=error_message)
            
            import tempfile
            import shutil
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_audio:
                shutil.copyfileobj(audio.file, temp_audio)
                audio_paths.append(temp_audio.name)
                temp_files.append(temp_audio.name)
                print(f"=== DEBUG: Wrote temp audio file to {temp_audio.name} ===")

        segments = [
            SceneSegment(text, audio_path)
            for text, audio_path in zip(texts, audio_paths)
        ]

        import tempfile
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

print("=== DEBUG: Finished loading main.py ===")
