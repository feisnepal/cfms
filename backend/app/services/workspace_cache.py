"""Workspace cache service — Redis-backed layer list cache with circuit breaker fallback."""
import json
import logging
from typing import Optional
from uuid import UUID

from ..core.config import settings
from ..core.resilient_redis import ResilientRedis

logger = logging.getLogger(__name__)

_redis: Optional[ResilientRedis] = None
CACHE_TTL = 60  # 60 seconds

def _get_redis() -> Optional[ResilientRedis]:
    global _redis
    if _redis is None and settings.REDIS_URL:
        try:
            _redis = ResilientRedis.from_url(settings.REDIS_URL)
            logger.info("WorkspaceCache: Redis connected")
        except Exception as e:
            logger.warning("WorkspaceCache: Redis unavailable (%s), using no-op cache", e)
            _redis = None
    return _redis

def _cache_key(calculation_id: UUID, suffix: str = "layers") -> str:
    return f"workspace:{calculation_id}:{suffix}"

def cache_layers_list(calculation_id: UUID, layers_data: list[dict]) -> None:
    r = _get_redis()
    if r is None:
        return
    try:
        r.set(
            _cache_key(calculation_id),
            json.dumps(layers_data, default=str),
            ex=CACHE_TTL,
        )
    except Exception as e:
        logger.debug("WorkspaceCache: set failed (%s)", e)

def get_cached_layers(calculation_id: UUID) -> Optional[list[dict]]:
    r = _get_redis()
    if r is None:
        return None
    try:
        raw = r.get(_cache_key(calculation_id))
        if raw:
            return json.loads(raw)
    except Exception as e:
        logger.debug("WorkspaceCache: get failed (%s)", e)
    return None

def invalidate_layers_cache(calculation_id: UUID) -> None:
    r = _get_redis()
    if r is None:
        return
    try:
        r.delete(_cache_key(calculation_id))
    except Exception as e:
        logger.debug("WorkspaceCache: delete failed (%s)", e)
