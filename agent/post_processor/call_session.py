"""Derive caller phone and call id from telephony handshake payloads."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any


@dataclass
class CallSession:
    customer_phone: str | None
    call_sid: str | None


def normalize_phone_number(phone_number: str) -> str:
    digits_only = "".join(filter(str.isdigit, phone_number))
    if digits_only.startswith("91") and len(digits_only) > 10:
        return digits_only[2:]
    if len(digits_only) > 10:
        return digits_only[-10:]
    if len(digits_only) < 10:
        return digits_only.zfill(10) if digits_only else ""
    return digits_only


def _phone_digits(value: str) -> str:
    return "".join(filter(str.isdigit, value or ""))


def _parse_custom_parameters(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def parse_call_session(call_data: dict[str, Any] | None) -> CallSession:
    if not call_data:
        return CallSession(customer_phone=None, call_sid=None)

    from_number = str(call_data.get("from") or "")
    to_number = str(call_data.get("to") or "")
    custom = _parse_custom_parameters(call_data.get("custom_parameters"))

    exotel_phone = os.getenv("EXOTEL_PHONE_NUMBER", "").strip()
    exotel_digits = _phone_digits(exotel_phone)
    from_digits = _phone_digits(from_number)

    is_outbound = custom.get("call_type") == "outbound"
    if exotel_digits and from_digits:
        if from_digits == exotel_digits or (
            len(from_digits) >= 10 and exotel_digits.endswith(from_digits[-10:])
        ):
            is_outbound = True

    raw_phone = (to_number or custom.get("phone", "")) if is_outbound else from_number
    normalized = normalize_phone_number(str(raw_phone))
    customer_phone = normalized if len(normalized) == 10 else None

    sid = call_data.get("call_id") or call_data.get("call_sid") or call_data.get("stream_id")
    return CallSession(
        customer_phone=customer_phone,
        call_sid=str(sid) if sid else None,
    )
