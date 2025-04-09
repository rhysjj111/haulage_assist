import google.generativeai as genai
import os

# Replace 'YOUR_API_KEY' with your actual Google API key
# GOOGLE_API_KEY = 'YOUR_API_KEY'

# Configure the genai library with your API key
genai.configure(api_key=os.environ.get("GOOGLE_API_KEY"))

# List all available models
models = genai.list_models()

# Print the names of each model
print("Available Gemini models:")
for model in models:
    # Check if the model is a generative model (can generate content)
    if 'generateContent' in model.supported_generation_methods:
        print(f"- {model.name}")