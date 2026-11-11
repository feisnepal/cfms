"""Forum posts: asking, answering, commenting, editing, deleting, tags and the read queries (``FORUM_SPEC.md`` sections 2-3).

Rules kept here: one answer per person per question; a new member's post (reputation below ``FORUM_REP_NO_REVIEW``) is held until a
moderator approves it; every edit writes a revision; a deleted or held post counts nowhere (answer counts, tag usage). Callers commit.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import and_, desc, exists, func, or_, select, update
from sqlalchemy.orm import Session

from ...core import forum_rules as rules
from ...models.forum import ForumAction, ForumPost, ForumPostRevision, ForumPostTag, ForumProfile, ForumTag, ForumTagSynonym
from ...models.user import User
from . import attachments, notifications
from .ledger import ForumPermissionError, ForumRuleError, cancel_action, get_profile, is_moderator, require_reputation

TITLE_MIN, TITLE_MAX = 15, 300
BODY_MIN, BODY_MAX = 30, 20000
COMMENT_MIN, COMMENT_MAX = 5, 1000
MAX_TAGS = 5
# letters (Latin or Devanagari), digits and . + # - ; starts with a letter or digit
_STEP_ID = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
_TAG_NAME = re.compile(r"^[a-z0-9ऀ-ॿ][a-z0-9ऀ-ॿ.+#-]{0,39}$")

SORTS = ("active", "newest", "votes", "unanswered")
# words that say nothing about the subject; dropped when looking for similar questions (the search config is `simple`, so the database keeps them)
_STOP = frozenset("the a an and or of to in on at for with from by is are was were be do does did how why what when where which who can could should would "
                  "this that these those it its my our your you we i me not no have has had".split())
_WORD = re.compile(r"[\w\u0900-\u097F]{3,}")


def any_word_query(q: str) -> Optional[str]:
    """A tsquery text matching any of the question's meaningful words ("print | boundary | labels"), or None when nothing meaningful is left."""
    words = []
    for w in _WORD.findall((q or "").lower()):
        if w not in _STOP and w not in words:
            words.append(w.replace("'", ""))
    return " | ".join(words[:12]) or None


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── visibility ──────────────────────────────────────────────────────────────────────────────────────────────────

def counts(post: ForumPost) -> bool:
    """A post counts in answer counts and tag usage only when it is neither deleted nor held."""
    return post.deleted_at is None and not post.pending_review


def visible_to(post: ForumPost, viewer: Optional[User], moderator: bool) -> bool:
    if post.deleted_at is not None:
        return moderator
    if post.pending_review:
        return moderator or (viewer is not None and post.author_id == viewer.id)
    return True


def _visible_clause(viewer: Optional[User], moderator: bool):
    """SQL condition for the posts a viewer may see."""
    if moderator:
        return True
    clause = and_(ForumPost.deleted_at.is_(None), ForumPost.pending_review.is_(False))
    if viewer is not None:
        clause = or_(clause, and_(ForumPost.deleted_at.is_(None), ForumPost.author_id == viewer.id))
    return clause


# ── tags ────────────────────────────────────────────────────────────────────────────────────────────────────────

def normalise_tag_names(raw: list[str]) -> list[str]:
    names: list[str] = []
    for item in raw:
        name = (item or "").strip().lower().lstrip("#")
        if not name:
            continue
        if not _TAG_NAME.match(name):
            raise ForumRuleError(f"{item!r} is not a valid tag (letters, digits, . + # -; up to 40 characters)")
        if name not in names:
            names.append(name)
    if not names:
        raise ForumRuleError("give the question at least one tag")
    if len(names) > MAX_TAGS:
        raise ForumRuleError(f"at most {MAX_TAGS} tags")
    return names


