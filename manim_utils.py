from typing import List, Optional
from manim import *
from audio_utils import get_audio_duration

class SceneSegment:
    def __init__(self, text: str, audio_path: Optional[str] = None):
        """Initialize a scene segment with text and optional audio.
        
        Args:
            text (str): The text to display in the scene
            audio_path (Optional[str]): Path to the audio file for this segment
        """
        self.text = text
        self.audio_path = audio_path
        self.has_audio = audio_path is not None
        self.duration = get_audio_duration(audio_path) if audio_path else 5.0

class CombinedScript(Scene):
    def __init__(self, segments: List[SceneSegment]):
        """Initialize the combined script scene.
        
        Args:
            segments (List[SceneSegment]): List of scene segments to render
        """
        super().__init__()
        self.segments = segments
        self.MIN_FONT_SIZE = 40
        self.INITIAL_FONT_SIZE = 72
        
    def create_text(self, content: str, font_size: float) -> MarkupText:
        """Create a text object with the given content and font size.
        
        Args:
            content (str): The text content to display
            font_size (float): Initial font size
            
        Returns:
            MarkupText: The configured text object
        """
        return MarkupText(
            content,
            line_spacing=1.2,
            font_size=font_size,
            width=config.frame_width * 0.8
        )

    def construct(self):
        """Construct the scene with all segments."""
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