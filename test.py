# test.py
import os
from pathlib import Path
from dotenv import load_dotenv

# 1. Force .env creation
env_path = Path(__file__).parent / ".env"
if not env_path.exists():
    with open(env_path, "w") as f:
        f.write("OPENAI_API_KEY=your_key_here\n")  # << REPLACE WITH REAL KEY

# 2. Load environment
load_dotenv(dotenv_path=env_path)

# 3. Debug checks
print(f".env location: {env_path}")
print(f"File exists: {env_path.exists()}")
print(f"API Key: {'SET' if os.getenv('OPENAI_API_KEY') else 'MISSING'}")

# 4. Test API connection
from openai import OpenAI
client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url="https://api.deepseek.com"
)

try:
    models = client.models.list()
    print("Success! Models:", [m.id for m in models.data])
except Exception as e:
    print("API Error:", e)