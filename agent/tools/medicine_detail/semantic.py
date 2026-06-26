from __future__ import annotations

import os
from typing import Any

from tools.medicine_detail.db import get_pool

SEMANTIC_ENABLED = os.getenv("SEMANTIC_SEARCH_ENABLED", "1").strip().lower() in (
    "1",
    "true",
    "yes",
)

_embedding_model = None


def semantic_search_available() -> bool:
    if not SEMANTIC_ENABLED:
        return False
    try:
        from fastembed import TextEmbedding  # noqa: F401

        return True
    except ImportError:
        return False


def _get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        from fastembed import TextEmbedding

        _embedding_model = TextEmbedding(
            model_name="sentence-transformers/all-MiniLM-L6-v2"
        )
    return _embedding_model


def embed_text(text: str) -> list[float]:
    model = _get_embedding_model()
    return list(next(model.embed([text])))


def prewarm_embedding_model() -> bool:
    if not semantic_search_available():
        return False
    embed_text("warmup")
    return True


_SEMANTIC_SQL = """
SELECT
    id, name, generic_name, brand_name, form, pack_size,
    selling_price, mrp, discount_percent, price_per_unit, currency,
    is_available, stock_quantity, prescription_required, pricing_model,
    1 - (embedding <=> $1::vector) AS similarity
FROM medicines
WHERE embedding IS NOT NULL
ORDER BY embedding <=> $1::vector
LIMIT 5
"""


async def semantic_search(mention: str) -> list[dict[str, Any]]:
    from tools.medicine_detail.db import format_medicine_row

    if not semantic_search_available():
        return []

    vec = embed_text(mention)
    vec_literal = "[" + ",".join(str(v) for v in vec) + "]"

    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(_SEMANTIC_SQL, vec_literal)

    results: list[dict[str, Any]] = []
    for row in rows:
        similarity = float(row["similarity"])
        results.append(
            format_medicine_row(
                row,
                match_score=round(similarity * 100, 1),
                match_method="semantic",
                similarity=round(similarity, 3),
            )
        )
    return results
