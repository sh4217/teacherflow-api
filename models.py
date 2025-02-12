from typing import NamedTuple, List, Literal, Optional, TypedDict
from pydantic import BaseModel
from enum import Enum

class AudioFile(NamedTuple):
    path: str
    duration: float

class ChatMessage(TypedDict):
    role: Literal['user', 'assistant', 'system', 'developer']
    content: str
    videoUrl: Optional[str]

class JobStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"

class JobMetadata(BaseModel):
    job_id: str
    status: JobStatus
    progress: float = 0.0
    videoUrl: Optional[str] = None

class VideoRequest(BaseModel):
    query: str
    is_pro: bool = False

class VideoStreamResponse(BaseModel):
    """Model for video streaming response metadata"""
    content_type: str
    content_length: int
    content_range: Optional[str] = None
    accept_ranges: str = "bytes"
    status_code: int = 200

class Scene(BaseModel):
    """A full scene for a Manim video"""
    synopsis: str         # Description of what the scene will cover
    concepts: List[str]   # Key concepts to include in the scene
    script: str           # Script for the voice-over audio that will be added to the scene
    visuals: str          # Description of the visuals for the scene that will eventually be written in Manim code
    audio_path: Optional[str] = None         # Path to the audio file for this scene
    audio_duration: Optional[float] = None   # Duration of the audio file in seconds

class VideoPlan(BaseModel):
    """Components for generating an educational Manim video"""
    synopsis: str         # Description of what the video will cover
    concepts: List[str]   # Key concepts to include in the video
    plan: List[Scene]     # List of plans for each scene in the video

class ManimScene(BaseModel):
    """Python Manim code for an individual scene"""
    code: str

class VideoCode(BaseModel):
    """The Manim code for a video"""
    scenes: List[ManimScene]
