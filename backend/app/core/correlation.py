"""Carry the correlation ID from the request into every log line (H3.9 · S2-30).

`middleware/correlation.py` has claimed since it was written that the ID is
"available in logging via LogRecord.correlation_id", and `logging_config.py`
was built to consume it::

    if hasattr(record, "correlation_id"):
        log_entry["correlation_id"] = record.correlation_id

Nothing ever set it. A repository-wide search for `ContextVar`, `logging.Filter`,
`addFilter` and `setLogRecordFactory` returned zero results, so that `hasattr`
was false on every record ever emitted. The middleware set
`request.state.correlation_id` and echoed a response header -- that was all.
The one feature built to make production incidents diagnosable was inert: a
support engineer holding an `X-Correlation-ID` from a user's failed request
could not find a single log line for it.

This matters more now than when it was found. H3.4 added roughly 182 log lines
describing exactly which record was dropped and what is therefore wrong with
the numbers -- and without a correlation ID, not one of them can be tied back
to the request that produced it.

Why a record factory and not the filter the report suggests
-----------------------------------------------------------
The report says "install a `logging.Filter` on the root handler". A filter
attached to one handler only stamps records that reach **that** handler, which
leaves three gaps: Sentry's handler and uvicorn's see unstamped records; a
handler added later gets nothing; and the text formatter's `%(correlation_id)s`
raises on any record that skipped the filter. Setting the record factory stamps
every record at creation, before any handler is consulted, so the attribute is
guaranteed present -- which is what lets the plain-text format include it at
all.

The previous factory is always called first, so this composes with anything
else that has installed one rather than silently replacing it.
"""

from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar, Token

# The placeholder for a log line with no request behind it -- startup, an arq
# job, a management script. A literal "-" rather than None or an empty string,
# so a log search for a real ID cannot accidentally match it and so the text
# format stays aligned.
NO_CORRELATION_ID = "-"

_correlation_id: ContextVar[str] = ContextVar(
    "correlation_id", default=NO_CORRELATION_ID
)


def get_correlation_id() -> str:
    """The current request's ID, or `NO_CORRELATION_ID` outside a request."""
    return _correlation_id.get()


def set_correlation_id(value: str) -> Token:
    """Bind an ID to this context. Pass the token to `reset_correlation_id`.

    Public because a background job is worth correlating too: an arq task can
    bind the ID of the request that enqueued it and have its own log lines join
    the same trace.
    """
    return _correlation_id.set(value)


def reset_correlation_id(token: Token) -> None:
    """Unbind, restoring whatever was in scope before.

    Resetting by token rather than setting back to the placeholder: contexts
    nest, and clobbering the value would break an outer scope that had its own.
    """
    _correlation_id.reset(token)


def new_correlation_id() -> str:
    return str(uuid.uuid4())


def install_log_record_factory() -> None:
    """Stamp `correlation_id` onto every LogRecord at creation.

    Idempotent: `configure_logging()` runs at import and a test may call it
    again, and chaining a factory onto itself would recurse until the stack
    gave out -- during logging, which is the worst place to lose a stack.
    """
    current = logging.getLogRecordFactory()
    if getattr(current, "_stamps_correlation_id", False):
        return

    def factory(*args, **kwargs) -> logging.LogRecord:
        record = current(*args, **kwargs)
        # `hasattr` rather than an unconditional set, so a factory installed
        # ahead of this one keeps whatever it decided.
        #
        # Note what this makes impossible: `logger.info(msg, extra={
        # "correlation_id": x})` now raises KeyError("Attempt to overwrite
        # 'correlation_id' in LogRecord") from `Logger.makeRecord`, because the
        # stdlib refuses to let `extra` shadow an attribute the record already
        # carries. No code in this repository does that -- it was checked -- and
        # the supported way to log under a different ID is
        # `set_correlation_id()`, which covers every line in scope instead of
        # one call. `tests/test_correlation_id.py` pins the behaviour so the
        # next person to try it learns from a test rather than from production.
        if not hasattr(record, "correlation_id"):
            record.correlation_id = _correlation_id.get()
        return record

    factory._stamps_correlation_id = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(factory)
