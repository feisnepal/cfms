"""Trusted-proxy-aware resolution of the real client address.

Every rate limit, audit row and abuse signal keyed on "the client" is only as
honest as this function. `request.client.host` is the address of whatever
opened the TCP connection — behind nginx or a load balancer that is the proxy,
so every request in the deployment shares one identity. The fix is
`X-Forwarded-For`, but that header is client-supplied and trivially forged: a
request arriving straight from the internet can claim any address it likes.

So the header is honoured only when the *peer* is a proxy we run. `TRUSTED_PROXY_IPS`
names those hops; anything else is taken at its connection address and its
`X-Forwarded-For` ignored.

Walking the chain from the right matters as much as the trust check. XFF is
appended to by each hop, so the rightmost entries are the ones our own
infrastructure wrote and the leftmost is whatever the original client sent —
which may be fabricated. We skip our own hops from the right and take the first
address that is not ours; that is the furthest-left entry we have any reason to
believe.
"""
from __future__ import annotations

import ipaddress
import logging
from functools import lru_cache
from typing import Sequence

from starlette.requests import Request

from .config import settings

logger = logging.getLogger(__name__)

UNKNOWN = "unknown"


@lru_cache(maxsize=1)
def _trusted_networks(raw: str) -> tuple[object, ...]:
    """Parse `TRUSTED_PROXY_IPS` into networks. `*` trusts every peer."""
    if raw.strip() == "*":
        return ("*",)
    nets = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            nets.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            logger.warning("TRUSTED_PROXY_IPS: ignoring unparseable entry %r", entry)
    return tuple(nets)


def is_trusted_proxy(addr: str) -> bool:
    """Whether `addr` is one of our own hops, so its XFF may be believed."""
    nets = _trusted_networks(getattr(settings, "TRUSTED_PROXY_IPS", "") or "")
    if not nets:
        return False
    if nets[0] == "*":
        return True
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        # TestClient uses the literal "testclient"; a unix socket has no address.
        return False
    return any(ip in net for net in nets)  # type: ignore[operator]


def _forwarded_chain(header: str) -> Sequence[str]:
    return [part.strip() for part in header.split(",") if part.strip()]


def _is_wildcard() -> bool:
    nets = _trusted_networks(getattr(settings, "TRUSTED_PROXY_IPS", "") or "")
    return bool(nets) and nets[0] == "*"


def resolve_client_ip(request: Request) -> str:
    """The best-supported client address for this request.

    Falls back to the peer address whenever the chain cannot be trusted, and to
    `UNKNOWN` when there is no peer at all (ASGI allows `request.client` to be
    None). Never raises: callers use this on the hot path.
    """
    peer = request.client.host if request.client else UNKNOWN

    if peer == UNKNOWN or not is_trusted_proxy(peer):
        return peer

    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded:
        return peer

    chain = _forwarded_chain(forwarded)
    if not chain:
        return peer

    if _is_wildcard():
        # `*` answers "may this peer's header be believed", and says nothing
        # about which entries in the chain are our own hops — under a wildcard
        # every address in the chain would test as trusted and the walk below
        # would consume the whole thing. The rightmost entry is the address our
        # nearest proxy actually observed; everything to its left is a claim
        # made by something upstream that we have no way to vouch for.
        return chain[-1]

    for candidate in reversed(chain):
        if not is_trusted_proxy(candidate):
            return candidate

    # Every hop in the chain is ours, which means the chain never left our
    # network. The nearest hop is the most specific thing we know.
    return peer
