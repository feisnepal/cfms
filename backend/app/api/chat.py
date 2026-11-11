"""Assistant access API (CHATBOT_PLAN C1.2). Every route needs a signed-in user; there is no anonymous use (D3).

Members ask for access and see how much of today is left; a super admin approves, revokes and sets caps. Changes are set-to-a-value
operations, so repeating one changes nothing (the module is listed as exempt from the replay guard in check_idempotency_coverage.py).
"""
import asyncio
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.middleware.rate_limit import WorkspaceRateLimiter
from app.models.user import User
from app.models.chat import ChatMessage as ChatMessageRow
from app.services.chatbot import access, conversation, usage
from app.services.chatbot.providers import configured_providers
from app.utils.auth import get_current_active_user

router = APIRouter()

#: asking for access, or opening the admin screen, is a human action; a loop is a bug or abuse
request_limiter = WorkspaceRateLimiter(max_requests=10, window_seconds=60, name="chat_access_request")


class StateOut(BaseModel):
    state: str
    allowed: bool
    daily_cap_tokens: int
    tokens_used_today: int
    tokens_left_today: int
    approx_questions_left: int
    expires_at: Optional[datetime]
    read_only: bool


class MessageIn(BaseModel):
    message: str = Field(max_length=4000)
    session_id: Optional[UUID] = None
    step: Optional[str] = Field(default=None, max_length=40)


class MessageOut(BaseModel):
    session_id: UUID
    message_id: UUID
    reply: str
    sources: List[str]
    state: StateOut


class FeedbackIn(BaseModel):
    value: int = Field(ge=-1, le=1)


class RequestIn(BaseModel):
    note: Optional[str] = Field(default=None, max_length=500)


class ApproveIn(BaseModel):
    daily_cap_tokens: Optional[int] = Field(default=None, ge=0)
    expires_at: Optional[datetime] = None


class CapIn(BaseModel):
    daily_cap_tokens: int = Field(ge=0)


class AccessRowOut(BaseModel):
    user_id: UUID
    email: str
    full_name: Optional[str]
    role: str
    status: str
    daily_cap_tokens: int
    requested_at: datetime
    request_note: Optional[str]
    approved_at: Optional[datetime]
    expires_at: Optional[datetime]
    tokens_used_today: int = 0
    messages_today: int = 0
    thumbs_down_30d: int = 0


class SettingsIn(BaseModel):
    enabled: bool
    pool_daily_tokens: Optional[int] = Field(default=None, ge=0)


class SettingsOut(BaseModel):
    enabled: bool
    pool_daily_tokens: Optional[int]
    pool_used_today: int


def _refuse(exc: access.AccessError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail={"code": exc.code, "message": str(exc)})


def _state_out(state: access.AccessState) -> StateOut:
    return StateOut(**state.__dict__)


@router.get("/access/me", response_model=StateOut)
def my_access(user: User = Depends(get_current_active_user), db: Session = Depends(get_db)):
    return _state_out(access.get_state(db, user))


@router.post("/access/request", response_model=StateOut)
def ask_for_access(body: RequestIn, user: User = Depends(get_current_active_user), db: Session = Depends(get_db)):
    request_limiter.check(str(user.id))
    try:
        return _state_out(access.request_access(db, user, body.note))
    except access.AccessError as exc:
        raise _refuse(exc)


@router.get("/admin/access", response_model=List[AccessRowOut])
def list_access(status: Optional[str] = Query(default=None), user: User = Depends(get_current_active_user), db: Session = Depends(get_db)):
    try:
        rows = access.list_access(db, user, status)
        use = access.usage_by_user(db, user)
    except access.AccessError as exc:
        raise _refuse(exc)
    return [
        AccessRowOut(
            user_id=a.user_id, email=u.email, full_name=u.full_name, role=u.role.value, status=a.status,
            daily_cap_tokens=a.daily_cap_tokens, requested_at=a.requested_at, request_note=a.request_note,
            approved_at=a.approved_at, expires_at=a.expires_at,
            **dict(zip(("tokens_used_today", "messages_today", "thumbs_down_30d"), use.get(a.user_id, (0, 0, 0)))),
        )
        for a, u in rows
    ]


