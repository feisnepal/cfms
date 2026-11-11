"""Resource tracking and monetary cost estimation for calculations.

Tracks CPU time and peak memory, converts to cost using configurable rates.
Stores results in Calculation.cost_estimate JSONB.
"""
import os
import time
import threading
from uuid import UUID
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import cast, func
from sqlalchemy.orm import Session

from app.models.calculation import Calculation

# ---------------------------------------------------------------------------
# Configurable rates (override via env vars)
# ---------------------------------------------------------------------------
# Model: Google-Cloud pay-as-you-go (on-demand) — vCPU and GB-RAM billed
# separately, per unit per hour. These defaults are INDICATIVE conservative
# blended rates, NOT live GCP prices. To price at real Google E2 on-demand
# (us-central1), set via env, e.g.:
#   CALC_CPU_COST_PER_HOUR=0.0338   (USD per CPU-hour)
#   CALC_MEMORY_COST_PER_GB_HOUR=0.0046  (USD per GB-RAM-hour)
# GCP changes prices; do NOT hardcode a rate map here. See
# cost_estimation_report.md for the full pay-as-you-go model.
CPU_COST_PER_HOUR = float(os.environ.get("CALC_CPU_COST_PER_HOUR", "0.10"))    # USD per CPU-hour
MEMORY_COST_PER_GB_HOUR = float(os.environ.get("CALC_MEMORY_COST_PER_GB_HOUR", "0.05"))  # USD per GB-RAM-hour
CURRENCY = os.environ.get("CALC_COST_CURRENCY", "USD")


def default_rates() -> dict:
    return {
        "cpu_cost_per_hour": CPU_COST_PER_HOUR,
        "memory_cost_per_gb_hour": MEMORY_COST_PER_GB_HOUR,
        "currency": CURRENCY,
    }


# ---------------------------------------------------------------------------
# Context manager — wraps a calculation run, tracks wall-clock time
# ---------------------------------------------------------------------------

class CalculationCostTracker:
    """Records elapsed time + estimates cost when used as a context manager.
    
    Usage:
        with CalculationCostTracker(db, calc_id) as tracker:
            ... run calculation ...
        # tracker.finalize() called automatically on __exit__
    """

    def __init__(self, db: Session, calculation_id: UUID):
        self.db = db
        self.calculation_id = calculation_id
        self._start = 0.0
        self._peak_memory_mb = 0.0
        self._estimates: dict[str, Any] | None = None

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed = time.perf_counter() - self._start
        success = exc_type is None
        self.finalize(elapsed, success=success)

    def record_memory(self, memory_mb: float):
        if memory_mb > self._peak_memory_mb:
            self._peak_memory_mb = memory_mb

    def finalize(self, cpu_seconds: float = 0.0, peak_memory_mb: float = 0.0, success: bool = True):
        """Compute and persist cost estimate."""
        if cpu_seconds <= 0:
            cpu_seconds = self._peak_memory_mb  # fallback placeholder
        if peak_memory_mb <= 0:
            peak_memory_mb = self._peak_memory_mb

        cpu_hours = cpu_seconds / 3600.0
        memory_gb = peak_memory_mb / 1024.0
        memory_gb_hours = memory_gb * cpu_hours

        cpu_cost = round(cpu_hours * CPU_COST_PER_HOUR, 6)
        memory_cost = round(memory_gb_hours * MEMORY_COST_PER_GB_HOUR, 6)
        total = round(cpu_cost + memory_cost, 6)

        self._estimates = {
            "cpu_seconds": round(cpu_seconds, 3),
            "peak_memory_mb": round(peak_memory_mb, 1),
            "cpu_cost": cpu_cost,
            "memory_cost": memory_cost,
            "total_cost": total,
            "currency": CURRENCY,
            "rates_applied": {
                "cpu_cost_per_hour": CPU_COST_PER_HOUR,
                "memory_cost_per_gb_hour": MEMORY_COST_PER_GB_HOUR,
            },
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }

        calc = self.db.query(Calculation).filter(Calculation.id == self.calculation_id).first()
        if calc:
            calc.cost_estimate = dict(self._estimates)
            self.db.flush()

    @property
    def estimates(self) -> dict[str, Any] | None:
        return self._estimates


def get_cost_estimate(calc: Calculation) -> dict | None:
    """Return the stored cost estimate, or None."""
    if not calc or not calc.cost_estimate:
        return None
    return dict(calc.cost_estimate) if isinstance(calc.cost_estimate, dict) else calc.cost_estimate


# ---------------------------------------------------------------------------
# Super-admin per-forest cost aggregation (Google pay-as-you-go model)
# ---------------------------------------------------------------------------

def forest_cost_report(db: Session) -> list[dict]:
    """Aggregated pay-as-you-go compute cost per forest.

    A forest is a Calculation with forest_name; cost per forest =
    SUM(cost_estimate.total_cost) grouped by forest. total_peak_memory_mb is a
    SUM of each calculation's peak (CUMULATIVE, not simultaneous usage) — the
    UI labels the column "Σ Peak Mem (GB)".

    Currency is assumed uniform per forest; MAX() selects the non-null value.
    Rows with NULL/blank forest_name fall back to the calculation id (COALESCE).
    Rows with no cost_estimate are excluded.
    """
    ce = Calculation.cost_estimate
    forest = func.coalesce(func.nullif(Calculation.forest_name, ""), cast(Calculation.id, sa.String))

    rows = (
        db.query(
            forest.label("forest_name"),
            func.count(Calculation.id).label("calculation_count"),
            func.coalesce(func.sum(cast(ce["cpu_seconds"].astext, sa.Float)), 0).label("total_cpu_seconds"),
            func.coalesce(func.sum(cast(ce["peak_memory_mb"].astext, sa.Float)), 0).label("total_peak_memory_mb"),
            func.coalesce(func.sum(cast(ce["cpu_cost"].astext, sa.Float)), 0).label("total_cpu_cost"),
            func.coalesce(func.sum(cast(ce["memory_cost"].astext, sa.Float)), 0).label("total_memory_cost"),
            func.coalesce(func.sum(cast(ce["total_cost"].astext, sa.Float)), 0).label("total_cost"),
            func.max(ce["currency"].astext).label("currency"),
            func.max(Calculation.completed_at).label("last_run_at"),
        )
        .filter(Calculation.cost_estimate.isnot(None))
        .group_by(forest)
        .order_by(func.sum(cast(ce["total_cost"].astext, sa.Float)).desc())
        .all()
    )

    return [
        {
            "forest_name": r.forest_name,
            "calculation_count": r.calculation_count,
            "total_cpu_seconds": round(r.total_cpu_seconds, 3),
            "total_peak_memory_mb": round(r.total_peak_memory_mb, 1),
            "total_cpu_cost": r.total_cpu_cost,
            "total_memory_cost": r.total_memory_cost,
            "total_cost": r.total_cost,
            "currency": r.currency,
            "last_run_at": r.last_run_at,
        }
        for r in rows
    ]
