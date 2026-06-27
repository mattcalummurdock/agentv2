from typing import Any

from post_processor.catalog import resolve_medicines_from_context


def _pick_quantity_tier(
    tiers: list[dict[str, Any]], quantity: int | None, pricing_intent: str
) -> dict[str, Any] | None:
    if not tiers:
        return None
    if quantity is not None:
        exact = next((t for t in tiers if int(t.get("quantity") or 0) == quantity), None)
        if exact:
            return exact
        if pricing_intent == "bulk":
            return max(tiers, key=lambda t: int(t.get("quantity") or 0))
    if pricing_intent == "bulk":
        return max(tiers, key=lambda t: int(t.get("quantity") or 0))
    return None


def format_rupees(amount: float) -> str:
    n = int(round(amount))
    s = str(n)
    if len(s) <= 3:
        return f"Rs. {s}"
    last3 = s[-3:]
    rest = s[:-3]
    groups: list[str] = []
    while len(rest) > 2:
        groups.insert(0, rest[-2:])
        rest = rest[:-2]
    if rest:
        groups.insert(0, rest)
    return f"Rs. {','.join(groups + [last3])}"


def compute_budget_from_db(medicine: dict[str, Any], med_ctx: dict[str, Any]) -> str:
    quantity = med_ctx.get("quantity")
    pricing_intent = med_ctx.get("pricing_intent") or "unknown"
    quantity_unit = med_ctx.get("quantity_unit") or "units"
    model = medicine.get("pricing_model") or "single_pack"
    pack_price = float(medicine.get("selling_price") or 0)

    if model == "quantity_tier":
        tiers = medicine.get("quantity_tiers") or []
        tier = _pick_quantity_tier(tiers, quantity, pricing_intent)
        if tier:
            label = tier.get("label") or f"{tier.get('quantity')} {quantity_unit}".strip()
            return f"{format_rupees(float(tier.get('total_price') or 0))} ({label})"
        if pack_price > 0:
            if quantity and pricing_intent == "packs":
                return f"{format_rupees(pack_price * quantity)} ({quantity} packs)"
            return f"{format_rupees(pack_price)} per pack"

    if model == "flat_per_unit":
        unit_price = float(medicine.get("price_per_unit") or 0)
        if unit_price <= 0:
            return ""
        if quantity and quantity > 0:
            return (
                f"{format_rupees(unit_price * quantity)} "
                f"({quantity} {quantity_unit} @ {format_rupees(unit_price)} each)"
            )
        return f"{format_rupees(unit_price)} per unit"

    if pack_price <= 0:
        return ""
    if quantity and quantity > 1 and pricing_intent in ("packs", "units", "unknown"):
        return f"{format_rupees(pack_price * quantity)} ({quantity} packs)"
    return format_rupees(pack_price)


def derive_medication_and_budget(med_ctx: dict[str, Any]) -> tuple[str, str]:
    resolution = resolve_medicines_from_context(med_ctx)
    primary = resolution.get("primary")
    if not primary:
        return "", ""
    course_interest = str(primary.get("name") or "")
    budget = compute_budget_from_db(primary, med_ctx)
    return course_interest, budget
