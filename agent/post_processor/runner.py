import asyncio

from post_processor.config import get_semaphore, is_postprocess_enabled, pp_logger
from post_processor.crm import shutdown_db_pool
from post_processor.processor import process_call_sync


async def process_call_end(
    messages: list[dict],
    *,
    caller_phone: str | None = None,
    call_sid: str | None = None,
) -> None:
    if not is_postprocess_enabled():
        pp_logger.info("Post-processing skipped (POSTPROCESS_ENABLED=0 or GROQ_API_KEY unset)")
        return

    sem = get_semaphore()
    async with sem:
        await asyncio.to_thread(
            process_call_sync,
            messages,
            caller_phone=caller_phone,
            call_sid=call_sid,
        )


def shutdown_postprocessor() -> None:
    shutdown_db_pool()
