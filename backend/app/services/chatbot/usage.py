"""Daily token cap with reserve-then-settle (CHATBOT_PLAN C1.3; R2, R3, D10).

Before a provider call the caller reserves an estimate of the most the call can use. The reservation is a single conditional UPDATE, so two
requests at once can never both fit into the room for one. When the call ends the hold is replaced by the real figures; a failed call
releases it and costs nothing. A shared daily ceiling for all users (``chat_settings.pool_daily_tokens``) guards a provider with one pool.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Awaitable, Callable, List, Optional, TypeVar

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.chat import ChatSettings, ChatUsage
from app.models.user import User
from app.services.chatbot import access
from app.services.chatbot.providers import ChatMessage, Usage
from app.services.chatbot.providers.base import estimate_tokens

logger = logging.getLogger(__name__)

T = TypeVar("T")

CODE_USER_CAP = "chat.cap_reached"
CODE_POOL = "chat.pool_reached"


class CapExceeded(Exception):
    """Nothing is left to spend. Carries what the screen needs: which cap, how much is left, when it resets."""

    def __init__(self, code: str, message: str, tokens_left: int, resets_at: datetime):
        super().__init__(message)
        self.code = code
        self.tokens_left = tokens_left
        self.resets_at = resets_at


@dataclass(frozen=True)
class Reservation:
    user_id: object
    day: date
    amount: int


def next_reset(day: date) -> datetime:
    """The next midnight in Nepal after ``day`` (when that day's counters stop applying), as an aware datetime."""
    return datetime.combine(day + timedelta(days=1), time.min, tzinfo=access.NEPAL)


def estimate_reservation(messages: List[ChatMessage], max_tokens: int, tools_chars: int = 0) -> int:
    """The most one call can use: the prompt (a character-count guess, high for Devanagari) plus the reply limit."""
    prompt = estimate_tokens("".join(m.content for m in messages)) + estimate_tokens("x" * tools_chars)
    return prompt + max_tokens


def reserve(db: Session, user: User, amount: int, now: Optional[datetime] = None) -> Reservation:
    """Hold ``amount`` tokens of today's room for one call, or raise ``CapExceeded`` / ``access.AccessError``."""
    if amount <= 0:
        raise ValueError("a reservation must be positive")
    now = now or datetime.now(timezone.utc)
    state = access.get_state(db, user, now)
    if not state.allowed:
        raise access.AccessError(f"chat.{state.state}", f"The assistant is not available to this account ({state.state}).", 403)
    day = access.nepal_today(now)
    reset = next_reset(day)

    settings = db.get(ChatSettings, 1)
    pool = settings.pool_daily_tokens if settings is not None else None
    if pool is not None:
        # one writer at a time per day while a shared ceiling is set, so two users cannot both take the last of the pool
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"chat_pool:{day.isoformat()}"})
        spent = db.execute(
            text("SELECT COALESCE(SUM(tokens_in + tokens_out + reserved), 0) FROM chat_usage WHERE day = :d"), {"d": day}
        ).scalar_one()
        if spent + amount > pool:
            db.rollback()
            raise CapExceeded(CODE_POOL, "The assistant has reached today's shared limit. It will be available again after midnight (Nepal time).",
                              max(0, pool - spent), reset)

    db.execute(pg_insert(ChatUsage).values(user_id=user.id, day=day).on_conflict_do_nothing(index_elements=["user_id", "day"]))
    held = db.execute(
        text(
            "UPDATE chat_usage SET reserved = reserved + :amt, messages = messages + 1, updated_at = now() "
            "WHERE user_id = :u AND day = :d AND tokens_in + tokens_out + reserved + :amt <= :cap"
        ),
        {"amt": amount, "u": user.id, "d": day, "cap": state.daily_cap_tokens},
    ).rowcount
    if held == 0:
        left = db.execute(
            text("SELECT GREATEST(:cap - (tokens_in + tokens_out + reserved), 0) FROM chat_usage WHERE user_id = :u AND day = :d"),
            {"cap": state.daily_cap_tokens, "u": user.id, "d": day},
        ).scalar_one()
        db.rollback()
        raise CapExceeded(CODE_USER_CAP, "You have used today's limit. It resets at midnight (Nepal time); exports and uploads still work.",
                          int(left), reset)
    db.commit()
    return Reservation(user.id, day, amount)


def settle(db: Session, reservation: Reservation, usage: Optional[Usage]) -> None:
    """Replace the hold with what the call really used. ``None`` (the call failed) releases it and charges nothing."""
    tokens_in = usage.input_tokens if usage else 0
    tokens_out = usage.output_tokens if usage else 0
    db.execute(
        text(
            "UPDATE chat_usage SET reserved = GREATEST(reserved - :amt, 0), tokens_in = tokens_in + :tin, tokens_out = tokens_out + :tout, "
            "updated_at = now() WHERE user_id = :u AND day = :d"
        ),
        {"amt": reservation.amount, "tin": tokens_in, "tout": tokens_out, "u": reservation.user_id, "d": reservation.day},
    )
    db.commit()


async def with_reservation(
    db: Session, user: User, amount: int, call: Callable[[], Awaitable[T]], now: Optional[datetime] = None,
    usage_of: Callable[[T], Optional[Usage]] = lambda reply: getattr(reply, "usage", None),
) -> T:
    """Reserve, await the provider call, settle with its real usage; release the hold if it raised or was cancelled."""
    reservation = reserve(db, user, amount, now)
    try:
        result = await call()
    except BaseException:
        settle(db, reservation, None)
        raise
    settle(db, reservation, usage_of(result))
    return result