def resolve_tags(db: Session, user: User, raw: list[str]) -> list[ForumTag]:
    """The tag rows for these names; synonyms resolve to their target, an unknown name needs the reputation to create a tag."""
    names = normalise_tag_names(raw)
    synonyms = dict(db.execute(select(ForumTagSynonym.source_name, ForumTagSynonym.tag_id).where(ForumTagSynonym.source_name.in_(names))).all())
    tags: list[ForumTag] = []
    for name in names:
        tag = db.get(ForumTag, synonyms[name]) if name in synonyms else db.execute(select(ForumTag).where(ForumTag.name == name)).scalar_one_or_none()
        if tag is None:
            require_reputation(db, user, rules.FORUM_REP_CREATE_TAG, f"creating the tag {name!r}")
            tag = ForumTag(name=name, created_by_id=user.id)
            db.add(tag)
            db.flush()
        if tag not in tags:
            tags.append(tag)
    return tags


def _tag_usage(db: Session, post_id: uuid.UUID, delta: int) -> None:
    """Move ``used_count`` of the post's tags by ``delta``, never below zero."""
    tag_ids = [r[0] for r in db.execute(select(ForumPostTag.tag_id).where(ForumPostTag.post_id == post_id)).all()]
    if tag_ids:
        db.execute(update(ForumTag).where(ForumTag.id.in_(tag_ids)).values(used_count=func.greatest(0, ForumTag.used_count + delta)))


def post_tags(db: Session, post_id: uuid.UUID) -> list[ForumTag]:
    return list(db.execute(
        select(ForumTag).join(ForumPostTag, ForumPostTag.tag_id == ForumTag.id).where(ForumPostTag.post_id == post_id).order_by(ForumTag.name)
    ).scalars())


# ── counters ────────────────────────────────────────────────────────────────────────────────────────────────────

def _recount(db: Session, question_id: uuid.UUID) -> None:
    """Recompute a question's answer and comment counts from the rows, so a delete, restore or approval cannot drift them."""
    live = and_(ForumPost.deleted_at.is_(None), ForumPost.pending_review.is_(False))
    answers = db.execute(select(func.count()).select_from(ForumPost).where(ForumPost.parent_id == question_id, ForumPost.kind == rules.KIND_ANSWER, live)).scalar_one()
    db.execute(update(ForumPost).where(ForumPost.id == question_id).values(answer_count=answers))
    for parent_id in [question_id] + [r[0] for r in db.execute(select(ForumPost.id).where(ForumPost.parent_id == question_id, ForumPost.kind == rules.KIND_ANSWER)).all()]:
        comments = db.execute(select(func.count()).select_from(ForumPost).where(ForumPost.parent_id == parent_id, ForumPost.kind == rules.KIND_COMMENT, live)).scalar_one()
        db.execute(update(ForumPost).where(ForumPost.id == parent_id).values(comment_count=comments))


def _touch(db: Session, question_id: uuid.UUID, user_id: uuid.UUID) -> None:
    db.execute(update(ForumPost).where(ForumPost.id == question_id).values(last_activity_at=_now(), last_activity_by_id=user_id))


# ── writing ─────────────────────────────────────────────────────────────────────────────────────────────────────

def _check_body(body: str, low: int, high: int, what: str) -> str:
    body = (body or "").strip()
    if len(body) < low:
        raise ForumRuleError(f"the {what} needs at least {low} characters")
    if len(body) > high:
        raise ForumRuleError(f"the {what} is longer than {high} characters")
    return body


def _held(db: Session, author: User) -> bool:
    return not is_moderator(db, author) and get_profile(db, author.id).reputation < rules.FORUM_REP_NO_REVIEW


def _add_revision(db: Session, post: ForumPost, editor: User, summary: Optional[str], tag_names: Optional[str]) -> None:
    db.add(ForumPostRevision(post_id=post.id, revision=post.active_revision, title=post.title, body_md=post.body_md,
                             tag_names=tag_names, summary=summary, author_id=editor.id))


