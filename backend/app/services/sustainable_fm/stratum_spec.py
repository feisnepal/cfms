"""Shared stratum classification for SFM कार्यविधि §16 sampling.

Constants (intensities, plot sizes, min-5 floor) plus two helpers:

* ``stratum_for_unit`` -- pure classifier (name + wkt + wc + orientation + sub_areas).
* ``classify_calc_units`` -- DB-aware batch: pulls forest_blocks & SFM result_data
  for a given calculation and returns ``{name: stratum}``.

Stratum precedence mirrors ``sampling_defaults.py:84-109`` (D11):

1. ``classify_block_by_majority_area(wkt, sub_areas)`` → ``"protection"``
2. ``working_circle == "protection"`` → ``"protection"``
3. ``orientation == "Protection"`` → ``"protection"``
4. ``orientation == "Conservation"`` → ``"conservation"``
5. else → ``"production"``
"""

from __future__ import annotations

import logging
from typing import Any, Sequence

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

try:
    from app.services.guideline_sampling import classify_block_by_majority_area
except Exception:  # noqa: BLE001
    classify_block_by_majority_area = None  # type: ignore[assignment]

# ── Constants ────────────────────────────────────────────────────────────
STRATUM_FLOOR_PCT: dict[str, float] = {
    "production": 2.0,
    "conservation": 1.0,
    "protection": 0.5,
}
STRATUM_PLOT_SQM: dict[str, int] = {
    "production": 500,
    "conservation": 500,
    "protection": 100,
}
MIN_SAMPLES_PER_UNIT: int = 5
STRATA = ("production", "conservation", "protection")


# ── Pure classifier ──────────────────────────────────────────────────────
def stratum_for_unit(
    name: str,
    wkt: str | None,
    working_circle: str | None,
    orientation: str | None,
    sub_areas: Sequence[dict[str, Any]] | None,
) -> str:
    """Return one of ``"production"`` / ``"conservation"`` / ``"protection"``.

    Precedence (D11):
    1. Sub-area majorityProtected → protection
    2. working_circle == "protection" → protection
    3. orientation == "Protection" → protection
    4. orientation == "Conservation" → conservation
    5. else → production
    """
    # 1. majority-protected sub-area
    if sub_areas and wkt and classify_block_by_majority_area is not None:
        try:
            if classify_block_by_majority_area(wkt, sub_areas):
                return "protection"
        except Exception:  # noqa: BLE001
            logger.debug(
                "majority-protected check failed for %s", name, exc_info=True
            )

    # 2. working-circle override
    if (working_circle or "").lower() == "protection":
        return "protection"

    # 3–4. orientation
    if orientation == "Protection":
        return "protection"
    if orientation == "Conservation":
        return "conservation"

    # 5. default
    return "production"


# ── The rule with its reason (used by the sampling screen AND the enforcement below, so they cannot disagree) ─────────────
SLOPE_STEEP_BAND = 4  # > 45 degrees


def stratum_and_source(
    name: str,
    wkt: str | None,
    working_circle: str | None,
    management_orientation: str | None,
    sfm_orientation: str | None,
    slope_band: int | None,
    sub_areas: Sequence[dict[str, Any]] | None,
) -> tuple[str, str]:
    """``(stratum, source)`` for one unit - the same precedence as :func:`stratum_for_unit`, plus a slope fallback and the reason.

    Needs no forest type, so a forest that has no plots yet (and therefore no SFM classification) still gets a stratum for every
    unit. Precedence:

    1. majority-protected sub-area            -> protection   (``protected_area``)
    2. protection working circle              -> protection   (``working_circle``)
    3. the unit's own orientation (user set)  -> that stratum (``user``)
    4. SFM's orientation for the unit         -> that stratum (``sfm``)
    5. steep slope (band 4, > 45 deg)         -> conservation (``slope``; owner rule 2026-09-14, every type)
    6. otherwise                              -> production   (``default``)
    """
    if sub_areas and wkt and classify_block_by_majority_area is not None:
        try:
            if classify_block_by_majority_area(wkt, sub_areas):
                return "protection", "protected_area"
        except Exception:  # noqa: BLE001
            logger.debug("majority-protected check failed for %s", name, exc_info=True)
    if (working_circle or "").lower() == "protection":
        return "protection", "working_circle"
    for orientation, source in ((management_orientation, "user"), (sfm_orientation, "sfm")):
        if orientation == "Protection":
            return "protection", source
        if orientation == "Conservation":
            return "conservation", source
        if orientation:  # Production, Restoration, Multi-use ...: production sampling
            return "production", source
    if slope_band == SLOPE_STEEP_BAND:
        return "conservation", "slope"
    return "production", "default"


# ── DB-aware batch classifier ───────────────────────────────────────────
def classify_calc_units(
    db: Session,
    calculation_id: str | Any,
    units: list[tuple[int, str | None, str, float]],
) -> dict[str, str]:
    """Classify every calculation unit and return ``{unit_name: stratum}``.

    *units* are the ``(number, wkt, name, area_ha)`` tuples produced by
    ``extract_blocks_from_calculation``.
    """
    from app.models.calculation import Calculation

    calc = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    sub_areas: list[dict[str, Any]] = []
    sfm_blocks: list[dict[str, Any]] = []
    if calc is not None:
        rd = calc.result_data or {}
        sub_areas = rd.get("sub_areas", []) or []
        sfm_blocks = rd.get("sfm", {}).get("blocks", []) or []

    # Working-circle map from forest_blocks table
    wc_rows = db.execute(
        text(
            "SELECT COALESCE(block_name, name) AS bn, "
            "COALESCE(working_circle, 'production') AS wc, "
            "management_orientation, dominant_slope_band "
            "FROM forest_blocks WHERE calculation_id = :cid"
        ),
        {"cid": str(calculation_id)},
    ).fetchall()
    wc_dict: dict[str, str] = {r.bn: r.wc for r in wc_rows}

    mgmt_orientation: dict[str, str | None] = {r.bn: r.management_orientation for r in wc_rows}
    slope_band: dict[str, int | None] = {r.bn: r.dominant_slope_band for r in wc_rows}
    # SFM's own orientation is the fallback for a unit whose orientation nobody has set
    sfm_orientation: dict[str, str | None] = {b.get("block_name"): b.get("orientation") for b in sfm_blocks}

    result: dict[str, str] = {}
    for _number, wkt, name, _area_ha in units:
        result[name], _source = stratum_and_source(
            name,
            wkt,
            wc_dict.get(name),
            mgmt_orientation.get(name),
            sfm_orientation.get(name),
            slope_band.get(name),
            sub_areas,
        )
    return result


__all__ = [
    "STRATUM_FLOOR_PCT",
    "STRATUM_PLOT_SQM",
    "MIN_SAMPLES_PER_UNIT",
    "STRATA",
    "stratum_for_unit",
    "stratum_and_source",
    "SLOPE_STEEP_BAND",
    "classify_calc_units",
]
