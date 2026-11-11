"""
Application configuration settings
"""
from pydantic_settings import BaseSettings
from pydantic import validator
from typing import List, Optional
import os


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # Database
    DATABASE_URL: str = ""  # Must be set in .env
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 30
    DB_POOL_RECYCLE: int = 3600
    DB_POOL_TIMEOUT: int = 30

    # H3.3 / S1-17: how many threads Starlette may use for `def` handlers.
    # 0 means "match the database pool ceiling", which is almost always what you
    # want — see app/core/concurrency.py. Raising it above that ceiling does not
    # buy concurrency, it just moves the queue from the threadpool (where
    # waiting is free) into pool.connect() (where waiting costs DB_POOL_TIMEOUT
    # and then raises).
    THREADPOOL_SIZE: int = 0
    # Workers this process will be run with. Used only to warn when
    # workers x pool would exceed the server's connection limit.
    WEB_CONCURRENCY: int = 1
    # Assumed PostgreSQL max_connections, for that same warning. Not read from
    # the server, because the check must work before the first connection.
    PG_MAX_CONNECTIONS: int = 100

    # JWT Authentication
    SECRET_KEY: str = ""  # Must be set in .env — minimum 32 characters
    ALGORITHM: str = "HS256"
    # H2.5 / S1-05: access tokens are short because they cannot be recalled
    # individually — 30 minutes bounds what a stolen one is worth. Sessions stay
    # long through refresh-token rotation, so this is not a usability cost.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    # Refresh tokens are rotated on every use and revoked as a family on reuse,
    # so a long lifetime here is a convenience, not a standing risk.
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14

    # File Upload
    # H2.15 / S2-56: this was defined here and enforced nowhere. It is now the
    # cap `RequestBodyLimitMiddleware` applies to a multipart body.
    MAX_UPLOAD_SIZE_MB: int = 50
    # Non-multipart bodies get a much tighter cap. The largest legitimate JSON
    # this application sends is a digitize bulk-upsert: 50 features at the
    # 5,000-vertex ceiling is roughly 5 MB. Sizing the JSON cap at the upload
    # cap would let a caller post 50 MB of coordinates to any route that takes
    # a body, which is the S2-56 attack with extra steps.
    MAX_JSON_BODY_SIZE_MB: int = 10
    WORKSPACE_IMPORT_MAX_FILE_SIZE_MB: int = 1
    WORKSPACE_IMPORT_MAX_CUMULATIVE_SIZE_MB: int = 5
    ALLOWED_EXTENSIONS: str = ".shp,.kml,.kmz,.geojson,.json,.gpkg,.gpx,.csv,.xlsx,.zip"
    UPLOAD_DIR: str = "./uploads"
    EXPORT_DIR: str = "./exports"

    # CORS
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:3001,http://localhost:8001"

    # Application
    APP_NAME: str = "Community Forest Management System"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False  # Must be explicitly enabled in .env for development
    API_V1_PREFIX: str = "/api/v1"  # Canonical API version prefix

    # Observability (all OFF when blank — safe no-op defaults)
    SENTRY_DSN: str = ""  # Backend Sentry; unset = disabled
    SENTRY_TRACES_SAMPLE_RATE: float = 0.1
    LOG_FORMAT: str = "text"  # "text" | "json" (structured logging)
    ENABLE_METRICS: bool = True  # Prometheus /metrics endpoint
    # H2.10 / S3-11: bearer token the Prometheus scraper must present at
    # /metrics. Unset means the endpoint is not exposed at all outside DEBUG —
    # metrics name every route, its call volume and its latency, which maps the
    # application and leaks usage patterns for a system holding household PII.
    METRICS_TOKEN: str = ""

    # Redis (optional — report/export jobs + cache; falls back to in-memory)
    REDIS_URL: str = ""

    # Idempotency on mobile-facing writes (H2.17 · S2-64)
    # False means a write without an `Idempotency-Key` proceeds unprotected and
    # is logged by name. It stays false until the mobile client sends one: the
    # web frontend calls these same endpoints today, so requiring a key now
    # would break the live app to protect a client that does not exist yet.
    # Flipping it to true is a launch-day step, taken with the 8.0 audit.
    IDEMPOTENCY_REQUIRE_KEY: bool = False

    # Optimistic locking on field-data writes (H8.2 · S2-63)
    # False means a write that carries no version is accepted and logged rather
    # than refused. The web frontend sends none today, so requiring one would
    # break the live app to protect a mobile client that does not exist yet --
    # the same call IDEMPOTENCY_REQUIRE_KEY makes. True turns the omission into
    # a 428. Flip both together, with the 8.0 audit.
    OPTIMISTIC_LOCK_REQUIRE_VERSION: bool = False
    # G-SYNC-2. Whether a versioned row updated WITHOUT taking its version
    # raises, or only logs at ERROR. Blank follows DEBUG: fatal where a
    # developer or a test will see it, non-fatal in production, where turning a
    # missed call into a 500 for a field worker is not an improvement on the
    # silent overwrite it replaces.
    OPTIMISTIC_LOCK_ENFORCE_GUARD: Optional[bool] = None

    # Rate limiting (H2.8 / H2.18 · S2-08)
    # Off only for deliberate load tests; the default limit applies to every
    # route so a new endpoint is covered the day it is written, not the day
    # someone remembers to decorate it.
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_DEFAULT: str = "600/minute"
    # Blank falls back to REDIS_URL, then to in-process memory. Memory means
    # each worker keeps its own counters, so a limit of N becomes N x workers
    # and every restart forgives the history — acceptable for a dev machine,
    # not for a deployment.
    RATE_LIMIT_STORAGE_URI: str = ""
    # Tight limits for the expensive routes: file ingest, document export and
    # analysis runs each cost far more than a read.
    RATE_LIMIT_UPLOAD: str = "20/minute"
    RATE_LIMIT_EXPORT: str = "10/minute"
    RATE_LIMIT_ANALYSIS: str = "30/minute"
    # Anonymous auth routes are keyed by address, and carrier-grade NAT puts a
    # whole district behind one. Keep these per-address limits loose enough
    # that a shared address is not a lockout, and rely on per-user keying
    # everywhere else.
    RATE_LIMIT_LOGIN: str = "60/minute"
    RATE_LIMIT_REGISTER: str = "20/minute"
    # Phone / email codes: per address, the per-number and per-account caps in
    # services/otp_service.py do the real limiting.
    RATE_LIMIT_OTP: str = "30/minute"

    # Sign-up verification. No SMS provider yet: "console" logs the code (dev
    # only); a real provider is one class in services/sms.py.
    SMS_PROVIDER: str = "console"
    SMS_API_KEY: str = ""
    SMS_SENDER_ID: str = ""
    OTP_TTL_SECONDS: int = 300
    OTP_MAX_ATTEMPTS: int = 5
    OTP_RESEND_COOLDOWN_SECONDS: int = 60
    OTP_DAILY_LIMIT_PER_TARGET: int = 10
    AUTH_TOKEN_TTL_MINUTES: int = 30
    # Facebook Login stays off until both are set (Meta developer app).
    FACEBOOK_APP_ID: str = ""
    FACEBOOK_APP_SECRET: str = ""
    # Frontend origin used in emailed links.
    PUBLIC_APP_URL: str = "http://localhost:3001"
    # The built frontend's index.html. The forum's search-engine pages (api/forum.py, services/forum/seo.py) write the question into it, so
    # a person still gets the app. Empty means ../frontend/dist/index.html; in Docker, mount the frontend build and set this.
    FORUM_SPA_INDEX_PATH: str = ""

    # AI providers (services/chatbot/providers/registry.py; also used by services/report/ai_generator.py). A blank key means "not
    # configured". Keys live in .env only. Hosted providers are treated as synthetic-data-only by the chatbot (CHATBOT_PLAN D13);
    # only Ollama (local) may receive real-forest tool results. Qwen, Kimi and OpenRouter have no default model: set it.
    # Report generation (services/report/ai_generator.py) sends real forest data in its prompts. Before the provider fold its Groq/Gemini keys
    # were never read (the settings fields did not exist), so only Ollama ever answered. Hosted providers stay OFF for reports until the owner
    # sets this to true.
    REPORT_ALLOW_HOSTED_PROVIDERS: bool = False
    CHATBOT_PROVIDER_ORDER: str = ""   # e.g. "ollama,groq,gemini"; blank = every provider that is configured
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = ""
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = ""
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = ""
    QWEN_API_KEY: str = ""
    QWEN_MODEL: str = ""
    QWEN_BASE_URL: str = ""
    KIMI_API_KEY: str = ""
    KIMI_MODEL: str = ""
    KIMI_BASE_URL: str = ""
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_MODEL: str = ""
    LMSTUDIO_BASE_URL: str = ""        # blank = http://localhost:1234/v1 (LM Studio local server, a real-data-OK provider)
    LMSTUDIO_MODEL: str = ""           # required: the model id LM Studio reports
    OLLAMA_BASE_URL: str = ""          # blank = http://localhost:11434/v1
    OLLAMA_MODEL: str = ""

    # Reverse proxies whose X-Forwarded-For may be believed. Comma-separated
    # IPs or CIDRs, or "*" to trust any peer. Empty means every request is
    # keyed on the address that actually connected — the safe default, and the
    # wrong answer the moment this sits behind nginx.
    TRUSTED_PROXY_IPS: str = ""

    @validator("SECRET_KEY")
    def validate_secret_key(cls, v: str) -> str:
        if not v or len(v) < 32:
            raise ValueError(
                "SECRET_KEY must be set in .env file with at least 32 characters. "
                "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(64))\""
            )
        return v

    @validator("DATABASE_URL")
    def validate_database_url(cls, v: str) -> str:
        if not v:
            raise ValueError("DATABASE_URL must be set in .env file")
        return v

    @validator("ALLOWED_EXTENSIONS")
    def parse_extensions(cls, v: "str | list[str]") -> "list[str]":
        """Convert comma-separated string to list"""
        if isinstance(v, str):
            return [ext.strip() for ext in v.split(",")]
        return v

    @validator("CORS_ORIGINS")
    def parse_cors_origins(cls, v: "str | list[str]") -> "list[str]":
        """Convert comma-separated string to list"""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"  # Allow extra env vars without error


# Create global settings instance
settings = Settings()

# Ensure upload and export directories exist.
#
# Best-effort on purpose. This runs at import, and `config` is imported by
# everything, so an OSError here does not fail an upload -- it makes the whole
# application unimportable, including alembic and the test suite. That is the
# failure compose-smoke hit in translation_service.py: the container runs as a
# non-root user (H5.1) against a host-owned bind mount, and an import-time
# mkdir turned a permissions problem into "the backend never started", with the
# real cause twelve frames down a uvicorn traceback.
#
# A missing directory still surfaces -- loudly, at first use, from the code
# that actually needs it and can say what it was trying to write. What it no
# longer does is take the process down at import.
for _label, _directory in (("UPLOAD_DIR", settings.UPLOAD_DIR),
                           ("EXPORT_DIR", settings.EXPORT_DIR)):
    try:
        os.makedirs(_directory, exist_ok=True)
    except OSError as _e:
        # No logger yet: logging is configured later and importing it here
        # would invert the dependency. stderr is read in exactly the situation
        # that matters -- a container that will not start.
        import sys as _sys
        print(f"WARNING: could not create {_label}={_directory!r}: {_e}. "
              f"Writes to it will fail until this is fixed.", file=_sys.stderr)
