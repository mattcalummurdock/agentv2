import asyncio

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.services.llm_service import FunctionCallParams

from ._cube import attach_bulk_pricing_parallel
from ._guards import is_non_medicine_lookup
from ._medicine_search import search_medicines_by_mention, search_terms_from_mention

SCHEMA = FunctionSchema(
    name="get_medicine_detail",
    description=(
        "Look up price, stock, Rx status, and bulk offers for a PHARMACEUTICAL PRODUCT "
        "(drug brand or generic) by name. "
        "DO NOT CALL unless the user EXPLICITLY asked for medicine price/stock/info in their "
        "last message AND named a product. "
        "DO NOT CALL if the user only gave their name, city, greeting, yes/no, Mr. Med, "
        "MrMed, Mister Med, Mr. V, Sarah, or asked what Mr. Med is — answer without tools. "
        "DO NOT CALL speculatively on STT noise or words that merely sound like drug names. "
        "CALL when the user asked for price/stock/info on a medicine — pass their exact "
        "words even if misspelled, mispronounced, or garbled; do NOT ask them to say the "
        "name properly first. "
        "Returns stock_quantity (exact units), is_available, stock_status, form, "
        "pack_size, and bulk_offer_line when applicable. Fuzzy-matches spoken or "
        "misspelled names via text + embedding + pack-letter search (e.g. garbled "
        "'oksiage el gee' or pack letters 'atr' may resolve to a catalog product). "
        "Check match_method: confirm with caller when match_method is 'semantic' or "
        "'pack_letters'."
    ),
    properties={
        "name": {
            "type": "string",
            "description": (
                "Medicine clue exactly as the user said it — full name, garbled name, or "
                "partial pack letters (e.g. 'I only see atr on the pack'). Never 'Mr. Med', "
                "'MrMed', or company names."
            ),
        },
    },
    required=["name"],
)


async def handler(params: FunctionCallParams):
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

    medicines = await asyncio.to_thread(search_medicines_by_mention, name)
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
        m
        for m in medicines
        if m.get("pricing_model") in ("quantity_tier", "flat_per_unit") and m.get("id")
    ]
    if bulk_targets:
        await attach_bulk_pricing_parallel(bulk_targets)

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
                f"The caller's wording did not exactly match the catalog. "
                f"Ask if they meant {best.get('name')!r} before quoting price or stock."
            )
    await params.result_callback(payload)



"""Fuzzy medicine name resolution — Cube text search + pgvector semantic fallback."""

from __future__ import annotations

import os
import re
from typing import Any

from ._cube import flatten_cube_rows

TEXT_CONFIDENT_SCORE = float(os.getenv("MEDICINE_TEXT_CONFIDENT_SCORE", "85"))
SEMANTIC_ENABLED = os.getenv("SEMANTIC_SEARCH_ENABLED", "1").strip().lower() in (
    "1",
    "true",
    "yes",
)


def prewarm_semantic_search() -> bool:
    """Load embedding model at agent startup (scripts/ on sys.path)."""
    import sys
    from pathlib import Path

    scripts = Path(__file__).resolve().parents[1] / "scripts"
    if scripts.is_dir() and str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    if not SEMANTIC_ENABLED:
        return False
    from semantic_search import prewarm_embedding_model

    return prewarm_embedding_model()

# Spoken filler / packaging words (not usually part of the brand name in DB).
_CLUE_STOP_WORDS = frozenset(
    {
        "can",
        "could",
        "only",
        "see",
        "saw",
        "letters",
        "letter",
        "pack",
        "packs",
        "box",
        "name",
        "drug",
        "medicine",
        "medicines",
        "pill",
        "pills",
        "what",
        "some",
        "just",
        "like",
        "maybe",
        "read",
        "reads",
        "written",
        "shows",
        "show",
        "says",
        "said",
        "spelling",
        "spelled",
        "blurry",
        "unclear",
    }
)

_FORM_NOISE = frozenset(
    {
        "in",
        "a",
        "an",
        "the",
        "of",
        "for",
        "tablet",
        "tablets",
        "capsule",
        "capsules",
        "syrup",
        "injection",
        "stick",
        "sticks",
        "strip",
        "strips",
        "pack",
        "packs",
        "bottle",
        "box",
    }
)


