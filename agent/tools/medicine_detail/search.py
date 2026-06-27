from __future__ import annotations

import os
import re
from typing import Any

from tools.medicine_detail.db import MEDICINE_COLUMNS, format_medicine_row, get_pool

TEXT_CONFIDENT_SCORE = float(os.getenv("MEDICINE_TEXT_CONFIDENT_SCORE", "85"))
TEXT_SIMILARITY_THRESHOLD = float(os.getenv("MEDICINE_TEXT_SIMILARITY_THRESHOLD", "0.25"))
PACK_SIMILARITY_THRESHOLD = float(os.getenv("MEDICINE_PACK_SIMILARITY_THRESHOLD", "0.2"))
MIN_SCORE_BY_METHOD = {
    "text": float(os.getenv("MEDICINE_MIN_SCORE_TEXT", "35")),
    "semantic": float(os.getenv("MEDICINE_MIN_SCORE_SEMANTIC", "30")),
    "pack_letters": float(os.getenv("MEDICINE_MIN_SCORE_PACK", "45")),
}

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

_TEXT_SQL = f"""
SELECT
    {MEDICINE_COLUMNS},
    GREATEST(
        word_similarity($1, name),
        word_similarity($1, COALESCE(generic_name, '')),
        word_similarity($1, COALESCE(brand_name, '')),
        similarity(lower($1), lower(name)),
        similarity(lower($1), lower(COALESCE(generic_name, ''))),
        similarity(lower($1), lower(COALESCE(brand_name, '')))
    ) AS score
FROM medicines
WHERE GREATEST(
    word_similarity($1, name),
    word_similarity($1, COALESCE(generic_name, '')),
    word_similarity($1, COALESCE(brand_name, '')),
    similarity(lower($1), lower(name)),
    similarity(lower($1), lower(COALESCE(generic_name, ''))),
    similarity(lower($1), lower(COALESCE(brand_name, '')))
) > $2
ORDER BY score DESC
LIMIT 10
"""

_PACK_CANDIDATE_SQL = f"""
SELECT
    {MEDICINE_COLUMNS},
    GREATEST(
        word_similarity($1, name),
        word_similarity($1, COALESCE(generic_name, '')),
        word_similarity($1, COALESCE(brand_name, '')),
        similarity(lower($1), lower(name)),
        similarity(lower($1), lower(COALESCE(generic_name, ''))),
        similarity(lower($1), lower(COALESCE(brand_name, '')))
    ) AS score
FROM medicines
WHERE GREATEST(
    word_similarity($1, name),
    word_similarity($1, COALESCE(generic_name, '')),
    word_similarity($1, COALESCE(brand_name, '')),
    similarity(lower($1), lower(name)),
    similarity(lower($1), lower(COALESCE(generic_name, ''))),
    similarity(lower($1), lower(COALESCE(brand_name, '')))
) > $2
ORDER BY score DESC
LIMIT 40
"""


_PLACEHOLDER_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "some",
        "any",
        "certain",
        "particular",
        "specific",
        "this",
        "that",
        "these",
        "those",
        "one",
        "another",
        "other",
        "medicine",
        "medicines",
        "medication",
        "medications",
        "med",
        "meds",
        "drug",
        "drugs",
        "pill",
        "pills",
        "tablet",
        "tablets",
        "capsule",
        "capsules",
        "syrup",
        "injection",
        "product",
        "item",
        "brand",
        "generic",
        "looking",
        "searching",
        "find",
        "need",
        "want",
        "get",
        "help",
        "tell",
        "know",
        "about",
        "regarding",
        "called",
        "named",
        "please",
        "kindly",
        "something",
        "anything",
        "prescription",
        "rx",
        "strip",
        "pack",
        "box",
        "for",
        "with",
        "from",
        "have",
        "got",
        "am",
        "im",
        "i",
        "you",
        "me",
        "my",
        "your",
    }
)

MISSING_DRUG_NAME_HINT = (
    "The caller did not name a specific medicine. Do NOT invent a search or quote catalog data. "
    "Ask them: 'Which medicine are you looking for? You can tell me the name as written on "
    "your prescription or pack — even if you're unsure of the spelling.'"
)


def mention_has_confident_name_tokens(mention: str) -> bool:
    """True when the caller spoke a substantial product name, not just short fragments."""
    tokens = [token for token in _core_name_tokens(mention) if len(token) >= 2]
    if any(len(token) >= 5 for token in tokens):
        return True
    return len(tokens) >= 2 and any(len(token) >= 4 for token in tokens)


def is_placeholder_mention(mention: str) -> bool:
    """True when the caller gave only generic words (e.g. 'specific medicine') with no drug name."""
    cleaned = mention.strip()
    if not cleaned:
        return True
    tokens = re.findall(r"[a-zA-Z0-9]+", cleaned.lower())
    if not tokens:
        return True
    meaningful = [token for token in tokens if token not in _PLACEHOLDER_WORDS]
    return len(meaningful) == 0


