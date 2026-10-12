import json
import logging
import os
from typing import Dict, Any, Optional

import redis.asyncio as redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)
redis_client = redis.Redis.from_url(
    os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    socket_connect_timeout=2, socket_timeout=2,
)


async def get_revenue_summary(
    property_id: str, tenant_id: str,
    month: Optional[int] = None, year: Optional[int] = None,
) -> Dict[str, Any]:
    if not tenant_id:
        raise ValueError("Tenant is required")
    # New namespace ignores legacy leaked/incorrect entries. JSON avoids collisions.
    cache_key = "revenue:v2:" + json.dumps(
        [tenant_id, property_id, year, month], separators=(",", ":")
    )
    try:
        cached = await redis_client.get(cache_key)
        if cached:
            result = json.loads(cached)
            if (result.get("tenant_id") == tenant_id
                    and result.get("property_id") == property_id
                    and all(field in result for field in ("total", "currency", "count"))):
                return result
    except (RedisError, ValueError, TypeError, AttributeError):
        logger.warning("Revenue cache unavailable or invalid; reading database")

    from app.services.reservations import calculate_total_revenue
    result = await calculate_total_revenue(property_id, tenant_id, month=month, year=year)
    try:
        await redis_client.setex(cache_key, 300, json.dumps(result))
    except RedisError:
        logger.warning("Revenue cache write failed; returning database result")
    return result

