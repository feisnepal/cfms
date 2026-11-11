"""Advisory sampling-intensity plan for the SFM regime (P3).

``SUSTAINABLE_FOREST_MANAGEMENT_PLAN.md`` §5 P3.

The कार्यविधि §16 sets minimum sampling intensities: Production 2 % /
Conservation 1 % / Protection 0.5 % — higher than the DoF-2061 defaults the
SamplingTab uses. This module produces a **suggestion** (per block: stratum +
intensity + a plot count) surfaced in the SFM tab; SamplingTab stays
authoritative.

Stratum precedence (D11): a block majority-covered by a digitized ``protected``
sub-area / protection working circle → ``protection``; else the block's
orientation → Protection / Conservation / Production.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.calculation import Calculation
from app.services.sustainable_fm.sfm_config import SfmParams
from app.services.sustainable_fm.stratum_spec import (
    MIN_SAMPLES_PER_UNIT,
    STRATUM_PLOT_SQM,
    stratum_for_unit,
)

logger = logging.getLogger(__name__)

try:
    from app.services.guideline_sampling import (
        get_sample_count_from_guideline,
    )
except Exception:  # noqa: BLE001 -- keep working if the helpers move
    get_sample_count_from_guideline = None  # type: ignore[assignment]


def _plots(db: Session, area_ha: float, intensity_pct: float, plot_sqm: int) -> int:
    """DoF-2061 lookup where a table exists (0.5 % / 1 %), else the manual
    ``area × intensity / plot size`` with a floor of 2."""
    if get_sample_count_from_guideline is not None and intensity_pct in (0.5, 1.0):
        try:
            # SAVEPOINT: a missing DoF table (bare test DB) must roll back just
            # this query, not poison the caller's transaction.
            with db.begin_nested():
                n = get_sample_count_from_guideline(
                    db, area_ha, intensity_pct, plot_sqm
                )
            return int(n)
        except Exception:  # noqa: BLE001 -- out of range / missing table
            logger.debug(
                "guideline plot lookup failed; using manual count", exc_info=True
            )
    return max(MIN_SAMPLES_PER_UNIT, math.ceil(area_ha * 10_000.0 * (intensity_pct / 100.0) / plot_sqm))


def sfm_sampling_plan(
    blocks: list[dict[str, Any]],
    calc: Calculation,
    db: Session,
    params: SfmParams,
) -> list[dict[str, Any]]:
    """One row per block. ``blocks`` are the assembled ``sfm['blocks']`` dicts
    with ``orientation`` already set; each carries a private ``_wkt``."""
    sub_areas = (calc.result_data or {}).get("sub_areas", []) or []
    wc = {
        r.bn: r.wc
        for r in db.execute(
            text(
                "SELECT COALESCE(block_name, name) AS bn, "
                "COALESCE(working_circle, 'production') AS wc "
                "FROM forest_blocks WHERE calculation_id = :cid"
            ),
            {"cid": str(calc.id)},
        ).fetchall()
    }

    out: list[dict[str, Any]] = []
    for b in blocks:
        name = b["block_name"]
        area_ha = float(b.get("area_ha") or 0.0)
        wkt = b.get("_wkt")

        stratum = stratum_for_unit(
            name,
            wkt,
            wc.get(name),
            b.get("orientation"),
            sub_areas,
        )

        intensity = params.intensity_for(stratum)
        plot_sqm = STRATUM_PLOT_SQM[stratum]
        out.append(
            {
                "block_name": name,
                "stratum": stratum,
                "intensity_pct": intensity,
                "plot_size_sqm": plot_sqm,
                "plots": _plots(db, area_ha, intensity, plot_sqm),
            }
        )
    return out


__all__ = ["sfm_sampling_plan"]
