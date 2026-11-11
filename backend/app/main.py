"""
Main FastAPI application
Community Forest Management System
"""
import os
import sys

# Set PROJ_LIB environment variable for PROJ database
# This must be set before importing any libraries that use PROJ (pyproj, rasterio, etc.)
_current_proj = os.environ.get('PROJ_LIB', '')
if not _current_proj or not os.path.exists(os.path.join(_current_proj, 'proj.db')):
    candidates = []

    # 1. User site-packages rasterio (most compatible with rasterio version)
    try:
        import site
        candidates.append(os.path.join(site.getusersitepackages(), 'rasterio', 'proj_data'))
        # 2. User site-packages pyproj
        candidates.append(os.path.join(site.getusersitepackages(), 'pyproj', 'proj_dir', 'share', 'proj'))
    except Exception:  # noqa: BLE001,S110 -- probing for optional PROJ data directories at import time; a missing user site-packages is the normal case, and the candidate list simply gets one fewer entry
        pass

    # 3. Venv pyproj path
    venv_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    candidates.append(os.path.join(venv_path, 'venv', 'Lib', 'site-packages', 'pyproj', 'proj_dir', 'share', 'proj'))

    for p in candidates:
        if os.path.exists(os.path.join(p, 'proj.db')):
            os.environ['PROJ_LIB'] = p
            print(f"Set PROJ_LIB to: {p}")
            break
    else:
        print(f"Warning: Could not find proj.db in any candidate path")

from fastapi import FastAPI, Request, APIRouter, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from contextlib import asynccontextmanager
import time
import logging
import httpx

logger = logging.getLogger(__name__)
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
from slowapi.middleware import SlowAPIMiddleware
from .core.rate_limit import limiter, storage_backend
from .middleware.body_limits import RequestBodyLimitMiddleware
from .middleware.tiered_rate_limit import TieredRateLimitMiddleware
from .core.constants import (
    REQUEST_MAX_TOTAL_VERTICES,
    WORKSPACE_IMPORT_MAX_VERTICES,
)
from sqlalchemy.exc import DataError, IntegrityError, SQLAlchemyError

from .core.exceptions import AppException
from .core.i18n_messages import get_message

from .core.config import settings
from .core.database import check_db_connection, read_alembic_revision, Base, engine, init_extensions
# H8.2 / G-SYNC-2. Imported for its side effect: registering the before_flush
# guard that refuses an unguarded update to a versioned record. It must be
# imported HERE and not left to `optimistic_lock`'s own lazy import -- that one
# only fires on the first `check_and_bump` call, so any unguarded write before
# it would pass unnoticed, which is the failure the guard exists to catch.
from .services import optimistic_lock_guard  # noqa: F401
from .core import observability
from .api import auth_router, forests_router, blocks_router, inventory_router, species_router, tree_models_router, all_tree_exports_router
from .api import fieldbook, sampling, fieldbook_list, sampling_list, biodiversity, field_inventory, ntfp, forum, chat
from .api import fire_lines
from .api import forest_metadata
from .api import forest_summary
from .services import user_group_auto_analysis  # noqa: F401  (registers the ORM hook)
from .services import fire_line_auto_sync  # noqa: F401  (registers the ORM hook: fire lines follow the units)
from .services import user_group_size_guard  # noqa: F401  (registers the over-limit refusal, owner decision D2)
from .api import location_search, tiles, user_group, household_info, forest_committee, yearly_activities, yearly_plan
from .api import soil_erosion_params
from .api import soil_erosion_profiles
from .api import hazard_vuln_params
from .api import hazard_vuln_profiles
from .api import hazard_erosion
from .api import structure as structure_impact_api
from .api import cost_benefit
from .api import cba_rate_profiles
from .api import sustainable_fm as sustainable_fm_api
from .api import sfm_prescriptions
from .api import sfm_profiles
from .api import compartments
from .api import workspace
from .api import workspace_layout
from .api import editing
from .api import calculation_lifecycle
from .api import reports
from .api import dbh_classes
from .api import demand_supply
from .api import translations
from .api.admin_flags import router as admin_flags_router
from .api.admin_costs import router as admin_costs_router
from .api.admin_users import router as admin_users_router
from .api.auth_verification import router as auth_verification_router
from .api.operational_plans import router as operational_plans_router
from .api.op_table_catalog import router as op_table_catalog_router
from .api.boundary import router as boundary_router
from .api.uploads import router as uploads_router

