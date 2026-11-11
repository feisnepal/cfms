"""Reputation as the member sees it: what it lets them do, how they got it, their public profile, and the check that the cached balance is the ledger's.

The ledger (``ledger.py``) is the only writer. Everything here reads, except ``reconcile`` with ``fix=True``, which rewrites a cached balance that
disagrees with the sum of its events.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from ...core import forum_rules as rules
from ...models.forum import ForumAction, ForumPost, ForumProfile, ForumReputationEvent
from ...models.user import User
from .ledger import get_profile, is_moderator, votes_cast_today

# privilege name -> the reputation it needs (a moderator or super admin needs none)
THRESHOLDS: dict[str, int] = {
    "vote_up": rules.FORUM_REP_VOTE_UP,
    "vote_down": rules.FORUM_REP_VOTE_DOWN,
    "flag": rules.FORUM_REP_FLAG,
    "comment": rules.FORUM_REP_COMMENT,
    "create_tag": rules.FORUM_REP_CREATE_TAG,
    "edit_others": rules.FORUM_REP_EDIT_OTHERS,
    "close_others": rules.FORUM_REP_CLOSE_OTHERS,
    "upload": rules.FORUM_REP_UPLOAD,
}


def privileges(db: Session, user: User) -> dict:
    """What this member may do now, the reputation each thing needs, and how many votes are left today."""
    moderator = is_moderator(db, user)
    reputation = get_profile(db, user.id).reputation
    return {
        "reputation": reputation,
        "is_moderator": moderator,
        "thresholds": dict(THRESHOLDS),
        "can": {name: moderator or reputation >= needed for name, needed in THRESHOLDS.items()},
        "votes_left_today": None if moderator else max(0, rules.FORUM_MAX_VOTES_PER_DAY - votes_cast_today(db, user.id)),
    }


def history(db: Session, user_id: uuid.UUID, limit: int = 100, offset: int = 0) -> list[dict]:
    """The member's reputation events, newest first, each with the post it came from (for a link)."""
    rows = db.execute(
        select(ForumReputationEvent, ForumAction.action_type, ForumPost)
        .outerjoin(ForumAction, ForumAction.id == ForumReputationEvent.action_id)
        .outerjoin(ForumPost, ForumPost.id == ForumAction.post_id)
        .where(ForumReputationEvent.user_id == user_id)
        .order_by(ForumReputationEvent.created_at.desc(), ForumReputationEvent.id)
        .limit(max(1, min(limit, 200))).offset(max(0, offset))
    ).all()
    out: list[dict] = []
    for event, action_type, post in rows:
        question_id = None
        title = None
        if post is not None:
            question_id = post.id if post.kind == rules.KIND_QUESTION else post.root_id
            title = post.title if post.kind == rules.KIND_QUESTION else (db.get(ForumPost, post.root_id).title if post.root_id else None)
        out.append({"value": event.value, "by_cancel": event.by_cancel, "created_at": event.created_at, "action_type": action_type,
                    "post_kind": post.kind if post else None, "question_id": question_id, "question_title": title})
    return out


def profile(db: Session, user_id: uuid.UUID) -> Optional[dict]:
    """A member's public profile: name, reputation and what they have posted. None for an unknown user."""
    user = db.get(User, user_id)
    if user is None:
        return None
    prof = db.get(ForumProfile, user_id)
    live = and_(ForumPost.deleted_at.is_(None), ForumPost.pending_review.is_(False))

    def count(*conditions) -> int:
        return db.execute(select(func.count()).select_from(ForumPost).where(ForumPost.author_id == user_id, live, *conditions)).scalar_one()

    return {
        "id": user.id, "name": user.full_name, "reputation": prof.reputation if prof else 0,
        "is_moderator": bool(prof and prof.is_moderator), "member_since": (prof.created_at if prof else user.created_at),
        "questions": count(ForumPost.kind == rules.KIND_QUESTION), "answers": count(ForumPost.kind == rules.KIND_ANSWER),
        "accepted_answers": count(ForumPost.kind == rules.KIND_ANSWER, ForumPost.accepted_at.is_not(None)),
    }


def reconcile(db: Session, fix: bool = False) -> list[dict]:
    """Members whose cached reputation is not the sum of their events. With ``fix`` the balance is set to the ledger's (callers commit)."""
    ledger_sum = (select(ForumReputationEvent.user_id.label("uid"), func.sum(ForumReputationEvent.value).label("total"))
                  .group_by(ForumReputationEvent.user_id).subquery())
    rows = db.execute(
        select(ledger_sum.c.uid, ledger_sum.c.total, ForumProfile.reputation)
        .outerjoin(ForumProfile, ForumProfile.user_id == ledger_sum.c.uid)
        .where(func.coalesce(ForumProfile.reputation, 0) != ledger_sum.c.total)
    ).all()
    # a profile with a balance but no events at all
    orphans = db.execute(
        select(ForumProfile.user_id, ForumProfile.reputation)
        .where(ForumProfile.reputation != 0, ~select(ForumReputationEvent.id).where(ForumReputationEvent.user_id == ForumProfile.user_id).exists())
    ).all()
    mismatches = [{"user_id": r[0], "cached": r[2] or 0, "ledger": int(r[1])} for r in rows]
    mismatches += [{"user_id": r[0], "cached": r[1], "ledger": 0} for r in orphans]
    if fix:
        for m in mismatches:
            get_profile(db, m["user_id"], lock=True).reputation = m["ledger"]
        db.flush()
    return mismatches
