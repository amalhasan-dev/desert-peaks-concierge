"""Lists the Gemini models your API key can use.

Run from the repo root:  python scripts/list_models.py
"""

from dotenv import load_dotenv
from google import genai

load_dotenv("park_concierge/.env")
client = genai.Client()
for m in client.models.list():
    if "generateContent" in (m.supported_actions or []) and "flash" in m.name:
        print(m.name.replace("models/", ""))
