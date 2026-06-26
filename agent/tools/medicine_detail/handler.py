from pipecat.services.llm_service import FunctionCallParams

from tools.medicine_detail.bulk_pricing import attach_bulk_pricing
from tools.medicine_detail.guards import is_non_medicine_lookup
from tools.medicine_detail.search import search_medicines_by_mention, search_terms_from_mention


async def handler(params: FunctionCallParams) -> None:
    name = params.arguments["name"]

    if is_non_medicine_lookup(name):
        await params.result_callback(
            {
                "medicines": [],
                "skipped": True,
                "reason": (
                    f"'{name}' is not a medicine product lookup — caller did not ask for this, "
                    "or this is Mr. Med / company / intake meta. Do NOT tell the caller you "
                    "could not find a medicine. Continue the conversation without mentioning tools."
                ),
            }
        )
        return

    medicines = await search_medicines_by_mention(name)
    if not medicines:
        await params.result_callback(
            {
                "medicines": [],
                "query": name,
                "search_terms_tried": search_terms_from_mention(name),
                "hint": (
                    "No catalog match. Tell the caller you could not find that exact product "
                    "in Mr. Med's catalog — do not invent stock or price."
                ),
            }
        )
        return

    bulk_targets = [
        medicine
        for medicine in medicines
        if medicine.get("pricing_model") in ("quantity_tier", "flat_per_unit") and medicine.get("id")
    ]
    if bulk_targets:
        await attach_bulk_pricing(bulk_targets)

    best = medicines[0]
    payload: dict = {
        "medicines": medicines,
        "best_match": best,
        "query": name,
        "resolved_name": best.get("name"),
        "resolved_id": best.get("id"),
        "match_method": best.get("match_method", "text"),
    }

    if best.get("match_method") in ("semantic", "pack_letters"):
        if best.get("match_method") == "pack_letters":
            clue = best.get("matched_clue") or name
            payload["confirm_with_caller"] = (
                f"The caller only gave partial pack letters ({clue!r}). "
                f"Ask: 'Are you looking for {best.get('name')}?' before quoting price or stock."
            )
        else:
            payload["confirm_with_caller"] = (
                "The caller's wording did not exactly match the catalog. "
                f"Ask if they meant {best.get('name')!r} before quoting price or stock."
            )

    await params.result_callback(payload)
