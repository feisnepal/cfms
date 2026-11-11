"""Single source for the arq / report-path Redis DSN.

Before this, the DSN was written out four times — `app/worker.py`,
`app/api/reports.py`, `app/services/report/job_store.py` and (correctly)
`app/calculation_worker.py` — and two of them hardcoded
``redis://localhost:6379/0``, ignoring ``settings.REDIS_URL``. In Compose or
any multi-host deployment the report worker then could not reach Redis, and
the API-side enqueue fell back to running generation inline on the request
thread — silently (S3-34 / hardening 3.13).

Every caller now goes through :func:`redis_dsn`. :func:`redacted` renders a
DSN for logs with any password removed.
"""

from urllib.parse import urlsplit, urlunsplit

from app.core.config import settings

DEFAULT_REDIS_DSN = "redis://localhost:6379/0"


def redis_dsn() -> str:
    """Return the configured Redis DSN, or the localhost default when unset."""
    return (settings.REDIS_URL or "").strip() or DEFAULT_REDIS_DSN


def redacted(dsn: str) -> str:
    """Return ``dsn`` with any password replaced by ``***`` — safe to log."""
    parts = urlsplit(dsn)
    if not parts.password:
        return dsn
    host = parts.hostname or ""
    if parts.username:
        userinfo = f"{parts.username}:***"
    else:
        userinfo = ":***"
    netloc = f"{userinfo}@{host}"
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit(parts._replace(netloc=netloc))
