"""Database concurrency utilities for dimension changes."""
import logging
from contextlib import asynccontextmanager, contextmanager
from typing import Optional, Generator, AsyncGenerator
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError

logger = logging.getLogger(__name__)

# Lock namespace — prevents collision with other advisory lock users
_LOCK_NAMESPACE = 0xCFDB  # "cf_db" hex


def _lock_id(resource_type: str, resource_id: int) -> int:
    """Compute a 64-bit advisory lock ID from namespace + type hash + id."""
    type_hash = hash(resource_type) & 0x7FFFFFFF
    return (_LOCK_NAMESPACE << 48) | (type_hash << 16) | (resource_id & 0xFFFF)


_RETRYABLE_MSGS = [
    'could not obtain lock',
    'deadlock detected',
    'lock timeout',
]


def _is_retryable(err: OperationalError) -> bool:
    msg = str(err.orig).lower() if err.orig else ''
    return any(m in msg for m in _RETRYABLE_MSGS)


@contextmanager
def advisory_lock(
    db: Session,
    resource_type: str,
    resource_id: int,
    retries: int = 3,
    delay_ms: int = 200,
) -> Generator[bool, None, None]:
    """PostgreSQL advisory transaction-level lock with retry.

    Acquires pg_advisory_xact_lock(lock_id) which auto-releases on
    transaction commit/rollback. Retries on retryable failures.

    Usage:
        with advisory_lock(db, 'forest', forest_id):
            # critical section
            db.commit()

    Args:
        db: SQLAlchemy Session.
        resource_type: Logical resource name (e.g. 'forest', 'calculation').
        resource_id: Numeric ID of the resource.
        retries: Number of retry attempts (default 3).
        delay_ms: Delay between retries in ms (default 200).

    Yields:
        True if lock acquired.
    """
    lock_id = _lock_id(resource_type, resource_id)
    last_exc = None
    for attempt in range(retries + 1):
        try:
            db.execute(text(f"SELECT pg_advisory_xact_lock({lock_id})"))
            yield True
            return
        except OperationalError as e:
            if _is_retryable(e) and attempt < retries:
                logger.warning(
                    "Lock retry %d/%d for %s/%s (id=%d): %s",
                    attempt + 1, retries, resource_type, resource_id, lock_id, e,
                )
                import time
                time.sleep(delay_ms / 1000.0)
                last_exc = e
                continue
            raise
    raise last_exc or RuntimeError("Lock acquisition failed — no exception recorded")


@contextmanager
def atomic_transaction(
    db: Session,
    description: str = "",
) -> Generator[Session, None, None]:
    """Atomic transaction context manager — commit on success, rollback on error.

    Usage:
        with atomic_transaction(db, "import layer") as session:
            session.add(layer)
            session.add(audit_entry)

    On success → db.commit() is called.
    On any exception → db.rollback() is called and the exception is re-raised.
    """
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Transaction rolled back: %s", description or "unknown")
        raise


@asynccontextmanager
async def advisory_lock_async(
    db: Session,
    resource_type: str,
    resource_id: int,
    retries: int = 3,
    delay_ms: int = 200,
) -> AsyncGenerator[bool, None]:
    """Async version of advisory_lock."""
    lock_id = _lock_id(resource_type, resource_id)
    last_exc = None
    for attempt in range(retries + 1):
        try:
            db.execute(text(f"SELECT pg_advisory_xact_lock({lock_id})"))
            yield True
            return
        except OperationalError as e:
            if _is_retryable(e) and attempt < retries:
                logger.warning(
                    "Lock retry %d/%d for %s/%s (id=%d): %s",
                    attempt + 1, retries, resource_type, resource_id, lock_id, e,
                )
                import asyncio
                await asyncio.sleep(delay_ms / 1000.0)
                last_exc = e
                continue
            raise
    raise last_exc or RuntimeError("Lock acquisition failed — no exception recorded")


@asynccontextmanager
async def atomic_transaction_async(
    db: Session,
    description: str = "",
) -> AsyncGenerator[Session, None]:
    """Async atomic transaction context manager."""
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Transaction rolled back: %s", description or "unknown")
        raise
