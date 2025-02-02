from openai import OpenAI
import os
from dotenv import load_dotenv
from typing import List, Dict, Literal, Optional, TypedDict
import re
import time
from pathlib import Path
from .constants import SYSTEM_PROMPT, O3_MINI, O1_MINI

# Load environment variables from .env file
load_dotenv()

# Initialize OpenAI client at module level
openai_api_key = os.getenv("OPENAI_API_KEY")
if not openai_api_key:
    print("=== WARNING: No OPENAI_API_KEY found in environment variables ===")
    client = None
else:
    client = OpenAI(api_key=openai_api_key)

# Constants for speech generation
MAX_RETRIES = 2
RETRY_DELAY = 0.2  # 200ms in seconds

class ChatMessage(TypedDict):
    role: Literal['user', 'assistant', 'system', 'developer']
    content: str
    videoUrl: Optional[str]

def generate_text(messages: List[ChatMessage], is_pro: bool = False) -> Dict[str, ChatMessage]:
    """
    Generate text response using OpenAI's chat completion API.
    
    Args:
        messages (List[ChatMessage]): List of chat messages
        is_pro (bool): Whether the user has a pro subscription
        
    Returns:
        Dict containing the assistant's response message
    """
    if client is None:
        raise Exception("OpenAI client not initialized")

    # Construct API messages based on user type
    if is_pro:
        api_messages = [{"role": "developer", "content": SYSTEM_PROMPT}, *messages]
    else:
        api_messages = [{"role": "user", "content": SYSTEM_PROMPT}, *messages]

    try:
        response = client.chat.completions.create(
            model=O3_MINI if is_pro else O1_MINI,
            messages=api_messages,
            temperature=1
        )

        completion = response.choices[0].message.content
        return {"message": {"role": "assistant", "content": completion}}
    
    except Exception as e:
        print(f"=== ERROR: Exception when calling OpenAI API: {e} ===")
        raise Exception(f"Failed to generate response: {str(e)}")

def parse_scenes(text: str) -> List[str]:
    """Extract content from <scene> tags in the text."""
    pattern = r'<scene>([\s\S]*?)</scene>'
    scenes = [match.group(1).strip() for match in re.finditer(pattern, text)]
    if not scenes:
        raise ValueError('No scenes found in text')
    return scenes

async def generate_speech(text: str, output_path: Path) -> bool:
    """
    Generate speech from text using OpenAI's TTS API.
    Returns True if successful, False if failed.
    """
    if client is None:
        raise Exception("OpenAI client not initialized")

    for attempt in range(MAX_RETRIES):
        try:
            if attempt > 0:
                time.sleep(RETRY_DELAY)

            response = client.audio.speech.create(
                model="tts-1",
                voice="alloy",
                input=text
            )
            
            # Handle potential file I/O errors when writing the audio chunks
            try:
                with open(output_path, 'wb') as f:
                    for chunk in response.iter_bytes():
                        f.write(chunk)
                return True
            except IOError as e:
                print(f"=== ERROR: Failed to write audio file: {e} ===")
                return False

        except Exception as e:
            print(f"=== ERROR: Speech synthesis attempt {attempt + 1} failed: {e} ===")
            print(f"=== ERROR: Exception type: {type(e)} ===")
            if attempt == MAX_RETRIES - 1:  # Last attempt
                return False

    return False

def fetch_manim_construct_snippet() -> str:
    """
    Calls OpenAI API to fetch exactly the code snippet for the `construct()` body.
    Returns a stripped Python code snippet or an empty string on error/invalid response.
    """
    if client is None:
        print("=== WARNING: OpenAI client not initialized. Returning empty snippet. ===")
        return ""

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
