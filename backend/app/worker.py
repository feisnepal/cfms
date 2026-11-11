"""
arq worker for report generation (Performance Audit T15).

Run with:  python -m app.worker
Requires Redis (REDIS_URL, default redis://localhost:6379/0). The DSN comes
from `app.core.redis_config.redis_dsn()` — the same source the API-side
enqueue and the job store use — so all three agree in any deployment.

The workerprocess opens its own DB session and runs the same generation
logic used by the inline path, updating shared job state in Redis so the
API's /status, /download, /preview endpoints work unchanged.
"""
import asyncio
import logging
from typing import Any, Dict

from arq import run_worker
from arq.connections import RedisSettings

from app.core.database import SessionLocal
from app.core.redis_config import redis_dsn, redacted
from app.services.report.data_collector import collect_all_data
from app.services.report.section_templates import REPORT_SECTIONS
from app.services.report.prompt_builder import build_prompt
from app.services.report.ai_generator import get_generator
from app.services.report.job_store import get_job, save_job

# Ensure every model's mapper is registered before any DB access. The worker
# process imports only a subset of modules, so string-based relationships
# (e.g. Calculation.operational_plan) can fail to resolve otherwise.
import app.models  # noqa: F401  (registers all mappers, including OperationalPlan)

logger = logging.getLogger(__name__)


async def generate_report_task(ctx: Dict[str, Any], job_id: str) -> None:
    """arq job: generate a report asynchronously, off the request thread."""
    job = get_job(job_id)
    if not job:
        logger.error("[worker] job %s not found", job_id)
        return

    db = SessionLocal()
    try:
        # Imported lazily to keep the module import-light for the worker bootstrap
        from app.api.reports import _run_report_generation

        await _run_report_generation(job_id, db)
    finally:
        db.close()


async def _on_startup(ctx: Dict[str, Any]) -> None:
    logger.info("[worker] reports worker connected to Redis at %s", redacted(redis_dsn()))


class WorkerSettings:
    """Arq worker settings for background report generation tasks."""
    functions = [generate_report_task]
    redis_settings = RedisSettings.from_dsn(redis_dsn())
    on_startup = _on_startup
    # Retry twice on transient failure, then mark failed
    retry_jobs = 2
    max_jobs_retries = 2
    keep_result = 86400  # keep job result 24h


if __name__ == "__main__":
    # main.py configures logging at import; a `python -m app.worker` process
    # never imports it, so without this call every INFO line (arq's own
    # "Starting worker" and the Redis-target line in _on_startup) is dropped
    # by the root logger's default WARNING level.
    from app.core.logging_config import configure_logging

    configure_logging()
    asyncio.run(run_worker(WorkerSettings))
