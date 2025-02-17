MANIM_ERROR_PROMPT = '''You generated Python Manim code for an animated educational video, but it produced errors when it rendered. 
        Return a fixed version of the code. Update ONLY the part of the code that has the error; otherwise, return the full, original code intact.
        IMPORTANT: You must use the exact same value for audio_path as it was in the original code.

        Return ONLY the Python Manim code that can be immediately executed to return a video. 
        Do not output any other text besides this code.
        Do not wrap the code output in ```python or ```.

        Your previous code: {previous_code}
        Error message: {error_message}'''

VIDEO_PLAN_PROMPT = '''You are an expert educational content creator specializing in creating clear, engaging video explanations. Your task is to create a detailed plan for an educational Manim video that will explain the Manim video that will explain the following topic: {userTopic}.

        The output should be a VideoPlan object that contains all the necessary components for generating an educational video. The VideoPlan should include:
        - synopsis: A clear description of what the video will teach and its key learning objectives
        - concepts: A list of 3-10 fundamental concepts that the video will explain, depending on topic complexity
        - plan: A list of FullScene objects that break down the topic into logical segments

        Each FullScene in the plan represents a complete scene in the final video and should include:
        - synopsis: A 1-2 sentence description of what this specific scene will cover
        - concepts: A list of 2-3 key concepts that this scene focuses on
        - script: The natural, conversational voiceover script for this scene
        - visuals: A clear description of what should appear on screen, focusing on simple but effective visuals.
                * Use text and relationship-based visuals, like text blocks, boxes, arrows, diagrams, tables, etc.
                * Do not attempt to build graphics out of geometric shapes.

        Guidelines for creating effective educational content:
        - Start with an engaging introduction that hooks the viewer
        - Break complex topics into digestible segments
        - Build concepts progressively
        - End with practical examples or applications
        - Write scripts in a conversational tone
        - Ensure visual descriptions are specific enough for Manim implementation, including:
        * Clear, minimalist visual elements
        * Simple animations and transitions
        * Clean layout and spacing'''

MANIM_CODE_PROMPT = '''You are an expert in creating educational animations using the Manim library. Your task is to convert a VideoPlan into executable Manim Python code. You will receive a VideoPlan containing scenes with scripts and visual descriptions, and you need to generate the corresponding Manim code for each scene.
        The output should be a VideoCode object that contains a list of ManimScene objects. Each ManimScene should include:
        - code: A complete, self-contained Python code string that implements one scene from the VideoPlan using Manim. The code should be ready to execute without any modifications.

        Guidelines for writing effective Manim code:
        - Each scene should be a separate class that inherits from Scene
        - Use descriptive class names prefixed with Scene_# (e.g., Scene_01_Introduction)
        - Make sure to include the audio file for each scene in the beginning of the code.
                * Its path location is set as audio_path for each scene.
                * Make sure the scene lasts at least as long as audio_duration in seconds.
        - Visuals should be simple and minimalistic.
                * Use text and relationship-based visuals, like text blocks, boxes, arrows, diagrams, tables, etc.
                * Do not attempt to build graphics out of geometric shapes.
                * Make sure to arrange visuals so they are evenly-spaced and not overlapping.
        - DO NOT INCLUDE any image files, like .png, .jpg, .ico, .svg, etc. -- you do not have access to image files and any attempt to include them are hallucinations.

        Include the standard Manim import:
        from manim import *

        The input VideoPlan is: {videoPlan}'''

# OpenAI model constants
O3_MINI = "o3-mini-2025-01-31"
O1_MINI = "o1-mini-2024-09-12"
GPT_4O = "gpt-4o-2024-11-20"
