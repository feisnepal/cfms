"""
Pytest harness for the Community Forest Management backend.

Provides:
- a PostGIS-enabled test database (`cf_db_test_<worker>`, rebuilt per session)
- a `db` session fixture
- a FastAPI `client` (TestClient) wired to the test DB
- an `auth_headers` fixture that registers + logs in a user and returns a
  Bearer token, so security/auth paths are tested for real (no mocks).

The test DB is created from the live DATABASE_URL by swapping the database name,
with a per-worker suffix so concurrent runs cannot collide (H1.7). Its schema is
built by running the real Alembic migrations (H1.6), so tests and production
cannot silently diverge. Requires PostGIS on the server.
"""
import os
import re
import sys
from pathlib import Path
import pytest
from urllib.parse import urlparse, urlunparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ===========================================================================
# H1.15 / S1-71 — point DATABASE_URL at the test database BEFORE importing any
# application module. Nothing below this block may import from `app`.
#
# Overriding FastAPI's get_db dependency — which is all this harness used to do
# — is not enough and never was. `app/core/database.py` creates `engine` and
# `SessionLocal` at import time from settings.DATABASE_URL, and thirteen code
# paths call SessionLocal() directly rather than receiving a session through
# get_db. Most bind the name at import (`from app.core.database import
# SessionLocal`), so patching the module attribute afterwards cannot reach them.
#
# The consequence was not theoretical. `app/main.py:116` sits in the lifespan
# startup handler and calls run_full_cleanup(), which DELETES export rows and
# files older than seven days. The `client` fixture enters TestClient(app),
# which fires that handler — so every test using it ran a destructive cleanup
# against the production database.
#
# It also made parallelism impossible: each process holds up to
# DB_POOL_SIZE + DB_MAX_OVERFLOW = 50 connections against the same live
# database. `pytest -n 2` produced 1,727 OperationalErrors and zero assertion
# failures before the server stopped accepting sessions altogether.
#
# Setting the variable here is safe despite the database not existing yet:
# create_engine() is lazy and does not connect until first use, by which time
# the session fixture has built it.
# ===========================================================================
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _worker_suffix() -> str:
    """A suffix unique to this pytest process.

    The test database name used to be a fixed `cf_db_test`, and the session
    fixture opens by dropping it WITH (FORCE), which terminates every other
    session's connections. Two concurrent runs destroyed each other, and xdist
    workers would have raced for one database.

    Under xdist, PYTEST_XDIST_WORKER is gw0, gw1, ... Outside it, fall back to
    the process id so two developers sharing one PostgreSQL still get their own.
    """
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    return worker if worker else f"p{os.getpid()}"


