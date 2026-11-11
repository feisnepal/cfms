"""
ResilientRedis: Redis client wrapper with circuit-breaker fallback.

- Uses pybreaker-style state machine: CLOSED -> OPEN -> HALF_OPEN -> CLOSED
- On repeated failures, opens circuit and falls back to in-memory
- Periodically tests Redis (half-open) to auto-recover
- Compatible with redis-py API (get/set/delete)
"""
import time
import logging
from enum import Enum
from typing import Any, Optional, Union

import redis

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states for Redis connection."""
    CLOSED = "closed"      # Normal operation, using Redis
    OPEN = "open"          # Redis failing, using fallback
    HALF_OPEN = "half_open"  # Testing Redis recovery


class ResilientRedis:
    """
    Redis client with circuit-breaker pattern.

    Usage:
        r = ResilientRedis.from_url("redis://localhost:6379/0")
        r.get("key")
        r.set("key", "value", ex=3600)

    The client automatically switches to an in-memory fallback when Redis
    is unavailable, and attempts to recover periodically.
    """

    def __init__(
        self,
        *,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: Optional[str] = None,
        socket_connect_timeout: int = 2,
        socket_timeout: int = 2,
        decode_responses: bool = True,
        failure_threshold: int = 3,
        recovery_timeout: int = 30,
        success_threshold: int = 1,
        **kwargs: Any,
    ) -> None:
        self._params = {
            "host": host,
            "port": port,
            "db": db,
            "password": password,
            "socket_connect_timeout": socket_connect_timeout,
            "socket_timeout": socket_timeout,
            "decode_responses": decode_responses,
            **kwargs,
        }
        self._r: Optional[redis.Redis] = None
        self._memory: dict = {}

        # Circuit breaker config
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._success_threshold = success_threshold

        # Circuit state
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float = 0

    @classmethod
    def from_url(cls, url: str, **kwargs: Any) -> "ResilientRedis":  # type: ignore[no-untyped-def]
        """Create from redis URL (redis://host:port/db)."""
        parsed = redis.connection.parse_url(url)
        return cls(**{**parsed, **kwargs})

    @property
    def state(self) -> CircuitState:
        # Check if we should transition from OPEN to HALF_OPEN
        if self._state == CircuitState.OPEN:
            if time.time() - self._last_failure_time >= self._recovery_timeout:
                logger.info("[ResilientRedis] Transitioning OPEN -> HALF_OPEN")
                self._state = CircuitState.HALF_OPEN
                self._success_count = 0
        return self._state

    def _ensure_connection(self) -> None:
        if self._r is None:
            self._r = redis.Redis(**self._params)

    def _record_success(self) -> None:
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self._success_threshold:
                logger.info("[ResilientRedis] Circuit CLOSED (recovered)")
                self._state = CircuitState.CLOSED
                self._failure_count = 0
        elif self._state == CircuitState.CLOSED:
            self._failure_count = 0  # Reset on success

    def _record_failure(self, exc: Exception) -> None:
        self._failure_count += 1
        self._last_failure_time = time.time()

        if self._state == CircuitState.HALF_OPEN:
            # Any failure in half-open -> back to OPEN
            logger.warning("[ResilientRedis] HALF_OPEN -> OPEN (recovery failed): %s", exc)
            self._state = CircuitState.OPEN
            self._failure_count = 0
        elif self._state == CircuitState.CLOSED:
            if self._failure_count >= self._failure_threshold:
                logger.warning("[ResilientRedis] Circuit OPEN after %d failures: %s",
                               self._failure_count, exc)
                self._state = CircuitState.OPEN

    # --- Redis-compatible API (subset) ---

    def get(self, key: str) -> Optional[str]:
        self.state  # trigger state check
        if self.state == CircuitState.OPEN:
            return self._memory.get(key)

        self._ensure_connection()
        assert self._r is not None
        try:
            val = self._r.get(key)
            self._record_success()
            return val  # type: ignore[return-value]
        except redis.RedisError as e:
            self._record_failure(e)
            return self._memory.get(key)

    def set(
        self,
        key: str,
        value: Union[str, bytes],
        ex: Optional[int] = None,
        px: Optional[int] = None,
        nx: bool = False,
        xx: bool = False,
    ) -> bool:
        self.state
        if self.state == CircuitState.OPEN:
            self._memory[key] = value
            return True

        self._ensure_connection()
        assert self._r is not None
        try:
            result = self._r.set(key, value, ex=ex, px=px, nx=nx, xx=xx)
            self._record_success()
            return bool(result)  # type: ignore[return-value]
        except redis.RedisError as e:
            self._record_failure(e)
            self._memory[key] = value
            return True  # fallback "succeeded"

    def delete(self, *keys: str) -> int:
        self.state
        if self.state == CircuitState.OPEN:
            count = 0
            for k in keys:
                if k in self._memory:
                    del self._memory[k]
                    count += 1
            return count

        self._ensure_connection()
        assert self._r is not None
        try:
            result = self._r.delete(*keys)
            self._record_success()
            return result  # type: ignore[return-value]
        except redis.RedisError as e:
            self._record_failure(e)
            count = 0
            for k in keys:
                if k in self._memory:
                    del self._memory[k]
                    count += 1
            return count

    def ping(self) -> bool:
        self.state
        if self.state == CircuitState.OPEN:
            return False

        self._ensure_connection()
        assert self._r is not None
        try:
            result = self._r.ping()
            self._record_success()
            return bool(result)  # type: ignore[return-value]
        except redis.RedisError as e:
            self._record_failure(e)
            return False

    # Alias for redis-py compatibility
    def setex(self, key: str, time: int, value: Union[str, bytes]) -> bool:
        return self.set(key, value, ex=time)