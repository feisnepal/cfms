"""
Authentication utilities for JWT tokens and password hashing
"""
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
import jwt
import bcrypt
from jwt import PyJWTError as InvalidTokenError  # PyJWT >= 2.0
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.database import get_db

logger = logging.getLogger(__name__)
from ..core.exceptions import i18n_error
from ..core.i18n_messages import get_message
from ..models.user import User, UserRole, UserStatus


# HTTP Bearer for token extraction
security = HTTPBearer()


def hash_password(password: str) -> str:
    """
    Hash a password using bcrypt
    Bcrypt has a 72-byte limit, so we truncate longer passwords
    """
    password_bytes = password.encode('utf-8')
    if len(password_bytes) > 72:
        password_bytes = password_bytes[:72]
    return bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash"""
    password_bytes = plain_password.encode('utf-8')
    if len(password_bytes) > 72:
        password_bytes = password_bytes[:72]
    try:
        return bcrypt.checkpw(password_bytes, hashed_password.encode('utf-8'))
    except Exception:
        # Failing closed is right. Failing closed SILENTLY is not: a corrupt
        # hash column or a bcrypt/backend mismatch presents as a user typing
        # the wrong password, forever, with nothing in the log.
        logger.warning(
            "password verification raised - treating the password as wrong. "
            "A stored hash may be corrupt or truncated.", exc_info=True,
        )
        return False


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT access token

    Args:
        data: Dictionary containing token data (typically {"sub": user_id, "email": email})
        expires_delta: Optional expiration time delta

    Returns:
        Encoded JWT token string
    """
    to_encode = data.copy()

    now = datetime.now(timezone.utc)

    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    # H2.5 / S1-05: `gen` is what makes revocation possible — see
    # token_is_still_valid. Callers pass the user's current token_generation in
    # `data`; a token minted without one belongs to generation 0.
    to_encode.setdefault("gen", 0)
    to_encode.update({
        "exp": expire,
        "iat": now,
        "jti": uuid.uuid4().hex,
        "type": "access",
    })

    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def create_refresh_token(user_id: str, family: str) -> tuple[str, str, datetime]:
    """Mint a refresh token. Returns (token, jti, expires_at).

    Separate from the access token by `type`, so one can never be presented
    where the other is expected — the previous design had no such separation
    and treated any access token, expired or not, as proof of a live session.
    """
    jti = uuid.uuid4().hex
    # Timezone-aware throughout: `refresh_tokens.expires_at` is timestamptz,
    # and Postgres reads a naive
    # datetime as *local* time. On a UTC+05:45 machine that silently shifts
    # every cutoff by nearly six hours — enough to make a revoked token look
    # valid, which is exactly what it did before this was caught.
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    token = jwt.encode(
        {
            "sub": str(user_id),
            "family": str(family),
            "jti": jti,
            "iat": datetime.now(timezone.utc),
            "exp": expires_at,
            "type": "refresh",
        },
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    return token, jti, expires_at


def verify_token(token: str) -> dict:
    """
    Verify and decode a JWT token

    Args:
        token: JWT token string

    Returns:
        Decoded token payload

    Raises:
        HTTPException: If token is invalid or expired
    """
    credentials_exception = _credentials_exception()

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except InvalidTokenError:
        raise credentials_exception


def token_is_still_valid(user: User, payload: dict) -> bool:
    """Whether an access token belongs to this user's current generation.

    Access tokens are stateless and cannot be individually recalled, so the
    token carries the generation it was minted under and the user row holds the
    current one. Logout and password change increment the counter, which
    invalidates every token issued before it in a single write.

    A token with no `gen` claim predates H2.5. Those are accepted only while the
    user has never revoked anything (generation 0) — otherwise a signed-out
    account would stay signed in on the strength of an old token format.
    """
    current = getattr(user, "token_generation", 0) or 0
    return int(payload.get("gen", 0)) == int(current)


def _credentials_exception() -> HTTPException:
    """401 with bilingual detail + WWW-Authenticate header (Bearer)."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "code": "auth.could_not_validate_credentials",
            "message": get_message("auth.could_not_validate_credentials")["en"],
            "message_np": get_message("auth.could_not_validate_credentials")["ne"],
        },
        headers={"WWW-Authenticate": "Bearer"},
    )


_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _enforce_user_type_limits(user: User, request: Optional[Request]) -> None:
    """Expired access is refused outright; a read-only type (student, researcher) may not change anything.

    One choke point on purpose: every route authenticates through get_current_user, so no endpoint has to
    remember. Account endpoints (/auth/...) stay open so a person can still fix their profile or sign out.
    A POST that only reads (a preview) is refused too -- the safe side of the line."""
    if user.access_expired:
        raise i18n_error(status.HTTP_403_FORBIDDEN, "auth.access_expired")
    if request is None or request.method in _SAFE_METHODS or "/auth/" in request.url.path:
        return
    if user.access_level == "read_only":
        raise i18n_error(status.HTTP_403_FORBIDDEN, "auth.read_only_account")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
    request: Request = None,
) -> User:
    """
    Get current authenticated user from JWT token

    Dependency for FastAPI routes that require authentication
    """
    token = credentials.credentials
    payload = verify_token(token)

    user_id: str = payload.get("sub")
    if user_id is None:
        raise i18n_error(
            status.HTTP_401_UNAUTHORIZED,
            "auth.invalid_auth_credentials",
        )

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise i18n_error(
            status.HTTP_401_UNAUTHORIZED,
            "auth.user_not_found",
        )

    # H2.5 / S1-05: refuse tokens minted before this user's sessions were
    # invalidated. Logout, password change and refresh-token reuse all move the
    # marker forward, which is the only way to recall an access token that is
    # otherwise valid until it expires on its own.
    if not token_is_still_valid(user, payload):
        raise i18n_error(
            status.HTTP_401_UNAUTHORIZED,
            "auth.session_revoked",
        )

    _enforce_user_type_limits(user, request)
    _bind_identity(user)
    return user


def _bind_identity(user: User) -> None:
    """Tell the request context WHO is acting, so the audit trails (household access log, geometry audit) can name them.

    Done here, in the base dependency, because routes that authenticate with ``get_current_user`` alone (the household endpoints, among
    others) never reach ``get_current_active_user``, and their audit rows then carried no user. Best-effort: a failure to record the
    identity must never refuse a request that authentication has just approved."""
    try:
        from app.core.request_context import get_identity, set_identity
        from dataclasses import replace

        set_identity(replace(get_identity(), user_id=str(user.id)))
    except Exception:  # noqa: BLE001 -- identity is never worth failing auth over
        logger.debug("could not attach user to the request identity", exc_info=True)


async def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    Get current active user (status must be ACTIVE)

    Dependency for routes that require an active user
    """
    if current_user.status != UserStatus.ACTIVE:
        raise i18n_error(
            status.HTTP_403_FORBIDDEN,
            "auth.account_status_inactive",
            status=f"'{current_user.status.value}'",
        )

    # H8.7: complete the request identity the correlation middleware started.
    #
    # The middleware runs before authentication -- dependencies have not
    # resolved yet -- so it can bind the address and client type but not who is
    # acting. This is the first point where that is known, and every route
    # requiring a user passes through here, so the audit gets a user id without
    # any endpoint being asked to remember one.
    #
    # Best-effort by design: a failure to record identity must never refuse a
    # request that authentication has just approved.
    try:
        from app.core.request_context import get_identity, set_identity
        from dataclasses import replace

        set_identity(replace(get_identity(), user_id=str(current_user.id)))
    except Exception:  # noqa: BLE001 -- identity is never worth failing auth over
        logger.debug("could not attach user to the request identity", exc_info=True)

    return current_user


async def require_approved(current_user: User = Depends(get_current_active_user)) -> User:
    """Refuse the limited tier: an ACTIVE account no super admin has approved yet.

    Put this on anything that must not be open to a self-registered or Facebook-only account."""
    if current_user.approved_at is None:
        raise i18n_error(status.HTTP_403_FORBIDDEN, "auth.approval_required")
    return current_user


def require_role(allowed_roles: list[UserRole]):
    """
    Dependency factory to require specific user roles

    Usage:
        @router.get("/admin-only", dependencies=[Depends(require_role([UserRole.SUPER_ADMIN]))])
    """
    async def role_checker(current_user: User = Depends(get_current_active_user)):
        if current_user.role not in allowed_roles:
            raise i18n_error(
                status.HTTP_403_FORBIDDEN,
                "auth.insufficient_permissions",
                roles=", ".join(r.value for r in allowed_roles),
            )
        return current_user
    return role_checker


# Convenience dependencies for common role checks
require_super_admin = require_role([UserRole.SUPER_ADMIN])
require_org_admin = require_role([UserRole.ORG_ADMIN, UserRole.SUPER_ADMIN])
# OP multi-template (OP_MULTI_TEMPLATE_PLAN.md §3.1): designers author + submit
# templates; only super admins review / publish / retire.
require_template_designer = require_role([UserRole.TEMPLATE_DESIGNER, UserRole.SUPER_ADMIN])
require_template_publisher = require_role([UserRole.SUPER_ADMIN])
