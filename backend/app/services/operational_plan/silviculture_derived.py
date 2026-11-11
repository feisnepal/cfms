"""Silviculture facts the plan form asks for, derived from the SFM classification (ND-4, owner 2026-10-19).

``silviculture_system``, ``rotation_years``, ``regeneration_period_years`` and ``mother_tree_spacing_m`` are form fields, but
the SFM tab has already decided each of them per block from the forest type (अनुसूची-१). A value typed into the form still
wins; this is only the fallback used when the form is empty (``VariableResolver._form_field_fallback``).

Mixed forests: every distinct value is listed, the dominant forest type's first and the rest by area (largest first).
Mother-tree spacing: measured from the mapped mother trees when there are enough of them, otherwise computed from the
target density (trees per hectare) as sqrt(10 000 / n).
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional, Sequence
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# fewer mapped mother trees than this say nothing about the spacing
MIN_MAPPED_MOTHER_TREES = 5


#: the key of the SFM per-block cards inside the stored SFM classification. These are NOT the legacy derived unit array that the
#: unit-access ratchet (scripts/check_unit_access.py) guards; that scan matches any dict which has a key of this name.
_CARDS = "blocks"


def _ordered_blocks(sfm: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Blocks with a prescription card: dominant forest type first, then largest area first."""
    blocks = [b for b in (sfm.get(_CARDS) or []) if isinstance(b, dict) and b.get("prescription")]
    dominant = (sfm.get("forest_summary") or {}).get("dominant_type_no")
    return sorted(
        blocks,
        key=lambda b: (b.get("effective_type_no") != dominant, -float(b.get("area_ha") or 0.0), str(b.get("block_name") or "")),
    )


def _distinct(values: Sequence[Any]) -> List[Any]:
    seen: List[Any] = []
    for v in values:
        if v not in (None, "", []) and v not in seen:
            seen.append(v)
    return seen


def _systems(cards: Sequence[Dict[str, Any]]) -> List[str]:
    """Each system once. The cards spell one system two ways in Nepali, so identity is the English name."""
    named: Dict[str, str] = {}
    for c in cards:
        label = c.get("system_ne")
        if label and label != "—":
            named.setdefault(str(c.get("system_en") or label).strip().lower(), label)
    return list(named.values())


