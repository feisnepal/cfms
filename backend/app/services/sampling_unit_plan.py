"""One row per polygon for the sampling screen: what the polygon is, what the rules say about it, and whether it already has plots.

The sampling engines work on the UNDIVIDED units (the leaf view) and enforce a minimum intensity per stratum (कार्यविधि §16:
production 2 % / conservation 1 % / protection 0.5 %, plots of 500 / 500 / 100 m²). This module shows the same facts BEFORE a design
exists, for every forest, with no forest type and no plots needed:

* ``stratum`` + ``stratum_source`` come from ``stratum_spec.stratum_and_source`` - the very function the engines enforce with, so
  the screen and the 400 "below the floor" cannot disagree. A steep unit (slope band 4) is proposed as conservation; the user can
  set any stratum, which is saved as the unit's own ``management_orientation`` so SFM and the Operational Plan agree with it.
* ``sampled_plots`` counts the plots the forest's one design already holds in the polygon. A polygon that already has plots cannot be
  sampled again until those plots are deleted; the screen disables it and says what to do.

Read-only.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.calculation import Calculation
from app.models.sampling import SamplingDesign
from app.services.forest_units.sampling_view import sampling_units
from app.services.sustainable_fm.stratum_spec import (
    STRATUM_FLOOR_PCT,
    STRATUM_PLOT_SQM,
    stratum_and_source,
)


def sampled_plots_by_unit(design: SamplingDesign | None) -> Dict[str, int]:
    """``{unit name: plots}`` for the plots the design already holds."""
    counts: Dict[str, int] = {}
    for a in (design.points_block_assignment or []) if design is not None else []:
        name = a.get("block_name")
        if name:
            counts[name] = counts.get(name, 0) + 1
    return counts


#: A polygon with less forest than this (percent of its area) is flagged on the sampling screen: its accessible forest, and so its
#: plots, will be small however large the polygon is.
LOW_FOREST_PCT = 30.0


def landcover_summary(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The unit's stored land-cover analysis -> what the sampling screen shows: the dominant class and its share, the largest classes
    (``breakdown``, largest first) and the forest share. All ``None`` / empty when the unit has not been analysed."""
    pcts: Dict[str, float] = {}
    for k, v in ((raw or {}).get("landcover_percentages") or {}).items():
        try:
            pcts[str(k)] = float(v)
        except (TypeError, ValueError):
            continue
    if not pcts:
        return {"landcover_dominant": None, "landcover_dominant_pct": None, "landcover_breakdown": [], "forest_pct": None}
    ranked = sorted(pcts.items(), key=lambda kv: -kv[1])
    dominant = (raw or {}).get("landcover_dominant") or ranked[0][0]
    return {
        "landcover_dominant": str(dominant),
        "landcover_dominant_pct": round(pcts.get(str(dominant), ranked[0][1]), 1),
        "landcover_breakdown": [{"name": k, "pct": round(v, 1)} for k, v in ranked if v > 0][:6],
        "forest_pct": round(sum(v for k, v in pcts.items() if "forest" in k.lower()), 1),
    }


def unit_plan(db: Session, calculation: Calculation) -> Dict[str, Any]:
    design = db.query(SamplingDesign).filter(SamplingDesign.calculation_id == calculation.id).first()
    sampled = sampled_plots_by_unit(design)
    sub_areas = (calculation.result_data or {}).get("sub_areas", []) or []
    from app.services.unit_analysis_service import raw_by_unit_id

    analysed = raw_by_unit_id(db, calculation.id)

    units: List[Dict[str, Any]] = []
    for u in sampling_units(db, calculation):
        stratum, source = stratum_and_source(
            u["name"], u["wkt"], u["working_circle"], u["management_orientation"], u["sfm_orientation"], u["slope_band"], sub_areas
        )
        units.append(
            {
                "unit_id": u["unit_id"],
                "name": u["name"],
                "display_name": u.get("display_name") or u["name"],
                "area_ha": round(u["area_ha"], 2),
                "slope_band": u["slope_band"],
                "stratum": stratum,
                "stratum_source": source,
                "management_orientation": u["management_orientation"],
                "floor_pct": STRATUM_FLOOR_PCT[stratum],
                "plot_size_sqm": STRATUM_PLOT_SQM[stratum],
                "sampled_plots": sampled.get(u["name"], 0),
                **landcover_summary(analysed.get(str(u["unit_id"]))),
            }
        )
    return {
        "state": "ready" if units else "no_units",
        "design_id": str(design.id) if design is not None else None,
        "units": units,
    }


#: The system always SUGGESTS at least this many plots per polygon (कार्यविधि §16's flat per-unit floor). A user may type fewer; they are
#: told. The legal limit that cannot be broken is the stratum's minimum INTENSITY, not this number.
MIN_SUGGESTED_PLOTS = 5
SQM_PER_HA = 10_000.0


def count_from_intensity(db: Session, area_ha: float, intensity_pct: float, plot_size_sqm: float, method: str) -> int:
    """How many plots an intensity amounts to for a polygon - the engines' own arithmetic. Guideline-2061 uses the Department of
    Forest lookup table where one exists and the area x intensity / plot size formula otherwise; the intensity engine always
    uses the formula."""
    if intensity_pct <= 0 or area_ha <= 0:
        return 0
    if method == "guideline":
        try:
            from app.services.guideline_sampling import get_sample_count_from_guideline

            with db.begin_nested():  # a missing lookup table must roll back just this query
                return int(get_sample_count_from_guideline(db=db, block_area_hectares=area_ha, intensity_percent=intensity_pct, plot_size_sqm=plot_size_sqm))
        except Exception:  # noqa: BLE001 -- out of the table's range / no table: the formula below is what the engine falls back to too
            pass
    return int((area_ha * (intensity_pct / 100.0)) / (plot_size_sqm / SQM_PER_HA))


def suggested_counts(db: Session, calculation: Calculation, intensities: Dict[str, float], method: str) -> Dict[str, Any]:
    """For each polygon: the plots its intensity amounts to (``computed``), the number we SUGGEST (never fewer than 5, unless the
    polygon is excluded at 0), the intensity that suggestion amounts to, and the legal range of plots for the polygon.

    An estimate: it works from the polygon's area. With the tree-cover filter on, the engine counts accessible area, so the exact
    layout is what "Preview sample plots" shows; a number the user types is what the engine then places.
    """
    out: Dict[str, Any] = {}
    for u in unit_plan(db, calculation)["units"]:
        pct = float(intensities.get(u["name"], u["floor_pct"]) or 0.0)
        area, plot = float(u["area_ha"]), float(u["plot_size_sqm"])
        computed = count_from_intensity(db, area, pct, plot, method)
        suggested = 0 if pct <= 0 else max(computed, MIN_SUGGESTED_PLOTS)
        per_plot_pct = (plot / (area * SQM_PER_HA) * 100.0) if area > 0 else 0.0  # intensity one plot amounts to
        out[u["name"]] = {
            "area_ha": area,
            "plot_size_sqm": plot,
            "intensity_pct": pct,
            "computed": computed,
            "suggested": suggested,
            "raised_to_minimum": suggested > computed,
            "equivalent_pct": round(suggested * per_plot_pct, 3),
            # the legal range of plots: at least the stratum's minimum intensity, at most the 5 % ceiling
            "min_plots_legal": math.ceil(u["floor_pct"] / per_plot_pct - 1e-9) if per_plot_pct > 0 else 0,
            "max_plots_legal": int(5.0 / per_plot_pct + 1e-9) if per_plot_pct > 0 else 0,
        }
    return {"minimum_suggested": MIN_SUGGESTED_PLOTS, "units": out}
