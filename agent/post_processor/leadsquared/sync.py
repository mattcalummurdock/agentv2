from __future__ import annotations

import requests

from post_processor.config import pp_logger
from post_processor.leadsquared import client
from post_processor.leadsquared.client import format_http_error
from post_processor.leadsquared.config import is_leadsquared_enabled
from post_processor.models import ProcessedCallRecord, SyncResult


def _format_activity_note(record: ProcessedCallRecord) -> str:
    languages = ", ".join(record.languages) if record.languages else "N/A"
    bulk = ", ".join(record.bulk_offers) if record.bulk_offers else "N/A"
    return (
        f"Call Type: {record.call_type}\n"
        f"Medicine of Interest: {record.course_interest or 'N/A'}\n"
        f"City: {record.city or 'N/A'}\n"
        f"Budget: {record.budget or 'N/A'}\n"
        f"Intent: {record.intent_level}\n"
        f"Languages: {languages}\n"
        f"Bulk Offers: {bulk}\n"
        f"Call SID: {record.call_sid or 'N/A'}\n"
        f"\nConversation Notes:\n{record.conversation}"
    )


def sync_call_to_leadsquared(
    record: ProcessedCallRecord,
    *,
    tag: str = "",
) -> SyncResult:
    prefix = f"[{tag}] " if tag else ""

    if not is_leadsquared_enabled():
        pp_logger.info(f"{prefix}LeadSquared skipped (disabled or missing credentials)")
        return SyncResult(lsq_ok=None, skip_reason="disabled")

    if not record.phone:
        pp_logger.info(f"{prefix}LeadSquared skipped (no phone)")
        return SyncResult(lsq_ok=None, skip_reason="no phone")

    try:
        lead = client.search_lead_by_phone(record.phone)
        if lead:
            prospect_id = str(lead.get("ProspectID") or lead.get("Id") or "")
        else:
            pp_logger.info(f"{prefix}LeadSquared: no lead found, creating")
            prospect_id = client.create_lead(record.name, record.phone)

        if not prospect_id:
            raise ValueError("Could not resolve LeadSquared prospect id")

        client.log_activity(
            prospect_id,
            call_type=record.call_type,
            medicine=record.course_interest,
            activity_note=_format_activity_note(record),
        )
        return SyncResult(lsq_ok=True, lsq_prospect_id=prospect_id)

    except requests.HTTPError as e:
        error = f"LeadSquared FAILED: {format_http_error(e)}"
        pp_logger.error(f"{prefix}{error}")
        return SyncResult(lsq_ok=False, error=error)

    except Exception as e:
        error = f"LeadSquared FAILED: {e}"
        pp_logger.error(f"{prefix}{error}")
        return SyncResult(lsq_ok=False, error=error)
