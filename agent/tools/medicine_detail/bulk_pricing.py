from typing import Any

from tools.medicine_detail.db import get_pool


async def attach_bulk_pricing(medicines: list[dict[str, Any]]) -> None:
    ids = [int(m["id"]) for m in medicines if m.get("id")]
    if not ids:
        return

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT medicine_id, quantity, total_price, label, display_order
            FROM medicine_quantity_tiers
            WHERE medicine_id = ANY($1::int[])
            ORDER BY medicine_id, display_order
            """,
            ids,
        )

    tiers_by_id: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        med_id = int(row["medicine_id"])
        tiers_by_id.setdefault(med_id, []).append(
            {
                "quantity": row["quantity"],
                "total_price": float(row["total_price"]),
                "label": row["label"],
            }
        )

    for medicine in medicines:
        med_id = int(medicine["id"])
        tiers = tiers_by_id.get(med_id, [])
        medicine["quantity_tiers"] = tiers
        if tiers:
            medicine["bulk_offer_line"] = "; ".join(
                f"{tier['label']}: ₹{tier['total_price']:.2f}" for tier in tiers
            )
        else:
            medicine["bulk_offer_line"] = None
