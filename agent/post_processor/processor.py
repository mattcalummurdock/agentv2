import time

from post_processor.call_session import normalize_phone_number
from post_processor.config import pp_logger
from post_processor.crm import persist_call_record
from post_processor.extraction import (
    detect_languages,
    extract_caller_info,
    extract_medicine_context,
    generate_analytics,
)
from post_processor.leadsquared import sync_call_to_leadsquared
from post_processor.models import ProcessedCallRecord, SyncResult
from post_processor.pricing import derive_medication_and_budget
from post_processor.transcript import messages_to_transcript, normalize_conversation_tags


def _format_lsq_summary(result: SyncResult) -> str:
    if result.lsq_ok is True:
        return f"LeadSquared OK (prospect={result.lsq_prospect_id})"
    if result.lsq_ok is False:
        return result.error or "LeadSquared FAILED"
    reason = result.skip_reason or "skipped"
    return f"LeadSquared skipped ({reason})"


def process_call_sync(
    messages: list[dict],
    *,
    caller_phone: str | None = None,
    call_sid: str | None = None,
) -> None:
    started = time.monotonic()
    tag = call_sid or f"call-{int(time.time() * 1000) % 100000}"
    pp_logger.info(f"[{tag}] Starting post-processing")

    transcript = messages_to_transcript(messages)
    if not transcript or "User:" not in transcript:
        pp_logger.info(f"[{tag}] Skipping — no user turns in transcript")
        return

    conversation = normalize_conversation_tags(transcript)
    languages = detect_languages(conversation)
    caller_info = extract_caller_info(conversation)

    phone = ""
    if caller_phone:
        phone = normalize_phone_number(caller_phone)
        if len(phone) != 10:
            phone = ""

    name = caller_info.get("name", "Unknown Caller")
    bulk_offers = caller_info.get("bulk_offers", [])

    med_ctx = extract_medicine_context(conversation)
    course_interest, budget = derive_medication_and_budget(med_ctx)
    analytics = generate_analytics(conversation)

    record = ProcessedCallRecord(
        name=name,
        phone=phone,
        course_interest=course_interest,
        city=analytics.get("city", ""),
        budget=budget,
        intent_level=analytics.get("intent_level", "TOFU"),
        conversation=conversation,
        languages=languages,
        bulk_offers=bulk_offers,
        call_type=analytics.get("call_type", "General Inquiry"),
        call_sid=call_sid,
    )

    caller_id, conv_id = persist_call_record(**record.crm_fields())
    lsq_result = sync_call_to_leadsquared(record, tag=tag)
    lsq_result.postgres_ok = True
    lsq_result.postgres_caller_id = caller_id
    lsq_result.postgres_conv_id = conv_id

    elapsed = time.monotonic() - started
    pp_logger.info(
        f"[{tag}] Done in {elapsed:.1f}s — "
        f"Postgres OK (caller={caller_id} conversation={conv_id}) — "
        f"{_format_lsq_summary(lsq_result)}"
    )
