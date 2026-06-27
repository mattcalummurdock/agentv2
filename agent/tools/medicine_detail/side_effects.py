from typing import Any

from tools.medicine_detail.db import get_pool

_SEVERITY_ORDER = ("common", "serious", "rare")

_SIDE_EFFECTS_SQL = """
SELECT effect_text, severity, display_order
FROM side_effects
WHERE medicine_id = $1
ORDER BY
    CASE severity
        WHEN 'common' THEN 1
        WHEN 'serious' THEN 2
        WHEN 'rare' THEN 3
        ELSE 4
    END,
    display_order
"""


async def fetch_side_effects(medicine_id: int) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(_SIDE_EFFECTS_SQL, medicine_id)

    return [
        {
            "effect_text": row["effect_text"],
            "severity": row["severity"],
            "display_order": row["display_order"],
        }
        for row in rows
    ]


def group_side_effects_by_severity(effects: list[dict[str, Any]]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {severity: [] for severity in _SEVERITY_ORDER}
    for effect in effects:
        severity = effect.get("severity") or "common"
        if severity not in grouped:
            grouped[severity] = []
        text = effect.get("effect_text")
        if text:
            grouped[severity].append(text)
    return {severity: texts for severity, texts in grouped.items() if texts}
