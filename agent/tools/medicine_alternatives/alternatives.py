import os
from typing import Any

from tools.medicine_detail.db import format_medicine_row, get_pool

ALTERNATIVES_LIMIT = int(os.getenv("MEDICINE_ALTERNATIVES_LIMIT", "10"))

_MEDICINE_SELECT = """
    m.id, m.name, m.generic_name, m.brand_name, m.form, m.pack_size,
    m.selling_price, m.mrp, m.discount_percent, m.price_per_unit, m.currency,
    m.is_available, m.stock_quantity, m.prescription_required, m.pricing_model
"""

_ALTERNATIVES_SQL = f"""
SELECT
    v.tier,
    v.match_score,
    v.match_reason,
    v.price_difference,
    v.alternative_price AS view_alternative_price,
    {_MEDICINE_SELECT.strip()}
FROM v_alternatives_ranked v
JOIN medicines m ON m.id = v.alternative_id
WHERE v.source_medicine_id = $1
  AND v.alternative_in_stock = TRUE
  AND COALESCE(m.stock_quantity, 0) > 0
  AND m.is_available = TRUE
  AND (
    $2::bool = FALSE
    OR v.source_price IS NULL
    OR v.alternative_price IS NULL
    OR v.alternative_price < v.source_price
  )
ORDER BY v.tier ASC, v.match_score DESC, v.alternative_price ASC NULLS LAST
LIMIT $3
"""


async def fetch_alternatives(
    *,
    source_medicine_id: int,
    cheaper_only: bool = True,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            _ALTERNATIVES_SQL,
            source_medicine_id,
            cheaper_only,
            limit or ALTERNATIVES_LIMIT,
        )

    alternatives: list[dict[str, Any]] = []
    for row in rows:
        item = format_medicine_row(row)
        item["alternative_tier"] = int(row["tier"])
        item["match_score"] = float(row["match_score"]) if row["match_score"] is not None else None
        item["match_reason"] = row["match_reason"]
        item["price_difference"] = (
            float(row["price_difference"]) if row["price_difference"] is not None else None
        )
        alternatives.append(item)

    return alternatives