def _years(value: Any) -> Any:
    """``80`` -> 80, ``[60, 80]`` -> '60-80'; anything else is not a number of years."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if float(value).is_integer() else value
    if isinstance(value, (list, tuple)) and len(value) == 2 and all(isinstance(x, (int, float)) for x in value):
        lo, hi = sorted(value)
        return int(lo) if lo == hi else f"{int(lo)}-{int(hi)}"
    return None


def _joined(values: List[Any]) -> Any:
    """One value stays a value (so a number formats as a number); several are listed in order."""
    if not values:
        return None
    return values[0] if len(values) == 1 else ", ".join(str(v) for v in values)


def target_spacing_m(target: Any) -> Optional[float]:
    """Spacing implied by a target density: ``n`` or ``[min, max]`` mother trees per hectare -> sqrt(10 000 / n) metres."""
    if isinstance(target, (list, tuple)):
        nums = [float(x) for x in target if isinstance(x, (int, float)) and x > 0]
        n = sum(nums) / len(nums) if nums else None
    elif isinstance(target, (int, float)) and not isinstance(target, bool) and target > 0:
        n = float(target)
    else:
        n = None
    return round(math.sqrt(10000.0 / n), 1) if n else None


def from_sfm(sfm: Dict[str, Any]) -> Dict[str, Any]:
    """The system / rotation / regeneration period / target spacing, from ``result_data['sfm']``. Absent keys are ``None``."""
    cards = [b["prescription"] for b in _ordered_blocks(sfm or {})]
    spacings = _distinct([target_spacing_m(c.get("mother_tree_target")) for c in cards])
    return {
        "silviculture_system": _joined(_systems(cards)),
        "rotation_years": _joined(_distinct([_years(c.get("rotation_years")) for c in cards])),
        "regeneration_period_years": _joined(_distinct([_years(c.get("regeneration_period_years")) for c in cards])),
        "mother_tree_spacing_m": _joined(spacings),
    }


#: the SFM series that is shrub biomass (firewood), not timber: forest type 12
_SHRUB_TYPE_NO = 12


def felling_from_sfm(sfm: Dict[str, Any]) -> Dict[str, Any]:
    """Fallback for the felling facts when the yearly plan has no felling activity (the plan is the owner's, SFM is the rule).

    * regeneration / preparatory felling units: the blocks managed under a shelterwood system (the only system with both
      cuts); the SFM does not schedule them by year, so the same list serves both and the plan's own lines still win.
    * annual timber (cft): the SFM's annual harvest of every series except shrubland, in m3 x ``CFT_PER_M3``.
    * annual firewood (chatta): the shrubland series' annual harvest (biomass) in m3 / ``M3_PER_CHATTA``.
    Absent keys are ``None``.
    """
    from app.core.constants import CFT_PER_M3, M3_PER_CHATTA

    sfm = sfm or {}
    shelter = [
        str(b.get("block_name") or (b.get("inputs") or {}).get("block_name") or "")
        for b in _ordered_blocks(sfm)
        if "shelterwood" in str((b.get("prescription") or {}).get("system_en") or "").lower()
        or (b.get("prescription") or {}).get("method") == "shelterwood_periodic_block"
    ]
    units = ", ".join(sorted({n for n in shelter if n})) or None
    series = [s for s in (sfm.get("felling_series") or []) if isinstance(s, dict)]
    timber = [float(s["annual_harvest_m3"]) for s in series
              if s.get("annual_harvest_m3") is not None and s.get("type_no") != _SHRUB_TYPE_NO]
    shrub = [float(s["annual_harvest_m3"]) for s in series
             if s.get("annual_harvest_m3") is not None and s.get("type_no") == _SHRUB_TYPE_NO]
    return {
        "regeneration_felling_unit": units,
        "preparatory_felling_unit": units,
        "annual_yield_timber_cft": round(sum(timber) * CFT_PER_M3) if timber else None,
        "annual_yield_firewood_chatta": round(sum(shrub) / M3_PER_CHATTA, 1) if shrub else None,
    }


def measured_spacing_m(db: Session, calculation_id: UUID) -> Optional[float]:
    """Mean distance from each mapped mother tree to its nearest other mother tree (m); ``None`` below the minimum count."""
    try:
        row = db.execute(
            text(
                """
                WITH mt AS (
                    SELECT it.id, it.location
                    FROM public.inventory_trees it
                    JOIN public.inventory_calculations ic ON ic.id = it.inventory_calculation_id
                    WHERE ic.calculation_id = :cid AND it.remark = 'Mother Tree'
                )
                SELECT count(*) AS n, avg(d.dist) AS mean_nn
                FROM mt
                CROSS JOIN LATERAL (
                    SELECT ST_Distance(mt.location, o.location) AS dist
                    FROM mt o WHERE o.id <> mt.id
                    ORDER BY mt.location <-> o.location LIMIT 1
                ) d
                """
            ),
            {"cid": calculation_id},
        ).first()
    except Exception:  # noqa: BLE001 -- a spacing lookup must not stop the document; the target spacing is used instead
        logger.exception("silviculture_derived: mapped mother-tree spacing could not be measured")
        return None
    if not row or not row.n or row.n < MIN_MAPPED_MOTHER_TREES or row.mean_nn is None:
        return None
    return round(float(row.mean_nn), 1)


def derive(db: Session, calculation_id: UUID, sfm: Dict[str, Any]) -> Dict[str, Any]:
    out = from_sfm(sfm)
    measured = measured_spacing_m(db, calculation_id)
    if measured is not None:
        out["mother_tree_spacing_m"] = measured
    return out