def create_question(db: Session, author: User, title: str, body: str, tags: list[str], workflow_step: Optional[str] = None) -> ForumPost:
    title = (title or "").strip()
    if not TITLE_MIN <= len(title) <= TITLE_MAX:
        raise ForumRuleError(f"the title needs {TITLE_MIN} to {TITLE_MAX} characters")
    if workflow_step and not _STEP_ID.match(workflow_step):
        raise ForumRuleError("the workflow step is not a valid step id")
    body = _check_body(body, BODY_MIN, BODY_MAX, "question")
    tag_rows = resolve_tags(db, author, tags)
    post = ForumPost(kind=rules.KIND_QUESTION, author_id=author.id, title=title, body_md=body, workflow_step=(workflow_step or None),
                     pending_review=_held(db, author), last_activity_by_id=author.id)
    db.add(post)
    db.flush()
    for tag in tag_rows:
        db.add(ForumPostTag(post_id=post.id, tag_id=tag.id))
    db.flush()
    _add_revision(db, post, author, None, " ".join(t.name for t in tag_rows))
    if counts(post):
        _tag_usage(db, post.id, 1)
    notifications.subscribe(db, author.id, post.id, auto=True)
    notifications.on_question(db, post)
    db.flush()
    db.refresh(post)
    return post


def create_answer(db: Session, author: User, question: ForumPost, body: str) -> ForumPost:
    if question.kind != rules.KIND_QUESTION or question.deleted_at is not None or (question.pending_review and question.author_id != author.id):
        raise ForumRuleError("this question cannot be answered")
    if question.closed_at is not None:
        raise ForumRuleError("this question is closed")
    body = _check_body(body, BODY_MIN, BODY_MAX, "answer")
    already = db.execute(select(ForumPost.id).where(ForumPost.parent_id == question.id, ForumPost.kind == rules.KIND_ANSWER,
                                                    ForumPost.author_id == author.id, ForumPost.deleted_at.is_(None))).first()
    if already:
        raise ForumRuleError("you already answered this question; edit your answer instead")
    post = ForumPost(kind=rules.KIND_ANSWER, author_id=author.id, body_md=body, parent_id=question.id, root_id=question.id,
                     pending_review=_held(db, author), last_activity_by_id=author.id)
    db.add(post)
    db.flush()
    _add_revision(db, post, author, None, None)
    _recount(db, question.id)
    if counts(post):
        _touch(db, question.id, author.id)
    notifications.subscribe(db, author.id, question.id, auto=True)
    notifications.on_answer(db, post)
    db.flush()
    db.refresh(post)
    return post


def create_comment(db: Session, author: User, parent: ForumPost, body: str) -> ForumPost:
    if parent.kind not in (rules.KIND_QUESTION, rules.KIND_ANSWER) or parent.deleted_at is not None:
        raise ForumRuleError("this post cannot be commented on")
    require_reputation(db, author, rules.FORUM_REP_COMMENT if parent.author_id != author.id else 0, "commenting on another person's post")
    body = _check_body(body, COMMENT_MIN, COMMENT_MAX, "comment")
    root_id = parent.id if parent.kind == rules.KIND_QUESTION else parent.root_id
    post = ForumPost(kind=rules.KIND_COMMENT, author_id=author.id, body_md=body, parent_id=parent.id, root_id=root_id,
                     pending_review=_held(db, author), last_activity_by_id=author.id)
    db.add(post)
    db.flush()
    _add_revision(db, post, author, None, None)
    _recount(db, root_id)
    if counts(post):
        _touch(db, root_id, author.id)
    notifications.subscribe(db, author.id, root_id, auto=True)
    notifications.on_comment(db, post)
    db.flush()
    db.refresh(post)
    return post


