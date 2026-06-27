import os
from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise EnvironmentError(f"Required environment variable '{name}' is not set.")
    return value


# Telegram
API_ID: int = int(_require("TELEGRAM_API_ID"))
API_HASH: str = _require("TELEGRAM_API_HASH")
PHONE: str = _require("TELEGRAM_PHONE")

# Groq
GROQ_API_KEY: str = _require("GROQ_API_KEY")
GROQ_MODEL: str = "llama-3.1-8b-instant"

# Dialogue limits
CONTEXT_WINDOW: int = int(os.getenv("CONTEXT_WINDOW", "6"))
MAX_MESSAGES_PER_SESSION: int = int(os.getenv("MAX_MESSAGES_PER_SESSION", "6"))

# Paths (inside /app/data so the Docker volume covers them)
DATA_DIR: str = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)

DB_PATH: str = os.path.join(DATA_DIR, "history.db")
SESSION_PATH: str = os.path.join(DATA_DIR, "ownbot")  # Pyrogram appends .session
