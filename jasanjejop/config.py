import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID", "0"))
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
JASANJEJOP_CHANNEL_URL = os.getenv("JASANJEJOP_CHANNEL_URL", "")

DB_PATH = "./chroma_db"
COOKIES_PATH = "./cookies.json"
STYLE_PROFILE_PATH = "./style_profile.json"
