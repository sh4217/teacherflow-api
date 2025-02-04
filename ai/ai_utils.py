from openai import OpenAI
import os
from dotenv import load_dotenv
from typing import List, Dict, Literal, Optional, TypedDict
import time
from pathlib import Path
from .constants import *

from typing import List, Literal
from pydantic import BaseModel


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
        api_messages = [{"role": "developer", "content": SCRIPT_PROMPT}, *messages]
    else:
        api_messages = [{"role": "user", "content": SCRIPT_PROMPT}, *messages]

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

def generate_system_design(user_question: str, json_data: str, previous_code: str = None, error_message: str = None, audio_file_path: str = None, audio_duration: float = None) -> str:
    """
    Calls OpenAI API to generate Manim code for system design visualization, using both the question and JSON data.
    
    Args:
        user_question (str): The topic/question to generate a video about
        json_data (str): The JSON string containing system design components and relationships
        previous_code (str, optional): The previous code that failed
        error_message (str, optional): The error message from the failed attempt
        
    Returns:
        str: The Manim Python code as a string
    """
    print(f"=== DEBUG: Starting generate_system_design for question: {user_question} ===")
    
    if client is None:
        print("=== WARNING: OpenAI client not initialized. Returning empty snippet. ===")
        return ""

    # Construct the appropriate prompt based on whether this is a retry
    if previous_code and error_message:
        print("=== DEBUG: Generating retry prompt with error feedback ===")
        prompt_text = MANIM_ERROR_PROMPT.format(
            previous_code=previous_code,
            error_message=error_message
        )
    else:
        print("=== DEBUG: Generating initial system design prompt ===")
        # Include both the question and JSON data in the prompt
        prompt_text = MANIM_SCENE_PROMPT.format(
            user_question=user_question,
            json_data=json_data,
            audio_file_path=audio_file_path,
            audio_duration=audio_duration
        )
    
    print(f"=== DEBUG: Using prompt:\n{prompt_text}\n=== END PROMPT ===")

    try:
        print("=== DEBUG: Calling OpenAI API for Manim code generation ===")
        response = client.chat.completions.create(
            model=O3_MINI,
            messages=[
                {
                    "role": "user",
                    "content": prompt_text
                }
            ]
        )

        content = response.choices[0].message.content
        print(f"=== DEBUG: Received Manim code response ({len(content)} chars) ===")
        print(f"=== DEBUG: First 200 chars of response:\n{content[:200]}...\n=== END PREVIEW ===")
        return content

    except Exception as e:
        print(f"=== ERROR: Exception when calling OpenAI API: {e} ===")
        return ""

def generate_concepts(messages: List[ChatMessage], is_pro: bool = False) -> Dict[str, ChatMessage]:
    """
    Generate a system design breakdown using OpenAI's chat completion API with structured output.
    The response will consist of two top-level lists: "components" and "relationships". Each component
    will have an "id", "name", and "description". Each relationship will include a "source", "target",
    "label", and a "direction" (either "forward" for a one-way connection or "bidirectional" for a two-way connection).

    Args:
        messages (List[ChatMessage]): List of chat messages.
        is_pro (bool): Whether the user has a pro subscription.

    Returns:
        Dict containing the assistant's response message with the JSON-formatted system design breakdown.
    """
    print(f"=== DEBUG: Starting generate_concepts with {len(messages)} messages ===")
    print(f"=== DEBUG: User query: {messages[0]['content']} ===")
    
    if client is None:
        raise Exception("OpenAI client not initialized")

    # Format the system prompt with the user's question
    formatted_prompt = SYSTEM_DESIGN_PROMPT.format(user_question=messages[0]['content'])
    
    # Construct API messages with the formatted prompt
    api_messages = [{"role": "developer", "content": formatted_prompt}, *messages]
    print("=== DEBUG: Constructed API messages with system design prompt ===")
    print(f"=== DEBUG: System prompt:\n{formatted_prompt}\n=== END PROMPT ===")

    try:
        print("=== DEBUG: Calling OpenAI API for structured system design ===")
        # Call the beta API method that supports structured output.
        # The response_format parameter is set to the SystemDesign class, which defines the expected output.
        completion = client.beta.chat.completions.parse(
            model=GPT_4O,
            messages=api_messages,
            response_format=SystemDesign,
            temperature=0
        )

        # Retrieve the parsed SystemDesign response.
        system_design = completion.choices[0].message.parsed
        print(f"=== DEBUG: Received structured response with {len(system_design.components)} components and {len(system_design.relationships)} relationships ===")

        # Return the JSON-formatted system design response.
        json_response = system_design.model_dump_json(indent=2)
        print(f"=== DEBUG: Generated JSON response ({len(json_response)} chars) ===")
        print(f"=== DEBUG: First 200 chars of JSON:\n{json_response[:200]}...\n=== END PREVIEW ===")
        
        return {"message": {"role": "assistant", "content": json_response}}

    except Exception as e:
        print(f"=== ERROR: Exception when calling OpenAI API: {e} ===")
        raise Exception(f"Failed to generate response: {str(e)}")
