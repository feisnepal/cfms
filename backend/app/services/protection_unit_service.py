"""Promote a protected sub-area to a protection working-circle unit, and back.

PROTECTION_WORKING_CIRCLE_PLAN.md P3. A ``category='protected'`` sub-area
overlay becomes a first-class ``forest_blocks`` row (``working_circle='protection'``,
numbered ``P-N``), clipped out of whatever production compartment(s) it sat in.
``demote`` is the exact inverse, using a snapshot stashed on ``result_data``.

Both operations are guarded by the structure lock and bump the geometry clock.
The reconcile services keep ``result_data['blocks'|'compartments']`` in step.
"""

from __future__ import annotations

import copy
import logging
import uuid
from typing import Any, Dict

from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import mapping, shape
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from ..core.constants import SQM_PER_HA
from ..models.calculation import Calculation
from ..models.forest_block import ForestBlock
from . import geometry_edit_service as geo
from .forest_units.model import DEPTH_TOP_BLOCK
from .sub_area_service import place_sub_area, SubAreaPlacementError, PLACEMENT_MESSAGES

logger = logging.getLogger(__name__)

_SNAP_KEY = "protection_unit_snapshots"
_MIN_OVERLAP_M2 = 1.0


def _guard_unlocked(calc: Calculation) -> None:
    if getattr(calc, "structure_locked", False):
        raise ValueError(
            "STRUCTURE_LOCKED: the forest structure is locked; unlock it before "
            "changing working circles."
        )


def next_protection_index(db: Session, calculation_id) -> int:
    """1-based running number for the ``P-N`` series (per calculation)."""
    n = (
        db.query(ForestBlock)
        .filter(
            ForestBlock.calculation_id == calculation_id,
            ForestBlock.working_circle == "protection",
        )
        .count()
    )
    return n + 1


def _areas(sqm: float) -> Dict[str, float]:
    return {"area_sqm": round(sqm, 2), "area_hectares": round(sqm / SQM_PER_HA, 4)}


def promote_subarea_to_unit(
    db: Session, calc: Calculation, sub_area_id: str
) -> Dict[str, Any]:
    """Turn a protected sub-area into a ``P-N`` protection unit. Does NOT commit."""
    _guard_unlocked(calc)

    rd = dict(calc.result_data or {})
    sub_areas = list(rd.get("sub_areas", []))
    idx = next(
        (i for i, sa in enumerate(sub_areas) if str(sa.get("id")) == str(sub_area_id)),
        None,
    )
    if idx is None:
        raise ValueError(f"SUBAREA_NOT_FOUND: {sub_area_id}")
    sub_area = sub_areas[idx]
    if sub_area.get("category") != "protected":
        raise ValueError(
            "NOT_PROTECTED: only a protected sub-area can become a protection unit."
        )
    raw = sub_area.get("geometry")
    if not isinstance(raw, dict):
        raise ValueError("SUBAREA_NO_GEOMETRY")
    sa_geom = shape(raw)
    if sa_geom.is_empty:
        raise ValueError("SUBAREA_EMPTY_GEOMETRY")

    # Clip the sub-area out of every overlapping unit; record the pre-clip shape.
    rows = (
        db.query(ForestBlock)
        .filter(ForestBlock.calculation_id == calc.id, ForestBlock.geometry.isnot(None))
        .all()
    )
    block_snap: Dict[str, Any] = {}
    # FS-4a.14: `carved_from` decides the promoted unit's parent/depth/branch
    # (below), so picking it needs to prefer the DEEPEST containing unit, not
    # just the largest raw overlap -- a top-level block's own geometry still
    # fully covers its own children's territory (a "parent-kept carve" never
    # hollows the parent row out), so a sub-area sitting inside a sub-block
    # overlaps BOTH the sub-block and its parent block, often by the exact
    # same area. `best_key` orders candidates by (division_level, overlap)
    # so the innermost/leaf-most unit wins ties, mirroring
    # `forest_units/sql.py::deepest_first`'s "the leaf match is the right
    # match" rule for point-in-polygon assignment.
    carved_from = None
    best_key = (-1, 0.0)
    for row in rows:
        try:
            rg = to_shape(row.geometry)
        except Exception:  # noqa: BLE001 -- an unreadable unit is left untouched
            continue
        inter = rg.intersection(sa_geom)
        inter_area = geo.area_sqm(inter)
        if inter.is_empty or inter_area < _MIN_OVERLAP_M2:
            continue
        key = (row.division_level or 0, inter_area)
        if key > best_key:
            best_key, carved_from = key, row
        block_snap[str(row.id)] = mapping(rg)
        new_geom = rg.difference(sa_geom)
        if new_geom.is_empty:
            raise ValueError(
                f"UNIT_CONSUMED: promoting this sub-area would empty unit '{row.name}'."
            )
        row.geometry = from_shape(new_geom, srid=4326)
        for k, v in _areas(geo.area_sqm(new_geom)).items():
            setattr(row, k, v)

    pidx = next_protection_index(db, calc.id)
    name = f"P-{pidx}"
    # FS-4a.14: the new unit becomes a SIBLING of whatever it was carved out
    # of (same parent, same depth, same branch) -- not always a top-level
    # orphan. Before this fix, `parent_block_id` was unconditionally `None`
    # while `division_level` copied `carved_from`'s own depth verbatim: for
    # a top-level `carved_from` that accidentally produced the right depth
    # anyway, but for a protected sub-area sitting inside a SUB-block/
    # SUB-compartment it minted a unit claiming a sub-level depth with no
    # parent at all -- an inconsistent (depth, ancestry) pair nothing else
    # in this package ever produces. `carved_from` is `None` only when the
    # sub-area overlapped no existing unit (e.g. drawn over unassigned
    # ground) -- falls back to the pre-fix top-level-block default, the one
    # case that was already correct.
    if carved_from is not None:
        parent_block_id = carved_from.parent_block_id
        division_level = carved_from.division_level
        is_compartment = bool(carved_from.is_compartment)
    else:
        parent_block_id = None
        division_level = DEPTH_TOP_BLOCK
        is_compartment = False
    unit = ForestBlock(
        id=uuid.uuid4(),
        calculation_id=calc.id,
        name=name,
        block_name=name,
        compartment_code=name,
        geometry=from_shape(sa_geom, srid=4326),
        index=geo.next_block_index(db, calc.id),
        working_circle="protection",
        is_compartment=is_compartment,
        division_level=division_level,
        parent_block_id=parent_block_id,
        **_areas(geo.area_sqm(sa_geom)),
    )
    db.add(unit)
    db.flush()

    # Drop the overlay; snapshot enough to reverse.
    sub_areas.pop(idx)
    rd["sub_areas"] = sub_areas
    rd["sub_areas_count"] = len(sub_areas)
    rd.setdefault(_SNAP_KEY, {})[str(unit.id)] = {
        "sub_area": copy.deepcopy(sub_area),
        "blocks": block_snap,
    }
    calc.result_data = rd
    flag_modified(calc, "result_data")

    from .forest_units.write import structure_write

    with structure_write(db, calc, change=f"promote sub-area to protection unit {name}"):
        pass
    return {
        "unit_id": str(unit.id),
        "name": name,
        "clipped_units": list(block_snap.keys()),
    }