def edit_post(db: Session, editor: User, post: ForumPost, *, body: Optional[str] = None, title: Optional[str] = None,
              tags: Optional[list[str]] = None, summary: Optional[str] = None) -> ForumPost:
    if post.deleted_at is not None:
        raise ForumRuleError("this post is deleted")
    if post.author_id != editor.id:
        require_reputation(db, editor, rules.FORUM_REP_EDIT_OTHERS, "editing another person's post")
    low, high, what = {
        rules.KIND_QUESTION: (BODY_MIN, BODY_MAX, "question"), rules.KIND_ANSWER: (BODY_MIN, BODY_MAX, "answer"),
        rules.KIND_COMMENT: (COMMENT_MIN, COMMENT_MAX, "comment"),
    }[post.kind]
    new_body = _check_body(body if body is not None else post.body_md, low, high, what)
    new_title = post.title
    if post.kind == rules.KIND_QUESTION and title is not None:
        new_title = title.strip()
        if not TITLE_MIN <= len(new_title) <= TITLE_MAX:
            raise ForumRuleError(f"the title needs {TITLE_MIN} to {TITLE_MAX} characters")
    tag_rows = None
    if post.kind == rules.KIND_QUESTION and tags is not None:
        tag_rows = resolve_tags(db, editor, tags)
    if new_body == post.body_md and new_title == post.title and tag_rows is None:
        return post
    if tag_rows is not None:
        if counts(post):
            _tag_usage(db, post.id, -1)
        db.query(ForumPostTag).filter(ForumPostTag.post_id == post.id).delete(synchronize_session=False)
        for tag in tag_rows:
            db.add(ForumPostTag(post_id=post.id, tag_id=tag.id))
        db.flush()
        if counts(post):
            _tag_usage(db, post.id, 1)
    post.body_md, post.title = new_body, new_title
    post.active_revision += 1
    names = " ".join(t.name for t in (tag_rows if tag_rows is not None else post_tags(db, post.id)))
    _add_revision(db, post, editor, (summary or "").strip() or None, names or None)
    _touch(db, post.root_id or post.id, editor.id)
    db.flush()
    db.refresh(post)
    return post


def delete_post(db: Session, actor: User, post: ForumPost) -> ForumPost:
    """Soft delete. The author may delete their own post while nobody has built on it (a question with no answers, an answer not accepted); a moderator any time."""
    if post.deleted_at is not None:
        return post
    if not is_moderator(db, actor):
        if post.author_id != actor.id:
            raise ForumPermissionError("only the author or a moderator can delete this post")
        if post.kind == rules.KIND_QUESTION and post.answer_count > 0:
            raise ForumRuleError("a question that has answers cannot be deleted; ask a moderator")
        if post.accepted_at is not None:
            raise ForumRuleError("an accepted answer cannot be deleted; ask a moderator")
    was_counted = counts(post)
    post.deleted_at, post.deleted_by_id = _now(), actor.id
    if post.accepted_at is not None:
        # a moderator removed the accepted answer: the mark and what it paid go with it (restoring the answer does not re-accept it)
        for action in db.execute(select(ForumAction).where(ForumAction.post_id == post.id, ForumAction.action_type == rules.ACTION_ACCEPT,
                                                           ForumAction.canceled_at.is_(None))).scalars():
            cancel_action(db, action, actor.id)
        post.accepted_at = None
    if post.kind == rules.KIND_QUESTION and was_counted:
        _tag_usage(db, post.id, -1)
    if post.kind != rules.KIND_QUESTION:
        _recount(db, post.root_id)
    db.flush()
    return post


def restore_post(db: Session, actor: User, post: ForumPost) -> ForumPost:
    if not is_moderator(db, actor):
        raise ForumPermissionError("only a moderator can restore a post")
    if post.deleted_at is None:
        return post
    post.deleted_at, post.deleted_by_id = None, None
    if post.kind == rules.KIND_QUESTION and counts(post):
        _tag_usage(db, post.id, 1)
    if post.kind != rules.KIND_QUESTION:
        _recount(db, post.root_id)
    db.flush()
    return post


def approve_post(db: Session, actor: User, post: ForumPost) -> ForumPost:
    """A moderator lets a held post through."""
    if not is_moderator(db, actor):
        raise ForumPermissionError("only a moderator can approve a held post")
    if not post.pending_review:
        return post
    post.pending_review = False
    attachments.approve_all_on_post(db, post.id)
    if post.kind == rules.KIND_QUESTION and post.deleted_at is None:
        _tag_usage(db, post.id, 1)
    if post.kind != rules.KIND_QUESTION:
        _recount(db, post.root_id)
    _touch(db, post.root_id or post.id, actor.id)
    notifications.on_approved(db, post, actor.id)
    db.flush()
    return post


