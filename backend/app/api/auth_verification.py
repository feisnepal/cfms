"""
Sign-in by phone code or Facebook, profile completion, phone/email verification and
password recovery. Mounted under /auth next to the password endpoints in auth.py.

Rules (owner, 2026-10-20):
- A new account is ACTIVE but unapproved (limited tier) until a super admin approves it.
- Facebook sign-in needs no further verification; the first login asks for the profile.
- A code or link goes only to a phone / email the user has verified.
"""
import logging
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.config import settings
from ..core.database import get_db
from ..core.exceptions import i18n_error
from ..core.rate_limit import limiter
from ..models.organization import Organization
from ..models.user import User, UserIdentity, UserStatus, UserType
from ..schemas.auth import (
    EmailLinkRequest, FacebookLogin, ForgotPassword, PhoneCodeRequest, PhoneLogin, PhoneVerify,
    ProfileUpdate, ResetLink, ResetPassword, Token, TokenBody, UserResponse,
)
from ..services import auth_challenge_service as challenges
from ..services import auth_mailer, facebook_auth, user_types
from ..services.sms import get_sender as get_sms_sender
from ..utils.auth import get_current_active_user, hash_password, require_super_admin
from ..schemas.auth import AccessUpdate, MemberResponse
from .auth import _revoke_family_for_user, issue_session

logger = logging.getLogger(__name__)

router = APIRouter()

ACCEPTED = {"sent": True}


def _challenge_error(exc: challenges.ChallengeError):
    return i18n_error(status.HTTP_400_BAD_REQUEST, exc.code)


def _send_sms_code(phone: str, code: str) -> None:
    get_sms_sender().send(phone, f"Forest Management code: {code}. Valid {settings.OTP_TTL_SECONDS // 60} min.")


def _require_active(user: User) -> None:
    if user.status != UserStatus.ACTIVE:
        raise i18n_error(status.HTTP_403_FORBIDDEN, "auth.account_inactive", status=f"'{user.status.value}'")


