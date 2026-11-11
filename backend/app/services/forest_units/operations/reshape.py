"""Re-clip sub-units when their parent's shape is edited (G2, FS-4a.10).

Owner-confirmed rule (`FOREST_STRUCTURE_RULE_AUDIT_REPORT.md` report §15,
"Owner confirmed G2"): editing a parent's shape re-clips its sub-units --
ground the edit REMOVES from the parent trims (or, if nothing meaningful of a
child is left inside the new shape, removes) that child; ground the edit ADDS
that no existing child already covers becomes a new remainder sub-unit, named
the same way any other sub-unit divide names one (no special "Remainder"
naming -- matches `block_area_invariant_service.enforce_block_coverage`,
which gives its own top-level remainder the next plain serial, not a
special name).

This is deliberately NOT :func:`operations.reparent.redistribute_children`
(FS-4a.7/4a.8's cut/merge helper): that function replaces every child with a
brand-new row under a brand-new (or several new) parent piece(s), because a
cut/merge/self-divide genuinely destroys and replaces the parent row itself.
Here the parent row's OWN id never changes -- only its geometry column does
-- so its existing children are the SAME rows, just trimmed (or removed) IN
PLACE. Nothing downstream that references a child by id (a tree/plot's
``unit_id``, an OP spatial assignment, ...) is invalidated by a reshape the
way it would be by a replace.

Recurses (A1: deeper nesting than one sub-level stays legal) -- a trimmed
child's own children are re-clipped to the child's NEW shape in the same
pass, before the child's row is touched again.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from geoalchemy2.shape import from_shape, to_shape
from shapely import make_valid
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from sqlalchemy.orm import Session

from ....core.naming_strategies import sub_unit_serial
from ....models.calculation import Calculation
from ....models.forest_block import ForestBlock, child_inherit_kwargs
from ... import geometry_edit_service as geo

logger = logging.getLogger(__name__)

SQM_PER_HA = 10_000.0


def _min_area_sqm() -> float:
    # Same "is this a real unit, or a sliver to fold away" floor every other
    # operation in this package agrees on -- lazy import, matching
    # `reparent._min_area_sqm`, to avoid tying module load order together.
    from ...compartment_divide_service import MIN_COMPARTMENT_AREA_M2

    return MIN_COMPARTMENT_AREA_M2


def _explode(geom: Any) -> List[Any]:
    """Single-part pieces only (a `ForestBlock` row is always one polygon)."""
    if geom is None or geom.is_empty:
        return []
    geom = make_valid(geom)
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, MultiPolygon):
        return [p for p in geom.geoms if p is not None and not p.is_empty]
    return []


def reclip_children(
    db: Session,
    calc: Calculation,
    parent_id: Any,
    new_parent_geom: BaseGeometry,
) -> Dict[str, Any]:
    """Re-clip every DIRECT child of ``parent_id`` to ``new_parent_geom``.

    Call this AFTER the parent row's own ``geometry`` column has been
    updated (the caller -- ``editing._write_geometry`` -- has not committed
    yet; this function mutates/flushes in the same uncommitted transaction).
    A no-op (returns the zeroed dict) when the parent has no children.

    Returns ``{trimmed: [ids], removed: [ids], remainder_added: [ids]}``.
    """
    result: Dict[str, Any] = {
        "trimmed": [], "removed": [], "remainder_added": [], "split": [],
    }
    children = (
        db.query(ForestBlock)
        .filter(ForestBlock.parent_block_id == parent_id)
        .all()
    )
    if not children:
        return result

    min_area = _min_area_sqm()
    survivors: List[Tuple[ForestBlock, BaseGeometry]] = []

    for child in children:
        child_geom = to_shape(child.geometry) if child.geometry is not None else None
        if child_geom is None or child_geom.is_empty:
            continue
        try:
            clipped = make_valid(child_geom.intersection(new_parent_geom))
        except Exception:  # noqa: BLE001 -- a bad geometry must not break the reshape
            logger.warning("[reshape] child intersection failed", exc_info=True)
            continue
        parts = _explode(clipped)
        area = sum(geo.area_sqm(p) for p in parts)

        if not parts or area < min_area:
            # Removed ground trims the child away entirely. D13: any
            # grandchildren travel with it -- `passive_deletes=True`
            # (FS-4a.9) lets Postgres's own ON DELETE CASCADE remove them,
            # recursively, no explicit walk needed here.
            result["removed"].append(str(child.id))
            db.delete(child)
            db.flush()
            continue

        if len(parts) == 1:
            kept_parts = parts
        else:
            # The re-clip pinched `child`'s territory into >1 disjoint
            # substantial piece (e.g. the parent's new shape now excludes a
            # strip running through the middle of the child -- exactly the
            # live case reported 2026-09-23: a 48.8 ha piece + a 0.19 ha
            # piece). A `ForestBlock` row is always exactly one polygon
            # (single_part_geometry.py); the old code here unioned the
            # disjoint parts back into one MultiPolygon and handed it to
            # `child.geometry`, which the model's own `@validates('geometry')`
            # guard correctly refused with `MultiPartFeatureError` ("N
            # disjoint substantial parts... only one row is being created for
            # it") rather than persist a corrupt row.
            #
            # Fold any part under the viable-unit floor into the largest kept
            # part first (mirrors `reparent.redistribute_children`'s own
            # sub-threshold fold -- a sliver fragment does not get a row of
            # its own), then treat what's left exactly like a cut that
            # happened to land on this child: one row per surviving piece,
            # its own children redistributed across them.
            parts_by_area = sorted(parts, key=lambda p: geo.area_sqm(p), reverse=True)
            kept_parts = [parts_by_area[0]]
            for p in parts_by_area[1:]:
                if geo.area_sqm(p) < min_area:
                    kept_parts[0] = make_valid(unary_union([kept_parts[0], p]))
                else:
                    kept_parts.append(p)

        old_area = geo.area_sqm(child_geom)

        if len(kept_parts) == 1:
            clipped = kept_parts[0]
            new_area = geo.area_sqm(clipped)
            materially_changed = abs(new_area - old_area) > 1.0  # > 1 sqm, not rounding noise

            child.geometry = from_shape(clipped, srid=4326)
            child.area_hectares = round(new_area / SQM_PER_HA, 4)
            child.area_sqm = round(new_area, 2)
            db.flush()
            survivors.append((child, clipped))

            if materially_changed:
                result["trimmed"].append(str(child.id))
                # A1: recurse onto whatever `child` itself has below it, now that
                # its own shape has changed -- BEFORE this call returns, so a
                # grandchild sticking out past the child's new edge is re-clipped
                # in the same pass, not left stale until someone edits the child
                # directly.
                sub = reclip_children(db, calc, child.id, clipped)
                for k in result:
                    result[k].extend(sub[k])
            continue

        # Genuine split: `child` no longer fits in one row. One new row per
        # surviving piece (named like `reparent.redistribute_children`'s own
        # straddle case), `child`'s own children redistributed onto them
        # (recursively, including their own descendants), then the old row
        # is removed -- the same "delete old, create new" pattern a cut/
        # divide already uses when a unit is replaced by several pieces.
        new_rows: List[Tuple[ForestBlock, Any]] = []
        for i, piece in enumerate(kept_parts, start=1):
            sqm = geo.area_sqm(piece)
            new_row = ForestBlock(
                calculation_id=calc.id,
                name=f"{child.name}-{i}",
                block_name=f"{child.block_name or child.name}-{i}",
                geometry=from_shape(piece, srid=4326),
                area_hectares=round(sqm / SQM_PER_HA, 4),
                area_sqm=round(sqm, 2),
                index=geo.next_block_index(db, calc.id),
                is_compartment=child.is_compartment,
                parent_block_id=parent_id,
                compartment_code=(
                    f"{child.compartment_code}-{i}" if child.compartment_code else None
                ),
                division_level=child.division_level,
                **child_inherit_kwargs(child),
            )
            db.add(new_row)
            db.flush()
            new_rows.append((new_row, piece))
            survivors.append((new_row, piece))
            result["split"].append(str(new_row.id))

        from .reparent import redistribute_children as _redistribute_children

        sub_ids = _redistribute_children(db, calc, child.id, new_rows)
        result["split"].extend(sub_ids)

        db.delete(child)
        db.flush()

    # Newly uncovered ground: whatever's left of the new parent shape that no
    # surviving child already covers.
    covered = make_valid(unary_union([g for _, g in survivors])) if survivors else Polygon()
    residual = make_valid(new_parent_geom.difference(covered))
    pieces = [p for p in _explode(residual) if geo.area_sqm(p) >= min_area]
    if pieces:
        parent = db.query(ForestBlock).filter(ForestBlock.id == parent_id).first()
        inherited = child_inherit_kwargs(parent) if parent is not None else {}
        is_compartment = bool(parent.is_compartment) if parent is not None else False
        parent_depth = (parent.division_level or 1) if parent is not None else 1
        parent_name = parent.name if parent is not None else ""
        start_index = len(children) - len(result["removed"]) + 1
        for offset, piece in enumerate(pieces):
            i = start_index + offset
            serial = sub_unit_serial(
                compartment=is_compartment, parent_name=parent_name, index=i
            )
            sqm = geo.area_sqm(piece)
            new_row = ForestBlock(
                calculation_id=calc.id,
                name=serial,
                block_name=serial,
                geometry=from_shape(piece, srid=4326),
                area_hectares=round(sqm / SQM_PER_HA, 4),
                area_sqm=round(sqm, 2),
                index=geo.next_block_index(db, calc.id),
                is_compartment=is_compartment,
                parent_block_id=parent_id,
                division_level=parent_depth + 1,
                **inherited,
            )
            db.add(new_row)
            db.flush()
            result["remainder_added"].append(str(new_row.id))
            logger.info(
                "[reshape] remainder sub-unit %s added under %s for calc=%s (%.2f ha)",
                serial, parent_id, calc.id, sqm / SQM_PER_HA,
            )

    return result
