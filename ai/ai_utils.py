from openai import OpenAI
import os
from dotenv import load_dotenv
from typing import List, Dict
import time
from pathlib import Path
from .constants import *
from models import ChatMessage, VideoPlan, VideoCode

load_dotenv()

openai_api_key = os.getenv("OPENAI_API_KEY")
if not openai_api_key:
    print("=== WARNING: No OPENAI_API_KEY found in environment variables ===")
    client = None
else:
    client = OpenAI(api_key=openai_api_key)

MAX_RETRIES = 2
RETRY_DELAY = 0.2

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

def generate_video_plan(messages: List[ChatMessage]) -> Dict[str, ChatMessage]:
    """
    Generate a detailed video plan using OpenAI's chat completion API with structured output.
    The response will be a VideoPlan object containing a synopsis, list of concepts, and a list of FullScene objects
    that break down the video into logical segments.

    Args:
        messages (List[ChatMessage]): List of chat messages.

    Returns:
        Dict containing the assistant's response message with the JSON-formatted video plan.
    """
    print(f"=== DEBUG: Starting generate_video_plan with {len(messages)} messages ===")
    print(f"=== DEBUG: User query: {messages[0]['content']} ===")
    
    if client is None:
        raise Exception("OpenAI client not initialized")

    formatted_prompt = VIDEO_PLAN_PROMPT.format(userTopic=messages[0]['content'])
    
    api_messages = [{"role": "developer", "content": formatted_prompt}, *messages]

    try:
        print("=== DEBUG: Calling OpenAI API for structured video plan ===")
        completion = client.beta.chat.completions.parse(
            model=GPT_4O,
            messages=api_messages,
            response_format=VideoPlan,
            temperature=0
        )

        video_plan = completion.choices[0].message.parsed
        json_response = video_plan.model_dump_json(indent=2)
        
        return {"message": {"role": "assistant", "content": json_response}}

    except Exception as e:
        print(f"=== ERROR: Exception when calling OpenAI API: {e} ===")
        raise Exception(f"Failed to generate response: {str(e)}")

def generate_manim_scenes(video_plan: VideoPlan) -> VideoCode:
    """
    Generate Manim code for each scene in the video plan using OpenAI's chat completion API.
    Returns a VideoCode object containing a list of ManimScene objects.
    
    Args:
        video_plan: The complete video plan with scenes and audio information
        
    Returns:
        VideoCode: Object containing list of ManimScene objects with Python code for each scene
    """
    if client is None:
        raise Exception("OpenAI client not initialized")

    try:
        completion = client.beta.chat.completions.parse(
            model=GPT_4O,
            messages=[{
                "role": "user",
                "content": MANIM_CODE_PROMPT.format(videoPlan=video_plan.model_dump_json())
            }],
            response_format=VideoCode,
            temperature=0
        )

        return completion.choices[0].message.parsed
    
    except Exception as e:
        print(f"=== ERROR: Exception when calling OpenAI API for Manim code generation: {e} ===")
        raise Exception(f"Failed to generate Manim scenes: {str(e)}")

def retry_manim_scene_generation(scene_code: str, error_message: str) -> str:
    """
    Regenerate a single Manim scene that had rendering errors.
    
    Args:
        scene_code (str): The original scene code that failed
        error_message (str): The error message from the failed attempt
        
    Returns:
        str: The fixed Manim code for the scene
    """
    if client is None:
        raise Exception("OpenAI client not initialized")

    try:
        response = client.chat.completions.create(
            model=GPT_4O,
            messages=[
                {
                    "role": "user",
                    "content": MANIM_ERROR_PROMPT.format(
                        previous_code=scene_code,
                        error_message=error_message
                    )
                }
            ]
        )

        return response.choices[0].message.content

    except Exception as e:
        print(f"=== ERROR: Exception when calling OpenAI API for Manim error fix: {e} ===")
        return ""