from .middleware.correlation import CorrelationIdMiddleware
from .core.logging_config import configure_logging
from .core.feature_flags import feature_flags
from .utils.auth import get_current_active_user

# Debug: Print router info
print(f"DEBUG: Species router loaded with prefix: {species_router.prefix}")
print(f"DEBUG: Species router has {len(species_router.routes)} routes")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan events
    Startup and shutdown logic
    """
    # ── Initialize Sentry (no-op when SENTRY_DSN unset) ──
    observability.init_sentry()

    # ── H3.3 / S1-17: size the threadpool to the database pool ──
    # Must happen inside the running loop: anyio's default limiter resolves
    # against the async context, so doing this at import time would configure a
    # different limiter from the one Starlette actually uses.
    from .core.concurrency import configure_threadpool

    configure_threadpool()

    # Startup
    print(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    print(f"Debug mode: {settings.DEBUG}")

    # H2.6 / S2-06: DEBUG is not a verbosity switch in this application — it
    # decides real security behaviour, and the shipped compose file used to
    # turn it on. Say so at startup so nobody discovers it from a pen test.
    if settings.DEBUG:
        logger.warning(
            "DEBUG is enabled: HSTS and CSP headers are suppressed, SQL is "
            "echoed, exception detail and type are returned to clients, and "
            "uvicorn binds 0.0.0.0. Never run this configuration in production."
        )
    
    # Check volume debug logging
    import os
    if os.environ.get('DEBUG_VOLUME_CALC', '').lower() == 'true':
        print(">>> DEBUG_VOLUME_CALC enabled - volume calculation logs will be printed <<<")

    # Check database connection
    if check_db_connection():
        print("Database connection successful")

        # H1.1 / S1-25: state the runtime versions, and warn on a mismatch with
        # the supported stack. Silence here previously meant a schema built on
        # one PostgreSQL major was being tested against another.
        from .core.database import log_runtime_versions
        log_runtime_versions()

        # Initialize PostGIS extensions once at startup (not per-connection)
        try:
            init_extensions()
        except Exception as e:
            logger.warning(f"PostGIS init failed (non-critical): {e}")

        # Run startup cleanup of old exports (7-day retention)
        try:
            from .services.export_cleanup import run_full_cleanup
            from .core.database import SessionLocal
            db = SessionLocal()
            export_dir = os.path.join(os.path.dirname(__file__), '..', 'exports')
            results = run_full_cleanup(db, export_dir, retention_days=7)
            total = sum(v for k, v in results.items() if k != "retention_days")
            if total > 0:
                print(f"Startup export cleanup: removed {total} items")
            else:
                print("Startup export cleanup: nothing to clean")
            db.close()
        except Exception as e:
            print(f"Warning: Startup export cleanup failed (non-critical): {e}")
    else:
        print("Database connection failed")

    # ── Initialize Redis/FastAPICache ──
    if settings.REDIS_URL:
        try:
            from fastapi_cache import FastAPICache
            from fastapi_cache.backends.redis import RedisBackend
            import redis.asyncio as aioredis
            redis_client = aioredis.from_url(settings.REDIS_URL)
            FastAPICache.init(RedisBackend(redis_client), prefix="cfm-cache:")
            print(f"Redis cache initialized at {settings.REDIS_URL}")
        except Exception as e:
            print(f"Warning: Redis cache init failed (non-critical): {e}")
    else:
        print("Redis not configured — cache disabled")

    # Note: We don't create tables here as they already exist in cf_db
    # Only the forest_managers table needs to be created via migration

    # Total Tree Exports live one hour. Reads also purge on demand, so this sweep
    # is only about freeing disk when nobody is looking at the page.
    async def _sweep_expired_tree_exports():
        import asyncio

        from .core.database import SessionLocal
        from .services.export_cleanup import purge_expired_all_tree_exports

        def _once():
            session = SessionLocal()
            try:
                purge_expired_all_tree_exports(session)
            finally:
                session.close()

        while True:
            await asyncio.sleep(600)
            try:
                await asyncio.to_thread(_once)
            except Exception:  # noqa: BLE001 -- a failed sweep must not stop the next one
                logger.exception("Total Tree Export sweep failed")

    import asyncio as _asyncio

    export_sweep_task = _asyncio.create_task(_sweep_expired_tree_exports())

    yield

    export_sweep_task.cancel()

    # H3.14 / S3-35: the image-proxy's shared httpx client was closed via the
    # deprecated `@on_event("shutdown")` handler. Starlette's lifespan shutdown
    # runs after in-flight requests drain; on_event handlers run under ASGI in
    # a way that left the client open or closed at the wrong time depending on
    # the lifespan implementation, and the decorator is deprecated. Closing it
    # here, beside App creation, keeps one shutdown path for the whole app.
    # Shutdown
    print("Shutting down application...")
    await tile_client.aclose()


# Create FastAPI app
# H2.10 / S3-11: the interactive docs and the OpenAPI schema are development
# tools. Served publicly they hand an attacker the full route inventory,
# parameter names and response shapes for a system holding household PII, and
# "Try it out" turns the schema into an attack console. Off unless DEBUG.
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="API for Community Forest Management and Analysis",
    lifespan=lifespan,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    openapi_url="/openapi.json" if settings.DEBUG else None,
)

# Initialize structured logging
configure_logging()

# Feature flags — log current state
logger = logging.getLogger(__name__)
logger.info("Feature flags: %s", feature_flags.all())

# Rate limiting (H2.8 / H2.18 · S2-08)
# The middleware applies `RATE_LIMIT_DEFAULT` to every route, including ones
# nobody remembered to decorate. It is registered before CORS on purpose:
# `add_middleware` builds outward, so CORS ends up outside it and a 429 still
# carries the headers a browser needs to read the status instead of reporting
# an opaque network failure.
app.state.limiter = limiter
# Body ingress limits (H2.15 / S2-56). Added first, so it ends up *inside* the
# two rate limiters and runs after them: a caller who is already over their
# budget should be turned away before anything reads their 50 MB. It stays
# inside CORS for the same reason the limiters do — a browser has to be able to
# read a 413.
app.add_middleware(RequestBodyLimitMiddleware)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(TieredRateLimitMiddleware)
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
logger.info(
    "Body limits: %d MB upload, %d MB JSON, %d vertices per geometry, %d per request",
    settings.MAX_UPLOAD_SIZE_MB,
    settings.MAX_JSON_BODY_SIZE_MB,
    WORKSPACE_IMPORT_MAX_VERTICES,
    REQUEST_MAX_TOTAL_VERTICES,
)
logger.info(
    "Rate limiting: %s (default %s, storage %s, trusted proxies %r)",
    "enabled" if settings.RATE_LIMIT_ENABLED else "DISABLED",
    settings.RATE_LIMIT_DEFAULT,
    storage_backend(),
    settings.TRUSTED_PROXY_IPS or "none",
)
app.add_exception_handler(AppException, lambda request, exc: JSONResponse(
    status_code=exc.http_status,
    content={
        "error_code": exc.error_code,
        "message": exc.message,
        "details": exc.details,
        "correlation_id": exc.correlation_id,
    },
))


# ---------------------------------------------------------------------------
# Database errors never reach the browser as database errors
# ---------------------------------------------------------------------------
# A bad value in a request used to surface as the driver's own exception, and
# under DEBUG the generic handler below put `str(exc)` in the response body.
# That body was the full SELECT — every column of the table, the WHERE clause
# and the bound parameters. It is unreadable to the person using the map, and
# to anyone else it is a free description of the schema.
#
# `DataError` is the value-shaped one (a non-UUID where a UUID belongs, a
# number out of range, a malformed date), so it is the caller's problem and
# answers 400. `IntegrityError` is a constraint the caller violated — a
# duplicate, or a row still referenced — and answers 409. Anything else is
# ours and answers 500. All three log the real exception server-side with the
# correlation id, so nothing is lost to whoever is debugging; only the browser
# is spared.
# Constraint name -> the sentence to show. Keyed on the name so the response
# never has to quote the database's own error text.
_NATURAL_KEY_MESSAGES = {
    "uq_household_calculation_house_no": "general.duplicate_household",
    "uq_measurement_plot_stand_sn": "general.duplicate_measurement",
    "uq_field_inventory_calculations_calculation_id": "general.duplicate_field_inventory",
}


def _violated_constraint(exc: IntegrityError) -> str:
    """The constraint name psycopg2 reports, or "" when the driver gives none."""
    diag = getattr(getattr(exc, "orig", None), "diag", None)
    return getattr(diag, "constraint_name", None) or ""


@app.exception_handler(SQLAlchemyError)
async def database_exception_handler(request: Request, exc: SQLAlchemyError):
    if isinstance(exc, DataError):
        status_code, code = 400, "general.invalid_value"
    elif isinstance(exc, IntegrityError):
        # H8.6 named two natural keys, and a 409 reading "Bad request" tells the
        # user nothing about what to change. Match on the CONSTRAINT NAME, never
        # on the driver's message text: the name is ours and is pinned by the
        # migration, while the message is the database's and carries the SQL and
        # bound parameters we deliberately keep out of the response.
        code = _NATURAL_KEY_MESSAGES.get(_violated_constraint(exc), "general.bad_request")
        status_code = 409
    else:
        status_code, code = 500, "general.internal_error"

    correlation_id = getattr(request.state, "correlation_id", None)
    logger.error(
        "Database error on %s %s (correlation_id=%s): %s",
        request.method, request.url.path, correlation_id, exc,
        exc_info=True,
    )
    entry = get_message(code)
    return JSONResponse(
        status_code=status_code,
        content={
            "detail": {
                "code": code,
                "message": entry["en"],
                "message_np": entry["ne"],
            },
            "correlation_id": correlation_id,
        },
    )


# Add CORS middleware
# Allow requests from frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS if isinstance(settings.CORS_ORIGINS, list) else
        [origin.strip() for origin in settings.CORS_ORIGINS.split(",")],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Requested-With"],
    expose_headers=["*"],
)


# Correlation ID middleware (injects X-Correlation-ID into every request)
app.add_middleware(CorrelationIdMiddleware)


# Request timing middleware
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    """Add processing time to response headers"""
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    return response


# Security headers middleware
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Add security headers to all responses"""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), interest-cohort=()"
    if not settings.DEBUG:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'self'"
    return response


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Anything nobody caught. The browser gets words; the log gets the truth.

    This used to branch on DEBUG: `str(exc)` plus the request URL when it was
    on, the bare string "Internal server error" when it was off. Both ends were
    wrong. The DEBUG branch is what put a full SQL statement, its column list
    and its bound parameters on a user's screen — the exception text of an
    arbitrary failure is written for a developer reading a stack trace, not for
    somebody halfway through drawing a forest boundary, and it can carry
    anything the exception happened to be holding. The production branch leaked
    nothing and said nothing: six words that tell the user neither what went
    wrong nor what to do about it.

    So the response no longer depends on the mode. Every caller gets the same
    readable, bilingual message and a `correlation_id`; every failure is logged
    in full with that same id, so anyone debugging has the traceback, the path
    and the exception one grep away. Under DEBUG the exception's *class name*
    is included as a convenience for local work — a name like `KeyError` aids
    the developer and discloses nothing, unlike the message it came with.
    """
    correlation_id = getattr(request.state, "correlation_id", None)
    logger.error(
        "Unhandled %s on %s %s (correlation_id=%s): %s",
        type(exc).__name__, request.method, request.url.path, correlation_id, exc,
        exc_info=True,
    )
    entry = get_message("general.unexpected_error")
    detail = {
        "code": "general.unexpected_error",
        "message": entry["en"],
        "message_np": entry["ne"],
    }
    if settings.DEBUG:
        detail["exception_type"] = type(exc).__name__
    return JSONResponse(
        status_code=500,
        content={"detail": detail, "correlation_id": correlation_id},
    )


# ---------------------------------------------------------------------------
# API versioning
# ---------------------------------------------------------------------------
# All routers are aggregated into a single versioned APIRouter. It is mounted
# twice: under /api/v1 (the canonical, current version) and under /api (a
# legacy shim kept for backward compatibility — all /api routes now carry a
# `Deprecation` header pointing callers at /api/v1). See docs/API_VERSIONING.md.
#
# To add a new router: append it to `SUB_ROUTERS` below with its mount prefix.
# ---------------------------------------------------------------------------
API_V1_PREFIX = settings.API_V1_PREFIX

SUB_ROUTERS = [
    (auth_router, "/auth", ["Authentication"]),
    (auth_verification_router, "/auth", ["Authentication"]),
    (forests_router, "/forests", ["Forest Management"]),
    (blocks_router, "/blocks", ["Blocks"]),
    (inventory_router, "/inventory", ["Tree Inventory"]),
    (species_router, "/species", ["Species"]),
    (fieldbook.router, "/calculations", ["Fieldbook"]),
    (fire_lines.router, "/calculations", ["Fire lines"]),
    (ntfp.router, "/calculations", ["NTFP inventory"]),
    (forum.router, "/forum", ["Forum"]),
    (chat.router, "/chat", ["Chat"]),
    # WORKSPACE_FLOW_NAV_PLAN D5. The router declares no prefix of its own, so it
    # takes `/calculations` from the mount exactly as `fieldbook` does below.
    (forest_metadata.router, "/calculations", ["Forest Metadata"]),
    (forest_summary.router, "/calculations", ["Forest Summary"]),
    (sampling.router, "", ["Sampling"]),
    (fieldbook_list.router, "", ["Fieldbook Lists"]),
    (sampling_list.router, "", ["Sampling Lists"]),
    (biodiversity.router, "", ["Biodiversity"]),
    (tree_models_router, "", ["Tree Distribution Models"]),
    (all_tree_exports_router, "", ["All Tree Export"]),
    (field_inventory.router, "/field-inventory", ["Field Inventory"]),
    (location_search.router, "/location", ["Location Search"]),
    (tiles.router, "", ["Raster Tiles"]),
    (user_group.router, "", ["User Group Map"]),
    (soil_erosion_params.router, "", ["Soil Erosion Params"]),
    (soil_erosion_profiles.router, "", ["Soil Erosion Profiles"]),
    (hazard_vuln_params.router, "", ["Hazard Vuln Params"]),
    (hazard_vuln_profiles.router, "", ["Hazard Vuln Profiles"]),
    (hazard_erosion.router, "", ["Hazard & Erosion"]),
    (structure_impact_api.router, "", ["Structure Impact"]),
    (cost_benefit.router, "", ["Cost-Benefit Analysis"]),
    (cba_rate_profiles.router, "", ["CBA Rate Profiles"]),
    (sustainable_fm_api.router, "", ["Sustainable FM"]),
    (sfm_prescriptions.router, "", ["SFM Prescriptions"]),
    (sfm_profiles.router, "", ["SFM Profiles"]),
    (household_info.router, "/household", ["Household Information"]),
    (forest_committee.router, "/forest-committee", ["Forest Committee"]),
    (yearly_activities.router, "/yearly-activities", ["Yearly Activities"]),
    (yearly_plan.router, "/yearly-activities", ["Yearly Plan"]),
    (compartments.router, "/compartments", ["Compartments"]),
    (operational_plans_router, "/operational-plans", ["Operational Plans"]),
    (op_table_catalog_router, "", ["OP Table Catalog"]),
    (demand_supply.router, "", ["Demand and Supply"]),
    (dbh_classes.router, "", ["DBH Classes"]),
    (translations.router, "", ["Translations"]),
    (admin_flags_router, "", ["Admin Flags"]),
    (admin_costs_router, "", ["Admin Costs"]),
    (admin_users_router, "", ["Admin Users"]),
    (boundary_router, "", ["Boundary Overlap"]),
    (uploads_router, "", ["Unified Upload"]),
    (workspace.router, "", ["Workspace Import"]),
    (workspace_layout.router, "", ["Workspace Layout"]),
    (editing.router, "", ["Feature Editing"]),
    # Both of these existed and were never mounted, so every endpoint in them
    # answered 404 while the UI called them. See CURRENT_PLAN.md; the gate
    # `scripts/check_unmounted_routers.py` now stops a third from arriving.
    (calculation_lifecycle.router, "", ["Calculation Lifecycle"]),
    (reports.router, "", ["Reports"]),
]


def _build_api_router(base: str) -> APIRouter:
    """Aggregate every sub-router under `base` (e.g. /api/v1 or /api)."""
    router = APIRouter()
    for sub, prefix, tags in SUB_ROUTERS:
        router.include_router(sub, prefix=f"{base}{prefix}", tags=tags)
    return router


# Canonical v1 API — mounted under /api/v1.
app.include_router(_build_api_router(API_V1_PREFIX))

# Legacy /api shim — functionally identical routes, kept for backward
# compatibility. A global middleware tags every /api (non-v1) response with a
# `Deprecation` header so clients know to migrate to /api/v1.
app.include_router(_build_api_router("/api"))


@app.middleware("http")
async def _deprecation_header(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/api/") and not path.startswith("/api/v1/"):
        response.headers["Deprecation"] = f'@{API_V1_PREFIX} ("use /api/v1")'
    return response


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint - API information"""
    import datetime
    return {
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running",
        "docs": "/docs",
        "reloaded_at": str(datetime.datetime.now(datetime.timezone.utc)),
        "endpoints": {
            "auth": "/api/v1/auth",
            "forests": "/api/v1/forests",
            "inventory": "/api/v1/inventory",
            "species": "/api/v1/species",
            "fieldbook": "/api/v1/calculations/{id}/fieldbook",
            "sampling": "/api/v1/calculations/{id}/sampling"
        },
        "api_versioning": {
            "current": API_V1_PREFIX,
            "legacy": "/api (deprecated — carries Deprecation header)",
        }
    }


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring (liveness)"""
    db_status = check_db_connection()

    return {
        "status": "healthy" if db_status else "unhealthy",
        "database": "connected" if db_status else "disconnected",
        "version": settings.APP_VERSION,
        # R-3 smoke's --expect-revision asserts this: /health is the one place
        # the pipeline and the served app agree on what schema is live.
        "alembic_revision": read_alembic_revision(),
    }


# Readiness endpoint — DB + Redis connectivity (used by orchestrators/k8s)
@app.get("/ready")
async def ready_check():
    """Readiness probe: reports dependency connectivity."""
    db_ok = check_db_connection()

    redis_ok = True
    redis_detail = "not configured"
    redis_url = getattr(settings, "REDIS_URL", "") or ""
    if redis_url:
        try:
            import redis  # local import — optional dependency

            r = redis.Redis.from_url(redis_url, socket_connect_timeout=2)
            redis_ok = bool(r.ping())
            redis_detail = "connected" if redis_ok else "unreachable"
        except Exception as e:  # pragma: no cover
            logger.warning(
                "Redis health probe failed - reporting it unreachable in "
                "/health", exc_info=True,
            )
            redis_ok = False
            redis_detail = f"error: {e}"

    healthy = db_ok and redis_ok
    return {
        "status": "ready" if healthy else "not_ready",
        "database": "connected" if db_ok else "disconnected",
        "redis": redis_detail,
        "version": settings.APP_VERSION,
    }


# Prometheus metrics (no-op when ENABLE_METRICS is false)
observability.instrument_metrics(app)


# H2.10 / S3-11: GET /test-species is deleted.
#
# It was unauthenticated and enumerated the application's routing table —
# paths and methods — to anyone who asked. That is reconnaissance handed out
# for free, and it existed only to debug a router-registration problem years
# ago. `/docs` covers the legitimate need, for callers entitled to it.


tile_client = httpx.AsyncClient(timeout=10.0)

# H2.11 / S3-11: GET /api/tile-proxy/{z}/{x}/{y}.png is deleted.
#
# It relayed openstreetmap.org tiles to anyone, unauthenticated, under
# Access-Control-Allow-Origin: *. Not an SSRF — the URL was hardcoded — but an
# open bandwidth relay that put this server's IP behind whatever volume a
# stranger cared to generate, against OSM's tile usage policy. Nothing in the
# frontend or backend referenced it; the map loads OSM directly.


from urllib.parse import unquote

# ---------------------------------------------------------------------------
# H2.2 / S1-02 — image proxy, previously a full unauthenticated read-SSRF.
#
# It fetched ANY caller-supplied URL with no authentication, no allowlist, no
# scheme restriction and no private-IP filtering, then returned the body
# verbatim under `Access-Control-Allow-Origin: *`. On a cloud host that reaches
# the instance metadata endpoint (169.254.169.254) and every internal service
# the application server can see — a credible path to credential theft.
#
# It could not simply be deleted: html2canvas uses it as its `proxy` in
# ExportButton.tsx and exportMapRenderer.ts, so map export depends on it. But
# the legitimate use is narrow — fetching basemap tiles that lack CORS headers —
# so an allowlist of the tile hosts the frontend actually loads is both
# sufficient and tight.
#
# Kept deliberately simple: an exact host allowlist is verifiable by reading it.
# DNS-rebinding defences and IP-range filtering would be needed if this took
# arbitrary hosts; it does not.
# ---------------------------------------------------------------------------
IMAGE_PROXY_ALLOWED_HOSTS = frozenset({
    "tile.openstreetmap.org",
    "a.tile.openstreetmap.org",
    "b.tile.openstreetmap.org",
    "c.tile.openstreetmap.org",
    "tile.opentopomap.org",
    "a.tile.opentopomap.org",
    "b.tile.opentopomap.org",
    "c.tile.opentopomap.org",
    "server.arcgisonline.com",
    "basemaps.cartocdn.com",
})

IMAGE_PROXY_MAX_BYTES = 8 * 1024 * 1024


@app.get("/api/image-proxy")
async def image_proxy(url: str, current_user=Depends(get_current_active_user)):
    from urllib.parse import urlparse

    decoded = unquote(url)
    parsed = urlparse(decoded)

    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Only http(s) URLs may be proxied")
    if parsed.hostname not in IMAGE_PROXY_ALLOWED_HOSTS:
        # Do not echo the host back — that turns the error into a probe oracle.
        logger.warning("image-proxy refused host=%r user=%s", parsed.hostname, current_user.id)
        raise HTTPException(status_code=403, detail="Host is not an allowed imagery source")

    try:
        resp = await tile_client.get(decoded)
    except Exception as e:
        logger.warning("image-proxy fetch failed: %s", e)
        raise HTTPException(status_code=502, detail="Image proxy failed")

    if len(resp.content) > IMAGE_PROXY_MAX_BYTES:
        raise HTTPException(status_code=502, detail="Proxied image exceeds the size limit")

    content_type = resp.headers.get("content-type", "image/png")
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=502, detail="Proxied resource is not an image")

    # No wildcard CORS: this is same-origin from the SPA, and `*` let any site
    # on the internet use the endpoint as an open relay.
    return Response(content=resp.content, media_type=content_type)


if __name__ == "__main__":
    import uvicorn
    host = "0.0.0.0" if settings.DEBUG else "127.0.0.1"
    uvicorn.run(
        "app.main:app",
        host=host,
        port=3001,
        reload=settings.DEBUG
    )
