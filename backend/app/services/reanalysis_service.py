"""Re-run the analysis of a calculation and save it -- the one implementation behind the Re-run Analysis button and the
workspace's "Update attribute" command, so the two can never differ.

``analysis_options`` is already merged (stored options overlaid with the caller's). On failure the calculation is marked FAILED and
the exception is re-raised for the caller to turn into its own error.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..models.calculation import Calculation, CalculationStatus
from ..utils.json_utils import sanitize_for_json
from .analysis import analyze_forest_boundary

logger = logging.getLogger(__name__)


async def run_reanalysis(db: Session, calculation: Calculation, analysis_options: Dict[str, Any]) -> None:
    calculation_id = calculation.id
    # Update calculation status to PROCESSING
    calculation.status = CalculationStatus.PROCESSING
    calculation.error_message = None
    db.commit()

    # Run analysis with new options
    try:
        logger.info(f"Starting re-analysis for calculation {calculation_id}")
        logger.info(f"Analysis options: {analysis_options}")

        analysis_results, processing_time = await analyze_forest_boundary(
            calculation_id, db, options=analysis_options
        )
        logger.info(f"Re-analysis completed with {len(analysis_results)} keys")

        # Record a cost estimate for this run -- same model as the main calculation pipeline, so re-analyses also show up
        # in the super-admin /admin/costs per-forest report. Best-effort: a tracking failure must not fail the re-analysis.
        try:
            from .calculation_cost_service import CalculationCostTracker

            CalculationCostTracker(db, calculation_id).finalize(
                cpu_seconds=float(processing_time or 0.0),
                peak_memory_mb=256.0,
            )
        except Exception as cost_err:  # noqa: BLE001 -- best effort, logged
            logger.warning(f"Re-analysis cost tracking failed: {cost_err}")

        # Preserve ALL existing result_data keys, then overlay new analysis results (a shallow copy keeps 'compartments',
        # 'total_compartments', 'polygon_type' and any future additions -- no whitelist).
        result_data = dict(calculation.result_data or {})
        result_data.update(analysis_results)

        # This re-run IS the answer to `structure_stale['analysis']`; without clearing it the flag is write-only.
        stale = result_data.get("structure_stale")
        if isinstance(stale, dict):
            stale = {**stale, "analysis": False}
            if not any(stale.get(d) for d in ("analysis", "sampling", "field_inventory")):
                del result_data["structure_stale"]
            else:
                result_data["structure_stale"] = stale

        # Sanitize data to remove NaN/Infinity values before JSON serialization
        sanitized_result_data = sanitize_for_json(result_data)
        sanitized_analysis_options = sanitize_for_json(analysis_options)

        db.execute(
            text(
                """
            UPDATE public.calculations
            SET
                result_data = CAST(:result_data AS jsonb),
                analysis_options = CAST(:analysis_options AS jsonb),
                processing_time_seconds = :processing_time,
                status = :status,
                completed_at = NOW()
            WHERE id = :calc_id
        """
            ),
            {
                "result_data": json.dumps(sanitized_result_data),
                "analysis_options": json.dumps(sanitized_analysis_options),
                "processing_time": processing_time,
                "status": "COMPLETED",
                "calc_id": str(calculation_id),
            },
        )
        db.commit()
        logger.info("Re-analysis update successful")
    except Exception as e:
        db.rollback()
        logger.error(f"Re-analysis failed: {str(e)}")
        # Update status to FAILED
        try:
            calculation.status = CalculationStatus.FAILED
            calculation.error_message = f"Re-analysis failed: {str(e)[:500]}"
            db.commit()
        except Exception as commit_error:  # noqa: BLE001 -- logged; the original error is re-raised below
            logger.error(f"Failed to update error status: {commit_error}")
            db.rollback()
        raise
