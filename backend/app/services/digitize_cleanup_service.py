"""Abandoned-draft cleanup (Task 1.5.2 / Gap 1.2).

Hourly arq cron hard-deletes orphaned digitize drafts:
- (draft_status='discarded' AND updated_at < now()-7d)
- OR (feature_count=0 AND created_at < now()-1d)

Guards:
- Only digitize-purpose layers (source_format='digitize') — never import layers.
- Runs in its own transaction, batch-limited (default 500/run).
- Emits `digitize_drafts_abandoned_total` per batch (via digitize_metrics_service).
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models.workspace_layer import WorkspaceLayer, DRAFT_STATUS_DISCARDED

logger = logging.getLogger(__name__)

DISCARDED_AGE_DAYS = 7
EMPTY_AGE_DAYS = 1
DEFAULT_BATCH_LIMIT = 500


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def count_abandoned_digitize_drafts(db: Session, *, now: Optional[datetime] = None) -> int:
    """Return how many digitize drafts currently qualify as abandoned."""
    now = now or _utcnow()
    cutoff_discarded = now - timedelta(days=DISCARDED_AGE_DAYS)
    cutoff_empty = now - timedelta(days=EMPTY_AGE_DAYS)
    return (
        db.query(WorkspaceLayer)
        .filter(WorkspaceLayer.source_format == "digitize")
        .filter(
            ((WorkspaceLayer.draft_status == DRAFT_STATUS_DISCARDED)
             & (WorkspaceLayer.updated_at < cutoff_discarded))
            | ((WorkspaceLayer.feature_count == 0)
               & (WorkspaceLayer.created_at < cutoff_empty))
        )
        .count()
    )


def cleanup_abandoned_digitize_drafts(
    db: Session,
    *,
    now: Optional[datetime] = None,
    batch_limit: int = DEFAULT_BATCH_LIMIT,
) -> dict:
    """Hard-delete abandoned digitize drafts up to batch_limit. Returns a summary.

    - Emits `digitize_drafts_abandoned_total` per deleted batch.
    - Commits its own transaction (safe to call from the arq cron or directly).
    - Never touches non-digitize (import) layers.
    """
    from ..services.digitize_metrics_service import increment_abandoned_drafts

    now = now or _utcnow()
    cutoff_discarded = now - timedelta(days=DISCARDED_AGE_DAYS)
    cutoff_empty = now - timedelta(days=EMPTY_AGE_DAYS)

    targets = (
        db.query(WorkspaceLayer)
        .filter(WorkspaceLayer.source_format == "digitize")
        .filter(
            ((WorkspaceLayer.draft_status == DRAFT_STATUS_DISCARDED)
             & (WorkspaceLayer.updated_at < cutoff_discarded))
            | ((WorkspaceLayer.feature_count == 0)
               & (WorkspaceLayer.created_at < cutoff_empty))
        )
        .limit(max(1, batch_limit))
        .all()
    )

    deleted = 0
    for layer in targets:
        db.delete(layer)
        deleted += 1

    if deleted:
        db.commit()
        increment_abandoned_drafts(deleted)
        logger.info(
            "digitize_cleanup_deleted",
            extra={"count": deleted, "batch_limit": batch_limit},
        )
    else:
        db.rollback()

    return {"deleted": deleted, "batch_limit": batch_limit, "remaining": None}


async def cleanup_abandoned_digitize_drafts_cron(ctx) -> dict:
    """arq cron entrypoint (hourly): opens its own session and runs the cleanup.

    Kept separate from the pure function so unit tests never need arq/Redis.
    """
    from ..core.database import SessionLocal

    db = SessionLocal()
    try:
        return cleanup_abandoned_digitize_drafts(db)
    finally:
        db.close()
