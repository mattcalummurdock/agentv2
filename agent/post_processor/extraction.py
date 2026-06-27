from typing import Any

from post_processor.config import pp_logger
from post_processor.groq_client import groq_json


def detect_languages(conversation: str) -> list[str]:
    try:
        result = groq_json(
            "Detect all languages in the conversation including transliterated Indian languages. "
            'Return JSON: {"languages": ["english", "hindi", ...]}',
            f"Conversation:\n{conversation}",
        )
        languages = sorted(
            {
                lang.lower().strip()
                for lang in result.get("languages", [])
                if lang and str(lang).strip()
            }
        )
        return languages or ["english"]
    except Exception as e:
        pp_logger.error(f"Language detection failed: {e}")
        return ["english"]


def extract_caller_info(conversation: str) -> dict[str, Any]:
    try:
        result = groq_json(
            "Extract caller contact info from a Mr. Med pharmacy call. "
            "Return JSON with keys: name (string), "
            "bulk_offers (array of bulk/promo offers mentioned). "
            "Do not extract phone, email, or medicine names.",
            f"Conversation:\n{conversation}",
        )
        return {
            "name": str(result.get("name", "") or "").strip() or "Unknown Caller",
            "bulk_offers": [
                str(o).strip()
                for o in result.get("bulk_offers", [])
                if o and str(o).strip()
            ],
        }
    except Exception as e:
        pp_logger.error(f"Caller extraction failed: {e}")
        return {"name": "Unknown Caller", "bulk_offers": []}


def extract_medicine_context(conversation: str) -> dict[str, Any]:
    try:
        result = groq_json(
            "Analyze a Mr. Med pharmacy call for medicine interest. "
            "Return JSON with:\n"
            "- medicine_mentions: array of medicine names as spoken\n"
            "- primary_mention: main medicine enquired about\n"
            "- quantity: integer if caller asked for a quantity, else null\n"
            "- quantity_unit: short unit if stated, else empty string\n"
            "- pricing_intent: one of bulk, single_pack, packs, units, unknown",
            f"Conversation:\n{conversation}",
        )
        mentions = [
            str(m).strip()
            for m in result.get("medicine_mentions", [])
            if m and str(m).strip()
        ]
        primary = str(result.get("primary_mention", "") or "").strip()
        if primary and primary not in mentions:
            mentions.insert(0, primary)
        quantity_raw = result.get("quantity")
        quantity = int(quantity_raw) if quantity_raw is not None else None
        if quantity is not None and quantity <= 0:
            quantity = None
        return {
            "medicine_mentions": mentions,
            "primary_mention": primary or (mentions[0] if mentions else ""),
            "quantity": quantity,
            "quantity_unit": str(result.get("quantity_unit", "") or "").strip(),
            "pricing_intent": str(result.get("pricing_intent", "unknown") or "unknown").lower(),
        }
    except Exception as e:
        pp_logger.error(f"Medicine context extraction failed: {e}")
        return {
            "medicine_mentions": [],
            "primary_mention": "",
            "quantity": None,
            "quantity_unit": "",
            "pricing_intent": "unknown",
        }


def generate_analytics(conversation: str) -> dict[str, Any]:
    try:
        result = groq_json(
            "Analyze a Mr. Med pharmacy sales call. Return JSON with: "
            "city (caller's city if mentioned, else empty string), "
            "intent_level (TOFU, MOFU, or BOFU — BOFU if ready to order).",
            f"Conversation:\n{conversation}",
        )
        intent_level = str(result.get("intent_level", "TOFU") or "TOFU").upper()
        if intent_level not in ("TOFU", "MOFU", "BOFU"):
            intent_level = "TOFU"
        return {
            "city": str(result.get("city", "") or "").strip(),
            "intent_level": intent_level,
        }
    except Exception as e:
        pp_logger.error(f"Analytics generation failed: {e}")
        return {"city": "", "intent_level": "TOFU"}