@router.post("/admin/access/{user_id}/approve", response_model=StateOut)
def approve(user_id: UUID, body: ApproveIn, user: User = Depends(get_current_active_user), db: Session = Depends(get_db)):
    try:
        access.approve(db, user, user_id, body.daily_cap_tokens, body.expires_at)
    except access.AccessError as exc:
        raise _refuse(exc)
    return _state_out(access.get_state(db, db.get(User, user_id)))


@router.post("/admin/access/{user_id}/revoke", response_model=StateOut)
def revoke(user_id: UUID, user: User = Depends(get_current_active_user), db: Session = Depends(get_db)):
    try:
        access.revoke(db, user, user_id)
    except access.AccessError as exc:
        raise _refuse(exc)
    return _state_out(access.get_state(db, db.get(User, user_id)))


@router.put("/admin/access/{user_id}/cap", response_model=StateOut)
def set_cap(user_id: UUID, body: CapIn, user: User = Depends(get_current_active_user), db: Session = Depends(get_db)):
    try:
        access.set_cap(db, user, user_id, body.daily_cap_tokens)
    except access.AccessError as exc:
        raise _refuse(exc)
    return _state_out(access.get_state(db, db.get(User, user_id)))


#: ten questions a minute per person (D10)
message_limiter = WorkspaceRateLimiter(max_requests=10, window_seconds=60, name="chat_message")


# A plain ``def``: FastAPI runs it in a worker thread, so the database calls never block the event loop, and the provider call is awaited in
# a loop of its own. (Token streaming, R4, is not built: the providers return whole replies.)
@router.post("/messages", response_model=MessageOut)
def send_message(body: MessageIn, user: User = Depends(get_current_active_user), db: Session = Depends(get_db)):
    message_limiter.check(str(user.id))
    state = access.get_state(db, user)
    try:
        turn = asyncio.run(conversation.answer(db, user, body.message, configured_providers(), session_id=body.session_id,
                                               step=body.step, read_only=state.read_only))
    except access.AccessError as exc:
        raise _refuse(exc)
    except usage.CapExceeded as exc:
        raise HTTPException(status_code=429, detail={"code": exc.code, "message": str(exc), "tokens_left": exc.tokens_left,
                                                     "resets_at": exc.resets_at.isoformat()})
    except conversation.ChatError as exc:
        raise HTTPException(status_code=exc.status, detail={"code": exc.code, "message": str(exc)})
    return MessageOut(session_id=turn.session_id, message_id=turn.message_id, reply=turn.reply, sources=turn.sources,
                      state=_state_out(access.get_state(db, user)))


@router.put("/messages/{message_id}/feedback", status_code=204)
def give_feedback(message_id: UUID, body: FeedbackIn, user: User = Depends(get_current_active_user), db: Session = Depends(get_db)):
    """Thumbs up (1), thumbs down (-1) or clear (0) on one of the caller's own assistant answers."""
    row = db.get(ChatMessageRow, message_id)
    if row is None or row.user_id != user.id or row.role != "assistant":
        raise HTTPException(status_code=404, detail={"code": "chat.not_found", "message": "No such answer."})
    row.feedback = body.value or None
    db.commit()


@router.get("/admin/settings", response_model=SettingsOut)
def get_settings(user: User = Depends(get_current_active_user), db: Session = Depends(get_db)):
    try:
        return SettingsOut(**access.get_settings(db, user))
    except access.AccessError as exc:
        raise _refuse(exc)


@router.put("/admin/settings", response_model=SettingsOut)
def put_settings(body: SettingsIn, user: User = Depends(get_current_active_user), db: Session = Depends(get_db)):
    """The kill switch (``enabled``) and the ceiling shared by every user. Set-to-a-value, so repeating it changes nothing."""
    try:
        return SettingsOut(**access.set_settings(db, user, body.enabled, body.pool_daily_tokens))
    except access.AccessError as exc:
        raise _refuse(exc)