# --------------------------------------------------------------------------- sign in by phone
@router.post("/login/phone-code", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(lambda: settings.RATE_LIMIT_OTP)
def request_login_code(request: Request, body: PhoneCodeRequest, db: Session = Depends(get_db)):
    """Send a sign-in code. The answer is the same whether or not the number is registered."""
    try:
        phone = challenges.normalize_phone(body.phone)
    except challenges.ChallengeError as exc:
        raise _challenge_error(exc)
    user = db.query(User).filter(User.phone == phone, User.phone_verified_at.isnot(None)).first()
    if user is not None:
        try:
            code = challenges.issue(db, purpose=challenges.LOGIN, channel="sms", target=phone, user_id=user.id)
            db.commit()
            _send_sms_code(phone, code)
        except challenges.ChallengeError as exc:
            logger.info("login code not sent: %s", exc.code)  # cooldown / daily cap: say nothing to the caller
    return ACCEPTED


@router.post("/login/phone", response_model=Token)
@limiter.limit(lambda: settings.RATE_LIMIT_LOGIN)
def login_with_phone(request: Request, body: PhoneLogin, db: Session = Depends(get_db)):
    try:
        phone = challenges.normalize_phone(body.phone)
        challenges.verify_code(db, purpose=challenges.LOGIN, target=phone, code=body.code)
    except challenges.ChallengeError as exc:
        raise _challenge_error(exc)
    user = db.query(User).filter(User.phone == phone, User.phone_verified_at.isnot(None)).first()
    if user is None:
        raise i18n_error(status.HTTP_401_UNAUTHORIZED, "auth.invalid_credentials")
    _require_active(user)
    return issue_session(db, user, request)


# --------------------------------------------------------------------------- sign in with Facebook
@router.post("/login/facebook", response_model=Token)
@limiter.limit(lambda: settings.RATE_LIMIT_LOGIN)
def login_with_facebook(request: Request, body: FacebookLogin, db: Session = Depends(get_db)):
    """Sign in (or sign up) with a Facebook access token. No further verification is asked.

    A first-time Facebook user gets an ACTIVE, unapproved account (limited tier) with no
    designation yet; /auth/me reports `profile_complete: false` until they fill it in."""
    try:
        fb = facebook_auth.verify_access_token(body.access_token)
    except facebook_auth.FacebookError as exc:
        raise i18n_error(status.HTTP_400_BAD_REQUEST, exc.code)

    identity = db.query(UserIdentity).filter_by(provider="facebook", subject=fb.subject).first()
    if identity is not None:
        user = db.query(User).filter(User.id == identity.user_id).one()
        _require_active(user)
        return issue_session(db, user, request)

    email = challenges.normalize_email(fb.email) if fb.email else None
    existing = db.query(User).filter(User.email == email).first() if email else None
    if existing is not None:
        # Facebook vouches for its own addresses; link only when OUR copy was verified too,
        # otherwise a stranger who typed someone's email at sign-up could be linked to them.
        if existing.email_verified_at is None:
            raise i18n_error(status.HTTP_400_BAD_REQUEST, "auth.email_already_registered")
        db.add(UserIdentity(user_id=existing.id, provider="facebook", subject=fb.subject))
        _require_active(existing)
        db.flush()
        return issue_session(db, existing, request)

    user = User(
        email=email,
        # Nobody knows this password; "forgot password" sets a real one.
        hashed_password=hash_password(secrets.token_urlsafe(24)),
        full_name=fb.name or "Facebook user",
        email_verified_at=datetime.now(timezone.utc) if email else None,
        status=UserStatus.ACTIVE,
    )
    db.add(user)
    try:
        db.flush()
        db.add(UserIdentity(user_id=user.id, provider="facebook", subject=fb.subject))
        db.flush()
    except IntegrityError:
        db.rollback()
        raise i18n_error(status.HTTP_400_BAD_REQUEST, "auth.facebook_already_linked")
    return issue_session(db, user, request)


# --------------------------------------------------------------------------- profile
@router.patch("/me/profile", response_model=UserResponse)
def update_profile(body: ProfileUpdate, current_user: User = Depends(get_current_active_user),
                   db: Session = Depends(get_db)):
    if body.full_name is not None:
        current_user.full_name = body.full_name
    if body.user_type is not None or body.designation is not None or body.sub_division is not None or body.details is not None:
        # An approved account keeps the type it was approved as: switching student -> official would
        # otherwise be a self-service upgrade from read-only to full access.
        if current_user.is_approved and current_user.user_type is not None:
            raise i18n_error(status.HTTP_403_FORBIDDEN, "auth.type_locked")
        kind = body.user_type or (UserType(current_user.user_type) if current_user.user_type else UserType.OFFICIAL)
        try:
            user_types.apply_type(
                db, current_user, kind,
                body.designation.value if body.designation else current_user.designation,
                body.sub_division if body.sub_division is not None else current_user.sub_division,
                body.details,
            )
        except user_types.TypeDetailsError as exc:
            db.rollback()
            raise i18n_error(status.HTTP_400_BAD_REQUEST, "auth.type_field_invalid", field=exc.field)
    if body.instagram_handle is not None:
        current_user.instagram_handle = body.instagram_handle
    db.commit()
    db.refresh(current_user)
    return current_user


@router.post("/me/phone/code", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(lambda: settings.RATE_LIMIT_OTP)
def request_my_phone_code(request: Request, body: PhoneCodeRequest,
                          current_user: User = Depends(get_current_active_user), db: Session = Depends(get_db)):
    try:
        phone = challenges.normalize_phone(body.phone)
        taken = db.query(User.id).filter(User.phone == phone, User.phone_verified_at.isnot(None),
                                         User.id != current_user.id).first()
        if taken:
            raise i18n_error(status.HTTP_400_BAD_REQUEST, "auth.phone_already_registered")
        code = challenges.issue(db, purpose=challenges.PHONE_VERIFY, channel="sms", target=phone,
                                user_id=current_user.id)
    except challenges.ChallengeError as exc:
        raise _challenge_error(exc)
    db.commit()
    _send_sms_code(phone, code)
    return {"sent": True, "resend_after": settings.OTP_RESEND_COOLDOWN_SECONDS}


@router.post("/me/phone/verify", response_model=UserResponse)
@limiter.limit(lambda: settings.RATE_LIMIT_OTP)
def verify_my_phone(request: Request, body: PhoneVerify,
                    current_user: User = Depends(get_current_active_user), db: Session = Depends(get_db)):
    try:
        phone = challenges.normalize_phone(body.phone)
        challenges.verify_code(db, purpose=challenges.PHONE_VERIFY, target=phone, code=body.code)
    except challenges.ChallengeError as exc:
        raise _challenge_error(exc)
    current_user.phone = phone
    current_user.phone_verified_at = datetime.now(timezone.utc)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise i18n_error(status.HTTP_400_BAD_REQUEST, "auth.phone_already_registered")
    db.refresh(current_user)
    return current_user


@router.post("/me/email/link", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(lambda: settings.RATE_LIMIT_OTP)
def request_my_email_link(request: Request, body: EmailLinkRequest,
                          current_user: User = Depends(get_current_active_user), db: Session = Depends(get_db)):
    email = challenges.normalize_email(body.email)
    other = db.query(User.id).filter(User.email == email, User.id != current_user.id).first()
    if other:
        raise i18n_error(status.HTTP_400_BAD_REQUEST, "auth.email_already_registered")
    try:
        token = challenges.issue(db, purpose=challenges.EMAIL_VERIFY, channel="email", target=email,
                                 user_id=current_user.id)
    except challenges.ChallengeError as exc:
        raise _challenge_error(exc)
    db.commit()
    auth_mailer.send_verify_email(email, token)
    return ACCEPTED


@router.post("/email/verify", response_model=UserResponse)
@limiter.limit(lambda: settings.RATE_LIMIT_OTP)
def verify_email(request: Request, body: TokenBody, db: Session = Depends(get_db)):
    """Open from the emailed link. The token alone proves the address; no sign-in needed."""
    try:
        ch = challenges.verify_token(db, purpose=challenges.EMAIL_VERIFY, token=body.token)
    except challenges.ChallengeError as exc:
        raise _challenge_error(exc)
    user = db.query(User).filter(User.id == ch.user_id).first()
    if user is None:
        raise i18n_error(status.HTTP_400_BAD_REQUEST, "auth.link_invalid")
    user.email = ch.target
    user.email_verified_at = datetime.now(timezone.utc)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise i18n_error(status.HTTP_400_BAD_REQUEST, "auth.email_already_registered")
    db.refresh(user)
    return user


# --------------------------------------------------------------------------- password recovery
@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(lambda: settings.RATE_LIMIT_OTP)
def forgot_password(request: Request, body: ForgotPassword, db: Session = Depends(get_db)):
    """Send a reset link (email) or code (phone) to a VERIFIED contact. Same answer for any input."""
    ident = body.identifier.strip()
    try:
        if "@" in ident:
            email = challenges.normalize_email(ident)
            user = db.query(User).filter(User.email == email, User.email_verified_at.isnot(None)).first()
            if user is not None:
                token = challenges.issue(db, purpose=challenges.PASSWORD_RESET, channel="email",
                                         target=email, user_id=user.id)
                db.commit()
                auth_mailer.send_reset_email(email, token)
        else:
            phone = challenges.normalize_phone(ident)
            user = db.query(User).filter(User.phone == phone, User.phone_verified_at.isnot(None)).first()
            if user is not None:
                code = challenges.issue(db, purpose=challenges.PASSWORD_RESET, channel="sms",
                                        target=phone, user_id=user.id)
                db.commit()
                _send_sms_code(phone, code)
    except challenges.ChallengeError as exc:
        logger.info("password reset not sent: %s", exc.code)  # invalid number, cooldown or cap: say nothing
    return ACCEPTED


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(lambda: settings.RATE_LIMIT_OTP)
def reset_password(request: Request, body: ResetPassword, db: Session = Depends(get_db)):
    try:
        if body.token:
            ch = challenges.verify_token(db, purpose=challenges.PASSWORD_RESET, token=body.token)
            user = db.query(User).filter(User.id == ch.user_id).first()
        elif body.phone and body.code:
            phone = challenges.normalize_phone(body.phone)
            challenges.verify_code(db, purpose=challenges.PASSWORD_RESET, target=phone, code=body.code)
            user = db.query(User).filter(User.phone == phone, User.phone_verified_at.isnot(None)).first()
        else:
            raise challenges.ChallengeError("auth.link_invalid")
    except challenges.ChallengeError as exc:
        raise _challenge_error(exc)
    if user is None:
        raise i18n_error(status.HTTP_400_BAD_REQUEST, "auth.link_invalid")
    user.hashed_password = hash_password(body.new_password)
    # Sign every existing session out: whoever held the old password loses access too.
    user.token_generation = (user.token_generation or 0) + 1
    _revoke_family_for_user(db, user, "password_reset")
    db.commit()
    if user.email and user.email_verified_at:
        auth_mailer.send_password_changed_notice(user.email)
    logger.info("password reset: user=%s", user.id)


@router.post("/users/{user_id}/reset-link", response_model=ResetLink)
def admin_reset_link(user_id: str, current_user: User = Depends(require_super_admin),
                     db: Session = Depends(get_db)):
    """For someone who lost both phone and email: a one-time link the super admin hands over
    after confirming who they are some other way. Every use is logged with the admin."""
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise i18n_error(status.HTTP_404_NOT_FOUND, "auth.user_not_found")
    try:
        token = challenges.issue(db, purpose=challenges.PASSWORD_RESET, channel="email",
                                 target=f"admin-reset:{user.id}", user_id=user.id, created_by=current_user.id)
    except challenges.ChallengeError as exc:
        raise _challenge_error(exc)
    db.commit()
    logger.warning("admin reset link issued: user=%s by=%s", user.id, current_user.id)
    return {
        "url": f"{settings.PUBLIC_APP_URL.rstrip('/')}/reset-password?token={token}",
        "expires_in": settings.AUTH_TOKEN_TTL_MINUTES * 60,
    }


# --------------------------------------------------------------------------- organisations & access
def _owner_of_verified_org(user: User) -> Organization:
    org = user.organization
    if org is None or org.verified_at is None or user.org_member_role != "owner":
        raise i18n_error(status.HTTP_403_FORBIDDEN, "auth.not_org_owner")
    return org


@router.get("/organization/members", response_model=list[MemberResponse])
def organization_members(current_user: User = Depends(get_current_active_user), db: Session = Depends(get_db)):
    """The people who joined the caller's organisation. Owner only."""
    if current_user.organization_id is None or current_user.org_member_role != "owner":
        raise i18n_error(status.HTTP_403_FORBIDDEN, "auth.not_org_owner")
    return (db.query(User).filter(User.organization_id == current_user.organization_id)
            .order_by(User.created_at).all())


@router.post("/organization/members/{user_id}/vouch", response_model=MemberResponse)
def vouch_for_member(user_id: str, current_user: User = Depends(get_current_active_user),
                     db: Session = Depends(get_db)):
    """The owner of a verified organisation says this person belongs to it. It is shown to the super admin
    who approves the account; it does not approve anyone by itself."""
    org = _owner_of_verified_org(current_user)
    member = db.query(User).filter(User.id == user_id, User.organization_id == org.id).first()
    if member is None:
        raise i18n_error(status.HTTP_404_NOT_FOUND, "auth.user_not_found")
    member.org_vouched_at = datetime.now(timezone.utc)
    member.org_vouched_by = current_user.id
    db.commit()
    db.refresh(member)
    return member


@router.post("/organizations/{org_id}/verify", status_code=status.HTTP_204_NO_CONTENT)
def verify_organization(org_id: str, current_user: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    """A super admin confirms the organisation is real; its owner can then vouch for members."""
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if org is None:
        raise i18n_error(status.HTTP_404_NOT_FOUND, "auth.user_not_found")
    org.verified_at = datetime.now(timezone.utc)
    db.commit()
    logger.info("organization verified: org=%s by=%s", org.id, current_user.id)


@router.patch("/users/{user_id}/access", response_model=UserResponse)
def set_user_access(user_id: str, body: AccessUpdate, current_user: User = Depends(require_super_admin),
                    db: Session = Depends(get_db)):
    """Set or clear the end date of a person's access, and (super admin only) change their declared type."""
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise i18n_error(status.HTTP_404_NOT_FOUND, "auth.user_not_found")
    if "access_expires_at" in body.model_fields_set:
        user.access_expires_at = body.access_expires_at
    if body.user_type is not None:
        user.user_type = body.user_type.value
    db.commit()
    db.refresh(user)
    logger.info("access updated: user=%s by=%s", user.id, current_user.id)
    return user
