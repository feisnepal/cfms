"""Community Q&A forum API (``FORUM_SPEC.md``, phase F1).

Reading is public: no token needed, rate-limited by IP, and a deleted or held post looks like a missing one. Writing needs an active account.
Sorting out who may do what is the services' job (``app/services/forum``); this module turns their errors into HTTP answers.
"""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core import forum_rules as rules
from app.core.database import get_db
from app.core.idempotent_route import IdempotentRoute
from app.middleware.rate_limit import WorkspaceRateLimiter
from app.models.forum import ForumAction, ForumAttachment, ForumPost
from app.models.user import User
from app.services.forum import attachments as att_service
from app.services.forum import ledger, moderation, notifications, posts as svc, reputation as rep_service, seo
from app.services.forum import markdown_lite
from app.utils.auth import get_current_active_user, get_current_user

router = APIRouter(route_class=IdempotentRoute)

_optional_bearer = HTTPBearer(auto_error=False)
#: anonymous readers are counted by address; a crawler reading every question must not starve the server
read_limiter = WorkspaceRateLimiter(max_requests=120, window_seconds=60, name="forum_read")
#: a person posting, voting or editing
write_limiter = WorkspaceRateLimiter(max_requests=30, window_seconds=60, name="forum_write")


async def get_optional_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_optional_bearer),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """The signed-in user, or None for an anonymous reader. A token that is present but bad is still refused, not treated as anonymous."""
    if credentials is None:
        return None
    return await get_current_user(credentials, db, request)


def _read_guard(request: Request, user: Optional[User]) -> None:
    read_limiter.check(str(user.id) if user else (request.client.host if request.client else "unknown"))


def _refuse(exc: ledger.ForumError) -> HTTPException:
    status = 403 if isinstance(exc, ledger.ForumPermissionError) else 422
    return HTTPException(status_code=status, detail={"code": "forum.permission" if status == 403 else "forum.rule", "message": str(exc)})


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail={"code": "forum.not_found", "message": "No such post"})


# ── shapes ──────────────────────────────────────────────────────────────────────────────────────────────────────

class AuthorOut(BaseModel):
    id: UUID
    name: str
    reputation: int


class AttachmentOut(BaseModel):
    id: UUID
    width: int
    height: int
    file_name: str
    approved: bool


class DuplicateOut(BaseModel):
    id: UUID
    title: Optional[str]


class PostOut(BaseModel):
    id: UUID
    kind: str
    parent_id: Optional[UUID]
    root_id: Optional[UUID]
    title: Optional[str]
    body_md: str
    body_html: str
    author: Optional[AuthorOut]
    score: int
    answer_count: int
    comment_count: int
    view_count: int
    tags: List[str]
    workflow_step: Optional[str]
    accepted: bool
    closed: bool
    closed_reason: Optional[str] = None
    duplicate_of: Optional[DuplicateOut] = None
    flag_count: int = Field(0, description="open flags; shown to moderators only")
    my_flag: bool = Field(False, description="the viewer has a live flag on it")
    pending_review: bool
    deleted: bool
    created_at: datetime
    last_activity_at: datetime
    my_vote: Optional[str] = Field(None, description="'up' or 'down' when the viewer has a live vote")
    can_edit: bool = False
    can_delete: bool = False
    attachments: List[AttachmentOut] = []


class QuestionListOut(BaseModel):
    items: List[PostOut]
    total: int
    page: int
    per_page: int


class ThreadOut(BaseModel):
    question: PostOut
    answers: List[PostOut]
    comments: dict[str, List[PostOut]] = Field(description="comments by the id of the post they sit under")
    related: List[PostOut]
    following: bool = Field(False, description="the viewer follows this question")


class TagOut(BaseModel):
    name: str
    description_md: Optional[str]
    used_count: int


class MeOut(BaseModel):
    id: UUID
    name: str
    reputation: int
    is_moderator: bool
    thresholds: dict[str, int] = Field(description="the reputation each privilege needs")
    can: dict[str, bool] = Field(description="what this member may do now")
    votes_left_today: Optional[int] = Field(None, description="null for a moderator (no cap)")


