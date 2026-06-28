from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ProcessedCallRecord:
    name: str
    phone: str
    course_interest: str
    city: str
    budget: str
    intent_level: str
    conversation: str
    languages: list[str]
    bulk_offers: list[str]
    call_type: str = "General Inquiry"
    call_sid: str | None = None

    def crm_fields(self) -> dict:
        return {
            "name": self.name,
            "phone": self.phone,
            "course_interest": self.course_interest,
            "city": self.city,
            "budget": self.budget,
            "intent_level": self.intent_level,
            "conversation": self.conversation,
            "languages": self.languages,
            "bulk_offers": self.bulk_offers,
        }


@dataclass
class SyncResult:
    postgres_ok: bool = False
    postgres_caller_id: str | None = None
    postgres_conv_id: str | None = None
    lsq_ok: bool | None = None
    lsq_prospect_id: str | None = None
    error: str | None = None
    skip_reason: str | None = None
