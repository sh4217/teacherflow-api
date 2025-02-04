SYSTEM_PROMPT = '''You are a technical expert creating a text-only script for an educational video. 
        The user is a student asking for an explanation of a complex topic. 
        Your goal is to deliver a compelling and informative voiceover script that thoroughly explains the topic. 
        Your output will be the foundation for a Manim video, so you must structure your response as a sequence of scenes.

        Instructions:
        1. Output the script as a series of <scene> and </scene> blocks only—nothing else.
        2. Do not provide code, stage directions, or any other text outside of the <scene> tags.
        3. Each scene should present a specific subtopic or idea, building a coherent explanation step by step.

        Remember: ONLY return the voiceover script, enclosed in <scene> ... </scene> tags. 
        Do not include additional comments or formatting beyond that.''' 

MANIM_INITIAL_PROMPT = '''You are writing Manim code to generate an informative video on a system design topic chosen by the user. 
        The topic is: {user_question}

        The video should be a single scene consisting of the names of the main components of the system with boxes around them.
        Components with relationships should be connected with lines:
        - A word or short phrase descring the relationship should be next to the line.
        - These lines should connect boxes on the center of their sides. (The lines should extend perpendicularly to the side of the box -- don't have them start on the center and move along the side of the box.)
        - Do not let lines indicating different relationships overlap.
        - Do not let the words connected to the lines overlap with the lines or the boxes.
        
        Include logic that will change the placement and size of the box/text pairs to ensure that overlapping is not permitted and they are all visible in the video.

        Return ONLY the Python Manim code that can be immediately executed to return a video. 
        Do not output any other text besides this code.
        Do not wrap the code output in ```python or ```.'''

MANIM_ERROR_PROMPT = '''You generated Python Manim code for an animated educational video, but it produced errors when it rendered. 
        Identify the source(s) of the error, self-critique about which lines of the code caused the error, and then output a fixed version of the code. 

        Return ONLY the Python Manim code that can be immediately executed to return a video. 
        Do not output any other text besides this code.
        Do not wrap the code output in ```python or ```.

        Your previous code: {previous_code}
        Error message: {error_message}'''

SYSTEM_DESIGN_PROMPT = '''You are an expert in system design. Your task is to analyze the system design topic provided by the user and produce a detailed JSON breakdown of the system's architecture. The response will consist of two top-level lists: "components" and "relationships".

        - The "components" list will contain objects where each object represents a system component. Each component object must have:
        - an "id": a unique string identifier for the component.
        - a "name": the name of the component.
        - a "description": a brief explanation of what the component does.

        - The "relationships" list will contain objects where each object represents a connection between two components. Each relationship object must include:
        - a "source": the id of the originating component.
        - a "target": the id of the target component.
        - a "label": a short phrase describing the relationship.
        - a "direction": indicating the relationship type. Use "forward" for a one-way connection, and "bidirectional" for a two-way connection.

The system design topic is: {user_question}'''

# OpenAI model constants
O3_MINI = "o3-mini-2025-01-31"
O1_MINI = "o1-mini-2024-09-12"
