"""
Logging configuration — structured JSON or text format, with correlation_id support.
"""
import logging
import json
import sys
from typing import Any

from .config import settings
from .correlation import install_log_record_factory


class StructuredFormatter(logging.Formatter):
    """JSON-structured log formatter for production. Includes correlation_id if set.

    Any extra kwargs passed to the log call (e.g. logger.info("digitize_action",
    extra={"calculation_id": ..., "layer_id": ...})) are merged into the JSON
    payload so structured queries can filter on them (Gap 7.3 / Task 1.4.4).
    """

    # Attributes injected onto the LogRecord by logging itself — never treat as extras
    _RESERVED = {
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
        "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
        "created", "msecs", "relativeCreated", "thread", "threadName",
        "processName", "process", "taskName", "message",
    }

    def formatTime(self, record: logging.LogRecord, datefmt=None) -> str:
        # Override to emit milliseconds without relying on an invalid strftime
        # directive ("%03d"). Produces ISO-8601 with .mmmZ consistently.
        import time
        from datetime import datetime, timezone

        ts = record.created
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{int(record.msecs):03d}Z"

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # H3.9 / S2-30: this `hasattr` was false on EVERY record ever emitted.
        # The middleware set `request.state.correlation_id` and nothing put it
        # on a LogRecord, so the field this branch exists to write never
        # appeared once. `install_log_record_factory()` below is what makes it
        # true; the guard stays because a record can still be constructed
        # before the factory is installed (very early import-time logging).
        if hasattr(record, "correlation_id"):
            log_entry["correlation_id"] = record.correlation_id
        for key, value in record.__dict__.items():
            if key not in self._RESERVED and not key.startswith("_"):
                log_entry[key] = value
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, default=str)


def configure_logging() -> None:
    """Configure the root logger: format from LOG_FORMAT, level from DEBUG.

    The only logging configuration in the application. There used to be a
    second, `observability.configure_logging()`, called from `lifespan`. It
    could never run: this one is invoked at import time (`main.py`), so by the
    time `lifespan` starts the root logger already has a handler and that
    function's `if root.handlers: return` guard returned immediately, every
    time. It was deleted in H3.10 rather than left as a plausible-looking
    alternative for the next reader to "fix" by calling it earlier.
    """
    # Before the formatter is chosen: the text format below REFERENCES
    # `correlation_id`, so the factory that guarantees it must already be in
    # place or the first log line raises.
    install_log_record_factory()

    fmt = settings.LOG_FORMAT
    if fmt == "json":
        formatter = StructuredFormatter()
    else:
        # The correlation ID belongs in the text format too, not only in JSON.
        # A developer reading the console is the person most likely to be
        # holding an ID from a failing request, and `%(correlation_id)s` is
        # safe here only because the record factory guarantees the attribute
        # on every record -- a formatter referencing a missing field raises
        # inside logging itself.
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] [%(correlation_id)s] %(name)s: "
            "%(message)s (%(filename)s:%(lineno)d)"
        )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    # H3.10 / S2-31: the level follows DEBUG. This was hardcoded to INFO, so
    # `DEBUG=True` never actually raised log verbosity — the one setting whose
    # entire purpose is to do that. The DEBUG-aware branch existed only in
    # `observability.configure_logging()`, which never ran (see below).
    root.setLevel(logging.DEBUG if settings.DEBUG else logging.INFO)
    root.handlers.clear()
    root.addHandler(handler)

    # FastAPI access logs at WARNING to reduce noise
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
