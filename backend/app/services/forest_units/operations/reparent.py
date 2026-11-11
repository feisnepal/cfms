"""Sub-unit redistribution across replacement pieces (D13, FS-4a.7/4a.8/4a.9).

``forest_blocks.parent_block_id`` is ``ON DELETE CASCADE``: replacing a unit
that has sub-units (``db.delete(row)`` followed by inserting the cut/divide
pieces, exactly what ``editing._replace_feature_with_pieces`` already does)
silently destroys every child along with it, with no re-homing at all. D13:
"sub-units travel with their parent on cut/merge/delete, never orphaned." This
module is the cut/merge case's half of that rule (FS-4a.7/4a.8, via
:func:`redistribute_children`) plus a small shared helper (:func:`child_count`)
FS-4a.9's DELETE endpoints use for their ``confirm_children`` gate -- a real
delete needs no redistribution (there is nowhere for the children to go),
just an explicit "are you sure" before Postgres's now-genuinely-firing
``ON DELETE CASCADE`` (``ForestBlock.compartments`` gained
``passive_deletes=True`` alongside this module) removes them along with their
parent.

A child entirely inside ONE new piece is simply re-parented onto it, geometry
unchanged (no clip artefacts for the common, non-straddling case). A child
whose own geometry straddles more than one new piece (a cut line passed
through its territory) is itself split along the same boundary -- one
grandchild per piece it substantially overlaps, clipped to the intersection.
An overlap below the minimum viable unit area is not made its own grandchild;
it is folded into the child's largest remaining fragment instead (the same
"absorb the sliver into its nearest kept neighbour" rule
``geometry_edit_service.divide_equal_area`` already applies to its own top-
level pieces), so a cut line that barely grazes a sub-unit does not spawn a
near-zero-area orphan.
"""

from __future__ import annotations

import logging
from typing import Any, List, Sequence, Tuple

from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from sqlalchemy.orm import Session

from ....models.calculation import Calculation
from ....models.forest_block import ForestBlock, child_inherit_kwargs
from ... import geometry_edit_service as geo

logger = logging.getLogger(__name__)

#: Same threshold `compartment_divide_service`/`operations.divide` already
#: use for "is this a real unit or a sliver" -- imported lazily below to avoid
#: a module-load-order cycle (compartment_divide_service does not import this
#: module, but importing it eagerly at the top would still tie their load
#: order together for no reason).


def _min_area_sqm() -> float:
    from ...compartment_divide_service import MIN_COMPARTMENT_AREA_M2

    return MIN_COMPARTMENT_AREA_M2


def child_count(db: Session, unit_id: Any) -> int:
    """How many DIRECT children ``unit_id`` has (FS-4a.9's ``confirm_children``
    gate needs this before every delete of a unit that might have sub-units --
    a plain ``db.delete()`` now genuinely removes every descendant, recursively,
    once the caller confirms)."""
    return (
        db.query(ForestBlock)
        .filter(ForestBlock.parent_block_id == unit_id)
        .count()
    )