def _derive_test_db_url() -> str:
    """Build the test database URL from the configured one.

    Reads the raw environment rather than app.core.config, because importing
    settings here would create the engine against the production database —
    the exact problem this block exists to prevent.
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. The test harness derives its database "
            "name from it; refusing to guess."
        )
    parts = urlparse(url)
    dbname = parts.path.lstrip("/") or "cf_db"

    # Always re-derive from the BASE name, never trust an existing suffix.
    #
    # xdist spawns workers as subprocesses, so they inherit the controller's
    # environment — including the DATABASE_URL this module already rewrote. An
    # earlier version short-circuited when it saw `_test_` in the name, on the
    # theory that it was already redirected. The effect was that every worker
    # kept the CONTROLLER's name and they all raced to create one database:
    # 2,270 UniqueViolations on pg_database_datname_index, all reporting the
    # same pid-suffixed name. Stripping first makes the derivation idempotent
    # per process rather than per environment.
    base = re.sub(r"_test_(gw\d+|p\d+)$", "", dbname)

    # PostgreSQL caps identifiers at 63 bytes; these stay far below it.
    return urlunparse(parts._replace(path=f"/{base}_test_{_worker_suffix()}"))


TEST_DB_URL = _derive_test_db_url()
TEST_DB_NAME = urlparse(TEST_DB_URL).path.lstrip("/")

# The redirection itself. Every `app.*` import below now resolves to the test
# database, including the module-level engine and SessionLocal.
os.environ["DATABASE_URL"] = TEST_DB_URL

# --- application imports begin here; DATABASE_URL is already redirected -----
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402,F401  (kept for parity)

from app.core.database import Base, init_extensions  # noqa: E402
import app.models  # noqa: E402,F401  (registers all mappers)
from app.main import app  # noqa: E402
from app.core.config import settings  # noqa: E402


def _assert_not_production() -> None:
    """Refuse to run if the application engine is not on a test database.

    A guard, not a comment: the previous arrangement failed silently and
    deleted from production for as long as nobody looked.
    """
    from app.core.database import engine as app_engine

    actual = app_engine.url.database or ""
    if "_test_" not in actual:
        raise RuntimeError(
            f"Refusing to run: the application engine is bound to {actual!r}, "
            f"which is not a test database. Expected {TEST_DB_NAME!r}. "
            "See report S1-71."
        )
    if settings.DATABASE_URL != TEST_DB_URL:
        raise RuntimeError(
            f"Refusing to run: settings.DATABASE_URL is {settings.DATABASE_URL!r}, "
            f"expected {TEST_DB_URL!r}."
        )


_assert_not_production()


test_engine = None  # created after the test DB exists (see _prepare_test_db)


@pytest.fixture(scope="session", autouse=True)
def _prepare_test_db():
    # Start from a completely clean test database so Alembic `upgrade head`
    # runs against an empty schema (avoids leftover objects from prior runs).
    admin_url = urlunparse(urlparse(TEST_DB_URL)._replace(path="/postgres"))
    admin = create_engine(admin_url, pool_pre_ping=True)
    with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))

    # Now that the DB exists fresh, build the shared engine.
    global test_engine
    test_engine = create_engine(TEST_DB_URL, pool_pre_ping=True)

    # Ensure PostGIS extensions + the `admin` schema (used by the read-only
    # CommunityForest mapping) exist on the test DB. PostGIS must be enabled
    # in BOTH public (default) and admin (geometry type lookup), otherwise
    # `CREATE TABLE admin."community forests"` fails with "type geometry
    # does not exist".
    try:
        with test_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text("CREATE SCHEMA IF NOT EXISTS admin"))
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis_raster"))
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis SCHEMA admin"))
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis_raster SCHEMA admin"))
    except Exception as e:  # pragma: no cover
        print(f"[conftest] extension init note: {e}")

    # ------------------------------------------------------------------
    # Build the schema with Alembic (task H1.6 / S1-12, S1-21).
    #
    # This previously built from `Base.metadata` with a per-table create_all
    # loop, because `alembic upgrade head` could not run from empty. It can
    # now — see 000_base_identity, which adds the five foundational tables no
    # migration ever created, plus the seven latent chain bugs fixed alongside.
    #
    # Running migrations here is the point of the change: tests and production
    # now derive their schema from the same source, so the two cannot silently
    # diverge. The old loop also swallowed any ProgrammingError whose message
    # contained "already exists", which is how `public.users` went missing in a
    # full run and produced 295 UndefinedTable failures. Nothing is swallowed
    # now: if the schema cannot be built, the session aborts loudly.
    # ------------------------------------------------------------------
    from alembic import command
    from alembic.config import Config as AlembicConfig

    backend_root = Path(__file__).resolve().parent.parent
    alembic_cfg = AlembicConfig(str(backend_root / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(backend_root / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", TEST_DB_URL.replace("%", "%%"))
    # env.py prefers DATABASE_URL over the ini; point it at the test DB too so
    # both resolution paths agree and a stray .env cannot redirect the run at
    # the developer's live database.
    _prev_db_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = TEST_DB_URL
    try:
        command.upgrade(alembic_cfg, "head")
    finally:
        if _prev_db_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = _prev_db_url

    # `admin."community forests"` is a read-only mapping onto an externally
    # maintained dataset, deliberately not owned by the migration chain. Create
    # it from the model so tests that read it have a table to read.
    community_forests = Base.metadata.tables.get('admin.community forests')
    if community_forests is not None:
        community_forests.create(bind=test_engine, checkfirst=True)

    yield

    # Tear down by dropping the whole database, not `Base.metadata.drop_all`.
    #
    # H1.6: now that the schema is built by Alembic it contains tables the models
    # do not know about (activity_spatial_data, dbh_class_systems, geometry_audits,
    # column_mapping_preferences, ...). drop_all only walks metadata, so it tried
    # to drop activity_year_details while the unmodelled activity_spatial_data
    # still held a foreign key into it, and failed with DependentObjectsStillExist.
    # Dropping the database is both simpler and complete, and mirrors what setup
    # already does at session start.
    test_engine.dispose()
    with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))


@pytest.fixture()
def db():
    TestSession = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def forget_forests(db):
    """Opt-in (`pytestmark = pytest.mark.usefixtures("forget_forests")`): run the test on
    empty ground, and leave none behind.

    The test database is built once per session and `client` commits, so a forest one
    test commits is still there for the next - including one from a different module. A
    module whose tests all draw their forest at the same fixed coordinates then finds
    those forests as *neighbours*: the boundary overlap gate answers with a preview
    instead of writing, and boundary writes are clipped against them. The outcome depends
    on test order - green alone, red in a whole-file or whole-suite run. See
    tests/_purge.py.

    Every calculation is removed before the test (leftovers from other modules) and again
    after it. Safe because the only module-scoped fixture that owns calculations lives in
    a different module and pytest runs a module's tests contiguously.
    """
    from sqlalchemy import text as _text

    from tests._purge import purge_calculations

    def _all():
        return [str(r[0]) for r in db.execute(_text("SELECT id FROM calculations")).fetchall()]

    db.rollback()
    purge_calculations(db, _all())
    yield
    db.rollback()
    purge_calculations(db, _all())


@pytest.fixture(autouse=True)
def _registration_status(request):
    """H2.1 / S1-01: keep pre-existing fixtures working after registration
    started producing PENDING accounts.

    21 test files register a user and immediately log in — a round-trip that no
    longer works, since an unapproved account cannot obtain a token. Rewriting
    all of them to drive the approval flow would test the fixtures rather than
    the features they cover, so registration is activated by default here.

    Tests that care about the approval boundary opt back in with
    `@pytest.mark.real_registration`, and tests/test_registration_approval.py
    covers it properly: PENDING on create, no token issued, login refused,
    approval requires an admin.
    """
    import app.api.auth as auth_module
    from app.models.user import UserStatus

    original = auth_module.NEW_ACCOUNT_STATUS
    if request.node.get_closest_marker("real_registration") is None:
        auth_module.NEW_ACCOUNT_STATUS = UserStatus.ACTIVE
    yield
    auth_module.NEW_ACCOUNT_STATUS = original


@pytest.fixture()
def client(db, request):
    def _override_get_db():
        try:
            yield db
        finally:
            pass

    from app.core.database import get_db
    import httpx

    # Reset the global slowapi limiter's storage before each test so
    # auth_fixture registrations never exhaust the 5/min limit across
    # the session.  (TestClient re-triggers the startup handler which
    # re-assigns app.state.limiter from this same global instance.)
    from app.core.rate_limit import limiter as _global_limiter
    _global_limiter._storage.reset()

    # H2.8 added a second counter store beside slowapi's own: the shared one
    # behind the tiered upload/export/analysis middleware and the workspace
    # per-user limiters. Resetting slowapi's alone leaves it accumulating
    # across the session, and a late test inherits a spent budget from an
    # early one.
    from app.core import rate_limit as _rl
    if _rl._SHARED_STORAGE is not None:
        _rl._SHARED_STORAGE.reset()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        if request.node.get_closest_marker("real_registration") is None:
            _complete_legacy_registrations(c, db)
        yield c
    app.dependency_overrides.clear()


def _complete_legacy_registrations(c, db):
    """Registration now needs a verified phone, a designation and a social handle.

    ~100 call sites predate that and only send email / password / name, so this fills the
    rest in (a fresh number with a real, just-issued code) rather than rewriting every
    fixture. Tests of registration itself carry `@pytest.mark.real_registration` and send
    the full payload."""
    import uuid

    from app.services import auth_challenge_service as challenges

    original_post = c.post

    def post(url, *args, **kwargs):
        body = kwargs.get("json")
        if str(url).rstrip("/").endswith("/auth/register") and isinstance(body, dict) and "phone_code" not in body:
            # uuid, not random: some tests seed `random`, which would repeat the number
            phone = "+97798" + f"{uuid.uuid4().int % 10 ** 8:08d}"
            code = challenges.issue(db, purpose=challenges.PHONE_VERIFY, channel="sms", target=phone, guard=False)
            db.commit()
            kwargs["json"] = {
                "user_type": "official", "designation": "ranger", "sub_division": "Test sub-division",
                "instagram_handle": "test_user", **body, "phone": phone, "phone_code": code,
            }
        return original_post(url, *args, **kwargs)

    c.post = post


@pytest.fixture()
def auth_headers(client, db):
    """Register a fresh user and return Bearer auth headers."""
    email = "testuser@example.com"
    payload = {
        "email": email,
        "password": "TestPass123!",
        "full_name": "Test User",
    }
    # register (may 409 if leftover; ignore)
    client.post("/api/auth/register", json=payload)

    # H2.1 / S1-01: registration now creates PENDING accounts that cannot log
    # in until an admin approves them. Tests need a working account, and making
    # each of them drive the approval flow would test the fixture rather than
    # the feature — so activate directly here. The approval path itself is
    # covered by tests/test_registration_approval.py.
    from app.models.user import User, UserRole, UserStatus
    u = db.query(User).filter(User.email == email).first()
    if u is not None and u.status != UserStatus.ACTIVE:
        u.status = UserStatus.ACTIVE
        db.commit()

    # This fixture promises an ORDINARY user, and dozens of authorisation tests
    # assert 403 on the strength of that promise. Because the email is FIXED and
    # registration is allowed to 409, the account is shared by the whole suite:
    # anything that promotes `testuser@example.com` and does not restore it
    # silently converts every later 403 assertion into a 200.
    #
    # That happened. test_calculation_lifecycle_routes.py promoted this row to
    # ORG_ADMIN/SUPER_ADMIN, and under CI's `-n auto -p randomly` four
    # authorisation tests in two unrelated files failed on the run that drew the
    # wrong order -- reporting a security regression that did not exist. The
    # opposite direction is worse: a test asserting an admin CAN act would pass
    # for entirely the wrong reason, and nothing would ever say so.
    #
    # So the promise is checked rather than assumed. One query, in a fixture
    # already making several, and it names the problem instead of leaving
    # somebody to infer it from a 200/403 mismatch three files away.
    if u is not None and u.role != UserRole.USER:
        raise AssertionError(
            f"`auth_headers` is meant to be an ordinary user, but "
            f"{email} currently has role {u.role!r}. Some test promoted this "
            f"SHARED account and did not restore it. Give that test its own "
            f"user -- restoring in teardown still races under `-n auto`, where "
            f"worker processes share one database."
        )

    resp = client.post(
        "/api/auth/login",
        json={"email": email, "password": "TestPass123!"},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# H1.17: Hypothesis health checks under parallel execution.
#
# `pytest -n 2` puts the workers in CPU contention, and Hypothesis's `too_slow`
# health check measures INPUT GENERATION time, not the property under test. It
# fired intermittently on test_property_hull_never_invalid and
# test_detect_workspace_columns_always_returns_dict, both of which pass
# consistently when run alone.
#
# Suppressing it removes a source of false failures without weakening any
# assertion: the properties still run and still have to hold. `deadline=None`
# for the same reason — a per-example time limit is meaningless when N workers
# are sharing the machine.
# ---------------------------------------------------------------------------
try:
    from hypothesis import HealthCheck, settings as _hyp_settings

    _hyp_settings.register_profile(
        "parallel",
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
        deadline=None,
    )
    _hyp_settings.load_profile("parallel")
except ImportError:  # hypothesis is not needed by most of the suite
    pass


def all_route_paths(node, _seen=None):
    """Every route path reachable from a FastAPI app or router.

    A flat scan of `app.routes` is not enough in this application: it holds
    thirteen entries, because the API is assembled from nested routers that
    FastAPI keeps as `_IncludedRouter` wrappers with the real router behind
    `original_router`. A test that scans the flat list reports "no such route"
    while the endpoint answers requests — which is exactly how a route-absence
    gate ends up passing against the defect it exists to catch.
    """
    _seen = set() if _seen is None else _seen
    if node is None or id(node) in _seen:
        return
    _seen.add(id(node))
    for route in getattr(node, "routes", []):
        path = getattr(route, "path", "")
        if path:
            yield path
        yield from all_route_paths(route, _seen)
        yield from all_route_paths(getattr(route, "original_router", None), _seen)
        yield from all_route_paths(getattr(route, "app", None), _seen)


@pytest.fixture()
def relax_user_group_limit(monkeypatch):
    """Opt-in (``pytestmark = pytest.mark.usefixtures("relax_user_group_limit")``): lift the 5,000 ha user group limit (owner decision D2).

    The user-group geometry suites (cut, merge, shared-vertex, union reads...) are about GEOMETRY and were written with degree-sized polygons far
    over the limit. They are not testing the limit, so they opt out; ``tests/test_user_group_size_limit.py`` is the suite that tests it.
    """
    from app.services import user_group_size_guard

    monkeypatch.setattr(user_group_size_guard, "USER_GROUP_MAX_ANALYSIS_AREA_HA", float("inf"))
