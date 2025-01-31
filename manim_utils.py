from typing import List, Optional
from manim import *
from audio_utils import get_audio_duration
from openai import OpenAI
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# -------------------------------------------------------------------
# 1) Helper function to call the OpenAI API and retrieve the snippet
# -------------------------------------------------------------------
def fetch_manim_construct_snippet_from_openai() -> str:
    """
    Calls OpenAI API to fetch exactly the code snippet for the `construct()` body.
    Returns a stripped Python code snippet or an empty string on error/invalid response.
    """

    # The environment variable 'OPENAI_API_KEY' must be set in your environment
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        print("=== WARNING: No OPENAI_API_KEY found. Returning empty snippet. ===")
        return ""
    client = OpenAI(api_key=openai_api_key)

    # The prompt: strictly instruct the model to return only the snippet
    prompt_text = """
        Return ONLY the Manim construct body code as a plain code block (no explanations).
        That code block is:

        <Code segment>
                \"\"\"Construct the scene with all segments.\"\"\"
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
        </Code segment>

        Do not wrap your answer in any markdown or text, including code fences 
        such as such as ```python or ```, other than the code.
        The user will handle code formatting and execution.
        """

    try:
        response = client.chat.completions.create(
            model="gpt-4o-2024-11-20",
            messages=[
                {
                    "role": "user",
                    "content": prompt_text
                }
            ],
            temperature=0.0
        )

        # Extract the full text from the response
        content = response.choices[0].message.content
        print(f"=== DEBUG: Raw OpenAI response ===\n{content}\n=== END DEBUG ===")

        # Attempt to locate code fences (``` ... ```) and extract the snippet inside
        snippet_code = content.strip()
        start_code = snippet_code.find("```")
        end_code = snippet_code.rfind("```")
        if start_code != -1 and end_code != -1 and start_code != end_code:
            # Extract between the first and last triple backticks
            snippet_code = snippet_code[start_code + 3 : end_code].strip()

        return snippet_code

    except Exception as e:
        print(f"=== ERROR: Exception when calling OpenAI API: {e} ===")
        return ""


# -------------------------------------------------------------------
# 2) Fallback: The original snippet (verbatim from your code)
# -------------------------------------------------------------------
_original_construct_snippet = '''"""Construct the scene with all segments."""
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
'''

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
        """
        Dynamically fetch and execute the Manim construct snippet from OpenAI;
        if the snippet is empty or invalid, fall back to the original snippet.
        """
        # snippet_code = fetch_manim_construct_snippet_from_openai()

        # # If the snippet is empty or malformed, use the fallback
        # if not snippet_code.strip():
        #     snippet_code = _original_construct_snippet

        # temporarily fall back to hardcoding the Manim logic
        # after testing Websocket works in prod, will debug LLM call
        snippet_code = _original_construct_snippet


        local_dict = {
            "self": self,
            "config": config,
            "ORIGIN": ORIGIN,
            "Exception": Exception,
            "print": print,
            "enumerate": enumerate,
            "max": max,
            "range": range,
        }

        exec(snippet_code, {}, local_dict)
