import os

# Try to load environment variables from a .env file if python-dotenv is available.
try:
    from dotenv import load_dotenv
except Exception:
    def load_dotenv():
        return None

load_dotenv()

class Settings:
    def __init__(self):
        self.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
        self.BASE_URL = os.getenv("BASE_URL", "")


settings = Settings()
