from pipecat.services.llm_service import FunctionCallParams

from tools.medicine_alternatives.alternatives import fetch_alternatives
from tools.medicine_detail.bulk_pricing import attach_bulk_pricing
from tools.medicine_detail.search import (
    MISSING_DRUG_NAME_HINT,
    is_placeholder_mention,
    search_medicines_by_mention,
    search_terms_from_mention,
)


def _confirm_with_caller(source: dict) -> str | None:
    # Only block on truly ambiguous pack-letter clues — not on fuzzy name match when
    # the caller already asked for alternatives for that name.
    if source.get("match_method") == "pack_letters":
        clue = source.get("matched_clue") or source.get("name")
        return (
            f"The caller only gave partial pack letters ({clue!r}). "
            f"Ask: 'Are you looking for {source.get('name')}?' before listing alternatives."
        )
    return None


async def handler(params: FunctionCallParams) -> None:
    name = params.arguments["name"]
    cheaper_only = params.arguments.get("cheaper_only", True)

    if is_placeholder_mention(name):
        await params.result_callback(
            {
                "source_medicine": None,
                "alternatives": [],
                "alternatives_count": 0,
                "query": name,
                "cheaper_only": cheaper_only,
                "missing_drug_name": True,
                "hint": MISSING_DRUG_NAME_HINT,
            }
        )
        return

    medicines = await search_medicines_by_mention(name)
    if not medicines:
        await params.result_callback(
            {
                "source_medicine": None,
                "alternatives": [],
                "alternatives_count": 0,
                "query": name,
                "cheaper_only": cheaper_only,
                "search_terms_tried": search_terms_from_mention(name),
                "hint": (
                    "No catalog match for that product. Tell the caller you could not find it "
                    "in Mr. Med's catalog — do not invent substitutes or prices."
                ),
            }
        )
        return

    source = medicines[0]
    alternatives = await fetch_alternatives(
        source_medicine_id=int(source["id"]),
        cheaper_only=cheaper_only,
    )

    bulk_targets = [
        medicine
        for medicine in [source, *alternatives]
        if medicine.get("pricing_model") in ("quantity_tier", "flat_per_unit") and medicine.get("id")
    ]
    if bulk_targets:
        await attach_bulk_pricing(bulk_targets)

    payload: dict = {
        "query": name,
        "source_medicine": source,
        "resolved_name": source.get("name"),
        "resolved_id": source.get("id"),
        "match_method": source.get("match_method", "text"),
        "alternatives": alternatives,
        "alternatives_count": len(alternatives),
        "cheaper_only": cheaper_only,
        "presentation_hint": (
            "The caller asked for alternatives. Present the substitutes from this result directly. "
            "Do not call get_medicine_detail. Do not ask which medicine again. "
            "If resolved_name differs from their wording, mention the matched product once briefly, "
            "then list alternatives with price and match_reason."
        ),
    }

    confirm = _confirm_with_caller(source)
    if confirm:
        payload["confirm_with_caller"] = confirm

    if not alternatives:
        payload["hint"] = (
            "No in-stock substitutes found for this product in the catalog. "
            "Say so clearly — do not invent alternatives."
        )

    await params.result_callback(payload)
