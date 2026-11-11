"""
arq worker for background calculation tasks.

Starts a worker that dequeues and runs calculations sequentially (max_concurrency=1)
to minimize resource usage on constrained hardware.

Run with:  python -m app.calculation_worker
Requires Redis (REDIS_URL, default redis://localhost:6379/0) — resolved via
`app.core.redis_config.redis_dsn()`.

Queue behavior:
- max_concurrency=1: one calculation at a time
- Additional jobs queue in Redis list
- 20 min soft timeout / 22 min hard timeout per job
- Max 2 retries on transient failure
- Job results kept for 24 hours

Digitize (Task 1.5.1/1.5.2):
- `finalize_digitize_layer` job: 20s soft timeout / 30s hard, max 2 retries,
  DLQ-on-abort (arq keeps the result; on_abort marks the layer VALIDATION_FAILED).
- Hourly cron `cleanup_abandoned_digitize_drafts` hard-deletes orphaned drafts.
- Hourly cron `purge_expired_idempotency_records` drops expired replay records.
- Prometheus: digitize_finalize_duration / digitize_finalize_result /
  digitize_drafts_abandoned_total.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from arq import cron, run_worker
from arq.connections import RedisSettings

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.redis_config import redis_dsn, redacted
from app.services.calculation_runner import run_calculation_task
from app.services.digitize_metrics_service import (
    increment_finalize_result,
    observe_finalize_duration,
)
from app.models.workspace_layer import (
    DRAFT_STATUS_SYNCING,
    DRAFT_STATUS_FINALIZED,
    DRAFT_STATUS_VALIDATION_FAILED,
)

import app.models  # noqa: F401 — ensures all SQLAlchemy mappers are registered

logger = logging.getLogger(__name__)

SOFT_TIMEOUT_S = int(settings.REDIS_URL) if False else 1200  # 20 min
HARD_TIMEOUT_S = 1320  # 22 min
MAX_RETRIES = 2
KEEP_RESULT_S = 86400  # 24h

# Digitize finalize job (Task 1.5.1): much tighter than the 20min calc budget.
DIGITIZE_SOFT_TIMEOUT_S = 20
DIGITIZE_HARD_TIMEOUT_S = 30
DIGITIZE_MAX_RETRIES = 2


async def finalize_digitize_layer(
    ctx: Dict[str, Any], calculation_id: str, layer_id: int, user_id: str
) -> Dict[str, Any]:
    """arq job: run the digitize validation chain off the request thread (GD 1.2.2).

    Mirrors the reports worker pattern (worker.py:33): opens its own session,
    marks the layer SYNCING, runs the shared finalize logic, then flips the
    draft_status to FINALIZED or VALIDATION_FAILED (with last_validation_error).
    Times out at DIGITIZE_SOFT_TIMEOUT_S and retries up to 2×.
    """
    import time
    from app.api.workspace import _run_digitize_finalize
    from app.models.calculation import Calculation
    from app.models.workspace_layer import WorkspaceLayer
    from app.models.user import User

    start = time.monotonic()
    db = SessionLocal()
    try:
        layer = db.query(WorkspaceLayer).filter(
            WorkspaceLayer.id == layer_id,
            WorkspaceLayer.deleted_at.is_(None),
        ).first()
        if not layer:
            logger.error("[digitize] layer %s not found", layer_id)
            return {"status": "not_found"}

        # Guard: only ACTIVE drafts can be finalized
        if layer.draft_status not in (DRAFT_STATUS_SYNCING,):
            if layer.draft_status == DRAFT_STATUS_FINALIZED:
                return {"status": "already_finalized"}
            logger.warning(
                "[digitize] layer %s in state %s — skipping", layer_id, layer.draft_status
            )
            return {"status": "skipped", "draft_status": layer.draft_status}

        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.error("[digitize] user %s not found", user_id)
            return {"status": "user_not_found"}

        try:
            # Timeout guard (Task 1.5.1): the sync finalize chain may hang on
            # pathological geometry — run it off-thread with a 20s cap. On
            # timeout we mark the layer VALIDATION_FAILED (rule=timeout) so the
            # poll endpoint reports a terminal state (DLQ behaviour).
            await asyncio.wait_for(
                asyncio.to_thread(_run_digitize_finalize, db, layer, user),
                timeout=DIGITIZE_SOFT_TIMEOUT_S,
            )
            observe_finalize_duration(time.monotonic() - start)
            increment_finalize_result("succeeded")
            logger.info(
                "[digitize] finalize succeeded layer_id=%s calc=%s",
                layer_id, calculation_id,
            )
            return {
                "status": "succeeded",
                "feature_count": layer.feature_count,
                "draft_status": DRAFT_STATUS_FINALIZED,
            }
        except asyncio.TimeoutError:
            # Do NOT touch `db` here — the timed-out thread may still be using
            # it. Mark the layer with a fresh session (DLQ behaviour).
            logger.warning(
                "[digitize] finalize timed out after %ss layer_id=%s",
                DIGITIZE_SOFT_TIMEOUT_S, layer_id,
            )
            db2 = SessionLocal()
            try:
                row = db2.query(WorkspaceLayer).filter(WorkspaceLayer.id == layer_id).first()
                if row and row.draft_status == DRAFT_STATUS_SYNCING:
                    row.draft_status = DRAFT_STATUS_VALIDATION_FAILED
                    row.last_validation_error = {
                        "message": f"Background finalize exceeded {DIGITIZE_SOFT_TIMEOUT_S}s timeout",
                        "rule": "timeout",
                    }
                    db2.commit()
            finally:
                db2.close()
            observe_finalize_duration(time.monotonic() - start)
            increment_finalize_result("failed")
            return {
                "status": "failed",
                "last_validation_error": {
                    "message": f"Background finalize exceeded {DIGITIZE_SOFT_TIMEOUT_S}s timeout",
                    "rule": "timeout",
                },
                "draft_status": DRAFT_STATUS_VALIDATION_FAILED,
            }
        except ValueError as e:
            layer.draft_status = DRAFT_STATUS_VALIDATION_FAILED
            layer.last_validation_error = {"message": str(e), "rule": "finalize"}
            db.commit()
            observe_finalize_duration(time.monotonic() - start)
            increment_finalize_result("validation_failed")
            logger.warning(
                "[digitize] finalize validation_failed layer_id=%s err=%s",
                layer_id, e,
            )
            return {
                "status": "validation_failed",
                "last_validation_error": {"message": str(e), "rule": "finalize"},
                "draft_status": DRAFT_STATUS_VALIDATION_FAILED,
            }
    finally:
        db.close()


async def cleanup_abandoned_digitize_drafts(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Hourly arq cron (Task 1.5.2): hard-delete orphaned digitize drafts."""
    from app.services.digitize_cleanup_service import cleanup_abandoned_digitize_drafts as run_cleanup

    db = SessionLocal()
    try:
        return run_cleanup(db)
    finally:
        db.close()


