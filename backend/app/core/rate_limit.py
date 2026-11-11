"""One rate limiter for the whole application.

Two things were wrong with what this replaced, and the second is the one that
bites in the field.

**It counted addresses, not people.** `get_remote_address` keys every request on
the connecting IP. Nepal's mobile networks put hundreds of subscribers behind
one carrier-grade NAT address, so a district's enumerators syncing after a day
offline arrive as a single client. A 10/min login limit locked out the district
the moment the eleventh person tried. Keys are now derived from the bearer
token where there is one, so two users behind one address never spend each
other's budget; only genuinely anonymous traffic falls back to an address, and
that address is resolved through `client_ip.resolve_client_ip` rather than
trusting whatever opened the socket.

**It lived in each worker's memory.** Counters in a process are counters that
multiply by the worker count and reset on every deploy. Pointing the storage at
Redis makes one limit mean one limit, and survive a restart. When Redis is not
configured — a developer machine — it degrades to memory and says so; when
Redis is configured but falls over, `in_memory_fallback` keeps the limiter
serving rather than failing requests closed.

The limiter also carries a **default limit for every route**, so a new endpoint
is protected the day it is written. Per-route decorators override it.
"""
from __future__ import annotations

import logging
from typing import Optional

import jwt
from slowapi import Limiter
from starlette.requests import Request

from .client_ip import resolve_client_ip
from .config import settings

logger = logging.getLogger(__name__)

# Namespaced so limiter counters cannot collide with the response cache, which
# shares the same Redis database under its own "cfm-cache:" prefix.
KEY_PREFIX = "cfm-rl"


def _bearer_subject(request: Request) -> Optional[str]:
    """The user id inside the request's bearer token, if it carries one.

    The signature is verified — an unsigned claim would let anyone mint a fresh
    bucket per request and sidestep the limit entirely. Expiry deliberately is
    not: an expired token still proves *who* the holder is, and a field worker
    whose token lapses mid-sync should keep their own budget rather than being
    dropped into the shared NAT bucket at the worst possible moment. The request
    is rejected on its own merits a few microseconds later either way.
    """
    header = request.headers.get("authorization") or ""
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={"verify_exp": False},
        )
    except jwt.InvalidTokenError:
        return None
    subject = payload.get("sub")
    return str(subject) if subject else None


def identity_key(request: Request) -> str:
    """Who this request should be billed to.

    `user:<id>` when the caller is authenticated, `ip:<addr>` otherwise. The
    prefixes keep the two namespaces from ever colliding — a user id and an
    address are different kinds of thing and must not share a bucket.
    """
    subject = _bearer_subject(request)
    if subject:
        return f"user:{subject}"
    return f"ip:{resolve_client_ip(request)}"


def resolve_storage_uri() -> str:
    """Where counters live: explicit setting, else Redis, else memory."""
    explicit = (getattr(settings, "RATE_LIMIT_STORAGE_URI", "") or "").strip()
    if explicit:
        return explicit
    redis_url = (getattr(settings, "REDIS_URL", "") or "").strip()
    if redis_url:
        return redis_url
    return "memory://"


_storage_uri = resolve_storage_uri()

if _storage_uri.startswith("memory://"):
    logger.warning(
        "Rate limiting is using in-process memory. Limits are per-worker and "
        "reset on restart. Set REDIS_URL for a shared, durable limiter."
    )

limiter = Limiter(
    key_func=identity_key,
    default_limits=[settings.RATE_LIMIT_DEFAULT],
    storage_uri=_storage_uri,
    key_prefix=KEY_PREFIX,
    enabled=settings.RATE_LIMIT_ENABLED,
    # If Redis goes down mid-request, keep limiting from memory instead of
    # failing the request. A degraded limit beats a 500 on every route.
    in_memory_fallback_enabled=True,
)


def storage_backend() -> str:
    """Which backend is in use, for /health and startup logging."""
    return "memory" if _storage_uri.startswith("memory://") else "redis"


_SHARED_STORAGE = None


def shared_storage():
    """The counter store used by everything that is not a slowapi decorator.

    slowapi builds its own storage from the same URI; this is the one the
    workspace limiters and the tiered middleware share. Created on first use,
    never at import — importing the app must not open a Redis connection, or
    `conftest` and the migration scripts cannot import it without a running
    Redis.

    One instance rather than one per caller so tests have a single thing to
    reset, and so an in-memory deployment does not silently multiply its limits
    by the number of components that happened to build a store.
    """
    global _SHARED_STORAGE
    if _SHARED_STORAGE is None:
        from limits.storage import storage_from_string

        _SHARED_STORAGE = storage_from_string(_storage_uri)
    return _SHARED_STORAGE