class ReputationEventOut(BaseModel):
    value: int
    by_cancel: bool
    created_at: datetime
    action_type: Optional[str]
    post_kind: Optional[str]
    question_id: Optional[UUID]
    question_title: Optional[str]


class ProfileOut(BaseModel):
    id: UUID
    name: str
    reputation: int
    is_moderator: bool
    member_since: datetime
    questions: int
    answers: int
    accepted_answers: int


class RevisionOut(BaseModel):
    revision: int
    title: Optional[str]
    body_md: str
    body_html: str
    tag_names: Optional[str]
    summary: Optional[str]
    author_name: Optional[str]
    revised_at: datetime


class AskIn(BaseModel):
    title: str = Field(..., max_length=svc.TITLE_MAX + 50)
    body: str = Field(..., max_length=svc.BODY_MAX + 1000)
    tags: List[str] = Field(..., max_length=20)
    workflow_step: Optional[str] = Field(None, max_length=40, pattern=r"^[a-z][a-z0-9_-]{0,39}$")


class BodyIn(BaseModel):
    body: str = Field(..., max_length=svc.BODY_MAX + 1000)


class EditIn(BaseModel):
    body: Optional[str] = Field(None, max_length=svc.BODY_MAX + 1000)
    title: Optional[str] = Field(None, max_length=svc.TITLE_MAX + 50)
    tags: Optional[List[str]] = Field(None, max_length=20)
    summary: Optional[str] = Field(None, max_length=300)


class FlagIn(BaseModel):
    reason: str = Field(..., max_length=moderation.REASON_MAX + 100)


class ResolveIn(BaseModel):
    resolution: str = Field(..., pattern="^(dismissed|user_warned|deleted)$")


class CloseIn(BaseModel):
    reason: str = Field(..., pattern="^(duplicate|off_topic|resolved)$")
    duplicate_of: Optional[UUID] = None


class FlagOut(BaseModel):
    id: UUID
    reason: Optional[str]
    by: Optional[str]
    created_at: datetime


class FlaggedOut(BaseModel):
    post: PostOut
    question_id: UUID
    question_title: Optional[str]
    flags: List[FlagOut]


class MemberOut(BaseModel):
    id: UUID
    name: str
    email: str
    is_moderator: bool


class ModeratorIn(BaseModel):
    is_moderator: bool


class PrefsOut(BaseModel):
    enabled: bool
    on_answer_to_mine: bool
    on_comment_reply: bool
    on_accepted: bool
    on_new_in_watched_tags: bool
    email_frequency: str
    watched_tags: List[str]


class PrefsIn(BaseModel):
    enabled: Optional[bool] = None
    on_answer_to_mine: Optional[bool] = None
    on_comment_reply: Optional[bool] = None
    on_accepted: Optional[bool] = None
    on_new_in_watched_tags: Optional[bool] = None
    email_frequency: Optional[str] = Field(None, pattern="^(immediate|daily|weekly|never)$")


class FollowIn(BaseModel):
    following: bool


class FollowOut(BaseModel):
    following: bool


class VoteIn(BaseModel):
    direction: str = Field(..., pattern="^(up|down|none)$")


