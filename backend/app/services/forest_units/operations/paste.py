"""Paste a copied feature into a unit layer (D12, FS-4a.11).

Owner decisions (`FOREST_STRUCTURE_RULE_AUDIT_REPORT.md` report §15,
"D12 paste into a unit layer only from another layer, takes ground from
neighbours after preview, cross-stream paste only while the target stream
is empty"):

- The pasted shape is clipped to its **shell** -- the parent's own geometry
  for a sub-level paste (``sub_blocks``/``sub_compartments``), or the
  virtual root (P3a-1's ``forest_area_geom``, protection units already
  punched out) for a top-level paste (``blocks``/``compartments``) --
  exactly the same shell every other create-fresh-children operation in
  this package resolves through :func:`virtual_root.resolve_divide_source`.
- **Take ground from neighbours**: wherever the clipped pasted shape
  overlaps an EXISTING sibling (same parent, same branch), the paste wins
  that ground -- the sibling shrinks. If shrinking a sibling would leave it
  below the sliver floor (``MIN_COMPARTMENT_AREA_M2``, the one every
  sibling operation in this package already agrees on), what's left of it
  is folded into the pasted shape instead of surviving as a near-empty
  stub (the same "absorb, don't orphan a sliver" rule
  ``reshape.reclip_children``/``reparent.redistribute_children`` already
  apply) -- the plan's own "(absorb tiny pieces)".
- **Same-place paste is refused with a reason**, not silently accepted:
  pasting a shape that (near-)exactly coincides with an existing sibling
  (IoU > 98%) would mean "take almost all of an existing unit's ground for
  no real structural change" -- clearly a mistake (e.g. pasting a unit
  right back where it was copied from, unmoved), not an intentional edit.
- **Cross-stream paste** (pasting into the block branch while the forest
  already carries real compartments, or vice versa) is refused with
  ``STREAM_EMPTY_REQUIRED`` unless the OTHER branch is currently completely
  empty -- the same mutual-exclusivity invariant (D1/I10) every other
  create path in this package enforces, phrased the way D12 asks for it:
  "only while the target stream is empty" reads as "only while switching
  away from nothing".

Attributes on every new pasted piece are inherited the same way any other
freshly-minted child in this package gets them --
``child_inherit_kwargs(parent)`` for a sub-level paste, nothing (fresh
defaults) for a top-level paste with no parent -- NOT from the copied
source feature's own original row (which the frontend clipboard already
strips identity/style columns from before copying, see
``lib/featureClipboard.ts::STRIPPED_KEYS``).

:func:`compute_paste` is the pure planning step (no DB writes) shared by
preview and apply, mirroring every other divide/reshape module's
preview/commit split. Preview calls it and serialises the result without
persisting; apply calls the SAME function then writes it.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from geoalchemy2.shape import from_shape, to_shape
from shapely import make_valid
from shapely.geometry import MultiPolygon, Polygon, mapping
from shapely.geometry import shape as shp
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from sqlalchemy.orm import Session

from ....core.naming_strategies import resolve_naming_strategy, sub_unit_serial
from ....models.calculation import Calculation
from ....models.forest_block import ForestBlock, child_inherit_kwargs
from ... import geometry_edit_service as geo
from ..model import DEPTH_TOP_BLOCK, DEPTH_TOP_COMPARTMENT
from .reshape import reclip_children
from .virtual_root import resolve_divide_source

logger = logging.getLogger(__name__)

ERR_PARENT_NOT_FOUND = "PARENT_NOT_FOUND: Forest division not found"
ERR_NOT_A_BLOCK = "NOT_A_BLOCK: Sub-blocks can only be pasted under a block."
ERR_NOT_A_COMPARTMENT = (
    "NOT_A_COMPARTMENT: Sub-compartments can only be pasted under a compartment."
)
ERR_LOCKED = "LOCKED: Target is locked from further division."
ERR_NO_USABLE_GEOMETRY = (
    "NO_USABLE_GEOMETRY: None of the pasted shapes have any ground inside the target area."
)
ERR_SAME_PLACE = (
    "SAME_PLACE: This shape already occupies (nearly) the same ground as an existing unit."
)
ERR_STREAM_EMPTY_REQUIRED = (
    "STREAM_EMPTY_REQUIRED: This forest already uses the other stream "
    "(blocks/compartments); pasting into this one is only allowed while it is empty."
)

#: IoU above which two polygons are "the same place", not a real edit.
SAME_PLACE_IOU: float = 0.98


def _min_area_sqm() -> float:
    from ...compartment_divide_service import MIN_COMPARTMENT_AREA_M2

    return MIN_COMPARTMENT_AREA_M2


def _explode(geom: Any) -> List[Any]:
    if geom is None or geom.is_empty:
        return []
    geom = make_valid(geom)
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, MultiPolygon):
        return [p for p in geom.geoms if p is not None and not p.is_empty]
    return []


def _union1(parts: List[Any]) -> BaseGeometry:
    return parts[0] if len(parts) == 1 else unary_union(parts)


def _is_compartment_branch(layer_type: str) -> bool:
    return layer_type in ("compartments", "sub_compartments")


def _is_sub_layer(layer_type: str) -> bool:
    return layer_type in ("sub_blocks", "sub_compartments")


def _other_branch_has_rows(db: Session, calc: Calculation, is_compartment: bool) -> bool:
    """D1/I10 mutual exclusivity: does the OTHER branch already have real
    units in this calc? (Any depth -- a lone sub-unit of the other branch
    still counts; there is no legal way to have one without a top-level
    unit of the same branch above it, but this checks directly rather than
    assuming that invariant already holds.)"""
    return (
        db.query(ForestBlock)
        .filter(
            ForestBlock.calculation_id == calc.id,
            ForestBlock.is_compartment.is_(not is_compartment),
        )
        .first()
        is not None
    )


def _shell_and_parent(
    db: Session, calc: Calculation, layer_type: str, parent_id: Optional[str]
) -> Tuple[BaseGeometry, Optional[ForestBlock]]:
    """The shell to clip pasted shapes to, and the parent row (``None`` for
    a top-level paste)."""
    if _is_sub_layer(layer_type):
        if not parent_id:
            raise ValueError(ERR_PARENT_NOT_FOUND)
        parent = (
            db.query(ForestBlock)
            .filter(ForestBlock.id == parent_id, ForestBlock.calculation_id == calc.id)
            .first()
        )
        if parent is None:
            raise ValueError(ERR_PARENT_NOT_FOUND)
        if layer_type == "sub_blocks" and parent.is_compartment:
            raise ValueError(ERR_NOT_A_BLOCK)
        if layer_type == "sub_compartments" and not parent.is_compartment:
            raise ValueError(ERR_NOT_A_COMPARTMENT)
        if parent.is_locked:
            raise ValueError(ERR_LOCKED)
        shell = to_shape(parent.geometry) if parent.geometry is not None else None
        if shell is None or shell.is_empty:
            raise ValueError(ERR_PARENT_NOT_FOUND)
        return shell, parent

    # Top-level (blocks/compartments): the virtual root, same shell every
    # root-level divide/auto-create resolves through (D6 -- no phantom
    # whole-forest parent row).
    shell, _exclude = resolve_divide_source(db, calc, None)
    if shell is None or shell.is_empty:
        raise ValueError(ERR_PARENT_NOT_FOUND)
    return shell, None


def compute_paste(
    db: Session,
    calc: Calculation,
    layer_type: str,
    parent_id: Optional[str],
    raw_features: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Plan (never persists) what pasting ``raw_features`` (GeoJSON geometry
    dicts) into ``layer_type`` under ``parent_id`` would do.

    Returns ``{new_pieces: [(name, shapely geometry)], trimmed: [(sibling_row,
    new shapely geometry)], absorbed: [sibling_row, ...], skipped: int,
    parent, is_compartment, depth}``. Raises ``ValueError`` (a code string,
    same convention as every other operation in this package) for a refusal
    that applies to the WHOLE paste (parent not found/wrong branch/locked,
    cross-stream, same-place) -- an individual feature with no usable
    ground after clipping is simply skipped (counted in ``skipped``), not a
    whole-request failure.
    """
    is_compartment = _is_compartment_branch(layer_type)
    # Parent/branch validity first: a specific wrong-parent selection
    # (sub_blocks under a compartment, a locked parent, a missing parent)
    # deserves its own precise reason before the broader forest-level
    # cross-stream policy check below -- which, for a sub-level paste,
    # would otherwise ALWAYS fire first and mask it (the very existence of
    # a wrong-branch parent to select means that branch already has rows).
    shell, parent = _shell_and_parent(db, calc, layer_type, parent_id)
    if _other_branch_has_rows(db, calc, is_compartment):
        raise ValueError(ERR_STREAM_EMPTY_REQUIRED)

    min_area = _min_area_sqm()

    if parent is not None:
        siblings = (
            db.query(ForestBlock)
            .filter(ForestBlock.parent_block_id == parent.id)
            .all()
        )
        depth = (parent.division_level or 1) + 1
        inherited = child_inherit_kwargs(parent)
    else:
        siblings = (
            db.query(ForestBlock)
            .filter(
                ForestBlock.calculation_id == calc.id,
                ForestBlock.is_compartment.is_(is_compartment),
                ForestBlock.parent_block_id.is_(None),
            )
            .all()
        )
        depth = DEPTH_TOP_COMPARTMENT if is_compartment else DEPTH_TOP_BLOCK
        # When the forest's top-level structure IS one Auto-Block layer (every sibling belongs to the
        # same layer), a pasted/drawn unit takes ground from that layer's units, so it joins the layer:
        # demoting the layer then hides it too, instead of leaving a legacy-looking orphan that blocks
        # the layer from being promoted again.
        _layers = {sib.raster_layer_id for sib in siblings}
        inherited = (
            {"raster_layer_id": next(iter(_layers))}
            if len(_layers) == 1 and None not in _layers
            else {}
        )

    # Working copy: sibling id -> current shapely geometry (None once fully
    # absorbed into a pasted piece).
    sib_geoms: Dict[Any, Optional[BaseGeometry]] = {
        s.id: to_shape(s.geometry) for s in siblings if s.geometry is not None
    }
    trimmed_ids: Dict[Any, BaseGeometry] = {}
    absorbed_ids: List[Any] = []

    new_pieces: List[Tuple[str, BaseGeometry]] = []
    placed_union: Optional[BaseGeometry] = None  # pieces already placed THIS call
    skipped = 0
    next_index = len(siblings) + 1

    for feat in raw_features:
        try:
            geom = make_valid(shp(feat))
        except Exception:  # noqa: BLE001 -- an unreadable feature is skipped, not fatal
            logger.warning("[paste] feature geometry unreadable", exc_info=True)
            skipped += 1
            continue
        try:
            clipped = make_valid(geom.intersection(shell))
        except Exception:  # noqa: BLE001 -- same: skip this one feature only
            logger.warning("[paste] clip to shell failed", exc_info=True)
            skipped += 1
            continue
        if placed_union is not None:
            # A later feature in the SAME batch never overlaps an earlier
            # one already placed -- first-in-the-batch wins.
            try:
                clipped = make_valid(clipped.difference(placed_union))
            except Exception:  # noqa: BLE001 -- keep the un-differenced clip rather than drop the feature
                logger.warning("[paste] batch self-overlap check failed", exc_info=True)
        parts = [p for p in _explode(clipped)]
        area = sum(geo.area_sqm(p) for p in parts)
        if not parts or area < min_area:
            skipped += 1
            continue
        piece_geom = _union1(parts)

        # Same-place refusal, checked against the CURRENT sibling state (an
        # earlier feature in this same batch may have already trimmed a
        # sibling) — a near-total overlap is judged against what actually
        # exists on the ground right now, not a stale pre-batch snapshot.
        for sid, sgeom in sib_geoms.items():
            if sgeom is None or sgeom.is_empty:
                continue
            try:
                inter_area = geo.area_sqm(piece_geom.intersection(sgeom))
            except Exception:  # noqa: BLE001 -- an unreadable sibling can't be same-place-checked
                logger.warning("[paste] same-place check failed", exc_info=True)
                continue
            if inter_area <= 0:
                continue
            union_area = geo.area_sqm(piece_geom) + geo.area_sqm(sgeom) - inter_area
            if union_area > 0 and inter_area / union_area > SAME_PLACE_IOU:
                raise ValueError(ERR_SAME_PLACE)

        # Take ground from neighbours.
        for sid, sgeom in list(sib_geoms.items()):
            if sgeom is None or sgeom.is_empty:
                continue
            try:
                if not piece_geom.intersects(sgeom):
                    continue
                remaining = make_valid(sgeom.difference(piece_geom))
            except Exception:  # noqa: BLE001 -- a bad sibling geometry must not break the paste
                logger.warning("[paste] neighbour trim failed", exc_info=True)
                continue
            rem_parts = _explode(remaining)
            rem_area = sum(geo.area_sqm(p) for p in rem_parts)
            if not rem_parts or rem_area < min_area:
                # Absorb whatever's left of this sibling into the pasted
                # piece rather than leave an orphan sliver.
                if rem_parts:
                    piece_geom = make_valid(unary_union([piece_geom, *rem_parts]))
                if sid not in absorbed_ids:
                    absorbed_ids.append(sid)
                trimmed_ids.pop(sid, None)
                sib_geoms[sid] = None
            else:
                new_sib_geom = _union1(rem_parts)
                sib_geoms[sid] = new_sib_geom
                trimmed_ids[sid] = new_sib_geom

        name = (
            sub_unit_serial(compartment=is_compartment, parent_name=parent.name, index=next_index)
            if parent is not None
            else resolve_naming_strategy(is_compartment=is_compartment).generate_default_name(next_index)
        )
        next_index += 1
        new_pieces.append((name, piece_geom))
        placed_union = piece_geom if placed_union is None else unary_union([placed_union, piece_geom])

    if not new_pieces:
        raise ValueError(ERR_NO_USABLE_GEOMETRY)

    return {
        "new_pieces": new_pieces,
        "trimmed": list(trimmed_ids.items()),
        "absorbed": absorbed_ids,
        "skipped": skipped,
        "parent": parent,
        "is_compartment": is_compartment,
        "depth": depth,
        "inherited": inherited,
    }


