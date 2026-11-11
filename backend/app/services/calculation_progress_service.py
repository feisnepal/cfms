"""Calculation progress tracking helpers."""
from uuid import UUID
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.calculation_progress import CalculationProgress

PROGRESS_STEPS: list[dict] = [
    {"step": "validating", "label": "Validating inputs", "weight": 5},
    {"step": "loading_boundary", "label": "Loading boundary data", "weight": 5},
    {"step": "processing_blocks", "label": "Processing blocks/compartments", "weight": 15},
    {"step": "computing_sub_areas", "label": "Computing sub-areas", "weight": 20},
    {"step": "computing_activity_features", "label": "Computing activity features", "weight": 15},
    {"step": "generating_results", "label": "Generating results", "weight": 10},
    {"step": "finalizing", "label": "Finalizing", "weight": 5},
]

TOTAL_WEIGHT = sum(s["weight"] for s in PROGRESS_STEPS)


def get_or_create_progress(db: Session, calculation_id: UUID) -> CalculationProgress:
    progress = db.query(CalculationProgress).filter(
        CalculationProgress.calculation_id == calculation_id
    ).first()
    if not progress:
        progress = CalculationProgress(
            calculation_id=calculation_id,
            current_step="pending",
            step_index=0,
            total_steps=len(PROGRESS_STEPS),
            percent=0.0,
        )
        db.add(progress)
        db.flush()
    return progress


def update_progress(
    db: Session,
    calculation_id: UUID,
    step: str | None = None,
    message: str | None = None,
    percent: float | None = None,
    error: str | None = None,
) -> CalculationProgress:
    progress = get_or_create_progress(db, calculation_id)

    if step:
        progress.current_step = step
        for i, s in enumerate(PROGRESS_STEPS):
            if s["step"] == step:
                progress.step_index = i
                progress.step_label = s["label"]
                break

    if message:
        progress.message = message
    if percent is not None:
        progress.percent = min(max(percent, 0.0), 100.0)
    if error:
        progress.error_message = error
        progress.failed_at = datetime.now(timezone.utc)

    if progress.current_step == "pending" and not progress.started_at:
        progress.started_at = datetime.now(timezone.utc)

    db.flush()
    return progress


def compute_percent_from_step(step_index: int, substep_pct: float = 0.0) -> float:
    weight_so_far = sum(s["weight"] for s in PROGRESS_STEPS[:step_index])
    current_weight = PROGRESS_STEPS[step_index]["weight"] if step_index < len(PROGRESS_STEPS) else 0
    return ((weight_so_far + current_weight * substep_pct / 100.0) / TOTAL_WEIGHT) * 100.0
