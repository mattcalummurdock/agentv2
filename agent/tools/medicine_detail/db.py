import os
from typing import Any

import asyncpg

_pool: asyncpg.Pool | None = None
_pool_refs: int = 0


async def acquire_pool(pool: asyncpg.Pool | None = None) -> asyncpg.Pool:
    if pool is not None:
        return pool
    return await get_pool()

MEDICINE_COLUMNS = """
    id, name, generic_name, brand_name, form, pack_size,
    selling_price, mrp, discount_percent, price_per_unit, currency,
    is_available, stock_quantity, prescription_required, pricing_model
"""


def stock_status(row: dict[str, Any]) -> str:
    if not row.get("is_available"):
        return "unavailable"
    qty = row.get("stock_quantity") or 0
    if qty <= 0:
        return "out_of_stock"
    if qty < 10:
        return "low_stock"
    return "in_stock"


def format_medicine_row(row: asyncpg.Record, **extra: Any) -> dict[str, Any]:
    data = dict(row)
    selling_price = data.get("selling_price")
    mrp = data.get("mrp")
    discount = data.get("discount_percent")
    price_per_unit = data.get("price_per_unit")

    item: dict[str, Any] = {
        "id": data["id"],
        "name": data.get("name"),
        "generic_name": data.get("generic_name"),
        "brand_name": data.get("brand_name"),
        "form": data.get("form"),
        "pack_size": data.get("pack_size"),
        "selling_price": float(selling_price) if selling_price is not None else None,
        "mrp": float(mrp) if mrp is not None else None,
        "discount_percent": float(discount) if discount is not None else None,
        "price_per_unit": float(price_per_unit) if price_per_unit is not None else None,
        "currency": data.get("currency") or "INR",
        "is_available": bool(data.get("is_available")),
        "stock_quantity": data.get("stock_quantity"),
        "stock_status": stock_status(data),
        "rx_required": bool(data.get("prescription_required")),
        "pricing_model": data.get("pricing_model"),
    }
    item.update(extra)
    return item


async def _create_pool() -> asyncpg.Pool:
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise ValueError("DATABASE_URL environment variable is not set")
    return await asyncpg.create_pool(dsn, min_size=2, max_size=10)


async def init_pool() -> None:
    """Acquire a reference to the shared pool (one per active bot session)."""
    global _pool, _pool_refs
    if _pool is None:
        _pool = await _create_pool()
    _pool_refs += 1


async def close_pool() -> None:
    """Release a session reference; close the pool when none remain."""
    global _pool, _pool_refs
    if _pool_refs > 0:
        _pool_refs -= 1
    if _pool_refs == 0 and _pool is not None:
        await _pool.close()
        _pool = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await _create_pool()
    return _pool
