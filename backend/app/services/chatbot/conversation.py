"""One question in, one answer out (CHATBOT_PLAN C1): the help assistant. Its only tool is ``search_help``; it reads no forest data.

Order of work: input limits -> history -> for each provider call reserve tokens (access, kill switch and cap are checked there) -> tool loop
-> settle -> store both messages. If a provider fails the next configured one is tried; a spent cap or lost access is never retried.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.chat import ChatMessage as ChatMessageRow
from app.models.user import User
from app.services.chatbot import guard, help_search, leak, usage
from app.services.chatbot.prompt import build_system_prompt
from app.services.chatbot.providers import ChatMessage, ChatProvider, ProviderError, ToolSpec

logger = logging.getLogger(__name__)

MAX_QUESTION_CHARS = 2000
MAX_OUTPUT_TOKENS = 1500           # D10
HISTORY_CHAR_BUDGET = 24_000       # about 8,000 tokens (D10), counted in characters because the tokenizer differs by provider
MAX_ROUNDS = 3

SEARCH_HELP = ToolSpec(
    "search_help",
    "Search the help text, rules and forum answers. Use for how-to and rule questions.",
    {"type": "object", "properties": {"query": {"type": "string"}}},
)


class ChatError(Exception):
    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code, self.status = code, status


@dataclass
class Turn:
    session_id: uuid.UUID
    message_id: uuid.UUID
    reply: str
    sources: List[str] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0


def _history(db: Session, user: User, session_id: uuid.UUID) -> List[ChatMessage]:
    """The latest turns of this session that fit the budget, oldest first. A purged message (content null) is skipped."""
    rows = (
        db.query(ChatMessageRow)
        .filter(ChatMessageRow.user_id == user.id, ChatMessageRow.session_id == session_id, ChatMessageRow.role.in_(("user", "assistant")),
                ChatMessageRow.content.isnot(None))
        .order_by(ChatMessageRow.created_at.desc())
        .limit(40)
        .all()
    )
    kept, used = [], 0
    for r in rows:
        used += len(r.content)
        if used > HISTORY_CHAR_BUDGET:
            break
        kept.append(ChatMessage(r.role, r.content))
    return list(reversed(kept))


def _passages(db: Session, query: str, question: str, step: Optional[str]):
    """(what the model is shown, the titles used as sources). Passages are reference text, not instructions: forum answers are written by
    users, so they are screened in the search and framed as data here (guard.py)."""
    hits = help_search.search(db, query or question, limit=3, step=step)
    if not hits:
        return {"note": "no relevant help found"}, []
    return {"reference": guard.frame({"title": h.title, "text": h.text} for h in hits)}, [h.title for h in hits]


async def _one_provider(db: Session, user: User, provider: ChatProvider, messages: List[ChatMessage], question: str, step: Optional[str]):
    tin = tout = 0
    sources: List[str] = []
    for _ in range(MAX_ROUNDS):
        reply = await usage.with_reservation(
            db, user, usage.estimate_reservation(messages, MAX_OUTPUT_TOKENS),
            lambda: provider.chat(messages, [SEARCH_HELP], max_tokens=MAX_OUTPUT_TOKENS, temperature=0.2),
        )
        tin += reply.usage.input_tokens
        tout += reply.usage.output_tokens
        if not reply.tool_calls:
            return reply.text, sources, tin, tout
        messages.append(ChatMessage("assistant", reply.text, tool_calls=reply.tool_calls))
        for call in reply.tool_calls:
            if call.name == "search_help":
                result, titles = _passages(db, str(call.arguments.get("query") or ""), question, step)
                sources += [t for t in titles if t not in sources]
            else:
                result = {"error": "unknown_tool"}
            result = leak.filter_tool_result(call.name, result)
            messages.append(ChatMessage("tool", json.dumps(result, ensure_ascii=False), tool_call_id=call.id, name=call.name))
    return "", sources, tin, tout


async def answer(
    db: Session, user: User, question: str, providers: List[ChatProvider], *,
    session_id: Optional[uuid.UUID] = None, step: Optional[str] = None, read_only: bool = False,
) -> Turn:
    question = (question or "").strip()
    if not question:
        raise ChatError("chat.empty", "Type a question first.", 422)
    if len(question) > MAX_QUESTION_CHARS:
        raise ChatError("chat.too_long", f"Please keep the question under {MAX_QUESTION_CHARS} characters.", 422)
    kind = leak.private_data_in(question)
    if kind:
        # refused before any model sees it, before anything is stored or charged; the reply never repeats the data
        raise ChatError("chat.private_data", f"Your message looks like it contains a {kind}. Household and location details must not be sent to "
                        "the assistant. Remove it and ask again; to change household data use the Household page.", 422)
    if not providers:
        raise ChatError("chat.no_provider", "The assistant is not set up yet.", 503)

    session_id = session_id or uuid.uuid4()
    history = _history(db, user, session_id)
    last_error: Optional[ProviderError] = None
    for provider in providers:
        messages = [ChatMessage("system", build_system_prompt(question, step=step, read_only=read_only)), *history,
                    ChatMessage("user", question)]
        try:
            text, sources, tin, tout = await _one_provider(db, user, provider, messages, question, step)
        except ProviderError as exc:
            logger.warning("chat provider %s failed (%s); trying the next", provider.name, exc.kind)
            last_error = exc
            continue
        text = leak.redact(text)
        if not text.strip():
            last_error = ProviderError("empty reply", "format")
            continue
        # one transaction gives both rows the same now(); explicit times keep the order of the conversation
        asked = datetime.now(timezone.utc)
        db.add(ChatMessageRow(user_id=user.id, session_id=session_id, role="user", content=question, created_at=asked))
        row = ChatMessageRow(user_id=user.id, session_id=session_id, role="assistant", content=text, provider=provider.name,
                             created_at=asked + timedelta(milliseconds=1),
                             model=provider.model, tokens_in=tin, tokens_out=tout, tool_names=["search_help"] if sources else [])
        db.add(row)
        db.commit()
        return Turn(session_id, row.id, text, sources, provider.name, provider.model, tin, tout)
    detail = last_error.kind if last_error else "unknown"
    raise ChatError("chat.provider_unavailable", f"The assistant could not answer just now ({detail}). Please try again soon.", 503)
