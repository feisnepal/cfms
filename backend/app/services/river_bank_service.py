"""River banks: 20 m each side of a river, inside the forest (FIRELINE_RIVERBANK_PLAN.md, RB-2).

The same machinery as the fire line (``fire_line_service``: the sync plan, the entries, the tick-list decisions, the drawn lines)
with a different SOURCE of centerlines (the rivers, ``river_sources``) and a different name: the units the bank runs through, then
the river, ``SC3-SC4 (Jorchhanga Khola)``. A river bank is a PROTECTION area (not productive); how that reaches the area figures is
``core.sub_area_kinds.PROTECTION_SUB_AREA_CATEGORIES``.

Unlike the fire line it does not need the units' shared edges, so overlapping units do not stop it: the units only give it a name.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Sequence, Tuple

from shapely.geometry.base import BaseGeometry
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.constants import RIVER_BANK_SIDE_M, STRIP_MIN_AREA_M2, STRIP_MIN_LENGTH_M
from app.core.sub_area_kinds import RIVER_BANK, real_sub_areas
from app.services import fire_line_service as fls
from app.services import strip_geometry as sg
from app.services.fire_line_service import Candidate, RIVER_KIND
from app.services.strip_geometry import Metric

logger = logging.getLogger(__name__)

#: a unit counts as "the bank runs through it" when this share of the bank lies in it
UNIT_SHARE = 0.10
MAX_UNITS_IN_NAME = 3


def units_in_name(strip_m: BaseGeometry, units: Sequence[Any], metric: Metric) -> List[str]:
    """The units a bank runs through (>= 10 % of it in each), natural order. The whole list; the name shortens it."""
    if not strip_m.area:
        return []
    hit = [u.name for u in units if strip_m.intersection(metric.to_m(u.polygon)).area / strip_m.area >= UNIT_SHARE]
    return sorted(hit, key=sg.natural_key)


def bank_name(units: Sequence[str], river: str) -> str:
    """'SC3-SC4 (river)'; more than three units are abbreviated ('SC1-SC2-SC3-…'), the table lists them all; no unit: the river."""
    if not units:
        return river
    shown = "-".join(units[:MAX_UNITS_IN_NAME]) + ("-…" if len(units) > MAX_UNITS_IN_NAME else "")
    return f"{shown} ({river})"


def river_candidates(
    forest: BaseGeometry,
    units: Sequence[Any],
    subareas: Sequence[Any],
    reaches: Sequence[Any],
    side_m: float = RIVER_BANK_SIDE_M,
    min_length_m: float = STRIP_MIN_LENGTH_M,
) -> Tuple[List[Candidate], Dict[str, int]]:
    """Every river-bank candidate: each river reach, 20 m each side, clipped to the forest area, trimmed against the earlier ones."""
    metric = Metric.for_geometry(forest)
    forest_m = metric.to_m(forest)
    private_m = [metric.to_m(s.polygon) for s in subareas if getattr(s, "category", "") == "private_land"]
    area_m = sg.forest_area(forest_m, private_m)

    items: List[Dict[str, Any]] = []
    per_ref: Dict[Tuple[str, str], int] = {}
    for reach in reaches:
        line_m = metric.to_m(reach.line)
        if line_m.length < min_length_m:
            continue
        n_seg = len(line_m.coords) - 1
        ref = (reach.source, reach.ref)
        per_ref[ref] = per_ref.get(ref, 0) + 1
        items.append({"reach": reach, "line_m": line_m, "n_seg": n_seg, "n": per_ref[ref],
                      "strip": sg.clip_to_area(sg.strip_polygon(line_m, [side_m] * n_seg), area_m)})

    trimmed = sg.trim_same_kind([i["strip"] for i in items])
    out: List[Candidate] = []
    seen: Dict[str, int] = {}
    for item, strip in zip(items, trimmed):
        reach = item["reach"]
        for i, part in enumerate(fls._parts_along(item["line_m"], strip)):
            if part.area < STRIP_MIN_AREA_M2:
                continue
            base = bank_name(units_in_name(part, units, metric), reach.name)
            seen[base] = seen.get(base, 0) + 1
            name = base if seen[base] == 1 else f"{base} ({seen[base]})"
            key = f"river:{reach.source}:{reach.ref}|{item['n']}"
            out.append(Candidate(
                unit_key=key if i == 0 else f"{key}~{i}", name=name if i == 0 else f"{name} ·{i + 1}", pair=(), tag="",
                centerline=metric.to_wgs(item["line_m"]), geometry=metric.to_wgs(part), geometry_m=part,
                length_m=round(sg.length_m(item["line_m"]), 2), area_ha=round(sg.area_ha(part), 4),
                segment_widths_m=[side_m] * item["n_seg"], source="river", river_name=reach.name,
            ))
    return out, {"river_reaches": len(items), "river_candidates": len(out)}


def sync_river_banks(db: Session, calculation_id: Any, force: bool = False) -> Dict[str, Any]:
    """Bring the stored river banks in step with the rivers. Commits. Same locking as ``sync_fire_lines``: the geometry is built
    without the row lock, the lock is held only for the short read-modify-write."""
    from app.models.calculation import Calculation
    from app.models.op_data_cache import OpDataCache
    from app.services.river_sources import river_reaches
    from app.services.workspace_cache import invalidate_layers_cache

    kind = RIVER_KIND
    db.info["fire_line_sync"] = True
    calc = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if calc is None:
        return {"state": "missing"}
    if getattr(calc, "structure_locked", False):
        return {"state": "locked"}
    inputs = fls._inputs(db, calc, require_units=False)
    if inputs is None:
        return {"state": "no_inputs"}
    forest, units, subs = inputs

    metric = Metric.for_geometry(forest)
    forest_m = metric.to_m(forest)
    private_m = [metric.to_m(s.polygon) for s in subs if getattr(s, "category", "") == "private_land"]
    area_wgs = metric.to_wgs(sg.forest_area(forest_m, private_m))
    reaches = river_reaches(db, calc, area_wgs)

    rd0 = dict(calc.result_data or {})
    sig = fls.input_signature(forest, units, subs, dict(rd0.get(kind.decisions_key) or {}), reaches)
    if not force and rd0.get(kind.signature_key) == sig:
        return {"state": "unchanged"}

    cands, cand_report = river_candidates(forest, units, subs, reaches)

    calc = db.query(Calculation).filter(Calculation.id == calculation_id).populate_existing().with_for_update().first()
    rd = dict(calc.result_data or {})
    decisions = dict(rd.get(kind.decisions_key) or {})
    zones_m: Dict[str, List[BaseGeometry]] = {}
    for sa in real_sub_areas(rd.get("sub_areas")):
        g = fls._sub_polygon(sa.get("geometry"))
        if g is not None and sa.get("category"):
            zones_m.setdefault(sa["category"], []).append(metric.to_m(g))
    new_list, report = fls.plan_sync(rd.get("sub_areas") or [], cands, decisions, area_wgs,
                                     fls.entry_factory(metric, units, zones_m, category=RIVER_BANK), category=RIVER_BANK)
    changed = any(report[k] for k in ("created", "updated", "dropped", "reclipped"))
    rd[kind.signature_key] = sig
    rd[kind.status_key] = {"state": "ok", "at": datetime.now(timezone.utc).isoformat(), **cand_report, "candidates": len(cands)}
    rd[kind.catalogue_key] = [fls.catalogue_entry(c) for c in cands]
    if changed:
        rd["sub_areas"] = new_list
        rd["sub_areas_count"] = len(new_list)
    calc.result_data = rd
    flag_modified(calc, "result_data")
    if changed:
        try:
            db.query(OpDataCache).filter(OpDataCache.calculation_id == calc.id).delete(synchronize_session=False)
        except Exception:  # noqa: BLE001 -- the cache is rebuilt on the next preview
            logger.warning("river_bank_service: op_data_cache could not be cleared for %s", calc.id, exc_info=True)
    db.commit()
    if changed:
        invalidate_layers_cache(calc.id)
    return {"state": "synced", **report, **cand_report, "candidates": len(cands)}
