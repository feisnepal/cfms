"""Boundary ≡ Blocks area invariant (plan IMPLEMENTATION_PLAN_BLOCK_BOUNDARY_INVARIANT).

Hard rule (user-confirmed 2026-08-11): **total block area == forest boundary
area** across ALL block/compartment creation paths (auto-create, import,
draw, split, merge, delete), for blocks AND compartments treated the same.

Two entry points:

- ``clip_and_validate_block(geom, calc, existing_shapes, level)`` — called
  BEFORE an edit/draw/import persists a new block. Clips the geometry to the
  forest boundary (a block can never lie outside). Raises:
    - ``ValueError("OUTSIDE_BOUNDARY")`` when the clipped result is empty
      (the proposed block lies fully outside the boundary).
    - ``ValueError("TOPOLOGY_REJECTED")`` when the proposed block materially
      overlaps an existing block of the same level (over-coverage cannot be
      auto-fixed → the edit is rejected).
  Returns the clipped Shapely polygon otherwise.

- ``enforce_block_coverage(db, calc, level)`` — called AFTER any committed
  edit that mutates blocks/compartments (cut, merge, delete, import,
  auto-block commit). Recomputes the union of the level's polygons vs the
  boundary:
    - **Over-coverage** (union area > boundary area + epsilon): raises
      ``ValueError("TOPOLOGY_REJECTED")`` — the calling transaction is rolled
      back, i.e. the edit that produced it is rejected.
    - **Under-coverage** (gap area > epsilon): silently inserts a
      **Remainder Block/Compartment** covering the uncovered boundary area so
      area equality holds. (Parts below the sliver floor are NOT remaindered —
      they are negligible rounding gaps, matching the cut/divide sliver rule.)
  Returns a dict ``{remainder_added, gap_ha, union_ha, boundary_ha}`` for the
  frontend result toast.
"""
import logging
from typing import Any, Dict, List, Optional, Tuple

from shapely import make_valid
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

from ..core.constants import (
    OVER_COVERAGE_CLAMP_M2,
    SQM_PER_HA,
)
from ..core.naming_strategies import compartment_serial, block_serial
from ..models.forest_block import ForestBlock
from .geometry_edit_service import (
    W_TOPOLOGY_REJECTED,
    area_sqm,
    boundary_region,
    next_block_index,
)

logger = logging.getLogger(__name__)

# Epsilon (m²) below which a coverage gap is treated as rounding noise and NOT
# turned into a remainder block (mirrors the cut/divide sliver philosophy).
COVERAGE_EPSILON_M2: float = 100.0

# Material-overlap floor (m²) for rejecting a new block against existing ones
# (shared edges are adjacency, not overlap).
OVERLAP_EPSILON_M2: float = 5.0

# Strict threshold (ha) above which the union of a level's blocks is treated as
# genuine over-coverage and the edit is rejected. Very small floating-point
# differences (1 m²) below this are absorbed by OVER_COVERAGE_CLAMP_M2.
OVER_COVERAGE_STRICT_HA: float = 1e-5


def _explode_multipart(geom: Any) -> List[Any]:
    """Single-part guarantee (Phase C): a block is always one contiguous polygon."""
    if geom is None or geom.is_empty:
        return []
    geom = make_valid(geom)
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, MultiPolygon):
        return [make_valid(p) for p in geom.geoms
                if p is not None and not p.is_empty and isinstance(p, Polygon)]
    return []


def _level_rows(
    db, calculation_id: str, level: str, raster_layer_id: Any = None
) -> List[ForestBlock]:
    """Top-level blocks (DEPTH_TOP_BLOCK, not compartment) or compartments (is_compartment).

    ``raster_layer_id`` (RS-2.16/P2.5), when given, scopes the coverage check
    to ONE Auto-Block layer's rows instead of every row at this level for the
    calculation -- required once a calculation can hold several independent,
    unpromoted layers at once (D51): the boundary-coverage invariant is a
    property of one layer's own geometry, not the union of unrelated trial
    layers that happen to share a level.
    """
    from .forest_units.model import DEPTH_TOP_BLOCK

    if level == "compartments":
        q = db.query(ForestBlock).filter(
            ForestBlock.calculation_id == calculation_id,
            ForestBlock.is_compartment.is_(True),
        )
    else:
        q = db.query(ForestBlock).filter(
            ForestBlock.calculation_id == calculation_id,
            ForestBlock.is_compartment.isnot(True),
            ForestBlock.division_level == DEPTH_TOP_BLOCK,
        )
    if raster_layer_id is not None:
        q = q.filter(ForestBlock.raster_layer_id == raster_layer_id)
    return q.all()


def _level_prefix(level: str) -> str:
    return "C" if level == "compartments" else "Block"


