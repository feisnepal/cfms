"""The virtual root (D6, FS-4a.4).

The outer boundary IS the root of the structure tree — no phantom whole-forest
``ForestBlock`` row is ever created to stand in for it (D6: "the boundary is the
root, so no phantom whole-forest parent block"). A TOP-LEVEL divide or
auto-create — one with no real parent unit row, because it is minting the
forest's first blocks/compartments, or adding another top-level unit directly —
works from the boundary directly instead.

Every operation in this package (FS-4a.5 equal-area divide, FS-4a.6
natural-feature divide/auto-create, …) answers "what am I dividing/creating
from" through :func:`resolve_divide_source`, so "is there a parent row or not"
is decided in exactly one place, the same way for every operation and every
unit type.
"""

from __future__ import annotations

from typing import Optional, Tuple

from geoalchemy2.shape import to_shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from sqlalchemy.orm import Session

from ....models.calculation import Calculation
from ....models.forest_block import ForestBlock
from ..area_model import forest_area_geom, private_land_geom, protection_unit_geoms

#: What a divide/auto-create resolves to: the polygon to carve up, and an
#: optional exclude_geom to punch out of it first (existing protection units
#: at root level; ``None`` when a real parent row is given -- that unit's own
#: exclusions were already applied when IT was created).
DivideSource = Tuple[Optional[BaseGeometry], Optional[BaseGeometry]]


def virtual_root_source(db: Session, calc: Calculation) -> DivideSource:
    """The ``(polygon, exclude_geom)`` a root-level divide/auto-create works from.

    ``polygon`` — the total forest area (P3a-1's ``forest_area_geom``: boundary
    minus every private-land sub-area, D8). ``exclude_geom`` — the union of any
    protection working-circle units that already exist, so a root-level divide
    punches around them rather than slicing through one, the same rule an
    existing parent's own children already follow via
    ``compartment_divide_service._exclusion_for_parent``.

    Returns ``(None, None)`` only when the calculation has no boundary at all.
    """
    polygon = forest_area_geom(calc)
    if polygon is None:
        return None, None
    protection_geoms = protection_unit_geoms(db, calc)
    exclude_geom = unary_union(protection_geoms) if protection_geoms else None
    return polygon, exclude_geom


def resolve_divide_source(
    db: Session, calc: Calculation, parent: Optional[ForestBlock]
) -> DivideSource:
    """The ``(polygon, exclude_geom)`` ONE divide/auto-create call works from.

    ``parent`` given (a real unit row) — that unit's own geometry, no further
    exclusion (its own private-land/protection carve-outs already happened when
    it was created). ``parent`` ``None`` — the virtual root (above).
    """
    if parent is not None:
        geom = to_shape(parent.geometry) if parent.geometry is not None else None
        return geom, None
    return virtual_root_source(db, calc)


def hole_protect_geom(db: Session, calc: Calculation) -> Optional[BaseGeometry]:
    """Union of private land + protection working-circle units (G1, FS-4a.12) —
    what hole-filling (``geometry_edit_service._fill_holes`` /
    ``auto_block_service._fill_holes``) must never silently swallow as an
    "MMU artifact void", because it is deliberately excluded ground, not a
    rendering glitch. A root divide's own polygon (P3a-1's
    ``forest_area_geom``) already carries a private-land-shaped HOLE for any
    parcel that sits fully inside the boundary — this is the value every
    divide/auto-create call site passes as ``protect_geom`` so that hole
    survives sanitize/hole-fill instead of being re-absorbed for being
    smaller than the MMU artifact threshold.

    ``None`` when neither private land nor a protection unit exists (the
    common case — every call site treats ``None`` as "nothing extra to
    protect", not an error).
    """
    geoms = []
    private = private_land_geom(calc)
    if private is not None and not private.is_empty:
        geoms.append(private)
    geoms.extend(protection_unit_geoms(db, calc))
    if not geoms:
        return None
    return unary_union(geoms)
