"""
Pre-synthesize hold-phrase audio at startup, then inject into the pipeline
via on_function_calls_started so there is always audio while a tool runs.

Uses Google Cloud TTS (LINEAR16, 16 kHz) with the same service-account
credentials as the Gemini Live service — no extra credentials needed.
"""

import io
import json
import random
import wave
from typing import Optional

from loguru import logger

HOLD_TEXTS = [
    "Let me check that for you.",
    "Just a moment, I'll look that up.",
    "Give me a second, checking now.",
    "Hold on, looking that up.",
    "One moment while I check.",
]

_PCM_CLIPS: list[bytes] = []


def _wav_to_raw_pcm(wav_bytes: bytes) -> bytes:
    """Strip the WAV header and return raw 16-bit PCM samples."""
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        return wf.readframes(wf.getnframes())


async def prewarm(credentials_json: str) -> bool:
    """
    Pre-synthesize every hold phrase to raw 16-kHz 16-bit mono PCM.
    Safe to call multiple times; subsequent calls are no-ops.
    """
    global _PCM_CLIPS
    if _PCM_CLIPS:
        return True

    try:
        from google.cloud import texttospeech
        from google.oauth2 import service_account

        creds = service_account.Credentials.from_service_account_info(
            json.loads(credentials_json)
        )
        client = texttospeech.TextToSpeechClient(credentials=creds)

        clips: list[bytes] = []
        for text in HOLD_TEXTS:
            response = client.synthesize_speech(
                input=texttospeech.SynthesisInput(text=text),
                voice=texttospeech.VoiceSelectionParams(
                    language_code="en-IN",
                    ssml_gender=texttospeech.SsmlVoiceGender.FEMALE,
                ),
                audio_config=texttospeech.AudioConfig(
                    audio_encoding=texttospeech.AudioEncoding.LINEAR16,
                    sample_rate_hertz=16000,
                ),
            )
            clips.append(_wav_to_raw_pcm(response.audio_content))

        _PCM_CLIPS = clips
        logger.info(f"Hold phrases pre-synthesized ({len(_PCM_CLIPS)} clips)")
        return True

    except Exception as exc:
        logger.warning(f"Hold-phrase pre-synthesis failed — tool calls will be silent: {exc}")
        return False


def get_random_pcm() -> Optional[bytes]:
    """Return a random pre-synthesized PCM clip, or None if not ready."""
    return random.choice(_PCM_CLIPS) if _PCM_CLIPS else None
