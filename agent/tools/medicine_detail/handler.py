from pipecat.services.llm_service import FunctionCallParams

from tools.medicine_detail.bulk_pricing import attach_bulk_pricing
from tools.medicine_detail.search import (
    MISSING_DRUG_NAME_HINT,
    is_placeholder_mention,
    search_medicines_by_mention,
    search_terms_from_mention,
)
from tools.medicine_detail.side_effects import fetch_side_effects, group_side_effects_by_severity

AMBIGUITY_SCORE_GAP = 10.0


def _is_ambiguous(candidates: list[dict]) -> bool:
    if len(candidates) < 2:
        return False
    gap = float(candidates[0].get("match_score") or 0) - float(candidates[1].get("match_score") or 0)
    return gap < AMBIGUITY_SCORE_GAP


def _build_name_resolution(query: str, best: dict, candidates: list[dict]) -> dict:
    ambiguous = _is_ambiguous(candidates)
    return {
        "caller_said": query,
        "resolved_name": best.get("name"),
        "resolved_id": best.get("id"),
        "match_method": best.get("match_method", "text"),
        "match_score": best.get("match_score"),
        "likely_same_product": not ambiguous,
        "alternate_candidates": [
            {
                "name": candidate.get("name"),
                "id": candidate.get("id"),
                "match_score": candidate.get("match_score"),
            }
            for candidate in candidates[1:3]
        ]
        if ambiguous
        else [],
    }


async def handler(params: FunctionCallParams) -> None:
    name = params.arguments["name"]

    if is_placeholder_mention(name):
        await params.result_callback(
            {
                "medicines": [],
                "query": name,
                "missing_drug_name": True,
                "hint": MISSING_DRUG_NAME_HINT,
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
    effects = await fetch_side_effects(int(best["id"]))
    effects_by_severity = group_side_effects_by_severity(effects)
    best["side_effects"] = effects
    best["side_effects_by_severity"] = effects_by_severity

    payload: dict = {
        "medicines": medicines,
        "best_match": best,
        "query": name,
        "resolved_name": best.get("name"),
        "resolved_id": best.get("id"),
        "match_method": best.get("match_method", "text"),
        "name_resolution": _build_name_resolution(name, best, medicines),
        "side_effects": effects,
        "side_effects_by_severity": effects_by_severity,
        "side_effects_count": len(effects),
    }

    if not effects:
        payload["side_effects_hint"] = (
            "No side effects listed in the catalog for this product. "
            "Say so if the caller asks — do not invent them."
        )

    if _is_ambiguous(medicines):
        runner_up = medicines[1]
        payload["confirm_with_caller"] = (
            f"The caller's wording could match more than one product. "
            f"Best guess: {best.get('name')!r} (match score {best.get('match_score')}). "
            f"Also possible: {runner_up.get('name')!r} (match score {runner_up.get('match_score')}). "
            "Ask which one they meant before quoting price or stock."
        )

    payload["presentation_hint"] = (
        f"Use the catalog name {best.get('name')!r} directly when speaking — e.g. "
        "'Oxiage LG is …', 'The price of Oxiage LG is …', 'Oxiage LG is in stock.' "
        "NEVER say 'based on what you said', 'this looks like', 'it seems like', "
        "'sounds like you mean', or any similar hedging phrase. "
        "Just state the product name and the details."
    )

    await params.result_callback(payload)
