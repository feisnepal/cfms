"""The forum's action ledger: votes, accepted answers and the reputation they earn, all reversible.

Every change to reputation is a ``ForumReputationEvent`` tied to a ``ForumAction``. ``value`` is the amount *applied* (after the clamp at
zero), so cancelling an action writes the exact opposite and the balance in ``forum_profiles.reputation`` always equals the sum of the events.
Callers commit; nothing here does.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ...core import forum_rules as rules
from ...models.forum import ForumAction, ForumPost, ForumProfile, ForumReputationEvent
from ...models.user import User, UserRole
from . import notifications


class ForumError(Exception):
    """Base of the errors the forum raises for a refused action."""


class ForumPermissionError(ForumError):
    """The user may not do this (not enough reputation, not the author, ...)."""


class ForumRuleError(ForumError):
    """The action breaks a rule (a second vote, voting on your own post, ...)."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_profile(db: Session, user_id: uuid.UUID, *, lock: bool = False) -> ForumProfile:
    """The user's forum profile, created on first use. ``lock`` takes a row lock for a reputation change."""
    query = select(ForumProfile).where(ForumProfile.user_id == user_id)
    if lock:
        query = query.with_for_update()
    profile = db.execute(query).scalar_one_or_none()
    if profile is None:
        profile = ForumProfile(user_id=user_id, reputation=0, is_moderator=False)
        db.add(profile)
        db.flush()
    return profile


def is_moderator(db: Session, user: User) -> bool:
    return user.role == UserRole.SUPER_ADMIN or bool(get_profile(db, user.id).is_moderator)


def require_reputation(db: Session, user: User, needed: int, what: str) -> None:
    """Raise unless the user is a moderator or has at least ``needed`` reputation."""
    if is_moderator(db, user):
        return
    have = get_profile(db, user.id).reputation
    if have < needed:
        raise ForumPermissionError(f"{what} needs {needed} reputation; you have {have}")


def apply_reputation(db: Session, user_id: uuid.UUID, value: int, action: ForumAction | None, *, by_cancel: bool = False) -> int:
    """Add ``value`` to the user's reputation, clamped so the balance never goes below 0. Returns the amount actually applied."""
    profile = get_profile(db, user_id, lock=True)
    applied = value
    if not rules.ALLOW_NEGATIVE_REPUTATION and profile.reputation + value < 0:
        applied = -profile.reputation
    profile.reputation = profile.reputation + applied
    db.add(ForumReputationEvent(user_id=user_id, action_id=action.id if action else None, value=applied, by_cancel=by_cancel))
    db.flush()
    return applied


def _new_action(db: Session, user_id: uuid.UUID, post: ForumPost, action_type: str) -> ForumAction:
    if action_type in rules.SINGLE_PER_USER_ACTIONS:
        live = db.execute(
            select(ForumAction.id).where(
                ForumAction.user_id == user_id, ForumAction.post_id == post.id,
                ForumAction.action_type == action_type, ForumAction.canceled_at.is_(None),
            )
        ).first()
        if live:
            raise ForumRuleError(f"you already did {action_type} on this post")
    action = ForumAction(user_id=user_id, post_id=post.id, action_type=action_type)
    db.add(action)
    db.flush()
    return action


def _bump_score(db: Session, post_id: uuid.UUID, delta: int) -> None:
    db.execute(update(ForumPost).where(ForumPost.id == post_id).values(score=ForumPost.score + delta))


def votes_cast_today(db: Session, user_id: uuid.UUID) -> int:
    since = _now() - timedelta(hours=24)
    return db.execute(
        select(func.count()).select_from(ForumAction).where(
            ForumAction.user_id == user_id, ForumAction.created_at >= since, ForumAction.canceled_at.is_(None),
            ForumAction.action_type.in_((rules.ACTION_VOTE_UP, rules.ACTION_VOTE_DOWN)),
        )
    ).scalar_one()


