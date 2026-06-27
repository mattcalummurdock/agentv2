import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

load_dotenv(override=True)

AGENT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"

logger.add(
    AGENT_DIR / "postprocessor.log",
    rotation="10 MB",
    level="INFO",
    filter=lambda record: record["extra"].get("postprocessor", False),
)

pp_logger = logger.bind(postprocessor=True)

_postprocess_semaphore: asyncio.Semaphore | None = None


def is_postprocess_enabled() -> bool:
    if os.getenv("POSTPROCESS_ENABLED", "1").strip().lower() in ("0", "false", "no"):
        return False
    return bool(os.getenv("GROQ_API_KEY", "").strip())


def get_semaphore() -> asyncio.Semaphore:
    global _postprocess_semaphore
    if _postprocess_semaphore is None:
        limit = int(os.getenv("POSTPROCESS_MAX_CONCURRENT", "5"))
        _postprocess_semaphore = asyncio.Semaphore(limit)
    return _postprocess_semaphore


def get_database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise ValueError("DATABASE_URL must be set in .env")
    return url


def get_groq_model() -> str:
    return os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL).strip()