def _normalize_match_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _normalize_spoken_mention(mention: str) -> str:
    cleaned = mention.strip()
    cleaned = re.sub(r"\bin\s+sticks?\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bsticks?\b", "strip", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _core_name_tokens(mention: str) -> list[str]:
    words = re.findall(r"[a-zA-Z0-9]+", _normalize_spoken_mention(mention))
    return [w for w in words if w.lower() not in _FORM_NOISE]


def _subsequence_match_score(clue: str, text: str) -> float:
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
    cleaned = _normalize_spoken_mention(mention)
    terms: list[str] = []
    seen: set[str] = set()

    def add(term: str) -> None:
        key = term.strip().lower()
        if not key or key in _FORM_NOISE or key in seen:
            return
        seen.add(key)
        terms.append(term.strip())

    core = _core_name_tokens(cleaned)
    if core:
        add(cleaned)
        add(" ".join(core))
    if len(core) >= 2:
        add(" ".join(core[:2]))
    if len(core) >= 3:
        add(" ".join(core[:3]))
    if core:
        add(core[0])
    for clue in extract_pack_letter_clues(mention):
        add(clue)

    expanded: list[str] = []
    for term in terms:
        expanded.append(term)
        lower = term.lower()
        if "y" in lower or "i" in lower:
            expanded.append(re.sub(r"y", "i", term, flags=re.IGNORECASE))
            expanded.append(re.sub(r"i", "y", term, flags=re.IGNORECASE))

    deduped: list[str] = []
    seen.clear()
    for term in expanded:
        key = term.strip().lower()
        if key and key not in seen:
            seen.add(key)
            deduped.append(term.strip())
    return deduped


def _passes_min_score(row: dict[str, Any]) -> bool:
    method = row.get("match_method", "text")
    threshold = MIN_SCORE_BY_METHOD.get(method, 35.0)
    return float(row.get("match_score") or 0) >= threshold


async def text_search(mention: str) -> list[dict[str, Any]]:
    terms = search_terms_from_mention(mention)
    best_by_id: dict[int, dict[str, Any]] = {}
    pool = await get_pool()
    async with pool.acquire() as conn:
        for term in terms:
            rows = await conn.fetch(_TEXT_SQL, term, TEXT_SIMILARITY_THRESHOLD)
            for row in rows:
                score = float(row["score"]) * 100
                item = format_medicine_row(row, match_score=round(score, 1), match_method="text")
                prev = best_by_id.get(item["id"])
                if prev is None or item["match_score"] > prev["match_score"]:
                    best_by_id[item["id"]] = item

    return sorted(best_by_id.values(), key=lambda x: x["match_score"], reverse=True)


async def pack_letter_search(mention: str, *, min_score: float = 45.0) -> list[dict[str, Any]]:
    clues = extract_pack_letter_clues(mention)
    if not clues:
        return []

    best_by_id: dict[int, dict[str, Any]] = {}
    pool = await get_pool()
    async with pool.acquire() as conn:
        for clue in clues[:4]:
            rows = await conn.fetch(_PACK_CANDIDATE_SQL, clue, PACK_SIMILARITY_THRESHOLD)
            for row in rows:
                fields = [
                    str(row.get("name") or ""),
                    str(row.get("generic_name") or ""),
                    str(row.get("brand_name") or ""),
                ]
                best_score = max(_subsequence_match_score(clue, field) for field in fields)
                trigram_score = float(row["score"]) * 100
                best_score = max(best_score, trigram_score)
                if best_score < min_score:
                    continue
                item = format_medicine_row(
                    row,
                    match_score=round(best_score, 1),
                    match_method="pack_letters",
                    matched_clue=clue,
                )
                prev = best_by_id.get(item["id"])
                if prev is None or item["match_score"] > prev["match_score"]:
                    best_by_id[item["id"]] = item

    return sorted(best_by_id.values(), key=lambda x: x["match_score"], reverse=True)


async def search_medicines_by_mention(
    mention: str,
    *,
    min_score: float = 40.0,
) -> list[dict[str, Any]]:
    if not mention.strip():
        return []

    text_results = await text_search(mention)
    if text_results and text_results[0]["match_score"] >= TEXT_CONFIDENT_SCORE:
        return text_results

    import asyncio

    from tools.medicine_detail.semantic import semantic_search

    pack_task = asyncio.create_task(pack_letter_search(mention))
    semantic_task = asyncio.create_task(semantic_search(mention))
    pack_results, semantic_results = await asyncio.gather(pack_task, semantic_task)

    merged: dict[int, dict[str, Any]] = {}
    for pool in (text_results, pack_results, semantic_results):
        for row in pool:
            med_id = int(row["id"])
            prev = merged.get(med_id)
            if prev is None or row["match_score"] > prev["match_score"]:
                merged[med_id] = row

    ranked = sorted(merged.values(), key=lambda row: row["match_score"], reverse=True)
    filtered = [row for row in ranked if _passes_min_score(row)]
    if filtered:
        return filtered

    # Last resort: return the top match if it is clearly ahead of the next candidate.
    if ranked and (
        len(ranked) == 1
        or ranked[0]["match_score"] >= 25
        and ranked[0]["match_score"] - ranked[1]["match_score"] >= 15
    ):
        return [ranked[0]]

    return [row for row in ranked if row["match_score"] >= min_score]
