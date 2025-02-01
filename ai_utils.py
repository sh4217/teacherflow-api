from openai import OpenAI
import os
from dotenv import load_dotenv
from typing import List, Dict, Literal, Optional, TypedDict
import re
import time
from pathlib import Path

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

    system_prompt = """You are an expert popularizer creating a text-only script for an educational video. 
        The user is a student asking for an explanation of a complex topic. 
        Your goal is to deliver a clear, precise, yet fun and engaging voiceover script that thoroughly explains the topic. 
        Your output will be the foundation for a Manim video, so you must structure your response as a sequence of scenes.

        Instructions:
        1. Output the script as a series of <scene> and </scene> blocks only—nothing else.
        2. Write the script in a lively, accessible tone while remaining accurate and in-depth.
        3. Speak directly to the student, using relatable examples or analogies where helpful.
        4. Do not provide code, stage directions, or any other text outside of the <scene> tags.
        5. Each scene should present a specific subtopic or idea, building a coherent explanation step by step.

        Remember: ONLY return the voiceover script, enclosed in <scene> ... </scene> tags. 
        Do not include additional comments or formatting beyond that."""

    model = "o3-mini-2025-01-31" if is_pro else "o1-mini-2024-09-12"
    
    # Construct API messages based on user type
    if is_pro:
        api_messages = [{"role": "developer", "content": system_prompt}, *messages]
    else:
        api_messages = [{"role": "user", "content": system_prompt}, *messages]

    try:
        response = client.chat.completions.create(
            model=model,
            messages=api_messages,
            temperature=1
        )

        completion = response.choices[0].message.content
        return {"message": {"role": "assistant", "content": completion}}
    
    except Exception as e:
        print(f"=== ERROR: Exception when calling OpenAI API: {e} ===")
        raise Exception("Failed to generate response")

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
            
            # Write the binary response directly to file
            with open(output_path, 'wb') as f:
                for chunk in response.iter_bytes():
                    f.write(chunk)
            return True

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
