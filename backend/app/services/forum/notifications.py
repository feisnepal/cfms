"""Following questions and the emails the forum sends (``FORUM_SPEC.md`` phase F5).

An event (a new answer, a comment, an accepted answer, a new question under a tag) writes one ``ForumNotification`` per member it concerns, in the
same transaction as the event, and only for members whose settings ask for it. Sending is separate: ``send_pending`` emails the rows after the
commit, either at once (``immediate``) or as one message per member (``daily`` / ``weekly``, run by ``scripts/forum_send_digests.py``).
A row whose post was deleted or held in the meantime is dropped, never emailed. Callers commit; the write helpers here do not.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core import forum_rules as rules
from ...core.config import settings
from ...models.forum import (
    ForumNotification, ForumNotificationPrefs, ForumPost, ForumPostTag, ForumSubscription, ForumTag, ForumTagMark,
)
from ...models.user import User, UserStatus

logger = logging.getLogger(__name__)

KIND_ANSWER, KIND_COMMENT, KIND_ACCEPTED, KIND_NEW_IN_TAG = "answer", "comment", "accepted", "new_in_tag"
FREQUENCIES = ("immediate", "daily", "weekly", "never")
#: the settings flag that must be on for each kind of notification
_FLAG = {KIND_ANSWER: "on_answer_to_mine", KIND_COMMENT: "on_comment_reply", KIND_ACCEPTED: "on_accepted", KIND_NEW_IN_TAG: "on_new_in_watched_tags"}
_EXCERPT = 200


def _now() -> datetime:
    return datetime.now(timezone.utc)


def send_mail(to: str, subject: str, body: str) -> bool:
    """The one place the forum hands a message to the app's mailer (tests replace it)."""
    from ..auth_mailer import _send
    return _send(to, subject, body)


# ── settings ────────────────────────────────────────────────────────────────────────────────────────────────────

def get_prefs(db: Session, user_id: uuid.UUID) -> ForumNotificationPrefs:
    """The member's settings, created with the defaults on first use (answers to my questions and replies to my comments, at once)."""
    prefs = db.get(ForumNotificationPrefs, user_id)
    if prefs is None:
        prefs = ForumNotificationPrefs(user_id=user_id, enabled=True, on_answer_to_mine=True, on_comment_reply=True, on_accepted=False,
                                       on_new_in_watched_tags=False, email_frequency="immediate")
        db.add(prefs)
        db.flush()
    return prefs


def update_prefs(db: Session, user_id: uuid.UUID, **changes) -> ForumNotificationPrefs:
    prefs = get_prefs(db, user_id)
    for name, value in changes.items():
        if value is None:
            continue
        if name == "email_frequency" and value not in FREQUENCIES:
            raise ValueError(f"email_frequency must be one of {', '.join(FREQUENCIES)}")
        setattr(prefs, name, value)
    db.flush()
    return prefs


def _wants(prefs: ForumNotificationPrefs, kind: str) -> bool:
    return bool(prefs.enabled) and prefs.email_frequency != "never" and bool(getattr(prefs, _FLAG[kind]))


# ── following ───────────────────────────────────────────────────────────────────────────────────────────────────

def subscribe(db: Session, user_id: uuid.UUID, question_id: uuid.UUID, *, auto: bool) -> None:
    """Follow a question. An explicit follow is kept as explicit when an automatic one comes later."""
    row = db.get(ForumSubscription, (user_id, question_id))
    if row is None:
        db.add(ForumSubscription(user_id=user_id, post_id=question_id, auto=auto))
    elif not auto:
        row.auto = False
    db.flush()


def unsubscribe(db: Session, user_id: uuid.UUID, question_id: uuid.UUID) -> None:
    row = db.get(ForumSubscription, (user_id, question_id))
    if row is not None:
        db.delete(row)
        db.flush()


def is_subscribed(db: Session, user_id: uuid.UUID, question_id: uuid.UUID) -> bool:
    return db.get(ForumSubscription, (user_id, question_id)) is not None