def _serialise(db: Session, items: list[ForumPost], viewer: Optional[User]) -> list[PostOut]:
    if not items:
        return []
    names = svc.authors(db, items)
    votes = svc.viewer_votes(db, viewer, [p.id for p in items])
    moderator = viewer is not None and ledger.is_moderator(db, viewer)
    pictures = att_service.for_posts(db, [p.id for p in items], viewer, moderator)
    dup_ids = {p.duplicate_of_id for p in items if p.duplicate_of_id}
    dup_titles = dict(db.query(ForumPost.id, ForumPost.title).filter(ForumPost.id.in_(dup_ids), ForumPost.deleted_at.is_(None), ForumPost.pending_review.is_(False)).all()) if dup_ids else {}
    flagged_by_me = set()
    if viewer is not None:
        flagged_by_me = {r[0] for r in db.query(ForumAction.post_id).filter(
            ForumAction.user_id == viewer.id, ForumAction.action_type == rules.ACTION_FLAG, ForumAction.canceled_at.is_(None),
            ForumAction.post_id.in_([p.id for p in items])).all()}
    out: list[PostOut] = []
    for p in items:
        who = names.get(p.author_id) if p.author_id else None
        mine = viewer is not None and p.author_id == viewer.id
        vote = votes.get(p.id)
        out.append(PostOut(
            id=p.id, kind=p.kind, parent_id=p.parent_id, root_id=p.root_id, title=p.title, body_md=p.body_md, body_html=markdown_lite.render(p.body_md),
            author=AuthorOut(id=p.author_id, name=who[0], reputation=who[1]) if who else None,
            score=p.score, answer_count=p.answer_count, comment_count=p.comment_count, view_count=p.view_count,
            tags=[t.name for t in svc.post_tags(db, p.id)] if p.kind == rules.KIND_QUESTION else [],
            workflow_step=p.workflow_step, accepted=p.accepted_at is not None, closed=p.closed_at is not None,
            closed_reason=p.closed_reason, duplicate_of=DuplicateOut(id=p.duplicate_of_id, title=dup_titles[p.duplicate_of_id]) if p.duplicate_of_id in dup_titles else None,
            flag_count=p.flag_count if moderator else 0, my_flag=p.id in flagged_by_me,
            pending_review=p.pending_review, deleted=p.deleted_at is not None, created_at=p.created_at, last_activity_at=p.last_activity_at,
            my_vote=("up" if vote == rules.ACTION_VOTE_UP else "down") if vote else None,
            can_edit=moderator or mine, can_delete=moderator or mine,
            attachments=[AttachmentOut(id=a.id, width=a.width, height=a.height, file_name=a.file_name, approved=a.approved_at is not None) for a in pictures.get(p.id, [])],
        ))
    return out


def _load(db: Session, post_id: UUID, viewer: Optional[User]) -> ForumPost:
    post = svc.get_post(db, post_id, viewer)
    if post is None:
        raise _not_found()
    return post


def _one(db: Session, post: ForumPost, viewer: Optional[User]) -> PostOut:
    db.refresh(post)
    return _serialise(db, [post], viewer)[0]


# ── reading (public) ────────────────────────────────────────────────────────────────────────────────────────────

@router.get("/questions", response_model=QuestionListOut)
def list_questions(
    request: Request,
    sort: str = Query("active", pattern="^(active|newest|votes|unanswered)$"),
    tag: Optional[str] = Query(None, max_length=80),
    q: Optional[str] = Query(None, max_length=200),
    mine: bool = False,
    match: str = Query("all", pattern="^(all|any)$"),
    step: Optional[str] = Query(None, max_length=40, pattern=r"^[a-z][a-z0-9_-]{0,39}$"),
    page: int = Query(1, ge=1, le=10000),
    per_page: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
    viewer: Optional[User] = Depends(get_optional_user),
):
    _read_guard(request, viewer)
    try:
        items, total = svc.list_questions(db, viewer, sort=sort, tag=tag, q=q, mine=mine, workflow_step=step, match=match, limit=per_page, offset=(page - 1) * per_page)
    except ledger.ForumError as exc:
        raise _refuse(exc)
    return QuestionListOut(items=_serialise(db, items, viewer), total=total, page=page, per_page=per_page)


@router.get("/questions/{question_id}", response_model=ThreadOut)
def get_question(request: Request, question_id: UUID, db: Session = Depends(get_db), viewer: Optional[User] = Depends(get_optional_user)):
    _read_guard(request, viewer)
    question = _load(db, question_id, viewer)
    if question.kind != rules.KIND_QUESTION:
        raise _not_found()
    svc.count_view(db, question)
    thread = svc.thread(db, question, viewer)
    db.commit()
    flat = [question] + thread["answers"] + [c for group in thread["comments"].values() for c in group]
    shaped = {p.id: s for p, s in zip(flat, _serialise(db, flat, viewer))}
    return ThreadOut(
        question=shaped[question.id],
        answers=[shaped[a.id] for a in thread["answers"]],
        comments={str(pid): [shaped[c.id] for c in group] for pid, group in thread["comments"].items()},
        related=_serialise(db, svc.related_questions(db, question), viewer),
        following=viewer is not None and notifications.is_subscribed(db, viewer.id, question.id),
    )


class StepCountOut(BaseModel):
    questions: int
    unanswered: int


