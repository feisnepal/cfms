"""A forest's units as a flat, ordered list that knows each unit's parent and how many sub-units it has.

For the readers that need the HIERARCHY (the per-sub-unit inventory report, the inventory consistency check) and must not know the
structure columns themselves: only this module does. Read-only; one query.
"""

from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy import text
from sqlalchemy.orm import Session

_HIERARCHY = text(
    """
    SELECT b.id::text AS id, b.block_name AS name, b.parent_block_id::text AS parent_id, b.division_level AS depth,
           b.index AS idx, ST_Area(b.geometry::geography) / 10000.0 AS area_ha,
           (SELECT count(*) FROM forest_blocks c WHERE c.parent_block_id = b.id) AS kids
    FROM forest_blocks b WHERE b.calculation_id = :cid ORDER BY b.division_level, b.index
    """
)


def unit_hierarchy(db: Session, calc_id: Any) -> List[Dict[str, Any]]:
    """Every unit of the forest, shallowest first: ``id, name, parent_id, depth, idx, area_ha`` (true hectares) and ``kids`` (its
    real number of sub-units, counted - not the stored ``child_count``). ``name`` is ``""`` for a unit without one."""
    out = []
    for r in db.execute(_HIERARCHY, {"cid": str(calc_id)}):
        d = dict(r._mapping)
        d["name"] = d["name"] or ""
        d["area_ha"] = float(d["area_ha"] or 0.0)
        out.append(d)
    return out


_LEAF_IDS = text(
    """
    SELECT b.id::text FROM forest_blocks b WHERE b.calculation_id = :c
    AND NOT EXISTS (SELECT 1 FROM forest_blocks k WHERE k.parent_block_id = b.id)
    """
)

_LEAF_BY_OVERLAP = text(
    """
    SELECT b.id::text FROM forest_blocks b WHERE b.calculation_id = :c
    AND NOT EXISTS (SELECT 1 FROM forest_blocks k WHERE k.parent_block_id = b.id)
    AND ST_Intersects(b.geometry, ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326))
    ORDER BY ST_Area(ST_Intersection(b.geometry, ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326))) DESC LIMIT 1
    """
)


def leaf_unit_ids(db: Session, calc_id: Any) -> set:
    """The ids (text) of the forest's leaf units - the ones that tile the boundary and that plan lines can be tied to."""
    return {r[0] for r in db.execute(_LEAF_IDS, {"c": str(calc_id)}).fetchall()}


def leaf_unit_by_overlap(db: Session, calc_id: Any, geojson: str) -> Any:
    """The leaf unit that a GeoJSON geometry overlaps most (its id as text), or None when it overlaps none."""
    return db.execute(_LEAF_BY_OVERLAP, {"c": str(calc_id), "g": geojson}).scalar()


_TREES_ON_A_DIVIDED_UNIT = text(
    """
    SELECT 1
      FROM public.inventory_trees t
      JOIN public.forest_blocks unit
        ON unit.calculation_id = :calc AND unit.is_compartment = TRUE AND unit.name = t.extra_columns->>'compartment_name'
       AND EXISTS (SELECT 1 FROM public.forest_blocks kid WHERE kid.parent_block_id = unit.id)
      JOIN public.forest_blocks leaf
        ON leaf.calculation_id = :calc AND leaf.is_compartment = TRUE
       AND NOT EXISTS (SELECT 1 FROM public.forest_blocks z WHERE z.parent_block_id = leaf.id)
       AND ST_Intersects(t.location::geometry, leaf.geometry)
     WHERE t.inventory_calculation_id = :inv AND jsonb_typeof(t.extra_columns) = 'object'
     LIMIT 1
    """
)


def has_trees_filed_under_a_divided_unit(db: Session, calc_id: Any, inventory_id: Any) -> bool:
    """Is any tree of this inventory filed (by the compartment name stored on it) under a unit that has been divided, although an
    undivided unit contains it? The attribute table lists only undivided units, so such a tree belongs to that leaf instead."""
    return db.execute(_TREES_ON_A_DIVIDED_UNIT, {"calc": str(calc_id), "inv": str(inventory_id)}).first() is not None
