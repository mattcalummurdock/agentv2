"""Daily.co room creation for browser voice sessions."""

from loguru import logger

import aiohttp

from transports.daily.config import get_daily_api_key, get_daily_api_url, get_room_expiry_epoch


async def create_daily_room() -> tuple[str, str]:
    """Create a Daily room and owner token for the voice bot."""
    api_key = get_daily_api_key()
    if not api_key:
        raise ValueError("DAILY_API_KEY is not set")

    api_url = get_daily_api_url()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{api_url}/rooms",
            headers=headers,
            json={
                "properties": {
                    "exp": get_room_expiry_epoch(),
                    "enable_chat": False,
                    "enable_emoji_reactions": False,
                }
            },
        ) as response:
            if response.status != 200:
                error_text = await response.text()
                logger.error(f"Failed to create Daily room: {response.status} - {error_text}")
                raise RuntimeError(f"Failed to create Daily room: {response.status}")

            room_data = await response.json()
            room_url = room_data.get("url")
            room_name = room_data.get("name")
            if not room_url or not room_name:
                raise RuntimeError("Invalid room data from Daily API")

        async with session.post(
            f"{api_url}/meeting-tokens",
            headers=headers,
            json={
                "properties": {
                    "room_name": room_name,
                    "is_owner": True,
                }
            },
        ) as response:
            if response.status != 200:
                error_text = await response.text()
                logger.error(f"Failed to create Daily token: {response.status} - {error_text}")
                raise RuntimeError(f"Failed to create Daily token: {response.status}")

            token_data = await response.json()
            token = token_data.get("token")
            if not token:
                raise RuntimeError("Invalid token data from Daily API")

    logger.info(f"Created Daily room: {room_url}")
    return room_url, token
