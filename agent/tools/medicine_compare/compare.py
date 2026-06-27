from typing import Any

from tools.medicine_detail.db import get_pool

_ENRICHMENT_COLUMNS = """
    dosage_strength, therapeutic_class, pharmacological_class
"""

_ALTERNATIVE_RELATIONSHIP_SQL = """
SELECT
    match_reason,
    match_score,
    tier,
    price_difference
FROM v_alternatives_ranked
WHERE (source_medicine_id = $1 AND alternative_id = $2)
   OR (source_medicine_id = $2 AND alternative_id = $1)
ORDER BY match_score DESC NULLS LAST
LIMIT 1
"""

_SALT_RELATIONSHIP_SQL = """
SELECT
    shared_salt_count,
    salt_match_percent,
    price_difference
FROM v_same_salt_alternatives
WHERE (source_medicine_id = $1 AND alternative_id = $2)
   OR (source_medicine_id = $2 AND alternative_id = $1)
ORDER BY salt_match_percent DESC NULLS LAST
LIMIT 1
"""

_CLASS_RELATIONSHIP_SQL = """
SELECT
    shared_class,
    price_difference
FROM v_same_class_alternatives
WHERE (source_medicine_id = $1 AND alternative_id = $2)
   OR (source_medicine_id = $2 AND alternative_id = $1)
LIMIT 1
"""


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    return text or None


def _price_diff(b: float | None, a: float | None) -> float | None:
    if a is None or b is None:
        return None
    return b - a


def _cheaper_label(price_a: float | None, price_b: float | None) -> str | None:
    if price_a is None or price_b is None:
        return None
    if price_a < price_b:
        return "a"
    if price_b < price_a:
        return "b"
    return "same"


async def enrich_medicine_details(medicines: list[dict[str, Any]]) -> None:
    ids = [int(m["id"]) for m in medicines if m.get("id")]
    if not ids:
        return

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT id, {_ENRICHMENT_COLUMNS.strip()}
            FROM medicines
            WHERE id = ANY($1::int[])
            """,
            ids,
        )

    by_id = {int(row["id"]): dict(row) for row in rows}
    for medicine in medicines:
        extra = by_id.get(int(medicine["id"]), {})
        medicine["dosage_strength"] = extra.get("dosage_strength")
        medicine["therapeutic_class"] = extra.get("therapeutic_class")
        medicine["pharmacological_class"] = extra.get("pharmacological_class")


async def fetch_relationship(medicine_id_a: int, medicine_id_b: int) -> dict[str, Any] | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        alt_row = await conn.fetchrow(_ALTERNATIVE_RELATIONSHIP_SQL, medicine_id_a, medicine_id_b)
        if alt_row:
            return {
                "type": "alternative",
                "match_reason": alt_row["match_reason"],
                "match_score": (
                    float(alt_row["match_score"]) if alt_row["match_score"] is not None else None
                ),
                "tier": int(alt_row["tier"]) if alt_row["tier"] is not None else None,
                "catalog_price_difference": (
                    float(alt_row["price_difference"])
                    if alt_row["price_difference"] is not None
                    else None
                ),
            }

        salt_row = await conn.fetchrow(_SALT_RELATIONSHIP_SQL, medicine_id_a, medicine_id_b)
        if salt_row:
            return {
                "type": "same_salt",
                "shared_salt_count": int(salt_row["shared_salt_count"]),
                "salt_match_percent": (
                    float(salt_row["salt_match_percent"])
                    if salt_row["salt_match_percent"] is not None
                    else None
                ),
                "catalog_price_difference": (
                    float(salt_row["price_difference"])
                    if salt_row["price_difference"] is not None
                    else None
                ),
            }

        class_row = await conn.fetchrow(_CLASS_RELATIONSHIP_SQL, medicine_id_a, medicine_id_b)
        if class_row:
            return {
                "type": "same_class",
                "shared_class": class_row["shared_class"],
                "catalog_price_difference": (
                    float(class_row["price_difference"])
                    if class_row["price_difference"] is not None
                    else None
                ),
            }

    return None


def build_comparison_summary(
    med_a: dict[str, Any],
    med_b: dict[str, Any],
    relationship: dict[str, Any] | None,
) -> dict[str, Any]:
    price_a = med_a.get("selling_price")
    price_b = med_b.get("selling_price")
    ppu_a = med_a.get("price_per_unit")
    ppu_b = med_b.get("price_per_unit")

    generic_a = _normalize_text(med_a.get("generic_name"))
    generic_b = _normalize_text(med_b.get("generic_name"))
    form_a = _normalize_text(med_a.get("form"))
    form_b = _normalize_text(med_b.get("form"))
    pack_a = _normalize_text(med_a.get("pack_size"))
    pack_b = _normalize_text(med_b.get("pack_size"))

    return {
        "same_generic": generic_a is not None and generic_a == generic_b,
        "same_form": form_a is not None and form_a == form_b,
        "same_pack_size": pack_a is not None and pack_a == pack_b,
        "price_difference": _price_diff(price_b, price_a),
        "cheaper": _cheaper_label(price_a, price_b),
        "price_per_unit_difference": _price_diff(ppu_b, ppu_a),
        "stock_summary": {
            "a": med_a.get("stock_status"),
            "b": med_b.get("stock_status"),
        },
        "rx_summary": {
            "a": med_a.get("rx_required"),
            "b": med_b.get("rx_required"),
        },
        "relationship": relationship,
    }