def set_watched_tag(db: Session, user_id: uuid.UUID, tag_name: str, watched: bool) -> bool:
    """Watch (or stop watching) a tag. Returns False when there is no such tag."""
    tag = db.execute(select(ForumTag).where(ForumTag.name == (tag_name or "").strip().lower())).scalar_one_or_none()
    if tag is None:
        return False
    row = db.get(ForumTagMark, (user_id, tag.id))
    if watched and row is None:
        db.add(ForumTagMark(user_id=user_id, tag_id=tag.id, reason="interesting"))
    elif not watched and row is not None:
        db.delete(row)
    db.flush()
    return True


def watched_tags(db: Session, user_id: uuid.UUID) -> list[str]:
    return list(db.execute(
        select(ForumTag.name).join(ForumTagMark, ForumTagMark.tag_id == ForumTag.id)
        .where(ForumTagMark.user_id == user_id, ForumTagMark.reason == "interesting").order_by(ForumTag.name)
    ).scalars())


# ── events ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _counted(post: ForumPost) -> bool:
    return post.deleted_at is None and not post.pending_review


def _record(db: Session, kind: str, post: ForumPost, question_id: uuid.UUID, candidates: Iterable[uuid.UUID], actor_id: Optional[uuid.UUID]) -> int:
    """One notification for each candidate who is not the actor, is an active member, and whose settings ask for this kind."""
    ids = {c for c in candidates if c and c != actor_id}
    if not ids:
        return 0
    active = set(db.execute(select(User.id).where(User.id.in_(ids), User.status == UserStatus.ACTIVE, User.email.is_not(None))).scalars())
    made = 0
    for user_id in sorted(active, key=str):
        if _wants(get_prefs(db, user_id), kind):
            db.add(ForumNotification(user_id=user_id, kind=kind, post_id=post.id, question_id=question_id))
            made += 1
    db.flush()
    return made


def _followers(db: Session, question_id: uuid.UUID) -> set[uuid.UUID]:
    return set(db.execute(select(ForumSubscription.user_id).where(ForumSubscription.post_id == question_id)).scalars())


def on_answer(db: Session, answer: ForumPost) -> int:
    """A new answer: the asker and everyone following the question."""
    if not _counted(answer) or answer.root_id is None:
        return 0
    question = db.get(ForumPost, answer.root_id)
    if question is None or question.deleted_at is not None:
        return 0
    return _record(db, KIND_ANSWER, answer, question.id, _followers(db, question.id) | {question.author_id}, answer.author_id)


def on_comment(db: Session, comment: ForumPost) -> int:
    """A new comment: the author of the post it sits under, and the others who commented there."""
    if not _counted(comment) or comment.parent_id is None or comment.root_id is None:
        return 0
    parent = db.get(ForumPost, comment.parent_id)
    if parent is None or parent.deleted_at is not None:
        return 0
    others = set(db.execute(select(ForumPost.author_id).where(
        ForumPost.parent_id == parent.id, ForumPost.kind == rules.KIND_COMMENT, ForumPost.deleted_at.is_(None), ForumPost.pending_review.is_(False),
    )).scalars())
    return _record(db, KIND_COMMENT, comment, comment.root_id, others | {parent.author_id}, comment.author_id)


def on_accepted(db: Session, answer: ForumPost, actor_id: Optional[uuid.UUID]) -> int:
    """An answer was accepted: its author."""
    if not _counted(answer) or answer.root_id is None:
        return 0
    return _record(db, KIND_ACCEPTED, answer, answer.root_id, {answer.author_id}, actor_id)


def on_question(db: Session, question: ForumPost) -> int:
    """A new question: members watching one of its tags."""
    if not _counted(question):
        return 0
    watchers = set(db.execute(
        select(ForumTagMark.user_id).join(ForumPostTag, ForumPostTag.tag_id == ForumTagMark.tag_id)
        .where(ForumPostTag.post_id == question.id, ForumTagMark.reason == "interesting")
    ).scalars())
    return _record(db, KIND_NEW_IN_TAG, question, question.id, watchers, question.author_id)


def on_approved(db: Session, post: ForumPost, actor_id: Optional[uuid.UUID]) -> int:
    """A held post was let through: tell the people it concerns now (nobody was told while it was held)."""
    if post.kind == rules.KIND_QUESTION:
        return on_question(db, post)
    if post.kind == rules.KIND_ANSWER:
        return on_answer(db, post)
    return on_comment(db, post)


# ── sending ─────────────────────────────────────────────────────────────────────────────────────────────────────

def _one_line(text: str, limit: int = 120) -> str:
    return re.sub(r"\s+", " ", text or "").strip()[:limit]


