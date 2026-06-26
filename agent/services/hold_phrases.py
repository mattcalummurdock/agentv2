"""
Pre-synthesize hold-phrase audio at startup, then inject into the pipeline
via on_function_calls_started so there is always audio while a tool runs.

Uses Gemini TTS (Google Cloud) with a style prompt for tone control — the
``prompt`` field on ``SynthesisInput`` steers delivery (accent, pace, warmth)
separately from the spoken text. See:
https://cloud.google.com/text-to-speech/docs/gemini-tts
"""

import io
import json
import random
import wave
from typing import Optional

from loguru import logger

from services.google_llm import DEFAULT_VOICE_ID

# Style instructions passed to Gemini TTS — not spoken aloud.
HOLD_STYLE_PROMPT = (
    "Say the following as Sarah, a warm Mr. Med pharmacy agent in India. "
    "Use conversational Indian English — natural pace, not slow or robotic. "
    "Sound reassuring, like a brief hold line while you look something up for the caller."
)

HOLD_TEXTS = [
    "Let me check that for you.",
    "Just a moment, I'll look that up.",
    "Give me a second, checking now.",
    "Hold on, looking that up.",
    "One moment while I check.",
]

TTS_MODEL = "gemini-3.1-flash-tts-preview"
TTS_LANGUAGE = "en-IN"
SAMPLE_RATE_HZ = 16000

_PCM_CLIPS: list[bytes] = []


def _wav_to_raw_pcm(wav_bytes: bytes) -> bytes:
    """Strip the WAV header and return raw 16-bit PCM samples."""
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        return wf.readframes(wf.getnframes())


def _synthesize_clip(client, text: str) -> bytes:
    from google.cloud import texttospeech

    response = client.synthesize_speech(
        input=texttospeech.SynthesisInput(
            text=text,
            prompt=HOLD_STYLE_PROMPT,
        ),
        voice=texttospeech.VoiceSelectionParams(
            language_code=TTS_LANGUAGE,
            name=DEFAULT_VOICE_ID,
            model_name=TTS_MODEL,
        ),
        audio_config=texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,
            sample_rate_hertz=SAMPLE_RATE_HZ,
        ),
    )
    return _wav_to_raw_pcm(response.audio_content)


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
            clips.append(_synthesize_clip(client, text))

        _PCM_CLIPS = clips
        logger.info(
            f"Hold phrases pre-synthesized ({len(_PCM_CLIPS)} clips, "
            f"model={TTS_MODEL}, voice={DEFAULT_VOICE_ID})"
        )
        return True

    except Exception as exc:
        logger.warning(f"Hold-phrase pre-synthesis failed — tool calls will be silent: {exc}")
        return False


def get_random_pcm() -> Optional[bytes]:
    """Return a random pre-synthesized PCM clip, or None if not ready."""
    return random.choice(_PCM_CLIPS) if _PCM_CLIPS else None
