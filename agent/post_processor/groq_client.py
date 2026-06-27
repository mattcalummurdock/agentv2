import json
import os

from groq import Groq

from post_processor.config import get_groq_model

_groq_client: Groq | None = None


def get_groq_client() -> Groq:
    global _groq_client
    if _groq_client is None:
        api_key = os.getenv("GROQ_API_KEY", "").strip()
        if not api_key:
            raise ValueError("GROQ_API_KEY must be set in .env")
        _groq_client = Groq(api_key=api_key)
    return _groq_client


def groq_json(system: str, user: str) -> dict:
    client = get_groq_client()
    response = client.chat.completions.create(
        model=get_groq_model(),
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content or "{}"
    return json.loads(raw)