def demote_unit_to_subarea(
    db: Session, calc: Calculation, block_id: str
) -> Dict[str, Any]:
    """Inverse of :func:`promote_subarea_to_unit`. Does NOT commit."""
    _guard_unlocked(calc)

    unit = (
        db.query(ForestBlock)
        .filter(ForestBlock.id == block_id, ForestBlock.calculation_id == calc.id)
        .first()
    )
    if unit is None:
        raise ValueError(f"UNIT_NOT_FOUND: {block_id}")
    if unit.working_circle != "protection":
        raise ValueError(
            "NOT_PROTECTION_UNIT: this unit is not a protection working circle."
        )

    rd = dict(calc.result_data or {})
    snap = (rd.get(_SNAP_KEY, {}) or {}).get(str(block_id))

    if snap:
        for bid, gj in (snap.get("blocks") or {}).items():
            row = db.query(ForestBlock).filter(ForestBlock.id == bid).first()
            if row is None:
                continue
            g = shape(gj)
            row.geometry = from_shape(g, srid=4326)
            for k, v in _areas(geo.area_sqm(g)).items():
                setattr(row, k, v)
        sub_area = copy.deepcopy(snap["sub_area"])
    else:
        # No snapshot (edge) — re-emit the sub-area from the unit's own geometry.
        g = to_shape(unit.geometry)
        sub_area = {
            "id": str(uuid.uuid4()),
            "name": unit.block_name or unit.name,
            "category": "protected",
            "geometry": mapping(g),
            "area_hectares": round(geo.area_sqm(g) / SQM_PER_HA, 4),
        }

    # While this was a protection unit the ground was free for others: a sub-area may
    # have been drawn over it since. Demoting must not put an overlap back.
    _sa_geom = sub_area.get("geometry")
    if _sa_geom:
        try:
            _placed = place_sub_area(db, calc, shape(_sa_geom))
        except SubAreaPlacementError as exc:
            raise ValueError(f"SUBAREA_PLACEMENT: {PLACEMENT_MESSAGES[exc.reason]}")
        if _placed.clipped_to_forest or _placed.overlap_removed:
            _sqm = geo.area_sqm(_placed.geometry)
            sub_area["geometry"] = mapping(_placed.geometry)
            sub_area["area_sqm"] = round(_sqm, 2)
            sub_area["area_hectares"] = round(_sqm / SQM_PER_HA, 4)
            if "area_ha" in sub_area:
                sub_area["area_ha"] = sub_area["area_hectares"]

    sub_areas = list(rd.get("sub_areas", []))
    sub_areas.append(sub_area)
    rd["sub_areas"] = sub_areas
    rd["sub_areas_count"] = len(sub_areas)
    rd.get(_SNAP_KEY, {}).pop(str(block_id), None)
    calc.result_data = rd
    flag_modified(calc, "result_data")

    db.delete(unit)
    db.flush()

    from .forest_units.write import structure_write

    with structure_write(db, calc, change="demote protection unit to sub-area"):
        pass
    return {
        "sub_area_id": sub_area["id"],
        "restored_units": list((snap or {}).get("blocks", {}).keys()),
    }
