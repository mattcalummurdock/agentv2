import asyncio
from typing import Any

import asyncpg

from post_processor.config import get_database_url, pp_logger


async def _resolve_mentions_batch(mentions: list[str]) -> dict[str, dict[str, Any] | None]:
    from tools.medicine_detail.bulk_pricing import attach_bulk_pricing
    from tools.medicine_detail.search import search_medicines_by_mention

    if not mentions:
        return {}

    pool = await asyncpg.create_pool(get_database_url(), min_size=1, max_size=3)
    try:
        resolved: dict[str, dict[str, Any] | None] = {}
        for mention in mentions:
            results = await search_medicines_by_mention(mention, pool=pool)
            if not results:
                resolved[mention] = None
                continue

            best = results[0]
            score = float(best.get("match_score") or 0)
            if score < 40:
                resolved[mention] = None
                continue

            if best.get("pricing_model") in ("quantity_tier", "flat_per_unit"):
                await attach_bulk_pricing([best], pool=pool)

            resolved[mention] = best
            pp_logger.info(
                f"Catalog resolved {mention!r} → {best.get('name')!r} "
                f"(id={best.get('id')}, score={score})"
            )
        return resolved
    finally:
        await pool.close()


def resolve_medicines_from_context(med_ctx: dict[str, Any]) -> dict[str, Any]:
    mentions = med_ctx.get("medicine_mentions") or []
    primary_mention = (med_ctx.get("primary_mention") or "").strip()
    ordered: list[str] = []
    seen: set[str] = set()
    for mention in [primary_mention, *mentions]:
        cleaned = mention.strip()
        key = cleaned.lower()
        if key and key not in seen:
            seen.add(key)
            ordered.append(cleaned)

    if not ordered:
        return {"primary": None, "all": []}

    try:
        batch = asyncio.run(_resolve_mentions_batch(ordered))
    except Exception as e:
        pp_logger.error(f"Catalog batch resolve failed: {e}")
        return {"primary": None, "all": []}

    resolved_by_id: dict[int, dict[str, Any]] = {}
    primary: dict[str, Any] | None = None
    for mention in ordered:
        record = batch.get(mention)
        if not record or not record.get("id"):
            continue
        med_id = int(record["id"])
        if med_id not in resolved_by_id:
            resolved_by_id[med_id] = record
        if primary is None and (
            not primary_mention or mention.lower() == primary_mention.lower()
        ):
            primary = record

    resolved = list(resolved_by_id.values())
    if primary is None and resolved:
        primary = resolved[0]
    return {"primary": primary, "all": resolved}
