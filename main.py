from audio_utils import validate_audio_file, get_audio_duration
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from uuid import uuid4
from typing import Optional, List
from pathlib import Path
from manim import *
import tempfile
import shutil
from fastapi.staticfiles import StaticFiles

app = FastAPI()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Path to Next.js public/generated-videos directory
VIDEOS_DIR = Path("videos")  # This will be relative to where the app is running

# Ensure the directory exists on startup
VIDEOS_DIR.mkdir(exist_ok=True)

# Mount the videos directory as a static file directory
app.mount("/videos", StaticFiles(directory="videos"), name="videos")

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
        self.MIN_FONT_SIZE = 40  # Minimum readable font size
        self.INITIAL_FONT_SIZE = 72  # Initial font size
        
    def create_text(self, content: str, font_size: float) -> MarkupText:
        """Create a MarkupText object with consistent styling parameters."""
        return MarkupText(
            content,
            line_spacing=1.2,
            font_size=font_size,
            width=config.frame_width * 0.8
        )

    def construct(self):
        frame_height = config.frame_height
        
        for i, segment in enumerate(self.segments):
            # Clear the previous scene
            self.remove(*self.mobjects)
            
            # Create initial text
            text = self.create_text(segment.text, self.INITIAL_FONT_SIZE)
            
            # If text is too tall, gradually reduce font size until it fits
            while text.height > frame_height * 0.85 and text.font_size > self.MIN_FONT_SIZE:
                current_size = text.font_size
                new_size = max(self.MIN_FONT_SIZE, current_size * 0.95)
                text = self.create_text(segment.text, new_size)
            
            # Center the text
            text.move_to(ORIGIN)
            
            # Add the text to the scene
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
            
            # Add a small pause between scenes
            if i < len(self.segments) - 1:
                self.wait(0.25)

@app.post("/generate-video")
async def generate_video(
    texts: List[str] = Form(...),
    audio_files: List[UploadFile] = File(...)
):
    if len(texts) != len(audio_files):
        raise HTTPException(status_code=400, detail="Number of texts must match number of audio files")

    temp_files = []  # Track temporary files for cleanup
    try:
        # Create videos directory if it doesn't exist
        VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
        
        # Generate unique filename for final video
        video_filename = f"{uuid4()}.mp4"
        video_path = VIDEOS_DIR / video_filename
        
        # Save audio files to temp files
        audio_paths = []
        for audio in audio_files:
            # Validate audio file
            is_valid, error_message = validate_audio_file(audio)
            if not is_valid:
                raise HTTPException(status_code=400, detail=error_message)
            
            # Stream audio to temp file instead of loading it all into memory
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_audio:
                shutil.copyfileobj(audio.file, temp_audio)
                audio_paths.append(temp_audio.name)
                temp_files.append(temp_audio.name)

        # Create scene segments
        segments = [
            SceneSegment(text, audio_path)
            for text, audio_path in zip(texts, audio_paths)
        ]

        # Create a temporary directory for Manim output
        with tempfile.TemporaryDirectory() as temp_dir:
            # Configure Manim
            config.media_dir = temp_dir
            config.quality = "medium_quality"
            config.output_file = "animation"
            
            # Create and render the combined scene
            scene = CombinedScript(segments)
            scene.render()
            
            # Find the generated video
            generated_video = Path(temp_dir) / "videos" / "720p30" / "animation.mp4"
            if not generated_video.exists():
                raise Exception("Video file not generated")
                
            # Copy the video to the final destination
            shutil.copy(generated_video, video_path)
        
        return {"videoUrl": video_filename}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Clean up all temporary files
        for temp_file in temp_files:
            try:
                Path(temp_file).unlink()
            except Exception:
                pass  # Ignore cleanup errors

@app.get("/health")
async def health_check():
    return {"status": "healthy"} 