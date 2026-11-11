"""Who may use the assistant, and how much of today is left (CHATBOT_PLAN C1.2; decisions D2, D3, D7, D10, D14).

Approval by a super admin, a daily token cap per user, no anonymous use. A super admin is always allowed (cap 500,000) and needs no row.
The decisions are made here; ``app/api/chat.py`` only turns the errors into HTTP answers.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.chat import (
    CHAT_STATUS_APPROVED, CHAT_STATUS_REQUESTED, CHAT_STATUS_REVOKED, DEFAULT_DAILY_CAP_TOKENS, ChatAccess, ChatMessage, ChatSettings, ChatUsage,
)
from app.models.user import User, UserRole

logger = logging.getLogger(__name__)

NEPAL = ZoneInfo("Asia/Kathmandu")
SUPER_ADMIN_CAP_TOKENS = 500_000       # D10
MAX_CAP_TOKENS = 5_000_000             # a ceiling for what an admin may type
# D14: who may be approved. `guest` never. Read-only accounts (students, researchers) may be approved but get no write tools.
ELIGIBLE_ROLES = frozenset({UserRole.USER, UserRole.ORG_ADMIN, UserRole.TEMPLATE_DESIGNER, UserRole.SUPER_ADMIN})
# A question that uses tools costs 5,000 to 15,000 tokens (D10); "about N questions left" uses the middle.
TOKENS_PER_QUESTION_ESTIMATE = 10_000

STATE_APPROVED = "approved"
STATE_NONE = "none"                 # eligible, never asked
STATE_REQUESTED = "requested"
STATE_REVOKED = "revoked"
STATE_EXPIRED = "expired"
STATE_SWITCHED_OFF = "switched_off"  # the kill switch (R3)
STATE_NOT_ELIGIBLE = "not_eligible"


class AccessError(Exception):
    """A refused change. ``status`` is the HTTP status the API should answer with."""

    def __init__(self, code: str, message: str, status: int = 403):
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class AccessState:
    state: str
    allowed: bool
    daily_cap_tokens: int
    tokens_used_today: int
    tokens_left_today: int
    approx_questions_left: int
    expires_at: Optional[datetime]
    read_only: bool


def nepal_today(now: Optional[datetime] = None) -> date:
    """The usage day rolls over at midnight Nepal time (D10), not UTC."""
    return (now or datetime.now(timezone.utc)).astimezone(NEPAL).date()


def is_eligible(user: User) -> bool:
    return user.role in ELIGIBLE_ROLES


def _is_super_admin(user: User) -> bool:
    return user.role == UserRole.SUPER_ADMIN


def _settings(db: Session) -> Optional[ChatSettings]:
    return db.get(ChatSettings, 1)


def _used_today(db: Session, user_id: UUID, day: date) -> int:
    row = db.get(ChatUsage, (user_id, day))
    return (row.tokens_in + row.tokens_out + row.reserved) if row else 0


def get_state(db: Session, user: User, now: Optional[datetime] = None) -> AccessState:
    now = now or datetime.now(timezone.utc)
    read_only = user.access_level == "read_only"

    def build(state: str, allowed: bool, cap: int, expires: Optional[datetime] = None) -> AccessState:
        used = _used_today(db, user.id, nepal_today(now)) if allowed or state == STATE_APPROVED else 0
        left = max(0, cap - used) if allowed else 0
        return AccessState(state, allowed, cap, used, left, left // TOKENS_PER_QUESTION_ESTIMATE, expires, read_only)

    if not is_eligible(user):
        return build(STATE_NOT_ELIGIBLE, False, 0)
    settings = _settings(db)
    if settings is not None and not settings.enabled:
        # the kill switch beats everything, including a super admin's own use
        return build(STATE_SWITCHED_OFF, False, 0)
    if _is_super_admin(user):
        return build(STATE_APPROVED, True, SUPER_ADMIN_CAP_TOKENS)
    row = db.get(ChatAccess, user.id)
    if row is None:
        return build(STATE_NONE, False, DEFAULT_DAILY_CAP_TOKENS)
    if row.status == CHAT_STATUS_REVOKED:
        return build(STATE_REVOKED, False, row.daily_cap_tokens, row.expires_at)
    if row.status == CHAT_STATUS_REQUESTED:
        return build(STATE_REQUESTED, False, row.daily_cap_tokens)
    if row.expires_at is not None and row.expires_at <= now:
        return build(STATE_EXPIRED, False, row.daily_cap_tokens, row.expires_at)
    return build(STATE_APPROVED, True, row.daily_cap_tokens, row.expires_at)


def request_access(db: Session, user: User, note: Optional[str] = None) -> AccessState:
    """Ask for access. Asking twice changes nothing; a revoked or expired member may ask again."""
    if not is_eligible(user):
        raise AccessError("chat.not_eligible", "This account type cannot use the assistant.", 403)
    if _is_super_admin(user):
        return get_state(db, user)  # always allowed, nothing to request
    now = datetime.now(timezone.utc)
    note = (note or "").strip()[:500] or None
    row = db.get(ChatAccess, user.id)
    if row is None:
        db.add(ChatAccess(user_id=user.id, status=CHAT_STATUS_REQUESTED, request_note=note))
    elif row.status == CHAT_STATUS_REQUESTED:
        if note:
            row.request_note = note
    elif row.status == CHAT_STATUS_REVOKED or (row.expires_at is not None and row.expires_at <= now):
        row.status = CHAT_STATUS_REQUESTED
        row.requested_at = now
        row.request_note = note
        row.revoked_at = None
    # an active approval is left exactly as it is
    db.commit()
    return get_state(db, user)


def _require_admin(admin: User) -> None:
    if not _is_super_admin(admin):
        raise AccessError("chat.admin_only", "Only a super admin can do this.", 403)


def _target(db: Session, user_id: UUID) -> User:
    target = db.get(User, user_id)
    if target is None:
        raise AccessError("chat.not_found", "No such user.", 404)
    return target


def _check_cap(cap: int) -> int:
    if not 0 <= cap <= MAX_CAP_TOKENS:
        raise AccessError("chat.bad_cap", f"The daily limit must be between 0 and {MAX_CAP_TOKENS:,} tokens.", 422)
    return cap


def approve(db: Session, admin: User, user_id: UUID, cap: Optional[int] = None, expires_at: Optional[datetime] = None) -> ChatAccess:
    _require_admin(admin)
    target = _target(db, user_id)
    if not is_eligible(target):
        raise AccessError("chat.not_eligible", "This account type cannot use the assistant.", 422)
    if _is_super_admin(target):
        raise AccessError("chat.super_admin", "A super admin always has access; there is nothing to approve.", 422)
    if expires_at is not None and expires_at <= datetime.now(timezone.utc):
        raise AccessError("chat.bad_expiry", "The expiry must be in the future.", 422)
    row = db.get(ChatAccess, user_id)
    if row is None:
        row = ChatAccess(user_id=user_id)
        db.add(row)
    row.status = CHAT_STATUS_APPROVED
    row.daily_cap_tokens = _check_cap(cap if cap is not None else (row.daily_cap_tokens if row.daily_cap_tokens else DEFAULT_DAILY_CAP_TOKENS))
    row.approved_by_id = admin.id
    row.approved_at = datetime.now(timezone.utc)
    row.expires_at = expires_at
    row.revoked_at = None
    db.commit()
    logger.info("chat access approved for %s by %s (cap %s)", user_id, admin.id, row.daily_cap_tokens)
    return row


def revoke(db: Session, admin: User, user_id: UUID) -> ChatAccess:
    _require_admin(admin)
    row = db.get(ChatAccess, user_id)
    if row is None:
        raise AccessError("chat.not_found", "That user has no assistant access to revoke.", 404)
    row.status = CHAT_STATUS_REVOKED
    row.revoked_at = datetime.now(timezone.utc)
    db.commit()
    logger.info("chat access revoked for %s by %s", user_id, admin.id)
    return row


def set_cap(db: Session, admin: User, user_id: UUID, cap: int) -> ChatAccess:
    _require_admin(admin)
    row = db.get(ChatAccess, user_id)
    if row is None:
        raise AccessError("chat.not_found", "That user has no assistant access.", 404)
    row.daily_cap_tokens = _check_cap(cap)
    db.commit()
    return row


def list_access(db: Session, admin: User, status: Optional[str] = None, limit: int = 200) -> List[tuple]:
    """(access row, user) pairs for the super admin screen, newest request first."""
    _require_admin(admin)
    stmt = select(ChatAccess, User).join(User, User.id == ChatAccess.user_id).order_by(ChatAccess.requested_at.desc()).limit(limit)
    if status:
        if status not in {CHAT_STATUS_REQUESTED, CHAT_STATUS_APPROVED, CHAT_STATUS_REVOKED}:
            raise AccessError("chat.bad_status", "Unknown status.", 422)
        stmt = stmt.where(ChatAccess.status == status)
    return list(db.execute(stmt).all())


def get_settings(db: Session, admin: User) -> dict:
    """The kill switch, the shared daily ceiling and how much of it is used today (held tokens count as used)."""
    _require_admin(admin)
    row = _settings(db)
    used = db.execute(
        select(func.coalesce(func.sum(ChatUsage.tokens_in + ChatUsage.tokens_out + ChatUsage.reserved), 0)).where(ChatUsage.day == nepal_today())
    ).scalar_one()
    return {"enabled": True if row is None else bool(row.enabled), "pool_daily_tokens": None if row is None else row.pool_daily_tokens,
            "pool_used_today": int(used)}


def set_settings(db: Session, admin: User, enabled: bool, pool_daily_tokens: Optional[int]) -> dict:
    _require_admin(admin)
    if pool_daily_tokens is not None and pool_daily_tokens < 0:
        raise AccessError("chat.bad_pool", "The shared daily limit cannot be negative.", 422)
    row = _settings(db)
    if row is None:
        row = ChatSettings(id=1)
        db.add(row)
    row.enabled, row.pool_daily_tokens, row.updated_by_id = enabled, pool_daily_tokens, admin.id
    db.commit()
    logger.warning("chat settings changed by %s: enabled=%s pool=%s", admin.id, enabled, pool_daily_tokens)
    return get_settings(db, admin)


def usage_by_user(db: Session, admin: User) -> dict:
    """{user_id: (tokens used today, messages today, thumbs-down answers in the last 30 days)} for the admin table."""
    _require_admin(admin)
    out: dict = {}
    for r in db.execute(select(ChatUsage.user_id, ChatUsage.tokens_in + ChatUsage.tokens_out, ChatUsage.messages).where(ChatUsage.day == nepal_today())):
        out[r[0]] = [int(r[1]), int(r[2]), 0]
    since = datetime.now(timezone.utc) - timedelta(days=30)
    for uid, n in db.execute(
        select(ChatMessage.user_id, func.count()).where(ChatMessage.feedback == -1, ChatMessage.created_at >= since).group_by(ChatMessage.user_id)
    ):
        out.setdefault(uid, [0, 0, 0])[2] = int(n)
    return out