# ── reading ─────────────────────────────────────────────────────────────────────────────────────────────────────

def list_questions(db: Session, viewer: Optional[User], *, sort: str = "active", tag: Optional[str] = None, q: Optional[str] = None,
                   mine: bool = False, workflow_step: Optional[str] = None, match: str = "all", limit: int = 20, offset: int = 0) -> tuple[list[ForumPost], int]:
    """Questions a viewer may see, with the total before paging. ``q`` searches titles and bodies of questions and of their answers: every word must match
    (``match="all"``), or any of its meaningful words (``match="any"``, ranked by how many match: for "has this been asked already")."""
    if sort not in SORTS:
        raise ForumRuleError(f"sort must be one of {', '.join(SORTS)}")
    moderator = viewer is not None and is_moderator(db, viewer)
    query = select(ForumPost).where(ForumPost.kind == rules.KIND_QUESTION, _visible_clause(viewer, moderator))
    if tag:
        name = tag.strip().lower()
        synonym = db.execute(select(ForumTagSynonym.tag_id).where(ForumTagSynonym.source_name == name)).scalar_one_or_none()
        tag_filter = ForumTag.id == synonym if synonym else ForumTag.name == name
        query = query.where(exists().where(ForumPostTag.post_id == ForumPost.id, ForumPostTag.tag_id == ForumTag.id, tag_filter))
    if workflow_step:
        query = query.where(ForumPost.workflow_step == workflow_step)
    if mine:  # an anonymous reader has no questions of their own
        query = query.where(ForumPost.author_id == (viewer.id if viewer is not None else None))
    if sort == "unanswered":
        query = query.where(ForumPost.answer_count == 0)
    rank = None
    if q and q.strip():
        if match == "any":
            text_query = any_word_query(q)
            if text_query is None:
                return [], 0
            tsq = func.to_tsquery("simple", text_query)
        else:
            tsq = func.plainto_tsquery("simple", q.strip())
        answer = ForumPost.__table__.alias("fa")
        in_answers = exists().where(answer.c.parent_id == ForumPost.id, answer.c.deleted_at.is_(None), answer.c.pending_review.is_(False), answer.c.search_vector.op("@@")(tsq))
        query = query.where(or_(ForumPost.search_vector.op("@@")(tsq), in_answers))
        rank = func.ts_rank(ForumPost.search_vector, tsq)
    total = db.execute(select(func.count()).select_from(query.subquery())).scalar_one()
    if rank is not None:
        query = query.order_by(desc(rank), desc(ForumPost.last_activity_at))
    elif sort == "newest":
        query = query.order_by(desc(ForumPost.created_at))
    elif sort == "votes":
        query = query.order_by(desc(ForumPost.score), desc(ForumPost.last_activity_at))
    else:
        query = query.order_by(desc(ForumPost.last_activity_at))
    return list(db.execute(query.limit(max(1, min(limit, 100))).offset(max(0, offset))).scalars()), total


def get_post(db: Session, post_id: uuid.UUID, viewer: Optional[User]) -> Optional[ForumPost]:
    """The post, or None when it does not exist or the viewer may not see it (a hidden post looks the same as a missing one)."""
    post = db.get(ForumPost, post_id)
    if post is None:
        return None
    moderator = viewer is not None and is_moderator(db, viewer)
    return post if visible_to(post, viewer, moderator) else None


def thread(db: Session, question: ForumPost, viewer: Optional[User]) -> dict:
    """A question's answers (accepted first, then by score) and the comments under the question and each answer, as the viewer may see them."""
    moderator = viewer is not None and is_moderator(db, viewer)
    visible = _visible_clause(viewer, moderator)
    answers = list(db.execute(
        select(ForumPost).where(ForumPost.parent_id == question.id, ForumPost.kind == rules.KIND_ANSWER, visible)
        .order_by(ForumPost.accepted_at.is_(None), desc(ForumPost.score), ForumPost.created_at)
    ).scalars())
    parents = [question.id] + [a.id for a in answers]
    comments = list(db.execute(
        select(ForumPost).where(ForumPost.parent_id.in_(parents), ForumPost.kind == rules.KIND_COMMENT, visible).order_by(ForumPost.created_at)
    ).scalars())
    by_parent: dict[uuid.UUID, list[ForumPost]] = {}
    for c in comments:
        by_parent.setdefault(c.parent_id, []).append(c)
    return {"answers": answers, "comments": by_parent}


