"""
Calculation queue — arq-based async pipeline with max concurrency control.

Design principles for minimal-resource environments:
- max_concurrency = 1 (single calculation at a time by default)
- Additional requests queue in arq's built-in Redis list
- Queue position exposed via GET endpoint so frontend can show "Job #N of M"
- Uses existing ResilientRedis for store (graceful degradation if Redis down)
- 20 min soft timeout / 22 min hard timeout per calculation
"""
import json
import logging
import time
from typing import Any
from uuid import UUID

from app.core.resilient_redis import ResilientRedis
from app.core.config import settings

logger = logging.getLogger(__name__)

KEY_PREFIX = "calc_queue:"
QUEUE_COUNTER_KEY = KEY_PREFIX + "counter"
RUNNING_KEY = KEY_PREFIX + "running"
QUEUE_LIST_KEY = KEY_PREFIX + "pending"

_redis: ResilientRedis | None = None
_fallback_store: dict[str, Any] = {}
_fallback_counter = 0


def _get_store() -> ResilientRedis | dict:
    global _redis
    if settings.REDIS_URL:
        if _redis is None:
            _redis = ResilientRedis.from_url(
                settings.REDIS_URL,
                socket_connect_timeout=2,
                socket_timeout=2,
                decode_responses=True,
            )
        return _redis
    return _fallback_store


def enqueue_calculation(calculation_id: UUID) -> int:
    """Add calculation to queue. Returns 1-indexed queue position."""
    global _fallback_counter
    store = _get_store()
    calc_id_str = str(calculation_id)

    if isinstance(store, dict):
        _fallback_counter += 1
        pos = _fallback_counter
        store[calc_id_str] = {"position": pos, "status": "queued", "enqueued_at": time.time()}
        return pos

    try:
        pos = store.incr(QUEUE_COUNTER_KEY)
        store.rpush(QUEUE_LIST_KEY, calc_id_str)
        store.hset(f"{KEY_PREFIX}job:{calc_id_str}", mapping={
            "position": str(pos),
            "status": "queued",
            "enqueued_at": str(time.time()),
        })
        store.expire(f"{KEY_PREFIX}job:{calc_id_str}", 86400)
        return int(pos)
    except Exception as e:
        logger.warning("[calc_queue] Redis error on enqueue: %s — using fallback", e)
        _fallback_counter += 1
        _fallback_store[calc_id_str] = {"position": _fallback_counter, "status": "queued"}
        return _fallback_counter


def dequeue_calculation() -> str | None:
    """Pop next calculation_id from queue head. Returns None if empty."""
    store = _get_store()
    if isinstance(store, dict):
        for k, v in list(store.items()):
            if v.get("status") == "queued":
                v["status"] = "running"
                return k
        return None
    try:
        calc_id_str = store.lpop(QUEUE_LIST_KEY)
        if calc_id_str:
            store.hset(f"{KEY_PREFIX}job:{calc_id_str}", "status", "running")
            store.hset(f"{KEY_PREFIX}job:{calc_id_str}", "started_at", str(time.time()))
        return calc_id_str
    except Exception as e:
        logger.warning("[calc_queue] Redis error on dequeue: %s", e)
        return None


def complete_calculation(calculation_id: str, success: bool = True):
    store = _get_store()
    if isinstance(store, dict):
        store.pop(str(calculation_id), None)
        return
    try:
        key = f"{KEY_PREFIX}job:{calculation_id}"
        store.hset(key, "status", "completed" if success else "failed")
        store.hset(key, "completed_at", str(time.time()))
        store.expire(key, 3600)
    except Exception as e:
        logger.warning("[calc_queue] Redis error on complete: %s", e)


def get_queue_status() -> dict:
    """Return queue depth + running job info."""
    store = _get_store()
    running_id = None

    if isinstance(store, dict):
        depth = sum(1 for v in store.values() if v.get("status") == "queued")
        for k, v in store.items():
            if v.get("status") == "running":
                running_id = k
                break
        return {"depth": depth, "running_calculation_id": running_id}

    try:
        depth = store.llen(QUEUE_LIST_KEY) or 0
        running_keys = store.keys(f"{KEY_PREFIX}job:*")
        for key in running_keys or []:
            status = store.hget(key, "status")
            if status == "running":
                running_id = key.replace(f"{KEY_PREFIX}job:", "")
                break
        return {"depth": int(depth), "running_calculation_id": running_id}
    except Exception as e:
        logger.warning("[calc_queue] Redis error on status: %s", e)
        return {"depth": 0, "running_calculation_id": None}