def cast_vote(db: Session, voter: User, post: ForumPost, direction: str) -> ForumAction:
    """Vote a post up or down. A vote the other way is cancelled first, so a user holds at most one live vote per post."""
    if direction not in (rules.ACTION_VOTE_UP, rules.ACTION_VOTE_DOWN):
        raise ForumRuleError(f"unknown vote direction {direction!r}")
    if post.deleted_at is not None or post.pending_review:
        raise ForumRuleError("this post cannot be voted on")
    if post.author_id == voter.id:
        raise ForumRuleError("you cannot vote on your own post")
    up = direction == rules.ACTION_VOTE_UP
    require_reputation(db, voter, rules.FORUM_REP_VOTE_UP if up else rules.FORUM_REP_VOTE_DOWN, "voting up" if up else "voting down")
    if not is_moderator(db, voter) and votes_cast_today(db, voter.id) >= rules.FORUM_MAX_VOTES_PER_DAY:
        raise ForumRuleError(f"at most {rules.FORUM_MAX_VOTES_PER_DAY} votes a day")

    opposite = rules.ACTION_VOTE_DOWN if up else rules.ACTION_VOTE_UP
    other = db.execute(
        select(ForumAction).where(
            ForumAction.user_id == voter.id, ForumAction.post_id == post.id,
            ForumAction.action_type == opposite, ForumAction.canceled_at.is_(None),
        )
    ).scalar_one_or_none()
    if other is not None:
        cancel_action(db, other, voter.id)

    action = _new_action(db, voter.id, post, direction)
    _bump_score(db, post.id, 1 if up else -1)
    if post.author_id is not None:
        if up:
            gain = rules.upvote_reputation(post.kind)
            if gain:
                apply_reputation(db, post.author_id, gain, action)
        else:
            apply_reputation(db, post.author_id, rules.REP_DOWNVOTED_AUTHOR, action)
    if not up:
        apply_reputation(db, voter.id, rules.REP_DOWNVOTING_VOTER, action)
    db.refresh(post)
    return action


def accept_answer(db: Session, actor: User, answer: ForumPost) -> ForumAction:
    """Mark ``answer`` as the accepted answer of its question. Only the asker or a moderator may; accepting another answer moves the mark."""
    if answer.kind != rules.KIND_ANSWER or answer.root_id is None:
        raise ForumRuleError("only an answer can be accepted")
    question = db.get(ForumPost, answer.root_id)
    if question is None or question.deleted_at is not None:
        raise ForumRuleError("the question is gone")
    if question.author_id != actor.id and not is_moderator(db, actor):
        raise ForumPermissionError("only the person who asked can accept an answer")
    if answer.deleted_at is not None or answer.pending_review:
        raise ForumRuleError("this answer cannot be accepted")
    if answer.accepted_at is not None:
        raise ForumRuleError("this answer is already accepted")

    previous = db.execute(
        select(ForumPost).where(ForumPost.root_id == question.id, ForumPost.accepted_at.is_not(None))
    ).scalars().all()
    for old in previous:
        live = db.execute(
            select(ForumAction).where(ForumAction.post_id == old.id, ForumAction.action_type == rules.ACTION_ACCEPT, ForumAction.canceled_at.is_(None))
        ).scalars().all()
        for action in live:
            cancel_action(db, action, actor.id)
        old.accepted_at = None  # also clears it when no live action was found (a moderator-set mark)
    db.flush()

    action = _new_action(db, actor.id, answer, rules.ACTION_ACCEPT)
    answer.accepted_at = _now()
    if answer.author_id is not None and answer.author_id != question.author_id:
        apply_reputation(db, answer.author_id, rules.REP_ANSWER_ACCEPTED, action)
        if question.author_id is not None:
            apply_reputation(db, question.author_id, rules.REP_ACCEPTING_ASKER, action)
    notifications.on_accepted(db, answer, actor.id)
    db.flush()
    return action


def cancel_action(db: Session, action: ForumAction, by_user_id: uuid.UUID | None) -> None:
    """Undo an action: its effect on the post, and every reputation change it caused (reversed event by event). Cancelling twice does nothing."""
    if action.canceled_at is not None:
        return
    action.canceled_at = _now()
    action.canceled_by_id = by_user_id
    events = db.execute(
        select(ForumReputationEvent).where(ForumReputationEvent.action_id == action.id, ForumReputationEvent.by_cancel.is_(False))
    ).scalars().all()
    for event in events:
        if event.value:
            apply_reputation(db, event.user_id, -event.value, action, by_cancel=True)
    if action.action_type == rules.ACTION_VOTE_UP:
        _bump_score(db, action.post_id, -1)
    elif action.action_type == rules.ACTION_VOTE_DOWN:
        _bump_score(db, action.post_id, 1)
    elif action.action_type == rules.ACTION_ACCEPT:
        db.execute(update(ForumPost).where(ForumPost.id == action.post_id).values(accepted_at=None))
    db.flush()


def reputation_from_events(db: Session, user_id: uuid.UUID) -> int:
    """The balance as the ledger says it. Equal to ``ForumProfile.reputation`` unless something wrote the profile directly."""
    return db.execute(
        select(func.coalesce(func.sum(ForumReputationEvent.value), 0)).where(ForumReputationEvent.user_id == user_id)
    ).scalar_one()
