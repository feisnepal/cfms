"""Branch-generic equal-area divide for blocks and sub-blocks (FS-4a.5).

Compartments/sub-compartments keep their existing, richer entry point
(``compartment_divide_service.divide_compartment`` / ``preview_divide_compartment``
-- multi-island parents, by-area division, automatic tree reassignment, split
history) untouched. This module gives BLOCKS and SUB-BLOCKS equal-area divide
(count-based strips/grid only) and is the engine for BOTH the root "blocks"
carve (FS-4a.5, new) and the parent-kept "sub-blocks" carve. ``trees_reassigned``
is always ``0`` on the block side -- tree reassignment is a compartment-side
feature; block/sub-block pieces keep the parent's tree membership untouched.

Two shapes, both going through :func:`resolve_divide_source`
(``operations.virtual_root``) so "is there a parent row or not" is answered
once:

* **Root divide** (``parent_id=None``): this forest's FIRST set of top-level
  blocks, carved from the total forest area (P3a-1's ``forest_area_geom`` --
  private land already excluded). Refuses (``BLOCKS_EXIST``) once ANY
  ``forest_blocks`` row exists for the calculation, mirroring
  ``auto_block_service.commit_blocks``'s own guard -- this is the equal-area
  sibling of that natural-feature flow, not a way to add "one more" top-level
  unit onto an existing set.
* **Sub-divide** (``parent_id`` given): a block's sub-blocks, from that block's
  own geometry. Mirrors ``compartment_divide_service``'s sub-compartment path
  exactly (parent must be on the block branch; locked parents refused; a parent
  already carrying children is refused -- one divide per parent).

Multi-island parents (disconnected packaging of a block's geometry, or a
multi-part root boundary) divide per-island via ``divide_multipolygon_equal_area``
+ ``allocate_island_counts`` -- the exact same plan the compartment engine uses,
so a visually disconnected parent does not 400 on the single-Polygon path.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from geoalchemy2.shape import from_shape
from shapely.geometry import mapping
from sqlalchemy.orm import Session

from .... import services  # noqa: F401 -- keeps the package import graph explicit
from ....core.naming_strategies import resolve_naming_strategy
from ....models.calculation import Calculation
from ....models.forest_block import ForestBlock, child_inherit_kwargs
from ... import geometry_edit_service as geo
from ..model import Branch, DEPTH_SUB, DEPTH_TOP_BLOCK, unit_from_row
from .virtual_root import hole_protect_geom, resolve_divide_source

logger = logging.getLogger(__name__)

ERR_BLOCKS_EXIST = "BLOCKS_EXIST"
ERR_PARENT_NOT_FOUND = "PARENT_NOT_FOUND: Forest division not found"
ERR_NOT_A_BLOCK = "NOT_A_BLOCK: Can only sub-divide a block."
ERR_LOCKED = "LOCKED: Block is locked from further division."
ERR_ONCE_ONLY = (
    "DIVISION_ONCE_ONLY: This area already has sub-divisions. Delete them first or select a different area."
)
SQM_PER_HA = 10_000.0


def layer_of(row: ForestBlock) -> str:
    """Classify a ``ForestBlock`` row into one of the four divide layer types
    (``blocks`` / ``sub_blocks`` / ``compartments`` / ``sub_compartments``).

    Lives here (an exempt ``forest_units`` module) so the endpoint router
    routes without writing bare ``division_level`` / ``is_compartment`` column
    references in ``editing.py`` -- the unit model's branch/depth is the single
    source of truth.
    """
    u = unit_from_row(row)
    if u.branch is Branch.COMPARTMENT:
        return "sub_compartments" if u.depth >= DEPTH_SUB else "compartments"
    return "sub_blocks" if u.depth >= DEPTH_SUB else "blocks"


def _resolve_parent(db: Session, calc: Calculation, parent_id: Optional[str]) -> Optional[ForestBlock]:
    """``None`` means a root divide. A given id must resolve to a real,
    non-compartment ``ForestBlock`` row -- the only thing a sub-block can be
    carved from (I10: branch, never depth)."""
    if not parent_id:
        return None
    row = (
        db.query(ForestBlock)
        .filter(ForestBlock.id == parent_id, ForestBlock.calculation_id == calc.id)
        .first()
    )
    if row is None:
        raise ValueError(ERR_PARENT_NOT_FOUND)
    if row.is_compartment:
        raise ValueError(ERR_NOT_A_BLOCK)
    return row


def _guard(db: Session, calc: Calculation, parent: Optional[ForestBlock]) -> None:
    if parent is None:
        existing = db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).count()
        if existing > 0:
            raise ValueError(ERR_BLOCKS_EXIST)
        return
    if parent.is_locked:
        raise ValueError(ERR_LOCKED)
    if db.query(ForestBlock).filter(ForestBlock.parent_block_id == parent.id).count() > 0:
        raise ValueError(ERR_ONCE_ONLY)


def _child_name(parent: Optional[ForestBlock], naming_pattern: str, i: int) -> str:
    """:func:`_persist_children`'s name for child ``i`` -- shared with the
    preview so the ghost labels match the committed names exactly."""
    if parent is not None:
        from ....core.naming_strategies import sub_unit_naming_pattern

        pattern = naming_pattern or sub_unit_naming_pattern(compartment=False)
        block_name = parent.block_name or parent.name
        return (
            pattern.replace("{parent_name}", parent.name)
            .replace("{block_name}", block_name)
            .replace("{index}", str(i))
        )
    return resolve_naming_strategy(is_compartment=False).generate_default_name(i)


def _compute_pieces(
    polygon,
    exclude_geom,
    *,
    layer_type: str,
    method: str,
    n: Optional[int],
    rows: Optional[int],
    cols: Optional[int],
    direction: str,
    direction_angle: Optional[float],
    protect_geom=None,
):
    """Single-Polygon strip/grid divide, or per-island divide when the source is
    a multi-part shape. Shares the plan with the compartment engine so the two
    streams never disagree on multi-part parents.

    ``protect_geom`` (G1, FS-4a.12) — private land ∪ protection units, passed
    straight through to the geometry layer so a hole in ``polygon`` that IS
    excluded ground never gets silently hole-filled for being smaller than
    the MMU artifact threshold."""
    from shapely.geometry import MultiPolygon

    from ...island_apportionment import allocate_island_counts

    shp = geo.as_shapely(polygon)
    if isinstance(shp, MultiPolygon) and len(shp.geoms) > 1:
        parts = list(shp.geoms)
        areas_ha = [max(geo.area_sqm(p) / SQM_PER_HA, 1e-9) for p in parts]
        counts = allocate_island_counts(areas_ha, int(n or 2))["counts"]
        return geo.divide_multipolygon_equal_area(
            shp,
            counts,
            layer_type=layer_type,
            method=method,
            direction=direction,
            rows=rows or 2,
            cols=cols or 2,
            direction_angle=direction_angle,
            exclude_geom=exclude_geom,
            protect_geom=protect_geom,
        )
    return geo.divide_equal_area(
        polygon,
        layer_type=layer_type,
        method=method,
        n=n,
        direction=direction,
        rows=rows,
        cols=cols,
        direction_angle=direction_angle,
        exclude_geom=exclude_geom,
        protect_geom=protect_geom,
    )


def _persist_children(
    db: Session,
    calc: Calculation,
    parent: Optional[ForestBlock],
    pieces: List[Any],
    naming_pattern: str,
) -> List[str]:
    """Root divide: serial names via ``naming_strategies`` (no parent to
    template off of -- ``BlockNamingStrategy`` gives ``Block 1``, ``Block 2``,
    …). Sub-divide: the same ``{parent_name}-SB{index}`` template
    ``compartment_divide_service`` already uses for sub-compartments, mirrored
    for blocks (FS-4a.2)."""
    inherited = child_inherit_kwargs(parent) if parent is not None else {}
    depth = (parent.division_level or DEPTH_TOP_BLOCK) + 1 if parent is not None else DEPTH_TOP_BLOCK

    created_ids: List[str] = []
    for i, piece in enumerate(pieces, start=1):
        sqm = geo.area_sqm(piece)
        child = ForestBlock(
            calculation_id=calc.id,
            name=_child_name(parent, naming_pattern, i),
            block_name=_child_name(parent, naming_pattern, i),
            geometry=from_shape(piece, srid=4326),
            area_hectares=round(sqm / SQM_PER_HA, 4),
            area_sqm=round(sqm, 2),
            index=geo.next_block_index(db, calc.id),
            is_compartment=False,
            parent_block_id=parent.id if parent is not None else None,
            division_level=depth,
            is_locked=False,
            child_count=0,
            display_order=i,
            **inherited,
        )
        db.add(child)
        db.flush()
        created_ids.append(str(child.id))
    if parent is not None:
        parent.child_count = len(created_ids)
    return created_ids


async def divide_blocks(
    db: Session,
    calc: Calculation,
    *,
    parent_id: Optional[str],
    method: str = "strips",
    n: Optional[int] = None,
    rows: Optional[int] = None,
    cols: Optional[int] = None,
    direction: Optional[str] = "vertical",
    direction_angle: Optional[float] = None,
    naming_pattern: str = "",
) -> Dict[str, Any]:
    """Equal-area divide into blocks (``parent_id`` absent, root) or sub-blocks
    (``parent_id`` given). Returns the same shape ``divide_compartment`` returns
    (``split_history_id``/``trees_reassigned`` included, both ``None``/``0`` --
    the block stream records no split history and never reassigns trees)."""
    if method not in {"strips", "grid"}:
        raise ValueError(f"unknown divide method: {method}")

    parent = _resolve_parent(db, calc, parent_id)
    _guard(db, calc, parent)

    polygon, exclude_geom = resolve_divide_source(db, calc, parent)
    if polygon is None:
        raise ValueError("This forest has no boundary to divide.")
    protect_geom = hole_protect_geom(db, calc)  # G1, FS-4a.12

    layer_type = "sub_blocks" if parent is not None else "blocks"
    pieces, warnings = _compute_pieces(
        polygon,
        exclude_geom,
        layer_type=layer_type,
        method=method,
        n=n,
        rows=rows,
        cols=cols,
        direction=direction or "vertical",
        direction_angle=direction_angle,
        protect_geom=protect_geom,
    )
    if geo.W_DIVIDE_TOLERANCE_EXCEEDED in warnings or len(pieces) < 2:
        raise ValueError("Equal-area division violates ±5% tolerance — no change made")

    created_ids = _persist_children(db, calc, parent, pieces, naming_pattern)

    try:
        from ...block_reconcile_service import reconcile_after_block_write

        reconcile_after_block_write(db, calc)
    except Exception:  # noqa: BLE001 -- reconciliation must never fail the divide
        logger.exception("[forest_units.operations.divide] result_data block reconcile failed")
    geo.bump_geometry_version(calc)
    db.commit()

    return {
        "parent_id": str(parent.id) if parent is not None else None,
        "children": created_ids,
        "trees_reassigned": 0,
        "warnings": warnings,
        "n_children": len(created_ids),
        "split_history_id": None,
    }


async def preview_divide_blocks(
    db: Session,
    calc: Calculation,
    *,
    parent_id: Optional[str],
    method: str = "strips",
    n: Optional[int] = None,
    rows: Optional[int] = None,
    cols: Optional[int] = None,
    direction: Optional[str] = "vertical",
    direction_angle: Optional[float] = None,
    naming_pattern: str = "",
) -> Dict[str, Any]:
    """Dry-run of :func:`divide_blocks` -- validates parent + guards, computes
    the pieces, and labels them with the EXACT names commit will persist
    (:func:`_child_name`). ``{success, pieces, warnings, total_pieces,
    parent_id}`` -- same shape as ``preview_divide_compartment``."""
    if method not in {"strips", "grid"}:
        raise ValueError(f"unknown divide method: {method}")

    parent = _resolve_parent(db, calc, parent_id)
    _guard(db, calc, parent)

    polygon, exclude_geom = resolve_divide_source(db, calc, parent)
    if polygon is None:
        raise ValueError("This forest has no boundary to divide.")
    protect_geom = hole_protect_geom(db, calc)  # G1, FS-4a.12

    layer_type = "sub_blocks" if parent is not None else "blocks"
    pieces, warnings = _compute_pieces(
        polygon,
        exclude_geom,
        layer_type=layer_type,
        method=method,
        n=n,
        rows=rows,
        cols=cols,
        direction=direction or "vertical",
        direction_angle=direction_angle,
        protect_geom=protect_geom,
    )
    if geo.W_DIVIDE_TOLERANCE_EXCEEDED in warnings:
        return {
            "success": False,
            "pieces": [],
            "warnings": warnings,
            "total_pieces": 0,
            "parent_id": str(parent.id) if parent is not None else None,
            "reason": "TOLERANCE_EXCEEDED",
        }
    if len(pieces) < 2:
        return {
            "success": False,
            "pieces": [],
            "warnings": warnings,
            "total_pieces": 0,
            "parent_id": str(parent.id) if parent is not None else None,
            "reason": "TOO_FEW_PIECES",
        }

    labelled = []
    for i, piece in enumerate(pieces, start=1):
        sqm = geo.area_sqm(piece)
        labelled.append(
            {
                "geometry": mapping(piece),
                "name": _child_name(parent, naming_pattern, i),
                "area_hectares": round(sqm / SQM_PER_HA, 4),
                "area_sqm": round(sqm, 2),
                "index": i,
            }
        )
    return {
        "success": True,
        "pieces": labelled,
        "warnings": warnings,
        "total_pieces": len(labelled),
        "parent_id": str(parent.id) if parent is not None else None,
    }