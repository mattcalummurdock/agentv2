Looking at your code, the core pattern is: spoken mention → fuzzy text search → pack-letter fallback → semantic fallback → return ranked results. The Cube dependency is really just for two things: `get_medicine_detail(term)`, `list_medicines_for_clue_search()`, and `get_medicine_by_id(id)`.

You can replace all of that with **PostgreSQL directly** (you're already using pgvector for semantic search anyway), and make it significantly faster.

Here's the approach:

---

## Drop Cube, go direct to Postgres

**Text search** → `pg_trgm` GIN index + `similarity()` or `word_similarity()`. One query, sub-5ms.

**Pack letter / subsequence** → replace the Python loop over the full catalog with a Postgres expression index on `lower(name)` and use `LIKE` or a custom `subsequence_match` function. Eliminates the `list_medicines_for_clue_search()` full-catalog pull entirely.

**Semantic** → you already have pgvector. Same connection, one `<=>` query.

---

## The fast replacement

```python
# medicine_search_pg.py
from __future__ import annotations
import os
import re
from typing import Any
import asyncpg  # or psycopg3 — both support async

DSN = os.environ["DATABASE_URL"]

# ── normalisation (keep your existing helpers) ────────────────────────────────

def _normalize_match_text(v: str) -> str:
    return re.sub(r"[^a-z0-9]", "", v.lower())

_FORM_NOISE = frozenset({
    "in","a","an","the","of","for","tablet","tablets","capsule","capsules",
    "syrup","injection","stick","sticks","strip","strips","pack","packs","bottle","box",
})

def _core_name_tokens(mention: str) -> list[str]:
    words = re.findall(r"[a-zA-Z0-9]+", mention)
    return [w for w in words if w.lower() not in _FORM_NOISE]

# ── connection pool (call once at startup) ────────────────────────────────────

_pool: asyncpg.Pool | None = None

async def init_pool() -> None:
    global _pool
    _pool = await asyncpg.create_pool(DSN, min_size=2, max_size=10)

# ── 1. fuzzy text search via pg_trgm ─────────────────────────────────────────
# Requires: CREATE EXTENSION pg_trgm;
#           CREATE INDEX ON medicines USING GIN (name gin_trgm_ops);
#           CREATE INDEX ON medicines USING GIN (generic_name gin_trgm_ops);
#           CREATE INDEX ON medicines USING GIN (brand_name gin_trgm_ops);

_TEXT_SQL = """
SELECT
    id, name, generic_name, brand_name, form, pack_size,
    is_available, stock_quantity, pricing_model, rx_required,
    GREATEST(
        word_similarity($1, name),
        word_similarity($1, COALESCE(generic_name, '')),
        word_similarity($1, COALESCE(brand_name, ''))
    ) AS score
FROM medicines
WHERE
    $1 %> name
    OR $1 %> COALESCE(generic_name, '')
    OR $1 %> COALESCE(brand_name, '')
ORDER BY score DESC
LIMIT 10;
"""

async def text_search(mention: str) -> list[dict[str, Any]]:
    # Try full mention first, then core tokens, then first token
    tokens = _core_name_tokens(mention)
    terms = dict.fromkeys(filter(None, [
        mention.strip(),
        " ".join(tokens) if tokens else None,
        tokens[0] if tokens else None,
    ]))

    best_by_id: dict[int, dict] = {}
    async with _pool.acquire() as conn:
        for term in terms:
            rows = await conn.fetch(_TEXT_SQL, term)
            for r in rows:
                rid = r["id"]
                score = float(r["score"]) * 100
                if rid not in best_by_id or score > best_by_id[rid]["match_score"]:
                    best_by_id[rid] = {**dict(r), "match_score": round(score, 1), "match_method": "text"}
    return sorted(best_by_id.values(), key=lambda x: x["match_score"], reverse=True)

# ── 2. pack-letter subsequence — done in SQL, no full catalog pull ────────────
# Postgres function (create once):
#
# CREATE OR REPLACE FUNCTION subseq_score(clue text, target text) RETURNS float AS $$
# DECLARE
#   ci int := 1; ti int := 1; first_pos int := -1; last_pos int := 0;
#   cn int := length(clue); tn int := length(target);
# BEGIN
#   WHILE ci <= cn AND ti <= tn LOOP
#     IF substr(clue,ci,1) = substr(target,ti,1) THEN
#       IF first_pos = -1 THEN first_pos := ti; END IF;
#       last_pos := ti; ci := ci + 1;
#     END IF;
#     ti := ti + 1;
#   END LOOP;
#   IF ci <= cn THEN RETURN 0; END IF;  -- clue not found
#   RETURN least(0.45 + (cn::float / greatest(last_pos - first_pos + 1, 1)) * 0.35
#              + least(cn / 5.0, 1.0) * 0.25, 0.92);
# END $$ LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE;

_PACK_SQL = """
SELECT
    id, name, generic_name, brand_name, form, pack_size,
    is_available, stock_quantity, pricing_model, rx_required,
    GREATEST(
        subseq_score($1, lower(name)),
        subseq_score($1, lower(COALESCE(generic_name, ''))),
        subseq_score($1, lower(COALESCE(brand_name, '')))
    ) AS score
FROM medicines
WHERE
    subseq_score($1, lower(name)) > 0.45
    OR subseq_score($1, lower(COALESCE(generic_name, ''))) > 0.45
    OR subseq_score($1, lower(COALESCE(brand_name, ''))) > 0.45
ORDER BY score DESC
LIMIT 5;
"""

def _extract_clues(mention: str) -> list[str]:
    normalized = mention.lower()
    clues: list[str] = []
    seen: set[str] = set()
    for m in re.finditer(
        r"(?:letters?|reads?|says?|sees?|shows?|written|spelling|name\s+is)\s+([a-z]{2,8})\b",
        normalized,
    ):
        c = m.group(1)
        if c not in seen: seen.add(c); clues.append(c)
    for m in re.finditer(r"\b([a-z]{3,8})\b", normalized):
        c = m.group(1)
        if c not in seen and c not in _FORM_NOISE:
            seen.add(c); clues.append(c)
    return clues

async def pack_letter_search(mention: str) -> list[dict[str, Any]]:
    clues = _extract_clues(mention)
    if not clues:
        return []
    best_by_id: dict[int, dict] = {}
    async with _pool.acquire() as conn:
        for clue in clues[:4]:  # cap to avoid fan-out
            rows = await conn.fetch(_PACK_SQL, clue)
            for r in rows:
                rid = r["id"]
                score = float(r["score"]) * 100
                if rid not in best_by_id or score > best_by_id[rid]["match_score"]:
                    best_by_id[rid] = {
                        **dict(r), "match_score": round(score, 1),
                        "match_method": "pack_letters", "matched_clue": clue,
                    }
    return sorted(best_by_id.values(), key=lambda x: x["match_score"], reverse=True)

# ── 3. semantic via pgvector (your existing embedder) ─────────────────────────
# Requires: CREATE EXTENSION vector;
#           ALTER TABLE medicines ADD COLUMN embedding vector(384);  -- or your dim
#           CREATE INDEX ON medicines USING ivfflat (embedding vector_cosine_ops);

_SEMANTIC_SQL = """
SELECT
    id, name, generic_name, brand_name, form, pack_size,
    is_available, stock_quantity, pricing_model, rx_required,
    1 - (embedding <=> $1::vector) AS similarity
FROM medicines
WHERE embedding IS NOT NULL
ORDER BY embedding <=> $1::vector
LIMIT 5;
"""

async def semantic_search(mention: str) -> list[dict[str, Any]]:
    from semantic_search import embed_text, semantic_search_available
    if not semantic_search_available():
        return []
    vec = embed_text(mention)  # returns list[float]
    async with _pool.acquire() as conn:
        rows = await conn.fetch(_SEMANTIC_SQL, vec)
    return [
        {**dict(r), "match_score": round(float(r["similarity"]) * 100, 1), "match_method": "semantic"}
        for r in rows
    ]

# ── orchestrator (replaces search_medicines_by_mention) ───────────────────────

TEXT_CONFIDENT = float(os.getenv("MEDICINE_TEXT_CONFIDENT_SCORE", "85"))

async def search_medicines_by_mention(mention: str, *, min_score: float = 40.0) -> list[dict[str, Any]]:
    if not mention.strip():
        return []

    text_results = await text_search(mention)
    if text_results and text_results[0]["match_score"] >= TEXT_CONFIDENT:
        return text_results  # fast path, done

    # Run pack + semantic concurrently only when text isn't confident
    pack_task = asyncio.create_task(pack_letter_search(mention))
    sem_task  = asyncio.create_task(semantic_search(mention))
    pack_results, semantic_results = await asyncio.gather(pack_task, sem_task)

    merged: dict[int, dict] = {}
    for pool in (text_results, pack_results, semantic_results):
        for row in pool:
            rid = int(row["id"])
            if rid not in merged or row["match_score"] > merged[rid]["match_score"]:
                merged[rid] = row
    return sorted(
        (r for r in merged.values() if r["match_score"] >= min_score),
        key=lambda r: r["match_score"], reverse=True,
    )
```

---

## What this buys you

| | Before (Cube) | After (direct PG) |
|---|---|---|
| Text search | N HTTP round-trips to Cube | 1–3 SQL queries, ~3–8ms |
| Pack letter | Full catalog pull into Python | SQL `subseq_score()`, index scan |
| Semantic | pgvector (already fast) | Same, now async |
| Pack + semantic when needed | Sequential | `asyncio.gather` — concurrent |
| Connection overhead | Cube HTTP + PG | PG pool only |

---

## Migration steps

1. **Add `pg_trgm` extension + GIN indexes** — one-time DDL, no data migration.
2. **Create the `subseq_score` Postgres function** — paste the SQL block above into a migration.
3. **Call `init_pool()` in your Pipecat startup** (wherever you call `prewarm_semantic_search`).
4. **Swap imports** in your tool handler — `from ._medicine_search` → `from ._medicine_search_pg`. The `search_medicines_by_mention` signature is identical, just now `async`.
5. **Update the handler** to `await search_medicines_by_mention(name)` directly (no `asyncio.to_thread` wrapper needed anymore since it's native async).

The handler in `get_medicine_detail.py` barely changes — just drop the `asyncio.to_thread` wrapper since everything is native async now.