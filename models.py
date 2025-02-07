from typing import NamedTuple, List, Literal, Optional, TypedDict
from pydantic import BaseModel
from enum import Enum

class AudioFile(NamedTuple):
    path: str
    duration: float

class Component(BaseModel):
    id: str            # Unique identifier for the component.
    name: str          # Name of the component.
    description: str   # Description of what the component does.

class Relationship(BaseModel):
    source: str        # The id of the originating component.
    target: str        # The id of the target component.
    label: str         # Description of the relationship.
    direction: Literal["forward", "bidirectional"]  # The arrow direction.

class SystemDesign(BaseModel):
    components: List[Component]
    relationships: List[Relationship]

class ChatMessage(TypedDict):
    role: Literal['user', 'assistant', 'system', 'developer']
    content: str
    videoUrl: Optional[str]

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

class Scene(BaseModel):
    name: str
    script: str

class SceneDesign(BaseModel):
    scenes: List[Scene]

class TextRequest(BaseModel):
    query: str
    is_pro: Optional[bool] = False

class ConceptRequest(BaseModel):
    query: str
    is_pro: bool = False

class ManimRequest(BaseModel):
    query: str

class VideoStreamResponse(BaseModel):
    """Model for video streaming response metadata"""
    content_type: str
    content_length: int
    content_range: Optional[str] = None
    accept_ranges: str = "bytes"
    status_code: int = 200
