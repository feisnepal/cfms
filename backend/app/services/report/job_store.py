"""
Redis-backed job store with in-memory fallback (for report generation jobs).

Uses a circuit-breaker Redis wrapper so the system degrades gracefully when
Redis is down and auto-recovers when it returns.
"""
import json
import logging
from typing import Any, Dict, Optional

from app.core.resilient_redis import ResilientRedis
from app.core.redis_config import redis_dsn, redacted

logger = logging.getLogger(__name__)

# Same source as the arq worker and the API-side enqueue — the three must
# agree on which Redis holds report-job state (S3-34 / hardening 3.13).
REDIS_URL = redis_dsn()
_KEY_PREFIX = "report_job:"


class _MemoryBackend:
    def __init__(self):
        self._store: Dict[str, Dict] = {}

    def get(self, job_id: str) -> Optional[Dict]:
        return self._store.get(job_id)

    def set(self, job_id: str, value: Dict) -> None:
        self._store[job_id] = value

    def delete(self, job_id: str) -> None:
        self._store.pop(job_id, None)


# Lazy-initialized resilient Redis client
_redis: Optional[ResilientRedis] = None
_use_redis = False
_memory_fallback: Optional[_MemoryBackend] = None


def _get_redis() -> ResilientRedis:
    global _redis
    if _redis is None:
        _redis = ResilientRedis.from_url(
            REDIS_URL,
            socket_connect_timeout=2,
            socket_timeout=2,
            decode_responses=True,
        )
        logger.info("[jobstore] ResilientRedis initialized at %s", redacted(REDIS_URL))
    return _redis


def _get_backend() -> Any:
    """Get the backing store (ResilientRedis or in-memory fallback)."""
    global _use_redis, _memory_fallback
    r = _get_redis()

    # Check circuit state to decide
    if r.state.name == "OPEN":
        if _use_redis:
            logger.warning("[jobstore] Circuit OPEN -> falling back to in-memory")
            _use_redis = False
    elif r.state.name == "CLOSED":
        if not _use_redis:
            logger.info("[jobstore] Circuit CLOSED -> using Redis")
            _use_redis = True

    if _use_redis:
        return r

    if _memory_fallback is None:
        _memory_fallback = _MemoryBackend()
    return _memory_fallback


def get_job(job_id: str) -> Optional[Dict]:
    """Retrieve a job from the store by its ID."""
    backend = _get_backend()
    if _use_redis:
        raw = backend.get(_KEY_PREFIX + job_id)
        return json.loads(raw) if raw else None
    return backend.get(job_id)


def save_job(job_id: str, job: Dict) -> None:
    """Save a job to the store (Redis with in-memory fallback)."""
    backend = _get_backend()
    if _use_redis:
        backend.set(_KEY_PREFIX + job_id, json.dumps(job), ex=86400)
    else:
        backend.set(job_id, job)


def delete_job(job_id: str) -> None:
    """Delete a job from the store by its ID."""
    backend = _get_backend()
    if _use_redis:
        backend.delete(_KEY_PREFIX + job_id)
    else:
        backend.delete(job_id)


def is_redis_enabled() -> bool:
    """Return True if the Redis backend is currently active (not in-memory fallback)."""
    _get_backend()
    return _use_redis