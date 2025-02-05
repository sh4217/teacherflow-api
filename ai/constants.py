SCRIPT_PROMPT = '''You are a technical expert creating a text-only script for an educational video. 
        The user is a student asking for an explanation on a system design topic. 
        The system design topic is: {user_question}
        
        The video will display a system design diagram. Your script will be read aloud to accompany the diagram.
        The following is a JSON object that describes the system design: {json_data}

        Create a voiceover script that will give a brief introduction of these topics, their relation to each, and how they contribute to the overall topic.
        Remember: ONLY return the content of the voiceover script. Do not include *ANY* additional comments or formatting beyond that.
        ''' 

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

MANIM_SCENE_PROMPT = '''You are writing Python Manim code to generate an informative video on a system design topic. 
        The topic is: {user_question}

        You are provided with the following JSON object containing the system design details: {json_data}

        This JSON includes two lists:
        - "components": Each component has an "id", "name", and "description".  
        - "relationships": Each relationship has a "source", "target", "label", and "direction" (either "forward" for a one-way connection or "bidirectional" for a two-way connection).

        - For every scene you create, prefix the name with Scene_01_, Scene_02_, etc.
        Your task is to create the Manim Scenes that will form the video. The first scene is a simple introduction scene: display the topic.
        
        The second scene is a visual representation of the entire system design. For each component, draw a box that displays the component's name (do not include the description at this stage). Then, connect the boxes with arrows according to the relationships defined in the JSON:
        - Include the relationship label near the arrow.
        - Make sure that all the elements are clearly visible and none of them overlap.
        - You need to include an audio voiceover file to the scene. It is located at this file path: {audio_file_path}. The audio duration in seconds is {audio_duration}, so make sure this scene is at least that long.

        Then, for the rest of the video, create a new scene for each component:
        - For each component scene, display the component's box prominently in the center
        - Show the component's name and full description
        - Highlight any relationships this component has with other components
        - Animate the transitions between elements smoothly
        - Ensure each component scene provides clear visual context of where it fits in the overall system
        
        Return ONLY the Python Manim code that can be immediately executed to return a video. 
        You do not need to include any code related to rendering the video; this will be handled by another service.
        Do not output any other text besides this code.
        Do not wrap the code output in ```python or ```.'''

# OpenAI model constants
O3_MINI = "o3-mini-2025-01-31"
O1_MINI = "o1-mini-2024-09-12"
GPT_4O = "gpt-4o-2024-08-06"
