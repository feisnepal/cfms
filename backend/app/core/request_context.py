"""Who is making this request, readable from any depth (H8.7 · S2-68).

The problem this solves
-----------------------
The geometry audit has to record the user, the address and the kind of client.
The single point every geometry write in `editing.py` passes through is
`_write_geometry(db, calc, layer_type, feature_id, geometry)` -- several frames
below the endpoint, with no `Request` in sight.

The alternative is threading `Request` and `current_user` through twelve
endpoints, three persist helpers and the write function. That is the shape S2-68
already describes: a thing that must be remembered at every call site, and is
therefore present at some of them. `geometry_audits` has 0 rows after five
months precisely because the audit depended on being remembered.

So the identity travels the same way the correlation id does (H3.9): bound once
by middleware, read wherever it is needed. `resolve_client_ip` (H2.18) supplies
the address, including the trusted-proxy walk that carrier-grade NAT makes
necessary.

What is deliberately absent
---------------------------
`device_id` and `app_version` are part of S2-68 and are NOT here. `device_id`
needs the `devices` table from 2.16 and `app_version` needs the `X-App-Version`
header from 8.4 -- both unstarted. Adding the fields now would mean columns that
are always NULL and a report that says the work is done. They are named in the
tracker as blocked instead.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Optional

# A request whose client sends no hint is "web": that is what the only client
# in existence is. It becomes a real signal the day the mobile app sends
# X-Client-Type, and until then it is honest rather than guessed -- the value
# says which client the row came from as far as anyone can tell.
DEFAULT_CLIENT_TYPE = "web"


@dataclass(frozen=True)
class RequestIdentity:
    """Who and what, for a row that must be attributable years from now."""

    user_id: Optional[str] = None
    ip_address: Optional[str] = None
    client_type: str = DEFAULT_CLIENT_TYPE
    user_agent: Optional[str] = None


_EMPTY = RequestIdentity()

# Frozen and replaced wholesale rather than mutated: a half-populated identity
# is worse than none, because it looks attributable.
_identity: ContextVar[RequestIdentity] = ContextVar("request_identity", default=_EMPTY)


def get_identity() -> RequestIdentity:
    """The current request's identity, or an empty one outside a request."""
    return _identity.get()


def set_identity(identity: RequestIdentity) -> Token:
    return _identity.set(identity)


def reset_identity(token: Token) -> None:
    """Reset by token, so nested scopes restore what was there before."""
    _identity.reset(token)


def identity_from_request(request, user_id: Optional[str] = None) -> RequestIdentity:
    """Build one from a Starlette request. Never raises.

    A failure to read a header must not fail the write it is describing. An
    audit trail that can break the operation it records is worse than no audit
    trail, which is the trade S2-68 is about in the first place.
    """
    ip = None
    try:
        from .client_ip import resolve_client_ip

        ip = resolve_client_ip(request)
    except Exception:  # noqa: BLE001 -- see the docstring; identity is best-effort
        ip = None

    try:
        # Inside the try, not before it. Reading `request.headers` can itself
        # raise -- it is a property on Starlette's Request -- so pulling it out
        # for readability put it outside the guard and made the guard useless.
        # A test with a hostile request object caught exactly that.
        headers = getattr(request, "headers", {}) or {}
        client_type = (
            headers.get("X-Client-Type") or ""
        ).strip().lower() or DEFAULT_CLIENT_TYPE
        user_agent = (headers.get("User-Agent") or "")[:300] or None
    except Exception:  # noqa: BLE001 -- as above
        client_type, user_agent = DEFAULT_CLIENT_TYPE, None

    return RequestIdentity(
        user_id=str(user_id) if user_id else None,
        ip_address=ip,
        client_type=client_type,
        user_agent=user_agent,
    )
