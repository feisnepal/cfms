"""Read the units of a forest. Every view is scoped to ONE calculation and ordered by ``index``."""

from __future__ import annotations

import uuid
from enum import Enum
from typing import List, Optional
from uuid import UUID

from sqlalchemy import exists, or_
from sqlalchemy.orm import Session, aliased

from app.models.forest_block import ForestBlock
from app.models.raster_layer import RasterLayer

from .model import Branch, Unit, unit_from_row


class View(str, Enum):
    TOP_LEVEL = "top_level"  # units directly under the outer boundary
    LEAF = "leaf"  # units that are not divided further - together they cover the forest once
    BY_LEVEL = "by_level"  # units at exactly one depth (optionally within one branch)


def _uuid(value) -> UUID:
    return value if isinstance(value, UUID) else uuid.UUID(str(value))


def _ordered(query):
    return query.order_by(ForestBlock.index, ForestBlock.name)


def promoted_or_unlayered(query):
    """Apply the RS-2.16/RS-2.18 (P2.5) promotion filter to an existing
    ``db.query(ForestBlock)...`` query.

    A row belongs to at most one Auto-Block layer. ``raster_layer_id IS
    NULL`` is either a pre-P2.5 row or one from a write path this phase
    hasn't moved onto layers yet (manual draw, import, divide/cut/merge) --
    both have always been real structure and stay visible unconditionally. A
    layered row only counts once its layer is PROMOTED -- this is the one
    filter that keeps an unpromoted trial layer from silently appearing as
    real blocks/compartments on the map, in the attribute table, or inflating
    sampling/OP/CBA/export totals (see RASTER_SOURCES_TRACKER.md "P2.5", the
    corruption this guards against — and the owner report, 2026-10-01, that
    found the FIRST version of this fix only covered `unit_rows` below, not
    the separate `GET .../blocks` endpoints `blocks.py`/`forests.py` also
    query directly).

    Callers must not already have joined `RasterLayer` under this alias --
    this adds its own `outerjoin`.
    """
    return query.outerjoin(
        RasterLayer, ForestBlock.raster_layer_id == RasterLayer.id
    ).filter(
        or_(
            ForestBlock.raster_layer_id.is_(None),
            RasterLayer.promoted_as.isnot(None),
        )
    )


def unit_rows(
    db: Session,
    calc_id,
    view: View = View.LEAF,
    depth: Optional[int] = None,
    branch: Optional[Branch] = None,
) -> List[ForestBlock]:
    """Same selection as :func:`units`, but the ORM rows - for the few callers (reconcile, writers) that need
    columns a ``Unit`` does not carry. Prefer :func:`units`."""
    q = db.query(ForestBlock).filter(ForestBlock.calculation_id == _uuid(calc_id))
    q = promoted_or_unlayered(q)
    if branch is not None:
        q = q.filter(ForestBlock.is_compartment.is_(branch is Branch.COMPARTMENT))

    if view is View.TOP_LEVEL:
        q = q.filter(ForestBlock.parent_block_id.is_(None))
    elif view is View.LEAF:
        child = aliased(ForestBlock)
        q = q.filter(~exists().where(child.parent_block_id == ForestBlock.id))
    elif view is View.BY_LEVEL:
        if depth is None:
            raise ValueError("View.BY_LEVEL needs a depth")
        q = q.filter(ForestBlock.division_level == depth)
    else:  # pragma: no cover - the enum is closed
        raise ValueError(f"unknown view {view!r}")

    return _ordered(q).all()


def units(
    db: Session,
    calc_id,
    view: View = View.LEAF,
    depth: Optional[int] = None,
    branch: Optional[Branch] = None,
) -> List[Unit]:
    """The units of a forest in one of three views.

    ``branch`` narrows any view to one branch (a legacy mixed forest holds both). ``depth`` is required for
    ``BY_LEVEL``. A forest that is ONE block or ONE compartment returns that one unit from every view.
    """
    return [unit_from_row(r) for r in unit_rows(db, calc_id, view, depth, branch)]


def unit_by_id(db: Session, unit_id) -> Optional[Unit]:
    row = db.query(ForestBlock).filter(ForestBlock.id == _uuid(unit_id)).first()
    return unit_from_row(row) if row else None


def children_of(db: Session, unit_id) -> List[Unit]:
    q = db.query(ForestBlock).filter(ForestBlock.parent_block_id == _uuid(unit_id))
    return [unit_from_row(r) for r in _ordered(q).all()]


def descendants_of(db: Session, unit_id) -> List[Unit]:
    """Every unit below ``unit_id`` (children, grandchildren, ...), nearest first."""
    out: List[Unit] = []
    frontier = [_uuid(unit_id)]
    seen = set(frontier)
    while frontier:
        rows = _ordered(
            db.query(ForestBlock).filter(ForestBlock.parent_block_id.in_(frontier))
        ).all()
        frontier = []
        for r in rows:
            if r.id in seen:  # a cycle would be corrupt data; never loop on it
                continue
            seen.add(r.id)
            out.append(unit_from_row(r))
            frontier.append(r.id)
    return out


def leaf_areas_by_name(db: Session, calc_id) -> dict:
    """``{unit block_name: area in hectares}`` over the leaf view - the per-unit area lookup that exports and
    tables key on. Empty when the forest has no unit rows (an upload-mode forest), so callers can fall back to
    the ``result_data`` arrays."""
    return {
        u.block_name: u.area_ha for u in units(db, calc_id, View.LEAF) if u.block_name
    }
