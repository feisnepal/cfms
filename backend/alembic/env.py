from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# Import your models' Base
import os
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from dotenv import load_dotenv

from app.core.database import Base
from app.models import *  # Import all models

# this is the Alembic Config object
config = context.config

# Interpret the config file for Python logging.
#
# `disable_existing_loggers=False` is load-bearing, not tidiness. It defaults to
# True, which sets `.disabled = True` on every logger that already exists — and
# `tests/conftest.py` runs `alembic upgrade head` IN-PROCESS to build the test
# schema (H1.6). So the default silenced every `app.*` logger imported before
# that point, for the whole session: H3.4's log lines emitted nothing under
# test, and any assertion about them passed or failed vacuously.
#
# Production was never affected — migrations run there as a separate process —
# which is exactly why this went unnoticed. Found 2026-08-25 while trying to
# assert on a log line and getting an empty capture.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)


# ---------------------------------------------------------------------------
# H1.4 / S1-12: resolve the target database from DATABASE_URL, not alembic.ini.
#
# alembic.ini ships a hardcoded `sqlalchemy.url` pointing at a local cf_db (and
# carries the password in a git-tracked file). Because env.py read only that
# option, EVERY `alembic upgrade` targeted that one database regardless of
# DATABASE_URL — so CI could not migrate its own service database, a deploy
# could not migrate the environment it was deploying to, and a test run against
# a scratch database silently hit the live one instead.
#
# Precedence: DATABASE_URL env var → .env file → alembic.ini fallback.
# ---------------------------------------------------------------------------
load_dotenv(Path(__file__).parent.parent / ".env")

_db_url = os.environ.get("DATABASE_URL")
if _db_url:
    # Escape %, which ConfigParser would otherwise treat as interpolation.
    config.set_main_option("sqlalchemy.url", _db_url.replace("%", "%%"))
elif not (config.get_main_option("sqlalchemy.url") or "").strip():
    # H1.13 / S2-69: fail loudly rather than defaulting to a live database.
    #
    # alembic.ini used to carry `postgresql://postgres:<password>@localhost/cf_db`,
    # so a missing DATABASE_URL silently sent migrations at whatever that pointed
    # to. Programmatic callers (the test harness) set the option directly, which
    # is why a non-empty ini value is still accepted here.
    raise RuntimeError(
        "DATABASE_URL is not set and alembic.ini defines no sqlalchemy.url.\n"
        "Refusing to guess a migration target — the previous default was a live "
        "database. Set it explicitly, e.g.\n\n"
        "    DATABASE_URL=postgresql://user:pass@host:5432/dbname alembic upgrade head\n"
    )

# Set target metadata for autogenerate
target_metadata = Base.metadata


# ---------------------------------------------------------------------------
# H1.18 / S1-74: migrations run with search_path pinned to public.
#
# `cf_db` carries a database-level `search_path = rasters, public, sde`, set for
# the GIS layers. An unqualified `op.create_table` lands in the FIRST entry of
# that path, so six application tables — translations (536 rows),
# workspace_layers (23), dbh_class_systems, dbh_classification_changes,
# digitize_audit_logs and refresh_tokens — were created inside the raster
# schema. Nothing broke, because `public` is second in the path and every read
# resolves; that is exactly why it went unnoticed for months.
#
# What it breaks is the promise Phase 1 exists to keep. A database built from
# this chain on a clean server puts those tables in `public`, because the stock
# search_path is `"$user", public`. Two databases at the same revision, with
# structurally different schemas, and `alembic check` cannot see it: the models
# are unqualified (H1.14), so they match whichever schema the path resolves to.
#
# Pinning here makes migration DDL depend on the chain rather than on a
# per-database setting. `alembic_version` already lives in public, so the
# revision is still read correctly.
# ---------------------------------------------------------------------------
MIGRATION_SEARCH_PATH = "public"


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# H1.11 / S1-12: scope what autogenerate and `alembic check` compare.
#
# Without this, `alembic check` reported ~350 differences against a database
# Alembic itself had just built. Almost none were real:
#
#   * PostGIS owns spatial_ref_sys and the geometry/raster catalog views. They
#     are created by CREATE EXTENSION, belong to no model, and autogenerate
#     wanted to drop them.
#   * `admin` holds a read-only mapping onto an externally maintained dataset
#     (admin."community forests"), deliberately not owned by the chain.
#   * Six tables are created by migrations and accessed with raw SQL rather than
#     the ORM, so no model declares them. Listing them explicitly is the honest
#     record: adding real models would be the stronger fix, and is tracked
#     separately rather than hidden behind a wildcard.
#
# Anything NOT named here is still compared, so genuine drift still fails.
# ---------------------------------------------------------------------------
POSTGIS_OWNED = {
    "spatial_ref_sys", "geometry_columns", "geography_columns",
    "raster_columns", "raster_overviews",
}

# Created by migrations, used via raw SQL, no ORM model. Tracked for modelling.
UNMODELLED_TABLES = {
    "activity_spatial_data",        # 020 — orphan; see report S1-12
    "column_mapping_preferences",
    "dbh_class_systems",            # read/written by api/dbh_classes.py via text()
    "dbh_classification_changes",
    "geometry_audits",              # written by services/audit_service.py via text()
    "pending_boundary_submissions",
}

IGNORED_SCHEMAS = {"admin", "tiger", "tiger_data", "topology"}


def include_object(obj, name, type_, reflected, compare_to):
    """Limit comparison to objects this migration chain actually owns."""
    schema = getattr(obj, "schema", None)
    if schema in IGNORED_SCHEMAS:
        return False
    if type_ == "table":
        return name not in POSTGIS_OWNED and name not in UNMODELLED_TABLES
    # Indexes/constraints hanging off an excluded table go with it.
    parent = getattr(obj, "table", None)
    if parent is not None:
        if getattr(parent, "schema", None) in IGNORED_SCHEMAS:
            return False
        if parent.name in POSTGIS_OWNED or parent.name in UNMODELLED_TABLES:
            return False
    return True


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        # The search_path is pinned as a libpq connect option, NOT by executing
        # `SET search_path` on the connection. The first attempt did the latter
        # and cost an hour: the statement opens an implicit transaction that
        # Alembic does not own, so `command.upgrade` closed the connection and
        # rolled the entire migration run back — silently, exit code 0, an
        # empty schema and no error anywhere. `-c` applies at connect time,
        # before any transaction exists.
        connect_args={"options": f"-csearch_path={MIGRATION_SEARCH_PATH}"},
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