@router.get("/steps", response_model=dict[str, StepCountOut])
def step_counts(request: Request, db: Session = Depends(get_db), viewer: Optional[User] = Depends(get_optional_user)):
    """Per workflow step, how many readable questions were asked from it (for the "N asked" next to a step's help link)."""
    _read_guard(request, viewer)
    return svc.step_counts(db)


@router.get("/tags", response_model=List[TagOut])
def list_tags(request: Request, q: Optional[str] = Query(None, max_length=40), db: Session = Depends(get_db), viewer: Optional[User] = Depends(get_optional_user)):
    _read_guard(request, viewer)
    return [TagOut(name=t.name, description_md=t.description_md, used_count=t.used_count) for t in svc.tag_list(db, q)]


@router.get("/me", response_model=MeOut)
def me(db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    info = rep_service.privileges(db, user)
    db.commit()
    return MeOut(id=user.id, name=user.full_name, reputation=info["reputation"], is_moderator=info["is_moderator"], thresholds=info["thresholds"],
                 can=info["can"], votes_left_today=info["votes_left_today"])


@router.get("/me/reputation", response_model=List[ReputationEventOut])
def my_reputation(limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0), db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    """How the signed-in member's reputation came about, newest first. Private: the events are not shown to anyone else."""
    return rep_service.history(db, user.id, limit, offset)


@router.get("/users/{user_id}", response_model=ProfileOut)
def member_profile(request: Request, user_id: UUID, db: Session = Depends(get_db), viewer: Optional[User] = Depends(get_optional_user)):
    _read_guard(request, viewer)
    found = rep_service.profile(db, user_id)
    if found is None:
        raise _not_found()
    return found


@router.get("/posts/{post_id}/revisions", response_model=List[RevisionOut])
def post_revisions(request: Request, post_id: UUID, db: Session = Depends(get_db), viewer: Optional[User] = Depends(get_optional_user)):
    """The edit history of a post anyone may read (the same text rules as the post)."""
    _read_guard(request, viewer)
    post = _load(db, post_id, viewer)
    revs = svc.revisions(db, post)
    names = {a: n for a, (n, _r) in svc.authors_by_id(db, {r.author_id for r in revs}).items()}
    return [RevisionOut(revision=r.revision, title=r.title, body_md=r.body_md, body_html=markdown_lite.render(r.body_md), tag_names=r.tag_names,
                        summary=r.summary, author_name=names.get(r.author_id), revised_at=r.revised_at) for r in revs]


# ── writing ─────────────────────────────────────────────────────────────────────────────────────────────────────

@router.post("/questions", response_model=PostOut, status_code=201)
def ask(body: AskIn, background: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    write_limiter.check(user.id)
    try:
        post = svc.create_question(db, user, body.title, body.body, body.tags, body.workflow_step)
        db.commit()
        background.add_task(notifications.send_immediate_job)
    except ledger.ForumError as exc:
        db.rollback()
        raise _refuse(exc)
    return _one(db, post, user)


@router.post("/questions/{question_id}/answers", response_model=PostOut, status_code=201)
def answer(question_id: UUID, body: BodyIn, background: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    write_limiter.check(user.id)
    question = _load(db, question_id, user)
    try:
        post = svc.create_answer(db, user, question, body.body)
        db.commit()
        background.add_task(notifications.send_immediate_job)
    except ledger.ForumError as exc:
        db.rollback()
        raise _refuse(exc)
    return _one(db, post, user)


@router.post("/posts/{post_id}/comments", response_model=PostOut, status_code=201)
def comment(post_id: UUID, body: BodyIn, background: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    write_limiter.check(user.id)
    parent = _load(db, post_id, user)
    try:
        post = svc.create_comment(db, user, parent, body.body)
        db.commit()
        background.add_task(notifications.send_immediate_job)
    except ledger.ForumError as exc:
        db.rollback()
        raise _refuse(exc)
    return _one(db, post, user)


@router.patch("/posts/{post_id}", response_model=PostOut)
def edit(post_id: UUID, body: EditIn, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    write_limiter.check(user.id)
    post = _load(db, post_id, user)
    try:
        svc.edit_post(db, user, post, body=body.body, title=body.title, tags=body.tags, summary=body.summary)
        db.commit()
    except ledger.ForumError as exc:
        db.rollback()
        raise _refuse(exc)
    return _one(db, post, user)


@router.delete("/posts/{post_id}", response_model=PostOut)
def delete(post_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    write_limiter.check(user.id)
    post = _load(db, post_id, user)
    try:
        svc.delete_post(db, user, post)
        db.commit()
    except ledger.ForumError as exc:
        db.rollback()
        raise _refuse(exc)
    return _one(db, post, user)


@router.post("/posts/{post_id}/restore", response_model=PostOut)
def restore(post_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    write_limiter.check(user.id)
    post = _load(db, post_id, user)
    try:
        svc.restore_post(db, user, post)
        db.commit()
    except ledger.ForumError as exc:
        db.rollback()
        raise _refuse(exc)
    return _one(db, post, user)


@router.post("/posts/{post_id}/approve", response_model=PostOut)
def approve(post_id: UUID, background: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    write_limiter.check(user.id)
    post = _load(db, post_id, user)
    try:
        svc.approve_post(db, user, post)
        db.commit()
        background.add_task(notifications.send_immediate_job)
    except ledger.ForumError as exc:
        db.rollback()
        raise _refuse(exc)
    return _one(db, post, user)


@router.post("/posts/{post_id}/vote", response_model=PostOut)
def vote(post_id: UUID, body: VoteIn, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    """Vote up or down, or take the vote back (``none``)."""
    write_limiter.check(user.id)
    post = _load(db, post_id, user)
    try:
        if body.direction == "none":
            for action in db.query(ledger.ForumAction).filter(
                ledger.ForumAction.user_id == user.id, ledger.ForumAction.post_id == post.id, ledger.ForumAction.canceled_at.is_(None),
                ledger.ForumAction.action_type.in_((rules.ACTION_VOTE_UP, rules.ACTION_VOTE_DOWN)),
            ).all():
                ledger.cancel_action(db, action, user.id)
        else:
            ledger.cast_vote(db, user, post, rules.ACTION_VOTE_UP if body.direction == "up" else rules.ACTION_VOTE_DOWN)
        db.commit()
    except ledger.ForumError as exc:
        db.rollback()
        raise _refuse(exc)
    return _one(db, post, user)


@router.post("/answers/{answer_id}/accept", response_model=PostOut)
def accept(answer_id: UUID, background: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    write_limiter.check(user.id)
    post = _load(db, answer_id, user)
    try:
        ledger.accept_answer(db, user, post)
        db.commit()
        background.add_task(notifications.send_immediate_job)
    except ledger.ForumError as exc:
        db.rollback()
        raise _refuse(exc)
    return _one(db, post, user)


@router.post("/posts/{post_id}/flag", response_model=PostOut)
def flag(post_id: UUID, body: FlagIn, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    """Report a post to the moderators. It stays visible until one of them decides."""
    write_limiter.check(user.id)
    post = _load(db, post_id, user)
    try:
        moderation.flag_post(db, user, post, body.reason)
        db.commit()
    except ledger.ForumError as exc:
        db.rollback()
        raise _refuse(exc)
    return _one(db, post, user)


@router.post("/questions/{question_id}/close", response_model=PostOut)
def close_question(question_id: UUID, body: CloseIn, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    write_limiter.check(user.id)
    post = _load(db, question_id, user)
    try:
        moderation.close_question(db, user, post, body.reason, body.duplicate_of)
        db.commit()
    except ledger.ForumError as exc:
        db.rollback()
        raise _refuse(exc)
    return _one(db, post, user)


@router.post("/questions/{question_id}/reopen", response_model=PostOut)
def reopen_question(question_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    write_limiter.check(user.id)
    post = _load(db, question_id, user)
    try:
        moderation.reopen_question(db, user, post)
        db.commit()
    except ledger.ForumError as exc:
        db.rollback()
        raise _refuse(exc)
    return _one(db, post, user)


@router.get("/moderation/flagged", response_model=List[FlaggedOut])
def flagged(db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    """Posts with open flags, most-flagged first."""
    if not ledger.is_moderator(db, user):
        raise _refuse(ledger.ForumPermissionError("moderators only"))
    rows = moderation.flagged(db)
    out = _serialise(db, [p for p, _ in rows], user)
    names = svc.authors_by_id(db, {f.user_id for _, fl in rows for f in fl if f.user_id})
    titles = dict(db.query(ForumPost.id, ForumPost.title).filter(ForumPost.id.in_({p.root_id or p.id for p, _ in rows})).all())
    return [
        FlaggedOut(post=po, question_id=p.root_id or p.id, question_title=titles.get(p.root_id or p.id),
                   flags=[FlagOut(id=f.id, reason=f.reason, by=names[f.user_id][0] if f.user_id in names else None, created_at=f.created_at) for f in fl])
        for po, (p, fl) in zip(out, rows)
    ]


@router.post("/moderation/posts/{post_id}/resolve", response_model=PostOut)
def resolve_flags(post_id: UUID, body: ResolveIn, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    """Settle all open flags on a post: dismiss them, warn the author, or delete the post (the last two cost the author reputation)."""
    write_limiter.check(user.id)
    post = _load(db, post_id, user)
    try:
        moderation.resolve_flags(db, user, post, body.resolution)
        db.commit()
    except ledger.ForumError as exc:
        db.rollback()
        raise _refuse(exc)
    return _one(db, post, user)


def _prefs_out(db: Session, user: User) -> PrefsOut:
    p = notifications.get_prefs(db, user.id)
    return PrefsOut(enabled=p.enabled, on_answer_to_mine=p.on_answer_to_mine, on_comment_reply=p.on_comment_reply, on_accepted=p.on_accepted,
                    on_new_in_watched_tags=p.on_new_in_watched_tags, email_frequency=p.email_frequency, watched_tags=notifications.watched_tags(db, user.id))


@router.get("/me/notifications", response_model=PrefsOut)
def my_notification_settings(db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    out = _prefs_out(db, user)
    db.commit()   # the first read creates the row with the defaults
    return out


@router.put("/me/notifications", response_model=PrefsOut)
def set_notification_settings(body: PrefsIn, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    write_limiter.check(user.id)
    notifications.update_prefs(db, user.id, **body.model_dump())
    out = _prefs_out(db, user)
    db.commit()
    return out


@router.put("/me/tags/{tag_name}", response_model=FollowOut)
def watch_tag(tag_name: str, body: FollowIn, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    """Watch a tag: a new question under it is emailed when the member asked for that."""
    write_limiter.check(user.id)
    if not notifications.set_watched_tag(db, user.id, tag_name, body.following):
        raise HTTPException(status_code=404, detail={"code": "forum.not_found", "message": "No such tag"})
    db.commit()
    return FollowOut(following=body.following)


@router.put("/questions/{question_id}/following", response_model=FollowOut)
def follow_question(question_id: UUID, body: FollowIn, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    """Follow a question to be told about its new answers, or stop."""
    write_limiter.check(user.id)
    question = _load(db, question_id, user)
    if question.kind != rules.KIND_QUESTION:
        raise _not_found()
    if body.following:
        notifications.subscribe(db, user.id, question.id, auto=False)
    else:
        notifications.unsubscribe(db, user.id, question.id)
    db.commit()
    return FollowOut(following=body.following)


@router.get("/moderation/members", response_model=List[MemberOut])
def moderation_members(
    q: Optional[str] = Query(None, max_length=60), moderators_only: bool = False,
    db: Session = Depends(get_db), user: User = Depends(get_current_active_user),
):
    """Super admin only: find members by name or email, or list the current moderators."""
    try:
        rows = moderation.members(db, user, q, moderators_only)
    except ledger.ForumError as exc:
        raise _refuse(exc)
    return [MemberOut(id=u.id, name=u.full_name, email=u.email, is_moderator=m) for u, m in rows]


@router.put("/moderation/moderators/{user_id}", response_model=MemberOut)
def set_moderator(user_id: UUID, body: ModeratorIn, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    """Super admin only: make a member a moderator, or take the role back."""
    write_limiter.check(user.id)
    try:
        target = moderation.set_moderator(db, user, user_id, body.is_moderator)
        db.commit()
    except ledger.ForumError as exc:
        db.rollback()
        raise _refuse(exc)
    return MemberOut(id=target.id, name=target.full_name, email=target.email, is_moderator=body.is_moderator)


@router.get("/moderation/held", response_model=List[PostOut])
def held(db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    """Posts waiting for a moderator."""
    if not ledger.is_moderator(db, user):
        raise _refuse(ledger.ForumPermissionError("moderators only"))
    rows = db.query(ForumPost).filter(ForumPost.pending_review.is_(True), ForumPost.deleted_at.is_(None)).order_by(ForumPost.created_at).limit(100).all()
    return _serialise(db, rows, user)


# ── screenshots ─────────────────────────────────────────────────────────────────────────────────────────────────

@router.post("/posts/{post_id}/attachments", response_model=PostOut, status_code=201)
def add_attachment(post_id: UUID, file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    """A screenshot on your own post: PNG, JPEG or WebP (the bytes are decoded, not the name), re-encoded without its metadata."""
    write_limiter.check(user.id)
    post = _load(db, post_id, user)
    data = file.file.read(rules.FORUM_MAX_UPLOAD_BYTES + 1)
    try:
        att_service.add_attachment(db, user, post, file.filename or "screenshot", data)
        db.commit()
    except ledger.ForumError as exc:
        db.rollback()
        raise _refuse(exc)
    return _one(db, post, user)


def _attachment(db: Session, attachment_id: UUID, viewer: Optional[User]):
    att = db.get(ForumAttachment, attachment_id)
    if att is None:
        raise _not_found()
    post = svc.get_post(db, att.post_id, viewer)
    moderator = viewer is not None and ledger.is_moderator(db, viewer)
    if post is None or not att_service.can_see(att, viewer, moderator):
        raise _not_found()
    return att


@router.get("/attachments/{attachment_id}")
def get_attachment(request: Request, attachment_id: UUID, db: Session = Depends(get_db), viewer: Optional[User] = Depends(get_optional_user)):
    """The picture file. Public once approved (an unapproved one is for its uploader and moderators only)."""
    _read_guard(request, viewer)
    att = _attachment(db, attachment_id, viewer)
    path = att_service.file_path(att)
    if path is None:
        raise _not_found()
    cache = "public, max-age=86400" if att.approved_at is not None else "private, max-age=60"
    return FileResponse(path, media_type=att.content_type, headers={"Cache-Control": cache, "X-Content-Type-Options": "nosniff"})


@router.delete("/attachments/{attachment_id}", response_model=PostOut)
def delete_attachment(attachment_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    write_limiter.check(user.id)
    att = _attachment(db, attachment_id, user)
    post = db.get(ForumPost, att.post_id)
    try:
        att_service.delete_attachment(db, user, att)
        db.commit()
    except ledger.ForumError as exc:
        db.rollback()
        raise _refuse(exc)
    return _one(db, post, user)


@router.post("/attachments/{attachment_id}/approve", response_model=PostOut)
def approve_attachment(attachment_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_active_user)):
    write_limiter.check(user.id)
    att = _attachment(db, attachment_id, user)
    post = db.get(ForumPost, att.post_id)
    try:
        att_service.approve_attachment(db, user, att)
        db.commit()
    except ledger.ForumError as exc:
        db.rollback()
        raise _refuse(exc)
    return _one(db, post, user)


# ── what search engines see (public; nginx maps /forum/q/<id>, /sitemap.xml and /robots.txt here) ──────────────────

@router.get("/pages/q/{question_id}", response_class=HTMLResponse)
def question_page(request: Request, question_id: UUID, db: Session = Depends(get_db)):
    """The question with its text in the HTML, for crawlers and for people (the app starts over it). A held or deleted question is a 404."""
    _read_guard(request, None)
    question = svc.get_post(db, question_id, None)
    if question is None or question.kind != rules.KIND_QUESTION:
        raise _not_found()
    answers = svc.thread(db, question, None)["answers"]
    return HTMLResponse(seo.question_page(db, question, answers), headers={"Cache-Control": "public, max-age=300"})


@router.get("/sitemap.xml")
def sitemap(db: Session = Depends(get_db)):
    return Response(seo.sitemap_xml(db), media_type="application/xml", headers={"Cache-Control": "public, max-age=3600"})


@router.get("/robots.txt")
def robots():
    return Response(seo.robots_txt(), media_type="text/plain", headers={"Cache-Control": "public, max-age=3600"})
