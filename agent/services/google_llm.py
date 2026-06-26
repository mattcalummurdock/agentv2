import json
import os
from typing import Optional

from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.services.google.gemini_live.vertex.llm import GeminiLiveVertexLLMService

from prompts.system import SYSTEM_INSTRUCTION
from prompts.tool_calls import TOOL_CALL_ANNOUNCEMENT

DEFAULT_MODEL_ID = "google/gemini-live-2.5-flash-native-audio"
DEFAULT_VOICE_ID = "Aoede"


def build_system_instruction() -> str:
    return f"{SYSTEM_INSTRUCTION.strip()}\n\n{TOOL_CALL_ANNOUNCEMENT.strip()}"


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


def create_llm(
    voice_id: str = DEFAULT_VOICE_ID,
    tools: Optional[ToolsSchema] = None,
) -> GeminiLiveVertexLLMService:
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT_ID")
    location = os.getenv("GOOGLE_CLOUD_LOCATION")

    return GeminiLiveVertexLLMService(
        credentials=fix_credentials(),
        project_id=project_id,
        location=location,
        tools=tools,
        settings=GeminiLiveVertexLLMService.Settings(
            model=DEFAULT_MODEL_ID,
            voice=voice_id,
            system_instruction=build_system_instruction(),
        ),
    )
