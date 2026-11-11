"""
Database connection and session management
"""
import logging
from typing import Iterator, Dict, Any
from sqlalchemy import create_engine, event, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool
from .config import settings

logger = logging.getLogger(__name__)


# Create database engine with connection pooling
engine = create_engine(
    settings.DATABASE_URL,
    poolclass=QueuePool,
    pool_size=settings.DB_POOL_SIZE,  # Now 20
    max_overflow=settings.DB_MAX_OVERFLOW,  # Now 30
    pool_pre_ping=True,  # Verify connections before use (keep — local PG safe)
    pool_recycle=settings.DB_POOL_RECYCLE,  # Recycle after 1 hour
    pool_timeout=settings.DB_POOL_TIMEOUT,  # 30 second timeout
    pool_use_lifo=True,  # Reuse idle connections first (less churn)
    echo=settings.DEBUG,  # SQL logging only when DEBUG enabled (prod stays quiet)
    connect_args={
        "connect_timeout": 10,  # PostgreSQL connection timeout
        "options": "-c statement_timeout=60000"  # 60 second query timeout
    }
)


def init_extensions() -> None:
    """Run DDL extensions ONCE at application startup (not per-connection).

    Previously this ran on every new DB connection via a connect event
    listener, adding DDL overhead to each checkout (Performance 2.4).
    """
    with engine.connect() as conn:
        try:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis_raster"))
            conn.commit()
            logger.info("PostGIS extensions initialized")
        except Exception as e:
            logger.warning(f"PostGIS extension init skipped: {e}")


# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create declarative base for models
Base = declarative_base()


# Dependency for FastAPI endpoints
def get_db() -> Iterator[Session]:
    """
    Get database session for dependency injection
    Usage: db: Session = Depends(get_db)
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_db_connection() -> bool:
    """Check if database connection is working"""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.error("Database connection failed: %s", e)
        return False


def read_alembic_revision() -> str | None:
    """Return the current schema migration revision, or None if unavailable.

    `/health` reports it so deploy R-3's `--expect-revision` gate can assert
    that the running stack is on the schema the deploy just applied.
    """
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT version_num FROM alembic_version LIMIT 1")
            ).first()
            return row[0] if row else None
    except Exception as e:  # table absent on a fresh DB, or DB down
        logger.warning("Could not read alembic revision: %s", e)
        return None


# H1.1 / S1-25: the supported stack. Dev, CI and Compose must agree; when they
# did not, "the tests pass" had no single truth value — the suite was green on
# PostgreSQL 15 in CI and red on 18 locally.
SUPPORTED_PG_MAJOR = 16
SUPPORTED_PYTHON = (3, 11)


def log_runtime_versions() -> None:
    """Log the Python and PostgreSQL versions in use, warning on a mismatch.

    A version mismatch used to be invisible until it produced a confusing test
    failure. Stating it at startup makes it a two-second diagnosis instead.
    Warns rather than refuses: an operator on a near-miss version should be told,
    not blocked.
    """
    import sys

    py = sys.version_info
    logger.info("Python %d.%d.%d", py.major, py.minor, py.micro)
    if (py.major, py.minor) != SUPPORTED_PYTHON:
        logger.warning(
            "Python %d.%d is not the supported version (%d.%d) — see .python-version",
            py.major, py.minor, *SUPPORTED_PYTHON,
        )

    try:
        with engine.connect() as conn:
            raw = conn.execute(text("SHOW server_version")).scalar()
            postgis = conn.execute(text("SELECT extversion FROM pg_extension WHERE extname='postgis'")).scalar()
    except Exception as e:  # pragma: no cover — connectivity is reported separately
        logger.warning("Could not read database version: %s", e)
        return

    logger.info("PostgreSQL %s / PostGIS %s", raw, postgis or "not installed")
    major = int(str(raw).split(".")[0])
    if major != SUPPORTED_PG_MAJOR:
        logger.warning(
            "PostgreSQL %s is not the supported major (%d). Dev, CI and Compose are "
            "expected to agree; a mismatch has previously produced test results that "
            "differed by machine.",
            raw, SUPPORTED_PG_MAJOR,
        )


def get_db_pool_status() -> Dict[str, Any]:
    """Get current connection pool status"""
    pool = engine.pool  # QueuePool at runtime
    return {
        "pool_size": pool.size(),  # type: ignore[attr-defined]
        "checked_out": pool.checkedout(),  # type: ignore[attr-defined]
        "overflow": pool.overflow(),  # type: ignore[attr-defined]
        "max_overflow": settings.DB_MAX_OVERFLOW,
    }