def _excerpt(post: ForumPost) -> str:
    return _one_line(post.body_md, _EXCERPT)


def _link(path: str) -> str:
    return f"{settings.PUBLIC_APP_URL.rstrip('/')}{path}"


_LINE = {
    KIND_ANSWER: ("New answer", "नयाँ उत्तर"),
    KIND_COMMENT: ("New comment", "नयाँ टिप्पणी"),
    KIND_ACCEPTED: ("Your answer was accepted", "तपाईंको उत्तर स्वीकार गरियो"),
    KIND_NEW_IN_TAG: ("New question in a tag you watch", "तपाईंले हेर्ने ट्यागमा नयाँ प्रश्न"),
}


def _item(db: Session, note: ForumNotification) -> Optional[str]:
    """The text for one notification, or None when the post it is about can no longer be shown."""
    post, question = db.get(ForumPost, note.post_id), db.get(ForumPost, note.question_id)
    if post is None or question is None or not _counted(post) or question.deleted_at is not None or question.pending_review:
        return None
    en, ne = _LINE[note.kind]
    return f"{en} / {ne}: {_one_line(question.title or '')}\n  \"{_excerpt(post)}\"\n  {_link('/forum/q/' + str(question.id))}"


_FOOT = (f"\nChange what you get, or stop these emails: {{settings}}\n"
         "के कस्ता इमेल पाउने भन्ने बदल्न वा रोक्न: {settings}\n")


def send_pending(db: Session, frequency: str = "immediate", user_ids: Optional[Iterable[uuid.UUID]] = None) -> int:
    """Email the unsent notifications of members whose setting is ``frequency``. Returns how many messages went out. Commits."""
    if frequency not in ("immediate", "daily", "weekly"):
        raise ValueError("frequency must be immediate, daily or weekly")
    query = (
        select(ForumNotification).join(ForumNotificationPrefs, ForumNotificationPrefs.user_id == ForumNotification.user_id)
        .where(ForumNotification.emailed_at.is_(None), ForumNotificationPrefs.email_frequency == frequency, ForumNotificationPrefs.enabled.is_(True))
        .order_by(ForumNotification.user_id, ForumNotification.created_at)
    )
    if user_ids is not None:
        query = query.where(ForumNotification.user_id.in_(list(user_ids)))
    pending = list(db.execute(query).scalars())
    by_user: dict[uuid.UUID, list[ForumNotification]] = {}
    for note in pending:
        by_user.setdefault(note.user_id, []).append(note)
    sent = 0
    settings_link = _link("/forum/settings")
    for user_id, notes in by_user.items():
        user = db.get(User, user_id)
        items = [(n, _item(db, n)) for n in notes]
        for note, text in items:
            if text is None:   # the post went away: nothing to say
                note.emailed_at = _now()
        shown = [(n, t) for n, t in items if t is not None]
        if not shown or user is None or not user.email or user.status != UserStatus.ACTIVE:
            for n, _ in shown:
                n.emailed_at = _now()
            continue
        groups = [shown] if frequency != "immediate" else [[pair] for pair in shown]
        for group in groups:
            subject = _one_line(group[0][1].split("\n")[0], 90) if len(group) == 1 else f"{len(group)} updates on the forum / फोरममा {len(group)} अपडेट"
            body = "\n\n".join(t for _, t in group) + _FOOT.format(settings=settings_link)
            try:
                ok = send_mail(user.email, subject, body)
            except Exception:  # noqa: BLE001 -- a mail failure must not lose the rows; they stay unsent for the next run
                logger.exception("forum notification email to user %s failed", user_id)
                ok = False
            if ok:
                for n, _ in group:
                    n.emailed_at = _now()
                sent += 1
    db.commit()
    return sent


def send_immediate_job(user_ids: Optional[Iterable[uuid.UUID]] = None) -> None:
    """Run after a request has committed (FastAPI background task): opens its own session so the request's is not shared."""
    from ...core.database import SessionLocal
    db = SessionLocal()
    try:
        send_pending(db, "immediate", user_ids)
    except Exception:  # noqa: BLE001 -- a background send cannot raise to anyone; the rows stay unsent and are logged
        logger.exception("forum immediate notification run failed")
        db.rollback()
    finally:
        db.close()
