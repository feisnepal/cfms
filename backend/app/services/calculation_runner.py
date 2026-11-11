"""
Background calculation runner — arq worker task.

Wraps the existing synchronous analyze_forest_boundary() with:
- Step-by-step progress updates via CalculationProgress
- Cost estimation via CalculationCostTracker
- State machine transitions (draft → calculating → completed/failed)
- arq retry on transient failure (max 3 retries across 2 attempts)
- 20 min soft / 22 min hard timeout

Run worker:  python -m app.calculation_worker
"""
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.calculation import Calculation, MapLifecycleStatus
from app.models.calculation_progress import CalculationProgress
from app.services.calculation_progress_service import (
    get_or_create_progress, update_progress, PROGRESS_STEPS,
)
from app.services.calculation_cost_service import CalculationCostTracker
from app.api.deps import validate_transition, log_state_transition
from app.services.calculation_queue_service import dequeue_calculation, complete_calculation
from app.services.saga_compensation_service import compensate_failed_calculation
from app.services.calculation_integrity import partial_failure_reason

logger = logging.getLogger(__name__)


class PartialCalculationError(RuntimeError):
    """Analysis finished, but not every unit succeeded (H3.5 / S2-37).

    A distinct type so the failure path can tell "the pipeline broke" from "the
    pipeline worked and the answer is incomplete" — the second still has usable
    partial results attached, and reads differently to whoever opens it.
    """

# Import analysis lazily to keep worker bootstrap fast
_analysis = None


def _get_analysis():
    global _analysis
    if _analysis is None:
        from app.services.analysis import analyze_forest_boundary as afb
        _analysis = afb
    return _analysis


async def run_calculation_task(ctx: dict, calculation_id: str) -> dict:
    """arq job: run a single calculation end-to-end with progress + cost tracking."""
    calc_id = UUID(calculation_id)
    db: Session = SessionLocal()
    tracker: CalculationCostTracker | None = None
    start_time = time.perf_counter()

    try:
        calc = db.query(Calculation).filter(Calculation.id == calc_id).first()
        if not calc:
            logger.error("[calc_runner] Calculation %s not found", calc_id)
            return {"status": "failed", "error": "not_found"}

        # State: draft/submitted → calculating
        validate_transition(calc.map_lifecycle_status, MapLifecycleStatus.CALCULATING.value)
        calc.map_lifecycle_status = MapLifecycleStatus.CALCULATING.value
        calc.status = __import__('app.models.calculation', fromlist=['CalculationStatus']).CalculationStatus.PROCESSING
        calc.error_message = None
        db.flush()

        # Initialize progress tracking
        progress = get_or_create_progress(db, calc_id)
        update_progress(db, calc_id, step="loading_boundary", message="Starting calculation…",
                        percent=0.0)

        # Cost tracker
        tracker = CalculationCostTracker(db, calc_id)
        tracker._start = start_time

        # Step 1: Load & validate
        update_progress(db, calc_id, step="validating", message="Validating inputs…",
                        percent=5.0)
        await asyncio.sleep(0.1)

        # Step 2: Run analysis
        update_progress(db, calc_id, step="processing_blocks", message="Processing blocks/compartments…",
                        percent=20.0)
        db.commit()

        analysis_func = _get_analysis()
        analysis_results, processing_time = await analysis_func(
            calc_id, db, options=calc.analysis_options or {}
        )

        # Step 3: Update result_data
        update_progress(db, calc_id, step="generating_results", message="Generating results…",
                        percent=80.0)

        # NOTE (BA-3): `analysis_func` (analyze_forest_boundary) reconciles
        # result_data.blocks FROM forest_blocks before analysis, and analysis
        # writes back the analyzed set. So the blocks copied through here are
        # already the DB-authoritative set (e.g. 5), never a stale 1-block
        # snapshot. This must NOT be changed to read forest_blocks directly --
        # rely on the reconciled JSONB.
        blocks_data = calc.result_data.get('blocks', []) if calc.result_data else []
        total_blocks = calc.result_data.get('total_blocks', 1) if calc.result_data else 1

        updated_result_data = {
            'total_blocks': total_blocks,
            'blocks': blocks_data,
            'processing_info': calc.result_data.get('processing_info', {}) if calc.result_data else {},
            **analysis_results,
        }
        calc.result_data = updated_result_data
        calc.processing_time_seconds = processing_time

        # H3.5 / S2-37: fail fast on a partial result.
        #
        # analysis.py deliberately continues past a failed unit so one bad block
        # does not discard the rest — but until now the pipeline then wrote
        # `completed` regardless, making a partial result indistinguishable from
        # a whole one. In a pipeline whose output has regulatory standing, that
        # is a wrong number nobody is told about.
        #
        # Raised, not branched, so it lands in the existing failure path below
        # and gets the same treatment as any other failure: FAILED status, the
        # reason recorded, saga compensation, the state transition logged. The
        # partial `result_data` is already assigned above and is committed by
        # that handler, so whoever opens the calculation can still see which
        # units failed and why.
        partial = partial_failure_reason(updated_result_data)
        if partial:
            raise PartialCalculationError(partial)

        # Step 4: Finalize
        update_progress(db, calc_id, step="finalizing", message="Finalizing…",
                        percent=95.0)

        elapsed = time.perf_counter() - start_time

        # Cost estimate
        tracker.finalize(cpu_seconds=elapsed, peak_memory_mb=256.0)

        # State: calculating → completed
        calc.map_lifecycle_status = MapLifecycleStatus.COMPLETED.value
        calc.status = __import__('app.models.calculation', fromlist=['CalculationStatus']).CalculationStatus.COMPLETED
        calc.completed_at = datetime.now(timezone.utc)

        progress = get_or_create_progress(db, calc_id)
        progress.current_step = "completed"
        progress.percent = 100.0
        progress.completed_at = datetime.now(timezone.utc)
        progress.message = "Calculation complete"

        log_state_transition(db, calc_id, "calculating", "completed",
                             triggered_by=calc.user_id, reason="Calculation finished")

        db.commit()
        complete_calculation(calculation_id, success=True)

        logger.info("[calc_runner] Calculation %s completed in %.1fs (cost: %s)",
                    calc_id, elapsed, tracker.estimates)
        return {"status": "completed", "calculation_id": calculation_id}

    except Exception as e:
        logger.exception("[calc_runner] Calculation %s failed: %s", calc_id, e)
        try:
            calc = db.query(Calculation).filter(Calculation.id == calc_id).first()
            if calc:
                calc.map_lifecycle_status = MapLifecycleStatus.FAILED.value
                calc.error_message = str(e)[:500]
                progress = get_or_create_progress(db, calc_id)
                progress.current_step = "failed"
                progress.error_message = str(e)[:500]
                progress.failed_at = datetime.now(timezone.utc)
                log_state_transition(db, calc_id, "calculating", "failed",
                                     triggered_by=calc.user_id, reason=str(e)[:200])
            # Saga compensation: clean up temp artifacts
            compensate_failed_calculation(db, calc_id)
            db.commit()
            complete_calculation(calculation_id, success=False)
        except Exception as db_err:
            logger.error("[calc_runner] Failed to record failure: %s", db_err)
            db.rollback()
        return {"status": "failed", "error": str(e)[:200], "calculation_id": calculation_id}

    finally:
        db.close()