def _serialize_piece(name: str, geom: BaseGeometry, *, id_: Optional[str] = None) -> Dict[str, Any]:
    sqm = geo.area_sqm(geom)
    out: Dict[str, Any] = {
        "name": name,
        "geometry": mapping(geom),
        "area_hectares": round(sqm / 10_000.0, 4),
        "area_sqm": round(sqm, 2),
    }
    if id_ is not None:
        out["id"] = id_
    return out


def preview_paste(
    db: Session,
    calc: Calculation,
    layer_type: str,
    parent_id: Optional[str],
    raw_features: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Read-only rehearsal of :func:`compute_paste` -- no DB writes at all."""
    plan = compute_paste(db, calc, layer_type, parent_id, raw_features)
    return {
        "new_pieces": [_serialize_piece(n, g) for n, g in plan["new_pieces"]],
        "trimmed": [
            _serialize_piece(f"trimmed:{sid}", g, id_=str(sid)) for sid, g in plan["trimmed"]
        ],
        "absorbed": [str(sid) for sid in plan["absorbed"]],
        "skipped": plan["skipped"],
    }


def apply_paste(
    db: Session,
    calc: Calculation,
    layer_type: str,
    parent_id: Optional[str],
    raw_features: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Same plan as :func:`preview_paste`, persisted. Does not commit -- the
    caller commits, same convention as every other operation module here."""
    plan = compute_paste(db, calc, layer_type, parent_id, raw_features)
    parent = plan["parent"]

    # Trim survivors first (still-real rows, same ids).
    for sid, new_geom in plan["trimmed"]:
        row = db.query(ForestBlock).filter(ForestBlock.id == sid).first()
        if row is None:
            continue
        sqm = geo.area_sqm(new_geom)
        row.geometry = from_shape(new_geom, srid=4326)
        row.area_hectares = round(sqm / 10_000.0, 4)
        row.area_sqm = round(sqm, 2)
        db.flush()
        # A shrunk sibling that is itself divided must take its own children with it, or they
        # would still cover the ground the paste just won (overlap). Same G2 rule an edit uses.
        reclip_children(db, calc, row.id, new_geom)

    # Absorbed siblings are fully gone -- passive_deletes=True (FS-4a.9)
    # cascades any of their own children along with them (D13), same as
    # every other "this row is going away" path in this package.
    for sid in plan["absorbed"]:
        row = db.query(ForestBlock).filter(ForestBlock.id == sid).first()
        if row is not None:
            db.delete(row)
            db.flush()

    created: List[Dict[str, Any]] = []
    for name, geom in plan["new_pieces"]:
        sqm = geo.area_sqm(geom)
        new_row = ForestBlock(
            calculation_id=calc.id,
            name=name,
            block_name=name,
            geometry=from_shape(geom, srid=4326),
            area_hectares=round(sqm / 10_000.0, 4),
            area_sqm=round(sqm, 2),
            index=geo.next_block_index(db, calc.id),
            is_compartment=plan["is_compartment"],
            parent_block_id=parent.id if parent is not None else None,
            division_level=plan["depth"],
            **plan["inherited"],
        )
        db.add(new_row)
        db.flush()
        created.append(_serialize_piece(name, geom, id_=str(new_row.id)))

    # A sub-level paste covers only PART of its parent. The rest must not be left as a gap: the
    # sub-units have to keep tiling the parent, so whatever no child covers becomes a remainder
    # sub-unit -- the same G2 rule `reclip_children` applies after a parent reshape (a no-op when
    # the pasted pieces and siblings already cover the parent).
    remainder_added: List[str] = []
    if parent is not None and parent.geometry is not None:
        remainder_added = reclip_children(db, calc, parent.id, to_shape(parent.geometry))[
            "remainder_added"
        ]

    return {
        "new_pieces": created,
        "remainder_added": remainder_added,
        "trimmed": [
            _serialize_piece(f"trimmed:{sid}", g, id_=str(sid)) for sid, g in plan["trimmed"]
        ],
        "absorbed": [str(sid) for sid in plan["absorbed"]],
        "skipped": plan["skipped"],
    }


def take_ground_for_restored(db: Session, calc: Calculation, row: ForestBlock) -> Dict[str, List[str]]:
    """A unit that is being put BACK (undo of a delete) wins the ground it comes back to.

    Deleting a unit makes the area invariant fill the hole with a Remainder unit; restoring the unit
    then lands it on top of that Remainder. Same rule as Paste (D12, "take ground from neighbours"):
    every same-branch sibling under the same parent that overlaps ``row`` shrinks, or -- when what is
    left would be below the sliver floor -- is absorbed. A shrunk sibling that is itself divided
    re-clips its own children (G2). The restored row keeps its own id and attributes; it only grows
    when it absorbs a sliver. Does not commit.
    """
    result: Dict[str, List[str]] = {"trimmed": [], "absorbed": []}
    if row.geometry is None:
        return result
    geom = to_shape(row.geometry)
    q = db.query(ForestBlock).filter(
        ForestBlock.calculation_id == calc.id,
        ForestBlock.id != row.id,
        ForestBlock.is_compartment.is_(bool(row.is_compartment)),
    )
    q = q.filter(
        ForestBlock.parent_block_id.is_(None)
        if row.parent_block_id is None
        else ForestBlock.parent_block_id == row.parent_block_id
    )
    min_area = _min_area_sqm()
    grew = False
    for sib in q.all():
        sg = to_shape(sib.geometry) if sib.geometry is not None else None
        if sg is None or sg.is_empty or not geom.intersects(sg):
            continue
        parts = _explode(make_valid(sg.difference(geom)))
        left = sum(geo.area_sqm(p) for p in parts)
        if not parts or left < min_area:
            if parts:
                geom = make_valid(unary_union([geom, *parts]))
                grew = True
            db.delete(sib)
            db.flush()
            result["absorbed"].append(str(sib.id))
        else:
            new_geom = _union1(parts)
            sqm = geo.area_sqm(new_geom)
            sib.geometry = from_shape(new_geom, srid=4326)
            sib.area_hectares = round(sqm / 10_000.0, 4)
            sib.area_sqm = round(sqm, 2)
            db.flush()
            reclip_children(db, calc, sib.id, new_geom)
            result["trimmed"].append(str(sib.id))
    if grew:
        sqm = geo.area_sqm(geom)
        row.geometry = from_shape(geom, srid=4326)
        row.area_hectares = round(sqm / 10_000.0, 4)
        row.area_sqm = round(sqm, 2)
        db.flush()
    return result


ERR_NO_UNIT_UNDER_POLYGON = (
    "NO_UNIT_UNDER_POLYGON: Start the polygon inside an existing unit - a sub-unit is carved out "
    "of the unit it lies in."
)


def parent_for_drawn_polygon(
    db: Session, calc: Calculation, layer_type: str, polygon: BaseGeometry
) -> Optional[str]:
    """Which unit a polygon drawn on a sub layer is carved out of (``None`` for a top-level layer).

    The undivided unit the polygon starts in decides it: under an undivided top-level unit it becomes
    that unit's child; over an existing sub-unit it joins that sub-unit's siblings (and takes ground
    from them). Raises ``ValueError(ERR_NO_UNIT_UNDER_POLYGON)`` when it starts in no unit.
    """
    if not _is_sub_layer(layer_type):
        return None
    from .. import queries as unit_queries

    is_compartment = _is_compartment_branch(layer_type)
    point = polygon.representative_point()
    for row in unit_queries.unit_rows(db, calc.id, unit_queries.View.LEAF):
        if bool(row.is_compartment) != is_compartment or row.geometry is None:
            continue
        if to_shape(row.geometry).covers(point):
            return str(row.parent_block_id or row.id)
    raise ValueError(ERR_NO_UNIT_UNDER_POLYGON)
