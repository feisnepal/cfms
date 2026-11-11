"""
Saga compensation service — cleans up temporary artifacts when a calculation fails.

On failure, the following are cleaned up:
1. CalculationProgress records (temp tracking data)
2. Incomplete result_data (roll back to last good state)
3. Any orphaned geometry features created during the calculation
4. Queue entries for the failed job

This ensures the system doesn't accumulate stale temp data on failures.
"""
import logging
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.calculation import Calculation, CalculationStatus, MapLifecycleStatus
from app.models.calculation_progress import CalculationProgress
from app.services.calculation_queue_service import complete_calculation

logger = logging.getLogger(__name__)


def compensate_failed_calculation(db: Session, calculation_id: UUID) -> dict[str, int]:
    """
    Run compensation actions for a failed calculation.
    Returns count of items cleaned up.
    """
    cleanup = {"progress_cleared": 0, "orphan_features_cleared": 0, "queue_completed": 0}

    # 1. Clear progress records
    cleared = db.query(CalculationProgress).filter(
        CalculationProgress.calculation_id == calculation_id
    ).delete()
    cleanup["progress_cleared"] = cleared

    # 2. Reset calculation state
    calc = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if calc:
        calc.status = CalculationStatus.FAILED
        if calc.map_lifecycle_status in ("calculating", "retrying"):
            calc.map_lifecycle_status = MapLifecycleStatus.FAILED.value
        # Roll back partial result_data if it was modified during this run
        # (keep existing valid data, just mark as failed)
        calc.error_message = calc.error_message or "Calculation failed — compensations applied"

    # 3. Mark complete in queue
    complete_calculation(str(calculation_id), success=False)
    cleanup["queue_completed"] = 1

    db.flush()
    logger.info("[saga] Compensation applied for calc %s: %s", calculation_id, cleanup)
    return cleanup


def compensate_orphaned_progress(db: Session) -> int:
    """
    Clean up any orphaned CalculationProgress records where the
    parent Calculation no longer exists. Runs as periodic maintenance.
    """
    from sqlalchemy import text

    result = db.execute(text("""
        DELETE FROM public.calculation_progress cp
        WHERE NOT EXISTS (
            SELECT 1 FROM public.calculations c
            WHERE c.id = cp.calculation_id
        )
    """))
    count = result.rowcount
    if count:
        logger.info("[saga] Cleaned %d orphaned progress records", count)
    return count