def count_view(db: Session, question: ForumPost) -> None:
    db.execute(update(ForumPost).where(ForumPost.id == question.id).values(view_count=ForumPost.view_count + 1))


def related_questions(db: Session, question: ForumPost, limit: int = 5) -> list[ForumPost]:
    """Questions sharing the most tags with this one."""
    mine = select(ForumPostTag.tag_id).where(ForumPostTag.post_id == question.id)
    shared = func.count(ForumPostTag.tag_id)
    rows = db.execute(
        select(ForumPost, shared).join(ForumPostTag, ForumPostTag.post_id == ForumPost.id)
        .where(ForumPostTag.tag_id.in_(mine), ForumPost.id != question.id, ForumPost.kind == rules.KIND_QUESTION,
               ForumPost.deleted_at.is_(None), ForumPost.pending_review.is_(False))
        .group_by(ForumPost.id).order_by(desc(shared), desc(ForumPost.last_activity_at)).limit(limit)
    ).all()
    return [r[0] for r in rows]


def tag_list(db: Session, q: Optional[str] = None, limit: int = 100) -> list[ForumTag]:
    query = select(ForumTag).order_by(desc(ForumTag.used_count), ForumTag.name).limit(max(1, min(limit, 500)))
    if q and q.strip():
        query = query.where(ForumTag.name.like(q.strip().lower() + "%"))
    return list(db.execute(query).scalars())


def authors(db: Session, posts: list[ForumPost]) -> dict[uuid.UUID, tuple[str, int]]:
    """author id -> (display name, reputation) for these posts."""
    return authors_by_id(db, {p.author_id for p in posts if p.author_id})


def authors_by_id(db: Session, ids: set) -> dict[uuid.UUID, tuple[str, int]]:
    """author id -> (display name, reputation) for these user ids."""
    ids = {i for i in ids if i}
    if not ids:
        return {}
    rows = db.execute(
        select(User.id, User.full_name, func.coalesce(ForumProfile.reputation, 0))
        .outerjoin(ForumProfile, ForumProfile.user_id == User.id).where(User.id.in_(ids))
    ).all()
    return {r[0]: (r[1], r[2]) for r in rows}


def viewer_votes(db: Session, viewer: Optional[User], post_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    """post id -> 'vote_up' / 'vote_down' for the viewer's live votes."""
    if viewer is None or not post_ids:
        return {}
    rows = db.execute(select(ForumAction.post_id, ForumAction.action_type).where(
        ForumAction.user_id == viewer.id, ForumAction.post_id.in_(post_ids), ForumAction.canceled_at.is_(None),
        ForumAction.action_type.in_((rules.ACTION_VOTE_UP, rules.ACTION_VOTE_DOWN)))).all()
    return {r[0]: r[1] for r in rows}


def revisions(db: Session, post: ForumPost) -> list[ForumPostRevision]:
    """The edit history of a post, newest first."""
    return list(db.execute(select(ForumPostRevision).where(ForumPostRevision.post_id == post.id).order_by(desc(ForumPostRevision.revision))).scalars())


def step_counts(db: Session) -> dict[str, dict[str, int]]:
    """Per workflow step: how many questions anyone may read were asked from it, and how many of those have no answer yet."""
    rows = db.execute(
        select(ForumPost.workflow_step, func.count(), func.count().filter(ForumPost.answer_count == 0))
        .where(ForumPost.kind == rules.KIND_QUESTION, ForumPost.workflow_step.is_not(None), ForumPost.deleted_at.is_(None), ForumPost.pending_review.is_(False))
        .group_by(ForumPost.workflow_step)
    ).all()
    return {r[0]: {"questions": r[1], "unanswered": r[2]} for r in rows}