def _normalize_match_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _normalize_spoken_mention(mention: str) -> str:
    """Clean STT quirks before building Cube search terms."""
    cleaned = mention.strip()
    # "in stick" on calls usually means strip packaging, not a stick dosage form.
    cleaned = re.sub(r"\bin\s+sticks?\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bsticks?\b", "strip", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _core_name_tokens(mention: str) -> list[str]:
    words = re.findall(r"[a-zA-Z0-9]+", _normalize_spoken_mention(mention))
    return [w for w in words if w.lower() not in _FORM_NOISE]


def _subsequence_match_score(clue: str, text: str) -> float:
    """Score how well ordered letters of clue appear in text (pack fragment matching)."""
    clue_norm = _normalize_match_text(clue)
    text_norm = _normalize_match_text(text)
    if len(clue_norm) < 2 or not text_norm:
        return 0.0

    positions: list[int] = []
    idx = 0
    for pos, char in enumerate(text_norm):
        if idx < len(clue_norm) and char == clue_norm[idx]:
            positions.append(pos)
            idx += 1
    if idx < len(clue_norm):
        return 0.0

    span = positions[-1] - positions[0] + 1
    compactness = len(clue_norm) / max(span, 1)
    length_bonus = min(len(clue_norm) / 5.0, 1.0) * 25.0
    start_bonus = 15.0 if text_norm.startswith(clue_norm[: min(2, len(clue_norm))]) else 0.0
    return min(45.0 + compactness * 35.0 + length_bonus + start_bonus, 92.0)


def extract_pack_letter_clues(mention: str) -> list[str]:
    """Pull short letter fragments from 'I only see atr on the pack' style queries."""
    normalized = mention.lower()
    clues: list[str] = []
    seen: set[str] = set()

    def add(clue: str) -> None:
        key = re.sub(r"[^a-z0-9]", "", clue.lower())
        if len(key) < 2 or key in seen or key in _CLUE_STOP_WORDS or key in _FORM_NOISE:
            return
        seen.add(key)
        clues.append(key)

    for match in re.finditer(
        r"(?:letters?|read(?:s|ing)?|says?|see(?:s)?|shows?|written|spelling|name\s+is)\s+([a-z]{2,8})\b",
        normalized,
    ):
        add(match.group(1))

    for match in re.finditer(r"\b([a-z]{2,8})\b", normalized):
        token = match.group(1)
        if token in _CLUE_STOP_WORDS or token in _FORM_NOISE:
            continue
        if len(token) >= 3:
            add(token)

    return clues


def search_terms_from_mention(mention: str) -> list[str]:
    """Build progressively broader Cube search terms from a spoken mention."""
    cleaned = _normalize_spoken_mention(mention)
    terms: list[str] = []
    seen: set[str] = set()

    def add(term: str) -> None:
        key = term.strip().lower()
        if not key or key in _FORM_NOISE or key in seen:
            return
        seen.add(key)
        terms.append(term.strip())

    if _core_name_tokens(cleaned):
        add(cleaned)
    core = _core_name_tokens(cleaned)
    if core:
        add(" ".join(core))
    if len(core) >= 2:
        add(" ".join(core[:2]))
    if len(core) >= 3:
        add(" ".join(core[:3]))
    if core:
        add(core[0])
    for clue in extract_pack_letter_clues(mention):
        add(clue)
    return terms


def score_medicine_match(mention: str, row: dict) -> float:
    mention_norm = _normalize_match_text(_normalize_spoken_mention(mention))
    if not mention_norm:
        return 0.0

    name = str(row.get("Medicines.name") or "")
    generic = str(row.get("Medicines.genericName") or "")
    brand = str(row.get("Medicines.brandName") or "")
    form = str(row.get("Medicines.form") or "")
    pack = str(row.get("Medicines.packSize") or "")

    candidates = [name, generic, brand]
    best = 0.0
    for candidate in candidates:
        candidate_norm = _normalize_match_text(candidate)
        if not candidate_norm:
            continue
        if mention_norm == candidate_norm:
            best = max(best, 100.0)
        elif mention_norm in candidate_norm:
            best = max(best, 85.0 + min(len(mention_norm) / max(len(candidate_norm), 1), 1.0) * 10)
        elif candidate_norm in mention_norm:
            best = max(best, 75.0 + min(len(candidate_norm) / max(len(mention_norm), 1), 1.0) * 10)
        else:
            mention_tokens = set(_core_name_tokens(mention))
            candidate_tokens = set(re.findall(r"[a-z0-9]+", candidate_norm))
            if mention_tokens and candidate_tokens:
                overlap = len(mention_tokens & candidate_tokens) / len(mention_tokens)
                if overlap >= 0.5:
                    best = max(best, 40.0 + overlap * 40.0)

    mention_lower = mention.lower()
    if ("stick" in mention_lower or "strip" in mention_lower) and "strip" in pack.lower():
        best += 5.0
    if form and form.lower() in mention_lower:
        best += 3.0

    return best


def _text_search_by_mention(
    mention: str,
    *,
    min_score: float,
) -> list[dict[str, Any]]:
    import cube_tools

    best_by_id: dict[int, tuple[float, dict]] = {}
    for term in search_terms_from_mention(mention):
        try:
            rows = cube_tools.get_medicine_detail(term)
        except Exception:
            continue
        for row in rows:
            med_id = row.get("Medicines.id")
            if med_id is None:
                continue
            score = score_medicine_match(mention, row)
            if score < min_score:
                continue
            key = int(med_id)
            prev = best_by_id.get(key)
            if prev is None or score > prev[0]:
                best_by_id[key] = (score, row)

    ranked = sorted(best_by_id.values(), key=lambda item: item[0], reverse=True)
    results: list[dict[str, Any]] = []
    for score, row in ranked:
        item = flatten_cube_rows([row])[0]
        item["match_score"] = round(score, 1)
        item["match_method"] = "text"
        results.append(item)
    return results


def _pack_letter_search_by_mention(
    mention: str,
    *,
    min_score: float = 45.0,
) -> list[dict[str, Any]]:
    """Match pack fragments (e.g. 'atr' on strip) via ordered-letter subsequence."""
    import cube_tools

    clues = extract_pack_letter_clues(mention)
    if not clues:
        return []

    try:
        catalog = cube_tools.list_medicines_for_clue_search()
    except Exception:
        return []

    best_by_id: dict[int, tuple[float, dict, str]] = {}
    for row in catalog:
        med_id = row.get("Medicines.id")
        if med_id is None:
            continue
        fields = [
            str(row.get("Medicines.name") or ""),
            str(row.get("Medicines.genericName") or ""),
            str(row.get("Medicines.brandName") or ""),
        ]
        best_for_row = 0.0
        best_clue = ""
        for clue in clues:
            for field in fields:
                score = _subsequence_match_score(clue, field)
                if score > best_for_row:
                    best_for_row = score
                    best_clue = clue
        if best_for_row < min_score:
            continue
        key = int(med_id)
        prev = best_by_id.get(key)
        if prev is None or best_for_row > prev[0]:
            best_by_id[key] = (best_for_row, row, best_clue)

    if not best_by_id:
        return []

    ranked = sorted(best_by_id.values(), key=lambda item: item[0], reverse=True)
    results: list[dict[str, Any]] = []
    for score, brief_row, clue in ranked:
        med_id = int(brief_row["Medicines.id"])
        try:
            rows = cube_tools.get_medicine_by_id(med_id)
        except Exception:
            continue
        if not rows:
            continue
        item = flatten_cube_rows([rows[0]])[0]
        item["match_score"] = round(score, 1)
        item["match_method"] = "pack_letters"
        item["matched_clue"] = clue
        results.append(item)
    return results


def _semantic_search_by_mention(mention: str, *, top_k: int = 3) -> list[dict[str, Any]]:
    import cube_tools

    try:
        from semantic_search import semantic_search, semantic_search_available
    except ImportError:
        return []
    if not SEMANTIC_ENABLED or not semantic_search_available():
        return []

    hits = semantic_search(mention, top_k=top_k)
    results: list[dict[str, Any]] = []
    for hit in hits:
        med_id = int(hit["medicine_id"])
        try:
            rows = cube_tools.get_medicine_by_id(med_id)
        except Exception:
            continue
        if not rows:
            continue
        item = flatten_cube_rows([rows[0]])[0]
        similarity = float(hit["similarity"])
        item["match_score"] = round(similarity * 100, 1)
        item["match_method"] = "semantic"
        item["similarity"] = round(similarity, 3)
        results.append(item)
    return results


def search_medicines_by_mention(
    mention: str,
    *,
    min_score: float = 40.0,
) -> list[dict[str, Any]]:
    """Resolve a spoken or misspelled mention via text search, then semantic fallback."""
    if not mention.strip():
        return []

    text_results = _text_search_by_mention(mention, min_score=min_score)
    if text_results and text_results[0]["match_score"] >= TEXT_CONFIDENT_SCORE:
        return text_results

    pack_results = _pack_letter_search_by_mention(mention)
    semantic_results = _semantic_search_by_mention(mention)

    pools: list[list[dict[str, Any]]] = []
    if text_results:
        pools.append(text_results)
    if pack_results:
        pools.append(pack_results)
    if semantic_results:
        pools.append(semantic_results)
    if not pools:
        return []

    merged: dict[int, dict[str, Any]] = {}
    for pool in pools:
        for row in pool:
            med_id = int(row["id"])
            prev = merged.get(med_id)
            if prev is None or row["match_score"] > prev["match_score"]:
                merged[med_id] = row
    return sorted(merged.values(), key=lambda r: r["match_score"], reverse=True)
