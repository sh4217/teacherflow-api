from pathlib import Path
from typing import Optional
from fastapi import HTTPException
from models import VideoStreamResponse

def get_video_file_response(video_path: Path, range_header: Optional[str] = None) -> VideoStreamResponse:
    """
    Generate appropriate response for video streaming based on range header.
    
    Args:
        video_path: Path to the video file
        range_header: Optional HTTP range header
        
    Returns:
        VideoStreamResponse with appropriate headers and content
    """
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Video not found")
    
    file_size = video_path.stat().st_size
    
    if range_header is None:
        return VideoStreamResponse(
            content_type="video/mp4",
            content_length=file_size,
            status_code=200
        )
    
    try:
        ranges = range_header.replace("bytes=", "").split("-")
        start = int(ranges[0]) if ranges[0] else 0
        end = int(ranges[1]) if len(ranges) > 1 and ranges[1] else file_size - 1
        
        if start >= file_size or start < 0 or end >= file_size or start > end:
            raise ValueError("Invalid range")
            
        chunk_size = end - start + 1
        
        return VideoStreamResponse(
            content_type="video/mp4",
            content_length=chunk_size,
            content_range=f"bytes {start}-{end}/{file_size}",
            status_code=206
        )
    except (ValueError, IndexError):
        raise HTTPException(status_code=416, detail="Invalid range header")

def read_video_chunk(video_path: Path, start: int = 0, chunk_size: Optional[int] = None) -> bytes:
    """
    Read a chunk of video file from the specified start position.
    
    Args:
        video_path: Path to the video file
        start: Starting byte position
        chunk_size: Number of bytes to read (None for entire file)
        
    Returns:
        Bytes of the video chunk
    """
    if chunk_size is None:
        return video_path.read_bytes()
        
    try:
        with open(video_path, "rb") as video:
            video.seek(start)
            return video.read(chunk_size)
    except (IOError, OSError) as e:
        raise HTTPException(status_code=500, detail="Error reading video file") from e