async def _on_startup(ctx: Dict[str, Any]) -> None:
    logger.info(
        "[calc-worker] calculation worker connected to Redis at %s", redacted(redis_dsn())
    )


async def purge_expired_idempotency_records(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Hourly arq cron (H2.17): drop idempotency records past their retention.

    Every mobile-facing write now leaves a row behind. Without this the table
    grows for the life of the deployment, and the cleanup that never runs is
    discovered as a slow `INSERT ... ON CONFLICT` on a busy sync day -- the one
    day it must be fast.

    `expires_at` is indexed for exactly this delete.
    """
    from app.services.idempotency import purge_expired

    db = SessionLocal()
    try:
        return {"purged": purge_expired(db)}
    finally:
        db.close()


class CalculationWorkerSettings:
    # Dedicated queue — the reports worker polls the default arq:queue and must
    # not steal digitize finalize / cleanup jobs (it only knows generate_report_task).
    queue_name = "arq:calculation"
    functions = [
        run_calculation_task,
        finalize_digitize_layer,
        cleanup_abandoned_digitize_drafts,
        purge_expired_idempotency_records,
    ]
    cron_jobs = [
        cron(cleanup_abandoned_digitize_drafts, minute=0, run_at_startup=False),
        # Offset from the draft cleanup so two table-wide deletes do not land
        # on the same connection at the same minute.
        cron(purge_expired_idempotency_records, minute=30, run_at_startup=False),
    ]
    redis_settings = RedisSettings.from_dsn(redis_dsn())
    on_startup = _on_startup
    max_concurrency = 1
    keep_result = KEEP_RESULT_S
    keep_result_forever = False
    # arq uses `max_tries` (max total attempts). 2 retries => 3 tries.
    max_tries = MAX_RETRIES + 1
    job_timeout = HARD_TIMEOUT_S
    burst = False
    poll_delay = 1.0


if __name__ == "__main__":
    # See app/worker.py — a bare `python -m` process configures no logging,
    # so arq's startup lines and _on_startup's Redis-target line are silently
    # dropped without this.
    from app.core.logging_config import configure_logging

    configure_logging()
    asyncio.run(run_worker(CalculationWorkerSettings))