def _as_shapely(g: Any):
    """Coerce WKB (geoalchemy2) / GeoJSON / WKT / Shapely into Shapely."""
    if g is None:
        return None
    if hasattr(g, "srid") and hasattr(g, "data"):  # geoalchemy2 WKB element
        from geoalchemy2.shape import to_shape
        return to_shape(g)
    if isinstance(g, (dict, str)):
        from ..services.geometry_edit_service import to_shapely
        return to_shapely(g)
    return g


def _level_is_compartment(level: str) -> bool:
    return level == "compartments"


def clip_and_validate_block(
    geom: Any,
    calculation: Any,
    existing_shapes: Optional[List[Any]] = None,
    level: str = "blocks",
) -> Tuple[Any, Dict[str, Any]]:
    """Clip a proposed new block to the boundary; reject outside/overlapping.

    Returns (clipped_shapely, info) where ``info`` carries warnings.  Raises
    ValueError("OUTSIDE_BOUNDARY") when the block lies fully outside the
    boundary, and ValueError("TOPOLOGY_REJECTED") when it materially overlaps
    an existing block of the same level.
    """
    info: Dict[str, Any] = {"clipped": False, "removed_ha": 0.0, "warnings": []}
    if geom is None or geom.is_empty:
        raise ValueError("invalid_geometry")

    region = boundary_region(calculation)
    if region is None:
        # No boundary → a block defines the forest (import/rule 1 auto-derives
        # the boundary later). Accept as-is.
        return make_valid(geom), info

    clipped = make_valid(region.intersection(geom))
    parts = _explode_multipart(clipped)
    if not parts:
        raise ValueError("OUTSIDE_BOUNDARY")
    clipped = unary_union(parts)

    before_ha = area_sqm(geom) / SQM_PER_HA
    after_ha = area_sqm(clipped) / SQM_PER_HA
    if after_ha < before_ha - 1e-9:
        info["clipped"] = True
        info["removed_ha"] = round(before_ha - after_ha, 4)
        info["warnings"].append("CLIPPED_TO_BOUNDARY")

    # Overlap against existing same-level blocks (over-coverage → reject).
    for other in existing_shapes or []:
        try:
            o = _as_shapely(other)
        except Exception:
            # This service exists to prove blocks tile the boundary. A shape it
            # cannot read is a shape it does not check, so the invariant passes
            # on less evidence than it claims.
            logger.exception(
                "geometry unreadable - it is excluded from the overlap check, so "
                "the invariant is verified against less than the full set"
            )
            continue
        o = make_valid(o)
        if o is None or o.is_empty:
            continue
        try:
            if clipped.intersects(o):
                inter = area_sqm(clipped.intersection(o))
                if inter > OVERLAP_EPSILON_M2:
                    info["warnings"].append(W_TOPOLOGY_REJECTED)
                    raise ValueError("TOPOLOGY_REJECTED")
        except ValueError:
            raise
        except Exception as e:
            logger.warning(f"[invariant] overlap check failed: {e}")

    return clipped, info


