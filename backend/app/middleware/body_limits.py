"""Ingress limits on the request body (H2.15 · S2-56).

Two defences were built and then not applied. `MAX_UPLOAD_SIZE_MB` was defined
in `config.py` and enforced by nothing — no middleware, no route, nowhere. And
`validate_vertex_count` was written carefully, comment and all, then wired into
exactly two call sites, both in `workspace.py`. Every other geometry entrance —
`geometry.py`, `editing.py`, `blocks.py`, `compartments.py`,
`yearly_activities.py`, the sub-area paths — took whatever it was given. A
single POST carrying a polygon of a million vertices reached Shapely and
PostGIS unguarded, and with the blocking work already on the event loop
(S1-17), one such request stalls the process for everyone.

**Why this is middleware and not the per-route dependency the plan named.**
The dependency form has to be declared on each route, which means the guard is
present exactly where someone remembered it — the same failure that produced
S2-56 in the first place, and the same argument that decided the tier
classifier in `tiered_rate_limit.py`. There is also no honest way to gate on
it: FastAPI cannot tell you which routes accept geometry, because a body typed
`Dict[str, Any]` (most of them) declares nothing. So the limit is derived from
what the request *is*. A body carrying coordinates is checked whatever route
receives it, including the route written next month.

Order of enforcement, cheapest first:

1. `Content-Length` over the cap — refused before the body is read at all.
2. A body that arrives larger than it declared, or declares nothing (chunked) —
   caught while streaming, so a lying header buys nothing.
3. Positions counted on JSON bodies, per geometry and per request.

Multipart bodies are counted but never buffered: FastAPI spools uploads to disk
past 1 MB, and holding 50 MB in middleware to protect against holding 50 MB
would be its own defect. JSON bodies are buffered, which is safe because by
then they are known to be under `MAX_JSON_BODY_SIZE_MB`.
"""
from __future__ import annotations

import json
import logging

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import settings
from app.core.constants import (
    REQUEST_MAX_TOTAL_VERTICES,
    WORKSPACE_IMPORT_MAX_VERTICES,
)
from app.services.geometry_sanitizer import count_positions

logger = logging.getLogger(__name__)

# Verbs that carry no body. Checking the method first keeps the whole middleware
# off the path of the reads, which are most of the traffic.
_BODYLESS_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "DELETE", "TRACE"})

# Content types whose body is JSON we can count. `application/geo+json` and the
# `+json` suffix convention are included because the geometry routes do use
# them, and a guard that a caller can step around by relabelling the body is
# not a guard.
_JSON_SUFFIXES = ("/json", "+json")

# Below this size a JSON body is scanned for the literal bytes `coordinates`
# and parsed only if it has them, which keeps the guard off the cost of
# ordinary traffic — logins, filters, settings — which is nearly all of it.
# Above it every body is parsed, because a substring scan is evadable: JSON
# permits `{"coordi\u006eates": ...}`, which decodes to the real key and would
# otherwise walk straight past. The threshold is set below what the smallest
# possible over-cap body could be — 5,001 positions cannot be encoded in fewer
# than about 30 KB even at `[1,2],` — so nothing the guard exists to catch can
# hide under it.
_PARSE_EVERY_BODY_ABOVE_BYTES = 16 * 1024


def is_json_body(content_type: str) -> bool:
    """True when the declared content type is some flavour of JSON."""
    base = content_type.split(";", 1)[0].strip().lower()
    return any(base.endswith(suffix) for suffix in _JSON_SUFFIXES)


def limit_bytes_for(content_type: str) -> int:
    """The size cap this body is held to, in bytes."""
    base = content_type.split(";", 1)[0].strip().lower()
    megabytes = (
        settings.MAX_UPLOAD_SIZE_MB
        if base == "multipart/form-data"
        else settings.MAX_JSON_BODY_SIZE_MB
    )
    return megabytes * 1024 * 1024


def _error(error_code: str, message: str, details: dict) -> bytes:
    return json.dumps(
        {
            "error_code": error_code,
            "message": message,
            "details": details,
        }
    ).encode("utf-8")


