"""Flags, closing and reopening (``FORUM_SPEC.md`` phase F4).

A flag is a member's report; it never hides anything by itself. A moderator resolves all the open flags of a post at once: dismiss them, warn the
author, or delete the post. An upheld flag (warned or deleted) costs the author ``REP_FLAG_UPHELD`` through the ledger, so a reversal is exact.
Closing stops new answers; a duplicate points at the question that has the answer. Callers commit; nothing here does.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ...core import forum_rules as rules
from ...models.forum import ForumAction, ForumFlag, ForumPost, ForumProfile
from ...models.user import User, UserRole
from . import posts as posts_service
from .ledger import ForumPermissionError, ForumRuleError, _new_action, apply_reputation, cancel_action, get_profile, is_moderator, require_reputation

REASON_MIN, REASON_MAX = 5, 300
#: the resolutions a moderator can choose ("hidden" exists in the table but nothing hides a post except deleting it)
RESOLUTIONS = ("dismissed", "user_warned", "deleted")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _open_flags(db: Session, post_id: uuid.UUID) -> list[ForumFlag]:
    return list(db.execute(
        select(ForumFlag).where(ForumFlag.post_id == post_id, ForumFlag.resolved_at.is_(None)).order_by(ForumFlag.created_at)
    ).scalars())


def _sync_flag_count(db: Session, post: ForumPost) -> None:
    db.flush()  # the count reads the flags just changed
    post.flag_count = db.execute(
        select(func.count()).select_from(ForumFlag).where(ForumFlag.post_id == post.id, ForumFlag.resolved_at.is_(None))
    ).scalar_one()


def flags_today(db: Session, user_id: uuid.UUID) -> int:
    since = _now() - timedelta(hours=24)
    return db.execute(
        select(func.count()).select_from(ForumAction).where(
            ForumAction.user_id == user_id, ForumAction.action_type == rules.ACTION_FLAG, ForumAction.created_at >= since
        )
    ).scalar_one()


def flag_post(db: Session, user: User, post: ForumPost, reason: str) -> ForumFlag:
    """Report a post to the moderators. One live flag per member per post; not your own post; a held or deleted post is not reportable."""
    if post.deleted_at is not None or post.pending_review:
        raise ForumRuleError("this post cannot be flagged")
    if post.author_id == user.id:
        raise ForumRuleError("you cannot flag your own post")
    reason = (reason or "").strip()
    if not REASON_MIN <= len(reason) <= REASON_MAX:
        raise ForumRuleError(f"say why in {REASON_MIN} to {REASON_MAX} characters")
    require_reputation(db, user, rules.FORUM_REP_FLAG, "flagging a post")
    if not is_moderator(db, user) and flags_today(db, user.id) >= rules.FORUM_MAX_FLAGS_PER_DAY:
        raise ForumRuleError(f"at most {rules.FORUM_MAX_FLAGS_PER_DAY} flags a day")
    action = _new_action(db, user.id, post, rules.ACTION_FLAG)  # refuses a second live flag from the same member
    flag = ForumFlag(post_id=post.id, user_id=user.id, reason=reason, source="member")
    db.add(flag)
    db.flush()
    _sync_flag_count(db, post)
    db.flush()
    return flag


def resolve_flags(db: Session, moderator: User, post: ForumPost, resolution: str) -> int:
    """Settle every open flag on ``post``. Returns how many were settled. ``user_warned`` and ``deleted`` uphold them."""
    if not is_moderator(db, moderator):
        raise ForumPermissionError("only a moderator can resolve flags")
    if resolution not in RESOLUTIONS:
        raise ForumRuleError(f"resolution must be one of {', '.join(RESOLUTIONS)}")
    flags = _open_flags(db, post.id)
    if not flags:
        raise ForumRuleError("this post has no open flags")
    now = _now()
    for flag in flags:
        flag.resolved_at, flag.resolved_by_id, flag.resolution = now, moderator.id, resolution
    if resolution != "dismissed" and post.author_id is not None:
        # the penalty hangs on the first flagger's action so cancelling that action would give it back
        first = db.execute(
            select(ForumAction).where(ForumAction.post_id == post.id, ForumAction.action_type == rules.ACTION_FLAG,
                                      ForumAction.user_id == flags[0].user_id).order_by(ForumAction.created_at.desc())
        ).scalars().first()
        apply_reputation(db, post.author_id, rules.REP_FLAG_UPHELD, first)
    if resolution == "deleted":
        posts_service.delete_post(db, moderator, post)
    _sync_flag_count(db, post)
    db.flush()
    return len(flags)


def flagged(db: Session, limit: int = 100) -> list[tuple[ForumPost, list[ForumFlag]]]:
    """Posts with open flags, most-flagged first, each with its open flags (oldest first). Deleted posts drop out of the queue."""
    rows = db.execute(
        select(ForumPost).join(ForumFlag, ForumFlag.post_id == ForumPost.id)
        .where(ForumFlag.resolved_at.is_(None), ForumPost.deleted_at.is_(None))
        .group_by(ForumPost.id).order_by(func.count(ForumFlag.id).desc(), func.min(ForumFlag.created_at)).limit(max(1, min(limit, 200)))
    ).scalars().all()
    return [(p, _open_flags(db, p.id)) for p in rows]


# ── closing ─────────────────────────────────────────────────────────────────────────────────────────────────────

def _may_close(db: Session, actor: User, question: ForumPost) -> None:
    if question.author_id == actor.id or is_moderator(db, actor):
        return
    require_reputation(db, actor, rules.FORUM_REP_CLOSE_OTHERS, "closing someone else's question")


def close_question(db: Session, actor: User, question: ForumPost, reason: str, duplicate_of: Optional[uuid.UUID] = None) -> ForumPost:
    """Close a question: no more answers. As a duplicate it names the question that already has the answer (never itself, never another duplicate)."""
    if question.kind != rules.KIND_QUESTION or question.deleted_at is not None:
        raise ForumRuleError("only a question can be closed")
    _may_close(db, actor, question)
    if reason not in rules.CLOSE_REASONS:
        raise ForumRuleError(f"reason must be one of {', '.join(rules.CLOSE_REASONS)}")
    if question.closed_at is not None:
        raise ForumRuleError("this question is already closed")
    target = None
    if reason == "duplicate":
        if duplicate_of is None:
            raise ForumRuleError("name the question this duplicates")
        if duplicate_of == question.id:
            raise ForumRuleError("a question cannot duplicate itself")
        target = db.get(ForumPost, duplicate_of)
        if target is None or target.kind != rules.KIND_QUESTION or target.deleted_at is not None or target.pending_review:
            raise ForumRuleError("that question does not exist")
        if target.closed_at is not None and target.closed_reason == "duplicate":
            raise ForumRuleError("that question is itself a duplicate; name the original")
    elif duplicate_of is not None:
        raise ForumRuleError("only a duplicate names another question")
    _new_action(db, actor.id, question, rules.ACTION_CLOSE)
    question.closed_at, question.closed_reason = _now(), reason
    question.duplicate_of_id = target.id if target is not None else None
    db.flush()
    return question


def reopen_question(db: Session, actor: User, question: ForumPost) -> ForumPost:
    if question.closed_at is None:
        raise ForumRuleError("this question is not closed")
    _may_close(db, actor, question)
    for action in db.execute(select(ForumAction).where(ForumAction.post_id == question.id, ForumAction.action_type == rules.ACTION_CLOSE,
                                                       ForumAction.canceled_at.is_(None))).scalars():
        cancel_action(db, action, actor.id)
    question.closed_at, question.closed_reason, question.duplicate_of_id = None, None, None
    db.flush()
    return question


# ── who moderates ───────────────────────────────────────────────────────────────────────────────────────────────

def _require_super_admin(actor: User) -> None:
    if actor.role != UserRole.SUPER_ADMIN:
        raise ForumPermissionError("only a super admin can choose moderators")


def members(db: Session, actor: User, q: Optional[str] = None, moderators_only: bool = False, limit: int = 20) -> list[tuple[User, bool]]:
    """Members a super admin can pick from: by name or email, or only those who moderate now. Each comes with whether they moderate."""
    _require_super_admin(actor)
    query = select(User, func.coalesce(ForumProfile.is_moderator, False)).outerjoin(ForumProfile, ForumProfile.user_id == User.id)
    if moderators_only:
        query = query.where(ForumProfile.is_moderator.is_(True))
    term = (q or "").strip()
    if term:
        like = "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        query = query.where(or_(User.full_name.ilike(like, escape="\\"), User.email.ilike(like, escape="\\")))
    elif not moderators_only:
        return []
    return [(u, bool(m)) for u, m in db.execute(query.order_by(User.full_name).limit(max(1, min(limit, 50)))).all()]


def set_moderator(db: Session, actor: User, user_id: uuid.UUID, value: bool) -> User:
    """Grant or take back the moderator role (``ForumProfile.is_moderator``). A super admin always moderates; their flag is not touched."""
    _require_super_admin(actor)
    user = db.get(User, user_id)
    if user is None:
        raise ForumRuleError("no such member")
    get_profile(db, user.id).is_moderator = bool(value)
    db.flush()
    return user