def enforce_block_coverage(
    db,
    calculation: Any,
    level: str = "blocks",
    raster_layer_id: Any = None,
) -> Dict[str, Any]:
    """After-edit enforcement: union of the level's blocks must equal the boundary.

    Over-coverage → raises ValueError("TOPOLOGY_REJECTED") (edit rolled back).
    Under-coverage → silently inserts a Remainder Block/Compartment covering
    the gap (unless the gap is below ``COVERAGE_EPSILON_M2``).

    ``raster_layer_id`` (RS-2.16/P2.5): scope both the coverage check and any
    inserted remainder row to one Auto-Block layer (see ``_level_rows``). A
    remainder inserted for a layer carries that same ``raster_layer_id``, so
    it is invisible everywhere else in the app until (and unless) its layer
    is promoted -- exactly like the rest of that layer's rows.
    """
    result: Dict[str, Any] = {
        "remainder_added": False,
        "gap_ha": 0.0,
        "union_ha": 0.0,
        "boundary_ha": 0.0,
        "warnings": [],
    }
    region = boundary_region(calculation)
    if region is None:
        return result
    result["boundary_ha"] = round(area_sqm(region) / SQM_PER_HA, 4)

    rows = _level_rows(db, str(calculation.id), level, raster_layer_id=raster_layer_id)
    shapes = []
    for r in rows:
        if r.geometry is not None:
            from geoalchemy2.shape import to_shape
            try:
                shapes.extend(_explode_multipart(to_shape(r.geometry)))
            except Exception:
                logger.exception(
                    "block geometry unreadable - it is left out of the coverage "
                    "union, which then looks smaller than the blocks really are"
                )
                continue
    if not shapes:
        # No blocks at all → remainder = whole boundary (single-block forest).
        shapes = []
        union = None
    else:
        union = make_valid(unary_union(shapes))

    # Over-coverage: union area must never exceed the boundary area.
    if union is not None and not union.is_empty:
        union_ha = area_sqm(union) / SQM_PER_HA
        result["union_ha"] = round(union_ha, 4)
        if union_ha > result["boundary_ha"] + OVER_COVERAGE_STRICT_HA:
            # If the excess is small (<= OVER_COVERAGE_CLAMP_M2), clip to boundary
            # and accept the clipped result (it's now guaranteed within boundary).
            if union_ha <= result["boundary_ha"] + OVER_COVERAGE_CLAMP_M2 / SQM_PER_HA:
                try:
                    union = make_valid(union.intersection(region))
                    union_ha = area_sqm(union) / SQM_PER_HA
                    result["union_ha"] = round(union_ha, 4)
                except Exception:
                    logger.exception(
                        "could not clip the union to the region - union_ha is left at its "
                        "unclipped value, overstating coverage"
                    )
                # After clipping to boundary, the union is by definition within boundary.
                # Accept even if tiny floating-point excess remains.
            if union_ha > result["boundary_ha"] + OVER_COVERAGE_CLAMP_M2 / SQM_PER_HA:
                logger.warning(
                    "[invariant] OVER-COVERAGE calc=%s level=%s union_ha=%.4f boundary_ha=%.4f excess_ha=%.4f",
                    calculation.id, level, union_ha, result["boundary_ha"],
                    union_ha - result["boundary_ha"],
                )
                result["warnings"].append(W_TOPOLOGY_REJECTED)
                raise ValueError("TOPOLOGY_REJECTED")

    # Under-coverage: gap = boundary minus union → remainder block.
    base = union if (union is not None and not union.is_empty) else Polygon()
    gap = make_valid(region.difference(base))
    gap_ha = area_sqm(gap) / SQM_PER_HA
    result["gap_ha"] = round(gap_ha, 4)
    if gap_ha > COVERAGE_EPSILON_M2 / SQM_PER_HA:
        # `_explode_multipart` already separates the gap into its disjoint
        # pieces (its own docstring: "a block is always one contiguous
        # polygon") -- re-`unary_union`-ing them back together right after,
        # as this used to do, undoes that: several genuinely separate gap
        # regions across the compartment mosaic (a common shape once more
        # than a couple of edits have happened) would re-fuse into one
        # MultiPolygon and get persisted as a SINGLE remainder row. One row
        # per real piece, matching every other multi-piece creation path
        # in this codebase (Auto-Block commit, cut/split/divide).
        parts = [p for p in _explode_multipart(gap) if area_sqm(p) > COVERAGE_EPSILON_M2]
        added_ha = 0.0
        from .forest_units.model import DEPTH_TOP_BLOCK, DEPTH_TOP_COMPARTMENT

        is_comp = _level_is_compartment(level)
        remainder_rows: List[ForestBlock] = []
        for part in parts:
            idx = next_block_index(db, str(calculation.id))
            serial = compartment_serial(idx) if is_comp else block_serial(idx)
            part_ha = area_sqm(part) / SQM_PER_HA
            block = ForestBlock(
                calculation_id=calculation.id,
                name=serial,
                block_name=serial,
                natural_name=None,
                geometry=_from_shape(part),
                area_hectares=round(part_ha, 4),
                area_sqm=round(area_sqm(part), 2),
                index=idx,
                is_compartment=is_comp,
                division_level=(DEPTH_TOP_COMPARTMENT if is_comp else DEPTH_TOP_BLOCK),
                raster_layer_id=raster_layer_id,
            )
            db.add(block)
            db.flush()
            remainder_rows.append(block)
            added_ha += part_ha
            logger.info(
                "[invariant] remainder %s added for calc=%s level=%s (%.2f ha)",
                _level_prefix(level).lower(), calculation.id, level, part_ha,
            )
        if remainder_rows:
            # RS-2.19: elevation is a read-only attribute of every unit, incl.
            # a fill-in remainder. Not re-running the forest-relative
            # Low/Mid/High zone assignment here -- that would need touching
            # sibling rows outside this call's own scope -- so a remainder
            # row's `dominant_elevation_zone` stays NULL; its min/mean/max
            # are still populated.
            from .elevation_service import apply_elevation

            apply_elevation(db, remainder_rows)
            db.flush()
        if parts:
            result["remainder_added"] = True
            result["gap_ha"] = round(added_ha, 4)
            if is_comp:
                result["warnings"].append("REMAINDER_COMPARTMENT_ADDED")
            else:
                result["warnings"].append("REMAINDER_BLOCK_ADDED")
    return result


def _from_shape(geom):
    from geoalchemy2.shape import from_shape
    return from_shape(make_valid(geom), srid=4326)
