# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Cermak
"""A11 — Performance Optimization snippets (good / medium / bad).

Domain: Query optimization, N+1 fixes, caching, eager loading, profiling.
"""

GOOD: dict = {
    "eval_score": 9.0,
    "output": "Fixed N+1 on /search: replaced lazy loads with joinedload, added Redis cache. p95 latency 820ms → 45ms.",
    "code": '''\
import hashlib
import json
import logging
from functools import wraps
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# --- Query cache decorator ---

class QueryCache:
    """Simple async-compatible cache backed by Redis.

    Features:
        - TTL-based expiration
        - Key derivation from query parameters
        - Automatic serialization via json
        - Cache invalidation by prefix
    """

    def __init__(self, redis_client, default_ttl: int = 300) -> None:
        self._redis = redis_client
        self._ttl = default_ttl

    def _make_key(self, prefix: str, params: dict) -> str:
        raw = json.dumps(params, sort_keys=True, default=str)
        digest = hashlib.sha256(raw.encode()).hexdigest()[:12]
        return f"cache:{prefix}:{digest}"

    async def get(self, prefix: str, params: dict) -> Any | None:
        key = self._make_key(prefix, params)
        data = await self._redis.get(key)
        if data:
            logger.debug("Cache HIT: %s", key)
            return json.loads(data)
        logger.debug("Cache MISS: %s", key)
        return None

    async def set(self, prefix: str, params: dict, value: Any, ttl: int | None = None) -> None:
        key = self._make_key(prefix, params)
        await self._redis.setex(key, ttl or self._ttl, json.dumps(value, default=str))

    async def invalidate(self, prefix: str) -> int:
        pattern = f"cache:{prefix}:*"
        keys = []
        async for key in self._redis.scan_iter(match=pattern):
            keys.append(key)
        if keys:
            await self._redis.delete(*keys)
        return len(keys)


# --- Optimized search query (fixes N+1) ---

async def search_products(
    db: AsyncSession,
    query: str,
    category_id: str | None = None,
    limit: int = 20,
    offset: int = 0,
    cache: QueryCache | None = None,
) -> list[dict]:
    """Search products with eager-loaded relations (no N+1).

    Before: each product triggered 3 lazy loads (category, images, reviews).
    After:  single query with joinedload + selectinload.

    Args:
        db: Async database session.
        query: Search term (matched against name and description).
        category_id: Optional filter by category.
        limit: Max results (default 20).
        offset: Pagination offset.
        cache: Optional query cache.

    Returns:
        List of product dicts with nested category, images, review_summary.
    """
    params = {"q": query, "cat": category_id, "limit": limit, "offset": offset}
    if cache:
        cached = await cache.get("search", params)
        if cached is not None:
            return cached

    stmt = (
        select(Product)
        .options(
            joinedload(Product.category),
            selectinload(Product.images),
            selectinload(Product.reviews),
        )
        .where(Product.search_vector.match(query))
    )
    if category_id:
        stmt = stmt.where(Product.category_id == category_id)

    stmt = stmt.order_by(Product.relevance_score.desc()).limit(limit).offset(offset)
    result = await db.execute(stmt)
    products = result.scalars().unique().all()

    response = [
        {
            "id": str(p.id),
            "name": p.name,
            "price": str(p.price),
            "category": p.category.name if p.category else None,
            "image_count": len(p.images),
            "avg_rating": sum(r.score for r in p.reviews) / len(p.reviews) if p.reviews else None,
        }
        for p in products
    ]

    if cache:
        await cache.set("search", params, response)

    return response
''',
}

MEDIUM: dict = {
    "eval_score": 5.8,
    "output": "Added eager loading to search query.",
    "code": """\
from sqlalchemy import select
from sqlalchemy.orm import joinedload

async def search_products(db, query, limit=20):
    stmt = (
        select(Product)
        .options(joinedload(Product.category))
        .where(Product.name.ilike(f"%{query}%"))
        .limit(limit)
    )
    result = await db.execute(stmt)
    return [{"id": p.id, "name": p.name, "category": p.category.name}
            for p in result.scalars().all()]
""",
}

BAD: dict = {
    "eval_score": 2.8,
    "output": "search works",
    "code": """\
async def search(db, q):
    products = db.query(Product).filter(Product.name.like(f"%{q}%")).all()
    results = []
    for p in products:
        cat = db.query(Category).get(p.category_id)  # N+1 query
        results.append({"name": p.name, "category": cat.name})
    return results
""",
}
