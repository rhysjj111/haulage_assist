import pathlib
import textwrap

import google.generativeai as genai



genai.configure(api_key=GOOGLE_API_KEY)

# for m in genai.list_models():
#     if 'generateContent' in m.supported_generation_methods:
#         print(m.name)
print('Determining model...')
model = genai.GenerativeModel('gemini-1.5-pro-latest')
print('Model determined.')
print('Question: Explain the difference between a for loop and a while loop in Python.')
print('Generating response...')
response = model.generate_content("Explain the difference between a for loop and a while loop in Python. Keep the response short.")
print(response.text)