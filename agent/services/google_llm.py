import json
import os
from typing import Any, Optional

from google.genai.types import ThinkingConfig, ThinkingLevel
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService

from prompts.system import SYSTEM_INSTRUCTION
from prompts.tool_calls import TOOL_GUIDANCE

DEFAULT_MODEL_ID = os.getenv(
    "GOOGLE_LIVE_MODEL", "models/gemini-3.1-flash-live-preview"
)
THINKING_LEVEL = os.getenv("GEMINI_THINKING_LEVEL", "minimal").strip().lower()
DEFAULT_VOICE_ID = "Aoede"
DEFAULT_TEMPERATURE = 0.2

_THINKING_LEVELS = {
    "minimal": ThinkingLevel.MINIMAL,
    "low": ThinkingLevel.LOW,
    "medium": ThinkingLevel.MEDIUM,
    "high": ThinkingLevel.HIGH,
}


def build_system_instruction() -> str:
    return (
        f"{SYSTEM_INSTRUCTION.strip()}\n\n{TOOL_GUIDANCE.strip()}\n\n"
        "LANGUAGE REMINDER: Reply in the caller's language from their first utterance. "
        "English only for the opening greeting before they speak. Never stay in English "
        "if they spoke Hindi, Tamil, Telugu, or any other language.\n"
        "LATENCY: Start speaking immediately. Keep replies to one or two short "
        "sentences at a natural conversational pace — never slow or drawn out.\n"
        "BANNED PHRASES when naming medicines: 'based on what you said', "
        "'this looks like', 'it seems like', 'sounds like you mean'."
    )


def fix_credentials() -> str:
    """
    Fix GOOGLE_VERTEX_CREDENTIALS so Pipecat can parse it.
    Supports both file paths and JSON strings.
    """
    creds = os.getenv("GOOGLE_VERTEX_CREDENTIALS")

    if not creds:
        raise ValueError("GOOGLE_VERTEX_CREDENTIALS environment variable is not set")

    creds = creds.strip()
    file_path = None
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    if os.path.isabs(creds):
        if os.path.isfile(creds):
            file_path = creds
    elif os.path.isfile(creds):
        file_path = os.path.abspath(creds)
    else:
        potential_path = os.path.join(script_dir, creds)
        if os.path.isfile(potential_path):
            file_path = potential_path

    if not file_path and creds.endswith(".json"):
        potential_path = os.path.join(script_dir, creds)
        if os.path.isfile(potential_path):
            file_path = potential_path

    if file_path and os.path.isfile(file_path):
        try:
            with open(file_path, "r") as f:
                creds_dict = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            raise ValueError(f"Failed to read credentials from file '{file_path}': {e}") from e
    else:
        try:
            creds_dict = json.loads(creds)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"GOOGLE_VERTEX_CREDENTIALS is not valid JSON and not a valid file path. "
                f"Value: '{creds[:50]}...' Error: {e}"
            ) from e

    if "private_key" in creds_dict:
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")

    return json.dumps(creds_dict)


def _thinking_config() -> ThinkingConfig | None:
    level = THINKING_LEVEL
    if level in ("off", "none", "disabled", ""):
        return None
    thinking_level = _THINKING_LEVELS.get(level)
    if thinking_level is None:
        raise ValueError(
            f"Invalid GEMINI_THINKING_LEVEL={THINKING_LEVEL!r}. "
            f"Use one of: off, {', '.join(_THINKING_LEVELS)}"
        )
    return ThinkingConfig(thinking_level=thinking_level)


def _llm_settings(*, model_id: str, voice_id: str) -> dict[str, Any]:
    settings: dict[str, Any] = {
        "model": model_id,
        "voice": voice_id,
        "temperature": DEFAULT_TEMPERATURE,
        "system_instruction": build_system_instruction(),
    }
    thinking = _thinking_config()
    if thinking is not None:
        settings["thinking"] = thinking
    return settings


def create_llm(
    voice_id: str = DEFAULT_VOICE_ID,
    tools: Optional[ToolsSchema] = None,
    model_id: str = DEFAULT_MODEL_ID,
) -> GeminiLiveLLMService:
    """Gemini 3.1 Flash Live via the Gemini API (requires GOOGLE_API_KEY)."""
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError(
            "GOOGLE_API_KEY is required. Get one from https://aistudio.google.com/apikey"
        )

    return GeminiLiveLLMService(
        api_key=api_key,
        tools=tools,
        settings=GeminiLiveLLMService.Settings(
            **_llm_settings(model_id=model_id, voice_id=voice_id),
        ),
    )
