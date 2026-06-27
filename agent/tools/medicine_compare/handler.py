import asyncio

from pipecat.services.llm_service import FunctionCallParams

from tools.medicine_compare.compare import (
    build_comparison_summary,
    enrich_medicine_details,
    fetch_relationship,
)
from tools.medicine_detail.bulk_pricing import attach_bulk_pricing
from tools.medicine_detail.search import (
    MISSING_DRUG_NAME_HINT,
    is_placeholder_mention,
    search_medicines_by_mention,
    search_terms_from_mention,
)


def _confirm_for_medicine(medicine: dict, query: str, label: str) -> str | None:
    method = medicine.get("match_method")
    if method == "pack_letters":
        clue = medicine.get("matched_clue") or query
        return (
            f"For medicine {label}, the caller only gave partial pack letters ({clue!r}). "
            f"Ask: 'Are you looking for {medicine.get('name')}?' before comparing."
        )
    if method == "semantic":
        return (
            f"For medicine {label}, the caller's wording did not exactly match the catalog. "
            f"Ask if they meant {medicine.get('name')!r} before comparing."
        )
    return None


def _build_confirm_message(med_a: dict, med_b: dict, name_a: str, name_b: str) -> str | None:
    parts = [
        msg
        for msg in (
            _confirm_for_medicine(med_a, name_a, "A"),
            _confirm_for_medicine(med_b, name_b, "B"),
        )
        if msg
    ]
    return " ".join(parts) if parts else None


async def handler(params: FunctionCallParams) -> None:
    name_a = params.arguments["name_a"]
    name_b = params.arguments["name_b"]

    if is_placeholder_mention(name_a) or is_placeholder_mention(name_b):
        await params.result_callback(
            {
                "query": {"name_a": name_a, "name_b": name_b},
                "medicine_a": None,
                "medicine_b": None,
                "missing_drug_name": True,
                "hint": MISSING_DRUG_NAME_HINT,
            }
        )
        return

    results_a, results_b = await asyncio.gather(
        search_medicines_by_mention(name_a),
        search_medicines_by_mention(name_b),
    )

    med_a = results_a[0] if results_a else None
    med_b = results_b[0] if results_b else None

    base_payload: dict = {
        "query": {"name_a": name_a, "name_b": name_b},
        "medicine_a": med_a,
        "medicine_b": med_b,
        "resolved_name_a": med_a.get("name") if med_a else None,
        "resolved_name_b": med_b.get("name") if med_b else None,
        "match_method_a": med_a.get("match_method", "text") if med_a else None,
        "match_method_b": med_b.get("match_method", "text") if med_b else None,
    }

    if not med_a and not med_b:
        base_payload["search_terms_tried"] = {
            "name_a": search_terms_from_mention(name_a),
            "name_b": search_terms_from_mention(name_b),
        }
        base_payload["hint"] = (
            "Neither product matched the catalog. Tell the caller you could not find either "
            "medicine in Mr. Med's catalog — do not invent prices or comparisons."
        )
        await params.result_callback(base_payload)
        return

    if not med_a or not med_b:
        missing = "name_a" if not med_a else "name_b"
        found = med_b if not med_a else med_a
        base_payload["search_terms_tried"] = search_terms_from_mention(
            name_a if not med_a else name_b
        )
        base_payload["hint"] = (
            f"Only one product matched ({found.get('name')}). The other was not found in the catalog. "
            "Tell the caller which one you found and that you could not find the other — "
            "do not invent a comparison."
        )
        base_payload["missing_query"] = missing
        await params.result_callback(base_payload)
        return

    if int(med_a["id"]) == int(med_b["id"]):
        base_payload["same_product"] = True
        base_payload["hint"] = (
            "Both names resolved to the same catalog product. Tell the caller they are the same "
            "medicine — there is nothing to compare."
        )
        await params.result_callback(base_payload)
        return

    bulk_targets = [
        medicine
        for medicine in [med_a, med_b]
        if medicine.get("pricing_model") in ("quantity_tier", "flat_per_unit") and medicine.get("id")
    ]
    if bulk_targets:
        await attach_bulk_pricing(bulk_targets)

    await enrich_medicine_details([med_a, med_b])

    relationship = await fetch_relationship(int(med_a["id"]), int(med_b["id"]))
    comparison = build_comparison_summary(med_a, med_b, relationship)

    payload: dict = {
        **base_payload,
        "comparison": comparison,
        "presentation_hint": (
            "The caller asked to compare two medicines. Present a clear spoken comparison: "
            "names, prices, stock, generic/composition, and relationship if present. "
            "Do not call get_medicine_detail or get_medicine_alternatives for this request."
        ),
    }

    confirm = _build_confirm_message(med_a, med_b, name_a, name_b)
    if confirm:
        payload["confirm_with_caller"] = confirm

    await params.result_callback(payload)
