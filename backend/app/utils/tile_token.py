"""Short-lived, calculation-scoped tokens for XYZ tile URLs.

H2.4 / S1-04. The tile routes were wide open, but they cannot simply be put
behind the normal bearer dependency: Leaflet renders them as `<img>` requests,
which carry no Authorization header and no way to add one.

Putting the session token in the query string would work and is what many
projects do, but a URL travels places a header does not — browser history,
`Referer`, proxy and CDN access logs, screenshots of a URL bar. So tiles get
their own credential instead: signed with the same key, valid for one
calculation, for thirty minutes, and useless for anything but reading tiles.
Losing one costs the attacker the imagery of a single calculation for half an
hour rather than the account.
"""
from datetime import datetime, timedelta, timezone

import jwt
from jwt import InvalidTokenError

from ..core.config import settings

TILE_TOKEN_TYPE = "tile"
TILE_TOKEN_TTL_MINUTES = 30


def create_tile_token(calculation_id: str, user_id: str) -> str:
    """Mint a tile token for one calculation, on behalf of one user."""
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "type": TILE_TOKEN_TYPE,
            "calc": str(calculation_id),
            "sub": str(user_id),
            "iat": now,
            "exp": now + timedelta(minutes=TILE_TOKEN_TTL_MINUTES),
        },
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )


def tile_token_grants(token: str, calculation_id: str) -> bool:
    """Whether `token` is a live tile token for exactly this calculation.

    The `type` check matters: without it an ordinary access token would be
    accepted here, and the whole point is that a URL-borne credential must not
    be a session credential.
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except InvalidTokenError:
        return False
    return (
        payload.get("type") == TILE_TOKEN_TYPE
        and payload.get("calc") == str(calculation_id)
    )
