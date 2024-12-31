import os
import google.generativeai as genai

class Gemini:
    def __init__(self, model_name=None):
        genai.configure(api_key=os.environ.get("GOOGLE_API_KEY"))
        if model_name is None:
            # model_name = 'gemini-1.5-pro-001'
            model_name = 'gemini-2.0-flash-exp'
            # model_name = 'gemini-2.0-flash-thinking-exp'
            # model_name = 'gemini-exp-1206'
        self.model = genai.GenerativeModel(model_name)

    def generate_response(self, prompt, temp=1):
        """
        Generates text using the Gemini model.

        Args:
            prompt (str): The prompt to generate text from.
            temp (int): The temperature required.

        Returns:
            str: The generated text.
        """
        try:
            response = self.model.generate_content(
                prompt, 
                generation_config=genai.types.GenerationConfig(
                    temperature=temp
                )
            )
            return response.text

        except Exception as e:
            print(f"Error generating response: {e}")
            return None
        
        def generate_response_json(self, prompt, json, temp=1):
            """
            Generates a json response using the Gemini model.

            Args:
                prompt (str): The prompt to generate text from.
                temp (int): The temperature required.
                json (str): The json schema to use.
            
            Returns:
                str: The generated json.
            """
            try:
                response = self.model.generate_content(
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=temp,
                        response_mime_type="application/json", 
                        response_schema=json
                    )
                )
                return response.text
            except Exception as e:
                print(f"Error generating response: {e}")
                return None