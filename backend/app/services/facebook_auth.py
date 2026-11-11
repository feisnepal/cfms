"""Facebook Login: confirm a client-side access token with Facebook itself.

The browser does the Facebook dialog and sends us the access token. We never
trust the id the browser claims: the token is checked with ``debug_token`` (it
must belong to OUR app and be valid), then the profile is read with it.
Off until FACEBOOK_APP_ID and FACEBOOK_APP_SECRET are set.
"""
import logging
from dataclasses import dataclass
from typing import Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

GRAPH = "https://graph.facebook.com/v21.0"


class FacebookError(Exception):
    """``code`` is an i18n key under auth.*."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass
class FacebookProfile:
    subject: str
    name: str
    email: Optional[str]


def is_configured() -> bool:
    return bool(settings.FACEBOOK_APP_ID and settings.FACEBOOK_APP_SECRET)


def verify_access_token(access_token: str) -> FacebookProfile:
    if not is_configured():
        raise FacebookError("auth.facebook_unavailable")
    app_token = f"{settings.FACEBOOK_APP_ID}|{settings.FACEBOOK_APP_SECRET}"
    try:
        with httpx.Client(timeout=10) as client:
            dbg = client.get(f"{GRAPH}/debug_token",
                             params={"input_token": access_token, "access_token": app_token})
            data = dbg.json().get("data", {}) if dbg.status_code == 200 else {}
            if not data.get("is_valid") or str(data.get("app_id")) != str(settings.FACEBOOK_APP_ID):
                raise FacebookError("auth.facebook_invalid")
            me = client.get(f"{GRAPH}/me", params={"fields": "id,name,email", "access_token": access_token})
            profile = me.json() if me.status_code == 200 else {}
    except httpx.HTTPError as exc:
        logger.warning("facebook verification failed: %s", exc)
        raise FacebookError("auth.facebook_invalid") from exc
    if not profile.get("id") or str(profile["id"]) != str(data.get("user_id")):
        raise FacebookError("auth.facebook_invalid")
    return FacebookProfile(subject=str(profile["id"]), name=profile.get("name") or "", email=profile.get("email"))
