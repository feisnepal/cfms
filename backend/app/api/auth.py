"""
Authentication API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import logging
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone
import uuid
import jwt
from jwt import InvalidTokenError

from ..core.database import get_db
from ..core.exceptions import i18n_error, i18n_success
from sqlalchemy.exc import IntegrityError
from ..models.user import User, UserStatus, UserRole, UserIdentity
from ..models.refresh_token import RefreshToken
from ..schemas.auth import (
    UserRegister, UserLogin, Token, UserResponse, PasswordChange, RefreshRequest,
    PhoneCodeRequest,
)
from ..utils.auth import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    get_current_active_user,
    require_super_admin,
)
from ..services import auth_challenge_service as challenges
from ..services import auth_mailer
from ..services import user_types
from ..services import facebook_auth
from ..services.sms import get_sender as get_sms_sender
from ..core.config import settings
from ..core.rate_limit import limiter

security = HTTPBearer(auto_error=False)

logger = logging.getLogger(__name__)

router = APIRouter()

# H2.1 / S1-01: the status a self-registered account starts in. A module
# constant rather than a literal so the test harness can opt out of the
# approval round-trip for the ~21 files whose fixtures predate it — see
# conftest._registration_status.
#
# Owner decision 2026-10-20: a new account is ACTIVE from the start, but `approved_at` stays
# empty until a super admin approves it. ACTIVE-and-unapproved is the limited tier (see
# utils/auth.require_approved). It has already proved its phone (OTP) or its Facebook login.
NEW_ACCOUNT_STATUS = UserStatus.ACTIVE


def _issue_refresh_token(db: Session, user: User, family, user_agent=None):
    """Mint a refresh token and record it, so it can later be consumed or revoked."""
    token, jti, expires_at = create_refresh_token(str(user.id), str(family))
    db.add(RefreshToken(
        id=uuid.uuid4(),
        jti=jti,
        family=family,
        user_id=user.id,
        expires_at=expires_at,
        user_agent=(user_agent or "")[:256] or None,
    ))
    return token, jti, expires_at


def _revoke_family_for_user(db: Session, user: User, reason: str) -> int:
    """Revoke every refresh token this user holds, across all their logins."""
    return (
        db.query(RefreshToken)
        .filter(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .update({"revoked_at": datetime.now(timezone.utc), "revoked_reason": reason},
                synchronize_session=False)
    )


def _revoke_family(db: Session, family, reason: str) -> int:
    """Revoke every token descended from one login.

    Revoking only the replayed token would leave the thief's freshly-minted
    successor working. The whole line goes.
    """
    return (
        db.query(RefreshToken)
        .filter(RefreshToken.family == family, RefreshToken.revoked_at.is_(None))
        .update({"revoked_at": datetime.now(timezone.utc), "revoked_reason": reason},
                synchronize_session=False)
    )



@router.post("/signup/phone-code", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(lambda: settings.RATE_LIMIT_OTP)
def request_signup_phone_code(request: Request, body: PhoneCodeRequest, db: Session = Depends(get_db)):
    """Send a code to a phone number that wants to sign up. Step 1 of registration."""
    try:
        phone = challenges.normalize_phone(body.phone)
        if db.query(User.id).filter(User.phone == phone, User.phone_verified_at.isnot(None)).first():
            raise i18n_error(status.HTTP_400_BAD_REQUEST, "auth.phone_already_registered")
        code = challenges.issue(db, purpose=challenges.PHONE_VERIFY, channel="sms", target=phone)
    except challenges.ChallengeError as exc:
        raise i18n_error(status.HTTP_400_BAD_REQUEST, exc.code)
    db.commit()
    get_sms_sender().send(phone, f"Forest Management code: {code}. Valid {settings.OTP_TTL_SECONDS // 60} min.")
    return {"sent": True, "resend_after": settings.OTP_RESEND_COOLDOWN_SECONDS}


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
# Keyed by resolved address, not by user — nobody has an identity yet. Read
# as a per-address budget shared by everyone behind one carrier NAT, which
# is why it is far looser than a per-user limit would be (H2.18).
@limiter.limit(lambda: settings.RATE_LIMIT_REGISTER)
def register_user(request: Request, user_data: UserRegister, db: Session = Depends(get_db)):
    """
    Register a new user.

    The phone is proved with the code from /auth/signup/phone-code. The account
    starts ACTIVE but unapproved (limited tier) until a super admin approves it.
    A social identity is required: a Facebook token (checked with Facebook) or an
    Instagram handle (stored as given, never verified).
    """
    email = challenges.normalize_email(user_data.email)
    try:
        phone = challenges.normalize_phone(user_data.phone)
    except challenges.ChallengeError as exc:
        raise i18n_error(status.HTTP_400_BAD_REQUEST, exc.code)
    try:  # check the declared type before a code is spent
        user_types.clean(user_data.user_type, user_data.designation.value if user_data.designation else None,
                         user_data.sub_division, user_data.details)
    except user_types.TypeDetailsError as exc:
        raise i18n_error(status.HTTP_400_BAD_REQUEST, "auth.type_field_invalid", field=exc.field)

    if db.query(User.id).filter(User.email == email).first():
        raise i18n_error(status.HTTP_400_BAD_REQUEST, "auth.email_already_registered")
    if db.query(User.id).filter(User.phone == phone, User.phone_verified_at.isnot(None)).first():
        raise i18n_error(status.HTTP_400_BAD_REQUEST, "auth.phone_already_registered")

    if not user_data.facebook_access_token and not user_data.instagram_handle:
        raise i18n_error(status.HTTP_400_BAD_REQUEST, "auth.social_required")
    fb = None
    if user_data.facebook_access_token:
        try:
            fb = facebook_auth.verify_access_token(user_data.facebook_access_token)
        except facebook_auth.FacebookError as exc:
            raise i18n_error(status.HTTP_400_BAD_REQUEST, exc.code)
        if db.query(UserIdentity.id).filter_by(provider="facebook", subject=fb.subject).first():
            raise i18n_error(status.HTTP_400_BAD_REQUEST, "auth.facebook_already_linked")

    try:
        challenges.verify_code(db, purpose=challenges.PHONE_VERIFY, target=phone, code=user_data.phone_code)
    except challenges.ChallengeError as exc:
        raise i18n_error(status.HTTP_400_BAD_REQUEST, exc.code)

    new_user = User(
        email=email,
        hashed_password=hash_password(user_data.password),
        full_name=user_data.full_name,
        phone=phone,
        phone_verified_at=datetime.now(timezone.utc),
        instagram_handle=user_data.instagram_handle,
        status=NEW_ACCOUNT_STATUS,
    )
    db.add(new_user)
    try:
        db.flush()
        user_types.apply_type(db, new_user, user_data.user_type,
                              user_data.designation.value if user_data.designation else None,
                              user_data.sub_division, user_data.details)
        if fb is not None:
            db.add(UserIdentity(user_id=new_user.id, provider="facebook", subject=fb.subject))
        token = challenges.issue(db, purpose=challenges.EMAIL_VERIFY, channel="email",
                                 target=email, user_id=new_user.id, guard=False)
        db.commit()
    except IntegrityError:
        # Two sign-ups racing for one email or number: the unique indexes decide.
        db.rollback()
        raise i18n_error(status.HTTP_400_BAD_REQUEST, "auth.email_already_registered")
    db.refresh(new_user)
    auth_mailer.send_verify_email(email, token)
    return new_user


@router.post("/login", response_model=Token)
# 10/minute per address locked out a whole district of enumerators sharing
# one carrier-grade NAT address. Brute-force protection that fails a
# hundred legitimate users to stop one attacker is not protection.
@limiter.limit(lambda: settings.RATE_LIMIT_LOGIN)
def login(request: Request, credentials: UserLogin, db: Session = Depends(get_db)):
    """
    Login with email and password

    Returns JWT access token
    """
    # Find user by email
    user = db.query(User).filter(User.email == credentials.email).first()
    if not user:
        raise i18n_error(
            status.HTTP_401_UNAUTHORIZED,
            "auth.invalid_credentials",
        )

    # Verify password
    if not verify_password(credentials.password, user.hashed_password):
        raise i18n_error(
            status.HTTP_401_UNAUTHORIZED,
            "auth.invalid_credentials",
        )

    # Check user status
    if user.status != UserStatus.ACTIVE:
        raise i18n_error(
            status.HTTP_403_FORBIDDEN,
            "auth.account_inactive",
            status=f"'{user.status.value}'",
        )

    return issue_session(db, user, request)


def issue_session(db: Session, user: User, request: Request) -> dict:
    """Open a login for ``user``: stamp last_login, mint the access + refresh pair, commit.

    Shared by every way of signing in (password, phone code, Facebook) so each one
    gets the same token family and revocation behaviour."""
    if user.access_expired:
        raise i18n_error(status.HTTP_403_FORBIDDEN, "auth.access_expired")
    # tz-aware: last_login is timestamptz, and a naive value is read as local
    # time — a naive value here would be off by the local UTC offset.
    user.last_login = datetime.now(timezone.utc)

    # H2.5 / S1-05: a login opens a token family. Everything refreshed from it
    # descends from this row, so the whole line can be revoked at once if one
    # of its tokens turns up in two hands.
    access_token = create_access_token(
        data={"sub": str(user.id), "email": user.email,
              "gen": user.token_generation or 0}
    )
    refresh, _jti, _expires = _issue_refresh_token(
        db, user, family=uuid.uuid4(), user_agent=request.headers.get("user-agent")
    )
    db.commit()

    return {
        "access_token": access_token,
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: User = Depends(get_current_active_user)):
    """
    Get current authenticated user information

    Requires valid JWT token in Authorization header
    """
    return current_user


@router.post("/change-password")
def change_password(
    request: Request,
    password_data: PasswordChange,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Change user password

    Requires current password for verification
    """
    # Verify old password
    if not verify_password(password_data.old_password, current_user.hashed_password):
        raise i18n_error(
            status.HTTP_400_BAD_REQUEST,
            "auth.wrong_current_password",
        )

    # Check new password is different
    if password_data.old_password == password_data.new_password:
        raise i18n_error(
            status.HTTP_400_BAD_REQUEST,
            "auth.new_password_same",
        )

    # Update password
    current_user.hashed_password = hash_password(password_data.new_password)

    # H2.5 / S1-05: changing a password must end the sessions that were opened
    # with the old one — otherwise the response to a suspected compromise
    # (change your password) leaves the attacker signed in. Every outstanding
    # token is invalidated and the caller gets a fresh pair, so the device doing
    # the change stays signed in and every other one does not.
    current_user.token_generation = (current_user.token_generation or 0) + 1
    _revoke_family_for_user(db, current_user, reason="password_changed")

    # Minted under the new generation, so this device stays signed in while
    # every token from the old one — including any the attacker holds — does not.
    access_token = create_access_token(
        data={"sub": str(current_user.id), "email": current_user.email,
              "gen": current_user.token_generation}
    )
    refresh, _jti, _exp = _issue_refresh_token(
        db, current_user, family=uuid.uuid4(),
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()

    return {
        **i18n_success("auth.password_changed"),
        "access_token": access_token,
        "refresh_token": refresh,
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


# ---------------------------------------------------------------------------
# H2.1 / S1-01 — admin approval for self-registered accounts.
#
# Registration now creates PENDING users, so something has to move them to
# ACTIVE. Restricted to org admins and above, and every decision is logged with
# the approver — an account gaining access to household PII should never be an
# anonymous event.
# ---------------------------------------------------------------------------
@router.get("/users/pending", response_model=list[UserResponse])
def list_pending_users(
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """List accounts awaiting approval: the limited tier, plus any legacy PENDING. Super admin only."""
    return (
        db.query(User)
        .filter((User.status == UserStatus.PENDING)
                | ((User.status == UserStatus.ACTIVE) & User.approved_at.is_(None)))
        .order_by(User.created_at)
        .all()
    )


@router.post("/users/{user_id}/approve", response_model=UserResponse)
def approve_user(
    user_id: str,
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """Approve an account, which lifts the limited tier. Super admin only."""
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise i18n_error(status.HTTP_404_NOT_FOUND, "auth.user_not_found")
    if user.status == UserStatus.ACTIVE and user.approved_at is not None:
        return user  # idempotent: approving twice is not an error
    user.status = UserStatus.ACTIVE
    user.approved_at = datetime.now(timezone.utc)
    user.approved_by = current_user.id
    db.commit()
    db.refresh(user)
    logger.info("account approved: user=%s approved_by=%s", user.id, current_user.id)
    return user


@router.post("/users/{user_id}/suspend", response_model=UserResponse)
def suspend_user(
    user_id: str,
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """Suspend an account, revoking its access. Super admin only."""
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise i18n_error(status.HTTP_404_NOT_FOUND, "auth.user_not_found")
    if user.id == current_user.id:
        raise i18n_error(status.HTTP_400_BAD_REQUEST, "auth.cannot_suspend_self")
    user.status = UserStatus.SUSPENDED
    db.commit()
    db.refresh(user)
    logger.warning("account suspended: user=%s suspended_by=%s", user.id, current_user.id)
    return user


@router.get("/roles")
async def get_available_roles():
    """
    Get list of available user roles

    Used for admin interfaces
    """
    from ..models.user import UserRole
    return {
        "roles": [
            {"value": role.value, "label": role.value.replace("_", " ").title()}
            for role in UserRole
        ]
    }


@router.post("/refresh")
def refresh_token(
    request: Request,
    body: RefreshRequest,
    db: Session = Depends(get_db),
):
    """Exchange a refresh token for a new pair, consuming the old one.

    H2.5 / S1-05. This endpoint used to decode the presented *access* token
    with `verify_exp: False` and hand back a fresh one — so any access token
    ever issued, including one that expired months ago, was a permanent
    credential, and logging out did nothing on the server.

    Now: refresh tokens are single-use. Presenting one that has already been
    exchanged means two parties hold the same credential, and the entire family
    descended from that login is revoked — the legitimate holder is signed out,
    which is the point. A thief cannot use a stolen token quietly.
    """
    try:
        payload = jwt.decode(
            body.refresh_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
    except InvalidTokenError:
        raise i18n_error(status.HTTP_401_UNAUTHORIZED, "auth.refresh_token_invalid")

    if payload.get("type") != "refresh":
        # An access token presented here is exactly the old vulnerability.
        raise i18n_error(status.HTTP_401_UNAUTHORIZED, "auth.invalid_token_type")

    jti = payload.get("jti")
    record = db.query(RefreshToken).filter(RefreshToken.jti == jti).first() if jti else None
    if record is None:
        raise i18n_error(status.HTTP_401_UNAUTHORIZED, "auth.refresh_token_invalid")

    if record.consumed_at is not None or record.revoked_at is not None:
        _revoke_family(db, record.family, reason="reuse_detected")
        db.commit()
        logger.warning(
            "refresh token reuse detected: family=%s user=%s — family revoked",
            record.family, record.user_id,
        )
        raise i18n_error(status.HTTP_401_UNAUTHORIZED, "auth.refresh_token_reused")

    if not record.is_live:
        raise i18n_error(status.HTTP_401_UNAUTHORIZED, "auth.refresh_token_invalid")

    user = db.query(User).filter(User.id == record.user_id).first()
    if user is None or user.status != UserStatus.ACTIVE:
        raise i18n_error(status.HTTP_401_UNAUTHORIZED, "auth.user_not_found_or_inactive")

    record.consumed_at = datetime.now(timezone.utc)
    access_token = create_access_token(
        data={"sub": str(user.id), "email": user.email,
              "gen": user.token_generation or 0}
    )
    new_refresh, _jti, _exp = _issue_refresh_token(
        db, user, family=record.family, user_agent=request.headers.get("user-agent")
    )
    db.commit()

    return {
        "access_token": access_token,
        "refresh_token": new_refresh,
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


@router.post("/logout")
def logout(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """End every session for this user.

    H2.5 / S1-05. There was no logout endpoint at all: signing out dropped the
    token from localStorage and left it valid on the server for the rest of its
    life. Incrementing the token generation invalidates every outstanding access
    token at once, and revoking the refresh rows stops them being renewed.
    """
    current_user.token_generation = (current_user.token_generation or 0) + 1
    revoked = (
        db.query(RefreshToken)
        .filter(RefreshToken.user_id == current_user.id,
                RefreshToken.revoked_at.is_(None))
        .update({"revoked_at": datetime.now(timezone.utc), "revoked_reason": "logout"},
                synchronize_session=False)
    )
    db.commit()
    logger.info("logout: user=%s refresh_tokens_revoked=%s", current_user.id, revoked)
    return i18n_success("auth.logged_out")


# H2.6 / S2-06: POST /auth/toggle-role is deleted.
#
# It promoted the caller to SUPER_ADMIN on request, gated only on
# `settings.DEBUG` — and the shipped docker-compose.yml set DEBUG=true, so any
# deployment from the repo as-published exposed one-click privilege escalation
# to every authenticated user. A convenience that is one environment variable
# away from being a total authorisation bypass does not belong in the codebase;
# use the approval routes above, or change the role directly in the database.
