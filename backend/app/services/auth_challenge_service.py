"""One-time secrets for sign-up and recovery: phone OTP codes and emailed link tokens.

Only an HMAC of the secret is stored. A code is single-use, expires, and allows a
few wrong guesses; issuing is limited by a resend cooldown and a daily cap per
phone number or email address.
"""
import hashlib
import hmac
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.user import AuthChallenge

logger = logging.getLogger(__name__)

PHONE_VERIFY = "phone_verify"
LOGIN = "login"
PASSWORD_RESET = "password_reset"
EMAIL_VERIFY = "email_verify"


class ChallengeError(Exception):
    """``code`` is an i18n key under auth.* for the API layer."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def normalize_phone(raw: str) -> str:
    """Return E.164. Nepal mobiles may be typed 98XXXXXXXX, 9779XXXXXXXXX or +977...; other countries need a leading +."""
    digits = re.sub(r"[\s\-().]", "", raw or "")
    if re.fullmatch(r"9[78]\d{8}", digits):
        return "+977" + digits
    if re.fullmatch(r"977\d{10}", digits):
        return "+" + digits
    if re.fullmatch(r"\+\d{8,15}", digits):
        return digits
    raise ChallengeError("auth.phone_invalid")


def normalize_email(raw: str) -> str:
    return (raw or "").strip().lower()


def _hash(secret: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), secret.encode(), hashlib.sha256).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _guard_issue(db: Session, target: str, purpose: str) -> None:
    """Daily cap per target across every purpose; the resend cooldown only within one purpose,
    so a sign-in code is not refused because a sign-up code went out a minute ago."""
    now = _now()
    recent = (
        db.query(AuthChallenge)
        .filter(AuthChallenge.target == target, AuthChallenge.created_at >= now - timedelta(days=1))
        .order_by(AuthChallenge.created_at.desc())
        .all()
    )
    if len(recent) >= settings.OTP_DAILY_LIMIT_PER_TARGET:
        raise ChallengeError("auth.too_many_codes")
    same = [r for r in recent if r.purpose == purpose]
    if same and (now - same[0].created_at).total_seconds() < settings.OTP_RESEND_COOLDOWN_SECONDS:
        raise ChallengeError("auth.code_resend_wait")


def issue(
    db: Session, *, purpose: str, channel: str, target: str,
    user_id=None, created_by=None, ttl_seconds: Optional[int] = None, guard: bool = True,
) -> str:
    """Create a challenge and return the raw secret (6 digits for sms, a URL-safe token for email). Caller delivers it and commits.

    ``guard=False`` skips the cooldown and daily cap: for the first verification email of a new account, which no one is spamming."""
    if guard:
        _guard_issue(db, target, purpose)
    if channel == "sms":
        secret = f"{secrets.randbelow(10 ** 6):06d}"
        ttl = settings.OTP_TTL_SECONDS
    else:
        secret = secrets.token_urlsafe(32)
        ttl = settings.AUTH_TOKEN_TTL_MINUTES * 60
    db.add(AuthChallenge(
        purpose=purpose, channel=channel, target=target, user_id=user_id,
        secret_hash=_hash(secret), expires_at=_now() + timedelta(seconds=ttl_seconds or ttl),
        created_by=created_by,
    ))
    db.flush()
    return secret


def verify_code(db: Session, *, purpose: str, target: str, code: str) -> AuthChallenge:
    """Check an SMS code against the newest open challenge for this target. Consumes it on success; counts a miss otherwise."""
    ch = (
        db.query(AuthChallenge)
        .filter(AuthChallenge.purpose == purpose, AuthChallenge.target == target,
                AuthChallenge.consumed_at.is_(None))
        .order_by(AuthChallenge.created_at.desc())
        .with_for_update()
        .first()
    )
    if ch is None or ch.expires_at <= _now():
        raise ChallengeError("auth.code_expired")
    if ch.attempts >= settings.OTP_MAX_ATTEMPTS:
        raise ChallengeError("auth.code_too_many_attempts")
    if not hmac.compare_digest(ch.secret_hash, _hash((code or "").strip())):
        ch.attempts += 1
        db.commit()  # the miss must survive the 4xx that follows
        raise ChallengeError("auth.code_wrong")
    ch.consumed_at = _now()
    db.flush()
    return ch


def verify_token(db: Session, *, purpose: str, token: str) -> AuthChallenge:
    """Look up an emailed link token by its hash. Consumes it on success."""
    ch = (
        db.query(AuthChallenge)
        .filter(AuthChallenge.purpose == purpose, AuthChallenge.secret_hash == _hash(token or ""),
                AuthChallenge.consumed_at.is_(None))
        .with_for_update()
        .first()
    )
    if ch is None or ch.expires_at <= _now():
        raise ChallengeError("auth.link_invalid")
    ch.consumed_at = _now()
    db.flush()
    return ch