def redistribute_children(
    db: Session,
    calc: Calculation,
    old_parent_id: Any,
    new_pieces: Sequence[Tuple[ForestBlock, BaseGeometry]],
) -> List[str]:
    """Re-home every existing child of ``old_parent_id`` onto whichever of
    ``new_pieces`` (``(row, shapely geometry)`` pairs) covers it.

    Call this BEFORE deleting the old parent row: the cascade then removes
    the now-superseded old child rows along with it, the same "delete old,
    create new" pattern the parent's own replacement pieces already follow.
    A no-op (returns ``[]``) when the parent has no children, or when
    ``new_pieces`` is empty (nothing to re-home onto -- the caller's delete
    then cascades the children away, which is only reachable if the caller
    is deleting the unit outright with no replacement, not this module's
    concern).
    """
    children = (
        db.query(ForestBlock)
        .filter(ForestBlock.parent_block_id == old_parent_id)
        .all()
    )
    if not children or not new_pieces:
        return []

    min_area = _min_area_sqm()
    created_ids: List[str] = []

    for child in children:
        # A1: deeper nesting than one sub-level stays legal, so THIS child may
        # itself have children -- redistribute them onto wherever `child`
        # itself lands (below), same rule, one level down, before `child`'s
        # own row is removed.
        #
        # NOTE this module exists BECAUSE the DB-level `ON DELETE CASCADE` on
        # `parent_block_id` does not actually fire the way it sounds like it
        # would: SQLAlchemy's ORM manages the `parent_block`/`compartments`
        # relationship itself, and on `db.delete(parent)` it issues an UPDATE
        # nulling every child's `parent_block_id` FIRST (its own built-in
        # "orphan the children" handling) -- by the time the DELETE reaches
        # Postgres, nothing points at the parent any more, so the DB cascade
        # never has anything to do. Without an explicit `db.delete(child)`
        # here, the OLD child row would silently survive with a NULLED
        # parent, not be cleanly replaced. This module deletes every child it
        # has captured/replaced itself, rather than trusting either the DB
        # constraint or the ORM's own default.
        grandchildren_targets: List[Tuple[ForestBlock, BaseGeometry]] = []
        child_geom = to_shape(child.geometry) if child.geometry is not None else None
        if child_geom is None or child_geom.is_empty:
            continue
        inherited = child_inherit_kwargs(child)

        # Overlap of this child with every new piece, biggest first.
        overlaps: List[Tuple[ForestBlock, BaseGeometry, float]] = []
        for piece_row, piece_geom in new_pieces:
            try:
                clipped = child_geom.intersection(piece_geom)
            except Exception:  # noqa: BLE001 -- a bad geometry must not break redistribution
                logger.warning("[reparent] intersection failed", exc_info=True)
                continue
            if clipped is None or clipped.is_empty:
                continue
            area = geo.area_sqm(clipped)
            if area <= 0:
                continue
            overlaps.append((piece_row, clipped, area))
        if not overlaps:
            # The child fell entirely outside every new piece (shouldn't
            # happen when the pieces tile the old parent; defensive). It is
            # simply dropped along with the old parent -- there is nothing to
            # re-home it onto. Deleted explicitly (see the note above): left
            # alone, it would survive as an orphan with a nulled parent.
            logger.warning(
                "[reparent] child %s of %s matched no replacement piece",
                child.id,
                old_parent_id,
            )
            db.delete(child)
            db.flush()
            continue
        overlaps.sort(key=lambda t: t[2], reverse=True)

        # Fold any below-threshold overlap into the largest one -- a sliver
        # of the child poking into a neighbouring piece is not a real
        # sub-unit of its own.
        kept = [overlaps[0]]
        for piece_row, clipped, area in overlaps[1:]:
            if area < min_area:
                merged = unary_union([kept[0][1], clipped])
                kept[0] = (kept[0][0], merged, kept[0][2] + area)
            else:
                kept.append((piece_row, clipped, area))

        if len(kept) == 1:
            # Entirely (or effectively entirely) inside one new piece: the
            # child moves across unchanged, no clip artefacts.
            piece_row, _clipped, _area = kept[0]
            new_row = ForestBlock(
                calculation_id=calc.id,
                name=child.name,
                block_name=child.block_name,
                geometry=from_shape(child_geom, srid=4326),
                area_hectares=child.area_hectares,
                area_sqm=child.area_sqm,
                index=geo.next_block_index(db, calc.id),
                is_compartment=child.is_compartment,
                parent_block_id=piece_row.id,
                compartment_code=child.compartment_code,
                division_level=child.division_level,
                **inherited,
            )
            db.add(new_row)
            db.flush()
            created_ids.append(str(new_row.id))
            grandchildren_targets.append((new_row, child_geom))
        else:
            # Genuine straddle: one replacement row per piece the child
            # substantially overlaps, clipped to the intersection.
            for i, (piece_row, clipped, _area) in enumerate(kept, start=1):
                sqm = geo.area_sqm(clipped)
                new_row = ForestBlock(
                    calculation_id=calc.id,
                    name=f"{child.name}-{i}",
                    block_name=f"{child.block_name or child.name}-{i}",
                    geometry=from_shape(clipped, srid=4326),
                    area_hectares=round(sqm / 10_000.0, 4),
                    area_sqm=round(sqm, 2),
                    index=geo.next_block_index(db, calc.id),
                    is_compartment=child.is_compartment,
                    parent_block_id=piece_row.id,
                    compartment_code=(
                        f"{child.compartment_code}-{i}" if child.compartment_code else None
                    ),
                    division_level=child.division_level,
                    **inherited,
                )
                db.add(new_row)
                db.flush()
                created_ids.append(str(new_row.id))
                grandchildren_targets.append((new_row, clipped))

        # A1: recurse onto whatever `child` itself had below it, now that its
        # replacement row(s) exist to re-home them onto -- BEFORE deleting
        # `child`'s own row, so the recursive call's query
        # (`parent_block_id == child.id`) still finds them.
        created_ids.extend(
            redistribute_children(db, calc, child.id, grandchildren_targets)
        )
        db.delete(child)
        db.flush()

    return created_ids