class RequestBodyLimitMiddleware:
    """Caps request body size, and the geometry a JSON body may carry.

    Written as raw ASGI rather than `BaseHTTPMiddleware` because it has to see
    the body as it streams — the size cap is only worth having if it survives a
    `Content-Length` that lies, and a chunked body has no length to read.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method", "").upper() in _BODYLESS_METHODS:
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        content_type = headers.get("content-type", "")
        limit = limit_bytes_for(content_type)

        declared = headers.get("content-length")
        if declared is not None:
            try:
                if int(declared) > limit:
                    await self._send_too_large(send, limit, int(declared))
                    return
            except ValueError:
                pass  # Unparseable length; the streaming counter still applies.

        if is_json_body(content_type):
            await self._handle_json(scope, receive, send, limit)
            return

        await self._handle_streamed(scope, receive, send, limit)

    # -- non-JSON: count bytes as they pass, never accumulate them ----------

    async def _handle_streamed(
        self, scope: Scope, receive: Receive, send: Send, limit: int
    ) -> None:
        seen = 0
        over_limit = False
        answered = False
        started = False

        async def counting_receive() -> Message:
            nonlocal seen, over_limit
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    # Cut the body off rather than raising. FastAPI wraps any
                    # exception thrown while it is reading the body into its own
                    # "There was an error parsing the body" 400, which would
                    # bury the real reason — so the request is disconnected here
                    # and the response is replaced below.
                    over_limit = True
                    return {"type": "http.disconnect"}
            return message

        async def gated_send(message: Message) -> None:
            nonlocal answered, started
            if not over_limit or started:
                # Once a response has begun there is no taking it back — a
                # second `http.response.start` is an ASGI protocol violation.
                # A handler streaming its answer while still reading the body
                # is rare, but it must not be turned into a crash.
                if message["type"] == "http.response.start":
                    started = True
                await send(message)
                return
            # Whatever the handler made of a truncated body, the honest answer
            # is that the body was too large. Its response is discarded.
            if not answered:
                answered = True
                await self._send_too_large(send, limit, seen)

        try:
            await self.app(scope, counting_receive, gated_send)
        except Exception:
            # A handler that raised on the truncated body is still owed a 413,
            # not a 500. Anything else is not ours and propagates.
            if started or not over_limit or answered:
                raise
            answered = True
            await self._send_too_large(send, limit, seen)
            return

        if over_limit and not answered and not started:
            await self._send_too_large(send, limit, seen)

    # -- JSON: buffer under the cap, then count what it carries -------------

    async def _handle_json(
        self, scope: Scope, receive: Receive, send: Send, limit: int
    ) -> None:
        chunks: list[bytes] = []
        seen = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            seen += len(chunk)
            if seen > limit:
                await self._send_too_large(send, limit, seen)
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break

        body = b"".join(chunks)
        rejection = self._geometry_rejection(body)
        if rejection is not None:
            status, payload = rejection
            await self._send_json(send, status, payload)
            return

        await self.app(scope, _replay(body), send)

    def _geometry_rejection(self, body: bytes) -> tuple[int, bytes] | None:
        """`None` if the body is acceptable, else the response to send instead."""
        if not body:
            return None
        if (
            b"coordinates" not in body
            and len(body) <= _PARSE_EVERY_BODY_ABOVE_BYTES
        ):
            # Too small to be hiding anything, and nothing shaped like geometry.
            return None

        try:
            decoded = json.loads(body)
        except (ValueError, RecursionError):
            # Malformed JSON is the route handler's 422 to give, not ours. It
            # never reaches geometry code, so there is nothing here to guard.
            return None

        budget = REQUEST_MAX_TOTAL_VERTICES + 1
        total, largest = count_positions(decoded, budget)

        if largest > WORKSPACE_IMPORT_MAX_VERTICES:
            return 400, _error(
                "IMPORT_MAX_VERTICES_EXCEEDED",
                f"Too many vertices: {largest} (max: {WORKSPACE_IMPORT_MAX_VERTICES})",
                {"count": largest, "max": WORKSPACE_IMPORT_MAX_VERTICES},
            )
        if total > REQUEST_MAX_TOTAL_VERTICES:
            return 400, _error(
                "IMPORT_MAX_VERTICES_EXCEEDED",
                (
                    f"Too many vertices in one request: {total} "
                    f"(max: {REQUEST_MAX_TOTAL_VERTICES})"
                ),
                {"count": total, "max": REQUEST_MAX_TOTAL_VERTICES},
            )
        return None

    # -- responses ----------------------------------------------------------

    async def _send_too_large(self, send: Send, limit: int, seen: int) -> None:
        logger.warning(
            "Request body rejected: %d bytes seen against a %d byte cap", seen, limit
        )
        from app.services.upload.findings import finding

        mb = f"{limit // (1024 * 1024)} MB"
        f = finding("file.too_large", expected=mb)
        payload = json.loads(
            _error("REQUEST_BODY_TOO_LARGE", f"Request body exceeds the {mb} limit", {"limit_bytes": limit})
        )
        # the same plain, bilingual shape every upload refusal uses, so the screen shows what to do instead of a bare number
        payload["detail"] = {
            "code": f.code, "message": f"{f.title_en} {f.fix_en}", "message_np": f"{f.title_ne} {f.fix_ne}", "findings": [f.to_dict()],
        }
        await self._send_json(send, 413, json.dumps(payload).encode("utf-8"))

    async def _send_json(self, send: Send, status: int, payload: bytes) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(payload)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": payload})


def _replay(body: bytes) -> Receive:
    """A receive channel that hands the buffered body to the app downstream."""
    sent = False

    async def receive() -> Message:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return receive
