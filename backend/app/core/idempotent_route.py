"""Idempotency applied by the route, not by remembering (H2.17 · S2-64).

`services/idempotency.py` is the mechanism. This is how it reaches the writes
that need it.

**Why a route class and not a per-handler call.** The service landed with two
call sites, both in `workspace.py` -- the same two the Redis version had. That
is the failure `body_limits.py` documents for `validate_vertex_count`: a guard
declared per handler is present exactly where somebody remembered it, and the
84 mobile-facing writes that nobody remembered were the whole finding. A router
built with `route_class=IdempotentRoute` covers every route it carries,
including the one added next month, and `scripts/check_idempotency_coverage.py`
fails the build if a router that should carry it does not.

FastAPI preserves the class through `include_router` (`route_class_override=
type(route)`), so mounting under both `/api/v1` and the legacy `/api` keeps the
guard on both.

**What it does, in order.** For a mutating request it takes the key from the
`Idempotency-Key` header or an `idempotency_key` field in the JSON body -- the
body form because `workspace.py`'s existing clients send it that way and this
must not break them. `begin()` then either hands over the reservation or
returns the previous response, and there is no third path: a duplicate cannot
proceed to the handler.

**Blocking work goes to the threadpool.** The wrapper is async because Starlette
requires it, but every database call inside is synchronous, and running one on
the event loop is the defect G-PERF-1 exists to stop (H3.1 moved 290 handlers
off it). `run_in_threadpool` keeps this off the loop.

**The key is not required yet.** `IDEMPOTENCY_REQUIRE_KEY` defaults to false:
the web frontend calls these same endpoints today without a key, so requiring
one now would break the live app to protect a mobile client that does not exist
yet. Unprotected writes are logged by name, so the gap is visible rather than
assumed. Flipping the setting to true is a launch-day step, and belongs with
the mobile client audit (8.0).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Coroutine, Optional

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool

from .config import settings
from .database import SessionLocal

logger = logging.getLogger(__name__)

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Only these are replayable. A streaming or file response has no `.body` to
# store, so replaying it is impossible and pretending otherwise would hand a
# retry an empty 200 -- worse than re-running the work.
_JSON_SUFFIXES = ("/json", "+json")

# The stored value carries the status code as well as the body, because a
# replayed 201 that comes back as 200 is a different answer to the same
# question. A stored value WITHOUT this marker is treated as a bare body at
# status 200, so records written by a direct `mark_completed()` call still
# replay correctly.
_ENVELOPE = "__idempotent__"


def _resource_of(request: Request) -> str:
    """Scope the key to this concrete path, version prefix removed.

    The concrete path and not the route pattern: `{calculation_id}` is exactly
    the part that makes two uploads different operations, and a pattern throws
    it away. The prefix is stripped so a client that retries against `/api`
    after reaching `/api/v1` is recognised as the same write -- the routers are
    mounted twice and both mounts serve the same handler.
    """
    path = request.url.path
    for prefix in (settings.API_V1_PREFIX, "/api"):
        if prefix and path.startswith(prefix + "/"):
            path = path[len(prefix) :]
            break
    return f"{request.method} {path}"[:255]


def _key_from(request: Request, parsed: Any) -> Optional[str]:
    """Header first, then an `idempotency_key` field in a JSON object body."""
    key = request.headers.get("Idempotency-Key")
    if key and key.strip():
        return key.strip()
    if isinstance(parsed, dict):
        value = parsed.get("idempotency_key")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _is_json(content_type: str) -> bool:
    base = content_type.split(";", 1)[0].strip().lower()
    return base.endswith(_JSON_SUFFIXES)


def _storable(response: Response, resource: str) -> Optional[dict[str, Any]]:
    """The envelope to store, or None when this response cannot be replayed."""
    if response.status_code >= 400:
        # A failed write must not be replayed as though it succeeded. Returning
        # None marks the record failed, so the client's retry gets a real
        # attempt rather than a cached error.
        return None
    body = getattr(response, "body", None)
    if body is None:
        logger.warning(
            "idempotency: %s returned a streaming response; retries will re-run it",
            resource,
        )
        return None
    if not body:
        return {_ENVELOPE: 1, "status": response.status_code, "body": None}
    try:
        return {
            _ENVELOPE: 1,
            "status": response.status_code,
            "body": json.loads(body),
        }
    except ValueError:
        logger.warning(
            "idempotency: %s returned a non-JSON body; retries will re-run it",
            resource,
        )
        return None


def _replay(stored: Any) -> JSONResponse:
    """Rebuild the original response.

    `Idempotent-Replay` tells the client this is a recorded answer and not a
    fresh one -- without it a device cannot distinguish "my retry worked" from
    "my retry was recognised", and that distinction matters when reconciling a
    field upload.
    """
    if isinstance(stored, dict) and stored.get(_ENVELOPE):
        status_code = int(stored.get("status") or 200)
        body = stored.get("body")
    else:
        status_code, body = 200, stored
    return JSONResponse(
        status_code=status_code,
        content=body,
        headers={"Idempotent-Replay": "true"},
    )


class IdempotentRoute(APIRoute):
    """An `APIRoute` whose mutating verbs are replay-safe."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def guarded(request: Request) -> Response:
            if request.method not in MUTATING_METHODS:
                return await original(request)

            content_type = request.headers.get("content-type", "")
            parsed: Any = None

            if _is_json(content_type):
                # Reading the body here caches it on the request, so the
                # handler's own parse still works -- Starlette returns the
                # cached bytes rather than re-reading a consumed stream.
                raw = await request.body()
                if raw:
                    try:
                        parsed = json.loads(raw)
                    except ValueError:
                        # Malformed JSON is the handler's error to report, with
                        # its own 422 and field detail. Passing it through
                        # unguarded is correct: it will not write anything.
                        return await original(request)
                fingerprint_source: Any = parsed
            else:
                # Multipart is never buffered. FastAPI spools uploads past 1 MB
                # to disk, and holding 50 MB in a wrapper to protect against
                # holding 50 MB would be its own defect (`body_limits.py` makes
                # the same call). The size stands in for the body: it will not
                # catch a same-length edit, but it does catch the ordinary
                # "same key, different file", and replay protection -- the part
                # that stops a duplicate upload -- does not depend on it.
                #
                # The media type WITHOUT its parameters: a multipart Content-Type carries a
                # fresh random boundary on every request, so a retry of the very same upload
                # would otherwise read as "a different request body" (422) instead of being
                # recognised -- which defeats the key on the one kind of write where a lost
                # answer is most common (a photo sent over a weak signal).
                fingerprint_source = {
                    "content_type": content_type.split(";", 1)[0].strip().lower(),
                    "content_length": request.headers.get("content-length"),
                }

            key = _key_from(request, parsed)
            if not key and not settings.IDEMPOTENCY_REQUIRE_KEY:
                logger.info(
                    "idempotency: unprotected write, no key on %s",
                    _resource_of(request),
                )
                return await original(request)

            resource = _resource_of(request)
            # Imported here rather than at module scope: `app.core` is imported
            # by nearly everything, and pulling a service in at that level is
            # how an import cycle starts.
            from ..services.idempotency import (  # noqa: PLC0415
                begin,
                mark_completed,
                mark_failed,
            )

            db = SessionLocal()
            try:
                outcome = await run_in_threadpool(
                    begin,
                    db,
                    key,
                    resource,
                    fingerprint_source,
                    required=settings.IDEMPOTENCY_REQUIRE_KEY,
                )
                if outcome.replay is not None:
                    return _replay(outcome.replay)
                if not outcome.owned:
                    # The record vanished between the insert and the read, so
                    # there is nothing to record against. `begin()` has already
                    # logged it; proceeding unguarded beats refusing a write
                    # that may never have happened.
                    return await original(request)

                try:
                    response = await original(request)
                except Exception as exc:
                    await run_in_threadpool(mark_failed, db, key, resource, exc)
                    raise

                stored = _storable(response, resource)
                if stored is None:
                    # Leaving the record `completed` here would hand the next
                    # retry an empty 200. Marking it failed lets that retry
                    # re-run the work, which is the honest outcome for a
                    # response we cannot reproduce.
                    await run_in_threadpool(
                        mark_failed,
                        db,
                        key,
                        resource,
                        "response is not replayable; retry will re-run",
                    )
                else:
                    await run_in_threadpool(mark_completed, db, key, resource, stored)
                return response
            finally:
                db.close()

        return guarded
