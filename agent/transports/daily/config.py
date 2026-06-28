import os
import time

DEFAULT_BOT_NAME = "Voice Bot"
DEFAULT_ROOM_EXPIRY_SECS = 3600
DEFAULT_DAILY_API_URL = "https://api.daily.co/v1"


def get_daily_api_key() -> str:
    return os.getenv("DAILY_API_KEY", "").strip()


def get_bot_name() -> str:
    return os.getenv("DAILY_BOT_NAME", DEFAULT_BOT_NAME).strip() or DEFAULT_BOT_NAME


def get_room_expiry_epoch() -> int:
    raw = os.getenv("DAILY_ROOM_EXPIRY_SECS", str(DEFAULT_ROOM_EXPIRY_SECS)).strip()
    try:
        secs = int(raw)
    except ValueError:
        secs = DEFAULT_ROOM_EXPIRY_SECS
    return int(time.time()) + max(secs, 60)


def get_daily_api_url() -> str:
    return os.getenv("DAILY_API_URL", DEFAULT_DAILY_API_URL).strip().rstrip("/")
