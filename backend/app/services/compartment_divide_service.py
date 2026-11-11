"""
Shared hybrid engine for compartment / sub-compartment equal-area division.

The single source of truth (D2): geometry comes from ``geometry_edit_service``
(``divide_equal_area``: strips/grid, sanitize, ±5% tolerance), persistence is
child-persist under a parent (P3) like the legacy compartment split flow, and
every legacy business guard / naming / history / tree-reassignment step is
replicated here so both the workspace divide endpoints and the legacy split
endpoints share ONE code path.
"""
from typing import Any, Dict, List, Optional, Tuple
import logging

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value
from geoalchemy2.shape import from_shape
from shapely.geometry import MultiPolygon

from ..core.constants import OVER_COVERAGE_CLAMP_M2, SQM_PER_HA
from ..core.naming_strategies import sub_unit_naming_pattern
from ..models.forest_block import ForestBlock, child_inherit_kwargs
from ..models.compartment import CompartmentSplitHistory
from .forest_units.operations.sampling_mutex import check_sampling_mutex
from . import geometry_edit_service as geo
from .island_apportionment import allocate_island_counts, UNDERSIZED_REL

logger = logging.getLogger(__name__)

# Minimum compartment / sub-compartment area — legacy business rule (P12).
MIN_COMPARTMENT_AREA_M2: float = 10000.0  # 1 ha

# Same fallback used by editing.py's cut/merge paths, for a parent row that
# somehow has no color of its own (pre-existing rows created before `color`
# was added).
COMPARTMENT_COLOR_FALLBACK = "#2980b9"


def _plan_island_divide(parent_geom, n, island_counts):
    """Multi-island parent → (parts, counts, alloc). Single-Polygon → (None, None, None).

    ``alloc`` mirrors :func:`allocate_island_counts`'s dict so the preview can
    show the per-island breakdown (MULTI_ISLAND_DIVIDE_PLAN.md P1/P2).
    """
    from shapely.geometry import MultiPolygon

    if not isinstance(parent_geom, MultiPolygon) or len(parent_geom.geoms) < 2:
        return None, None, None

    parts = [p for p in parent_geom.geoms]
    areas_ha = [max(geo.area_sqm(p) / SQM_PER_HA, 1e-9) for p in parts]

    if island_counts and len(island_counts) == len(parts):
        counts = [max(1, int(c)) for c in island_counts]
        total_c = sum(counts)
        target = sum(areas_ha) / max(total_c, 1)
        alloc = {
            "counts": counts,
            "n_effective": total_c,
            "target_area": target,
            "undersized": [
                i
                for i in range(len(parts))
                if areas_ha[i] / counts[i] < UNDERSIZED_REL * target
            ],
        }
    else:
        alloc = allocate_island_counts(areas_ha, int(n or 2))
        counts = alloc["counts"]

    return parts, counts, alloc


def _exclusion_for_parent(db: Session, calc, parent_geom):
    """Union (∩ parent) of what an equal-area divide must punch out:
    private-land sub-areas + existing protection working-circle units.
    Returns a Shapely geometry or None. Best-effort — a bad geometry is skipped.
    See PROTECTION_WORKING_CIRCLE_PLAN.md P2.
    """
    from shapely.geometry import shape as _shape
    from shapely.ops import unary_union as _uu

    parts = []
    rd = (getattr(calc, "result_data", None) or {})
    for sa in (rd.get("sub_areas", []) if isinstance(rd, dict) else []):
        if sa.get("category") != "private_land" or sa.get("isExcluded", False):
            continue
        raw = sa.get("geometry")
        if not isinstance(raw, dict):
            continue
        try:
            g = _shape(raw)
            if g and not g.is_empty:
                parts.append(g)
        except Exception:  # noqa: BLE001 -- a bad sub-area must not fail the divide
            logger.warning("[compartment_divide] skipping unparseable private-land sub-area")

    for row in (
        db.query(ForestBlock)
        .filter(ForestBlock.calculation_id == calc.id, ForestBlock.working_circle == "protection")
        .all()
    ):
        try:
            g = geo.as_shapely(row.geometry)
            if g and not g.is_empty:
                parts.append(g)
        except Exception:  # noqa: BLE001
            logger.warning("[compartment_divide] skipping unreadable protection-unit geometry")

    if not parts:
        return None
    try:
        union = _uu(parts)
        clipped = union.intersection(parent_geom)
        return clipped if (clipped and not clipped.is_empty) else None
    except Exception:  # noqa: BLE001 -- fall back to no exclusion rather than fail
        logger.warning("[compartment_divide] exclusion union/clip failed — dividing gross area")
        return None


# Legacy guard messages (surfaced verbatim so the FE toast matches). The leading
# code prefix lets the API layer route `ValueError` text through the i18n registry.
ERR_ONCE_ONLY = (
    "DIVISION_ONCE_ONLY: This area already has sub-divisions. Delete them first or select a different area."
)
ERR_NOT_COMPARTMENT = "NOT_COMPARTMENT: Can only sub-divide compartments."
ERR_LOCKED = "LOCKED: Block is locked from further division."
ERR_PARENT_NOT_FOUND = "PARENT_NOT_FOUND: Forest division not found"
ERR_BLOCK_REQUIRED = "BLOCK_REQUIRED: Only forest blocks (top level, not yet divided, non-compartment) can be divided into compartments."
# FS-4a.5 root carve: same guard the block stream's public root divide uses
# (``operations.divide`` / ``auto_block_service.commit_blocks``) — the forest
# boundary may be carved into its FIRST top-level set exactly once, and only
# while no unit row exists yet.
ERR_BLOCKS_EXIST = "BLOCKS_EXIST"


def _resolve_parent(db: Session, parent_id: Any, layer_type: str) -> Optional[ForestBlock]:
    """``None`` (and only for ``layer_type="compartments"``) means a ROOT carve:
    the forest boundary itself is the parent (FS-4a.5). The root has no row, so
    geometry comes from the virtual root source, not a ``ForestBlock``."""
    if not parent_id and layer_type == "compartments":
        return None
    row = db.query(ForestBlock).filter(ForestBlock.id == parent_id).first()
    if row is None:
        raise ValueError(ERR_PARENT_NOT_FOUND)
    if layer_type == "compartments":
        # FS-1c.2: was a numeric-level test for "top-level block", which only worked while top blocks sat at
        # depth zero; migration 094 moves them to depth 1 (equal to top compartments), so the numeric test
        # stopped separating the branches. Branch + parent is what the rule means (D5): a compartment division
        # may only start from a top-level, non-compartment block.
        if row.is_compartment or row.parent_block_id is not None:
            raise ValueError(ERR_BLOCK_REQUIRED)
    elif layer_type == "sub_blocks":
        # FS-4a.6 (D3/D1): the block branch's own "one level deeper" layer. Any
        # block-branch unit may be natural-divided on its own basis (a top-level
        # block or a deeper sub-block -- A1 keeps deeper nesting legal); a
        # compartment never specialises back onto the block branch.
        if row.is_compartment:
            raise ValueError(ERR_NOT_COMPARTMENT)
    else:  # sub_compartments
        if not row.is_compartment:
            raise ValueError(ERR_NOT_COMPARTMENT)
    return row


def _guard(db: Session, calc, parent: ForestBlock, layer_type: str) -> None:
    """FS-4a.5: the cross-block ``_check_once_only`` restriction ("at most ONE
    block in the calculation may own a compartment set", P7) is gone -- a
    legacy-chain-model rule with no meaning once compartments never nest under
    a block (D6/D1). ``auto_block_service.resolve_divide_scope`` already
    carries this exact same removal + reasoning for the natural-feature divide
    (2026-09-22, "every block may be divided on its own basis"); this makes
    the equal-area divide consistent with it. What still holds, matching that
    precedent exactly: the sampling mutex, the lock, and "this specific parent
    is divided once" (a second divide on the SAME parent would stack a second
    generation of children on top of the first, silently orphaning it)."""
    if layer_type == "compartments":
        if parent is None:
            # FS-4a.5 root carve: the sampling mutex applies, and the forest may
            # only be carved into its first set of top-level compartments while
            # NO unit row exists yet (mirroring the block stream's BLOCKS_EXIST
            # guard). Different parents are NOT restricted — every block may be
            # divided on its own basis.
            check_sampling_mutex(db, calc.id)
            existing = (
                db.query(ForestBlock)
                .filter(ForestBlock.calculation_id == calc.id)
                .count()
            )
            if existing > 0:
                raise ValueError(ERR_BLOCKS_EXIST)
            return
        check_sampling_mutex(db, calc.id)
    elif parent.is_locked:
        raise ValueError(ERR_LOCKED)
    if parent is not None and db.query(ForestBlock).filter(ForestBlock.parent_block_id == parent.id).count() > 0:
        raise ValueError(ERR_ONCE_ONLY)


def _child_division_level(parent: ForestBlock, layer_type: str) -> int:
    if layer_type == "compartments":
        return 1
    return (parent.division_level or 1) + 1


def _apply_naming_pattern(pattern: str, block_name: str, parent_name: str, index: int) -> str:
    return (
        pattern.replace("{block_name}", block_name)
        .replace("{parent_name}", parent_name)
        .replace("{index}", str(index))
    )


def _child_name(
    parent: Optional[ForestBlock],
    layer_type: str,
    naming_pattern: str,
    index: int,
) -> str:
    """The name a child will persist with -- shared by :func:`_persist_children`
    and the preview so ghost labels match committed names.

    Root carve (``parent`` is ``None``): no ``{block_name}`` / ``{parent_name}``
    to template off of, so the default is the serial ``C{index}`` name
    (:func:`compartment_serial`); a caller-supplied pattern may still use
    ``{index}``.
    """
    if parent is not None:
        block_name = parent.block_name or parent.name
        pattern = naming_pattern or (
            "{block_name}-C{index}"
            if layer_type == "compartments"
            else sub_unit_naming_pattern(compartment=layer_type != "sub_blocks")
        )
        from ..core.naming_strategies import top_unit_name

        return _apply_naming_pattern(pattern, top_unit_name(block_name), top_unit_name(parent.name), index)
    if naming_pattern:
        return naming_pattern.replace("{index}", str(index))
    from ..core.naming_strategies import compartment_serial

    return compartment_serial(index)


def _persist_children(
    db: Session,
    calc,
    parent: Optional[ForestBlock],
    layer_type: str,
    pieces: List[Any],
    naming_pattern: str,
    created_by,
    extras: Optional[List[Dict[str, Any]]] = None,
    allow_multipart: bool = False,
) -> List[str]:
    """``extras`` (optional, one dict per piece) overrides inherited columns for that piece --
    used by the natural-feature divide to record the piece's own dominant slope / aspect /
    canopy class and river-ridge name; ``None`` values fall back to the parent's.

    ``allow_multipart`` (default False): a plain equal-area divide's pieces are
    always genuinely single-part by construction, so a ``MultiPolygon`` piece
    here means the caller has a bug and the model's own
    ``@validates('geometry')`` guard should raise loudly (``MultiPartFeatureError``).
    The natural-feature divide (``auto_block_service.commit_children``) is the
    one caller that can legitimately hand this a ``MultiPolygon``: when a
    below-floor sliver is folded into its largest neighbour and the two are
    disjoint, `.union()` stays a `MultiPolygon` (same "one explicit exception
    to the single-part invariant" `commit_blocks` already documents for the
    whole-forest case) -- it passes ``allow_multipart=True`` and this bypasses
    the validator the same way ``commit_blocks`` does, via
    ``set_committed_value``, instead of raising for a shape it produced on
    purpose."""
    child_level = _child_division_level(parent, layer_type)
    # Dividing changes geometry only — every non-geometric attribute
    # describing the parent's forest/management character (working circle,
    # orientation, style, natural name, dominant slope/aspect/canopy, color)
    # still describes the same ground, so every child inherits it unchanged
    # (same principle as `_replace_feature_with_pieces`'s cut/split/
    # self-divide path; D-2026-09-15 -- previously this path reset color to
    # a fresh palette entry and silently dropped working_circle/orientation/
    # style/natural_name entirely).
    inherited = child_inherit_kwargs(parent) if parent is not None else {}
    if not inherited.get("color"):
        inherited["color"] = COMPARTMENT_COLOR_FALLBACK

    created_ids: List[str] = []
    compartment_branch = layer_type != "sub_blocks"
    for i, piece in enumerate(pieces, start=1):
        sqm = geo.area_sqm(piece)
        name = _child_name(parent, layer_type, naming_pattern, i)
        own = {k: v for k, v in ((extras[i - 1] if extras else None) or {}).items() if v is not None}
        child = ForestBlock(
            calculation_id=calc.id,
            name=name,
            area_hectares=round(sqm / SQM_PER_HA, 4),
            area_sqm=round(sqm, 2),
            index=geo.next_block_index(db, calc.id),
            is_compartment=compartment_branch,
            parent_block_id=parent.id if parent is not None else None,
            compartment_code=name if compartment_branch else None,
            block_name=name,
            division_level=child_level,
            is_locked=False,
            child_count=0,
            display_order=i,
            **{**inherited, **own},
        )
        # A below-floor sliver folded into a disjoint neighbour (natural-
        # feature divide only, see the docstring) stays a genuine
        # MultiPolygon -- bypass the single-part guard for that one
        # deliberate case instead of raising for a shape the caller made on
        # purpose. Every other divide path's pieces are always single-part
        # by construction, so a MultiPolygon there still raises loudly.
        if allow_multipart and isinstance(piece, MultiPolygon):
            set_committed_value(child, "geometry", from_shape(piece, srid=4326))
        else:
            child.geometry = from_shape(piece, srid=4326)
        db.add(child)
        db.flush()
        created_ids.append(str(child.id))
    if parent is not None and layer_type != "compartments":
        parent.child_count = len(created_ids)
    return created_ids


_DIRECTION_ANGLE = {"vertical": 90.0, "horizontal": 0.0}


def _normalize_direction_angle(direction: Optional[str], direction_angle: Optional[float]) -> Optional[float]:
    """Resolve the split angle in degrees (legacy convention 0=N-S, 90=E-W).

    Numeric ``direction_angle`` wins; otherwise map the legacy virtual
    directions vertical/horizontal onto the same scale.
    """
    if direction_angle is not None:
        return float(direction_angle)
    return _DIRECTION_ANGLE.get(direction or "", None)


def _write_history(
    db: Session,
    calc,
    parent: ForestBlock,
    method: str,
    direction: Optional[str],
    parameters: Dict[str, Any],
    n_children: int,
    naming_pattern: str,
    notes: Optional[str],
    created_by,
) -> str:
    history = CompartmentSplitHistory(
        parent_block_id=parent.id,
        calculation_id=calc.id,
        split_method=method,
        split_direction=_normalize_direction_angle(direction, parameters.get("direction_angle")),
        split_parameters=parameters,
        number_of_compartments=n_children,
        created_by=created_by,
        naming_pattern=naming_pattern,
        notes=notes,
    )
    db.add(history)
    db.flush()
    return str(history.id)


def _set_compartment_mode(calc) -> None:
    rd = dict(calc.result_data or {})
    rd["polygon_type"] = "compartment"
    calc.result_data = rd


# C.1 — parent-scoped area invariant: children must exactly tile their parent.
ERR_OVER_COVERAGE = (
    "OVER_COVERAGE: Divide creates over-coverage: children would extend beyond the parent area. "
    "No change was made."
)


def _validate_parent_coverage(db, calc, parent: ForestBlock, child_ids: List[str]) -> None:
    """Union of the newly created children must equal the parent geometry.

    Over-coverage beyond `OVER_COVERAGE_CLAMP_M2` → ValueError (the caller's
    router maps it to HTTP 400 and the transaction is rolled back). Under-coverage
    is not expected (divide_equal_area sanitizes pieces to the parent); any
    numeric slop within the clamp is tolerated.
    """
    children = (
        db.query(ForestBlock)
        .filter(ForestBlock.id.in_(child_ids), ForestBlock.geometry.isnot(None))
        .all()
    )
    if not children:
        return
    from shapely.ops import unary_union as _uu
    from shapely import make_valid as _mv

    child_shapes = [_mv(geo.as_shapely(c.geometry)) for c in children]
    child_union = _uu([s for s in child_shapes if s is not None and not s.is_empty])
    parent_shape = _mv(geo.as_shapely(parent.geometry))
    if child_union is None or child_union.is_empty or parent_shape is None or parent_shape.is_empty:
        return
    excess_m2 = geo.area_sqm(child_union.difference(parent_shape))
    if excess_m2 > OVER_COVERAGE_CLAMP_M2:
        logger.warning(
            "[compartment_divide] OVER-COVERAGE calc=%s parent=%s excess_m2=%.1f",
            calc.id, parent.id, excess_m2,
        )
        db.rollback()
        raise ValueError(ERR_OVER_COVERAGE)


async def divide_compartment(
    db: Session,
    calc,
    parent_id,
    layer_type: str,
    method: str,
    n: Optional[int],
    rows: Optional[int],
    cols: Optional[int],
    direction: Optional[str],
    direction_angle: Optional[float] = None,
    naming_pattern: str = "",
    reassign_trees: bool = False,
    notes: Optional[str] = None,
    created_by=None,
    island_counts: Optional[List[int]] = None,
    target_area_sqm: Optional[float] = None,
) -> Dict[str, Any]:
    """Equal-area divide of a block / compartment into children (compartments / sub-compartments).

    Raises ValueError with a legacy guard message (mapped to HTTP 400 by the router).
    Returns {children, split_history_id, trees_reassigned, warnings, parent_id}.

    ``target_area_sqm`` (user 2026-09-13) — when set, divides by a per-piece
    target area instead of a piece count: every child except the last comes out
    at ~``target_area_sqm`` and the LAST child is the remainder (see
    ``geometry_edit_service.divide_equal_area_by_area``). Takes precedence over
    ``n`` / ``rows`` / ``cols``.

    ``island_counts`` (MULTI_ISLAND_DIVIDE_PLAN.md) — when the parent geometry is
    a MultiPolygon, the per-part piece counts; when omitted they are derived
    from ``n`` by :func:`allocate_island_counts`.
    """
    if layer_type not in {"compartments", "sub_compartments"}:
        raise ValueError(f"divide_compartment only supports compartments/sub_compartments, got '{layer_type}'")
    if method not in {"strips", "grid"}:
        raise ValueError(f"unknown divide method: {method}")

    parent = _resolve_parent(db, parent_id, layer_type)
    _guard(db, calc, parent, layer_type)
    if parent is not None:
        # A parent-style template needs a real parent row to fill
        # {block_name}/{parent_name}; the root carve falls back to the raw
        # caller pattern (or the serial "C1/C2/..." default in _child_name).
        naming_pattern = naming_pattern or (
            "{block_name}-C{index}" if layer_type == "compartments" else sub_unit_naming_pattern(compartment=True)
        )

    if parent is not None:
        parent_geom = geo.as_shapely(parent.geometry)
        exclude_geom = _exclusion_for_parent(db, calc, parent_geom)
    else:
        # FS-4a.5 root compartments: the boundary itself is the parent. Source
        # is the same virtual root the block stream uses (forest_area_geom is
        # boundary minus private land; the exclusion is the protection units).
        from .forest_units.operations.virtual_root import resolve_divide_source

        parent_geom, exclude_geom = resolve_divide_source(db, calc, None)
        if parent_geom is None:
            raise ValueError("This forest has no boundary to divide.")
    from .forest_units.operations.virtual_root import hole_protect_geom

    protect_geom = hole_protect_geom(db, calc)  # G1, FS-4a.12
    if target_area_sqm is not None:
        parts, counts, _alloc = _plan_island_divide(parent_geom, None, island_counts)
        if parts is not None:
            pieces, warnings = geo.divide_multipolygon_equal_area_by_area(
                parent_geom,
                target_area_sqm,
                layer_type=layer_type,
                direction=direction or "vertical",
                min_area_sqm=MIN_COMPARTMENT_AREA_M2,
                direction_angle=direction_angle,
                exclude_geom=exclude_geom,
                protect_geom=protect_geom,
            )
        else:
            pieces, warnings = geo.divide_equal_area_by_area(
                parent_geom,
                target_area_sqm,
                layer_type=layer_type,
                direction=direction or "vertical",
                min_area_sqm=MIN_COMPARTMENT_AREA_M2,
                direction_angle=direction_angle,
                exclude_geom=exclude_geom,
                protect_geom=protect_geom,
            )
    else:
        parts, counts, _alloc = _plan_island_divide(parent_geom, n, island_counts)
        if parts is not None:
            pieces, warnings = geo.divide_multipolygon_equal_area(
                parent_geom,
                counts,
                layer_type=layer_type,
                method=method,
                direction=direction or "vertical",
                rows=rows or 2,
                cols=cols or 2,
                min_area_sqm=MIN_COMPARTMENT_AREA_M2,
                direction_angle=direction_angle,
                exclude_geom=exclude_geom,
                protect_geom=protect_geom,
            )
        else:
            pieces, warnings = geo.divide_equal_area(
                parent_geom,
                layer_type=layer_type,
                method=method,
                n=n,
                direction=direction or "vertical",
                rows=rows,
                cols=cols,
                min_area_sqm=MIN_COMPARTMENT_AREA_M2,
                direction_angle=direction_angle,
                exclude_geom=exclude_geom,
                protect_geom=protect_geom,
            )
    if geo.W_DIVIDE_TOLERANCE_EXCEEDED in warnings or len(pieces) < 2:
        raise ValueError("Equal-area division violates ±5% tolerance — no change made")

    resolved_angle = _normalize_direction_angle(direction, direction_angle)
    parameters: Dict[str, Any] = {
        "method": method,
        "direction": direction,
        "direction_angle": resolved_angle,
        "count": n,
        "rows": rows,
        "cols": cols,
        "target_area_sqm": target_area_sqm,
        "min_area_sqm": MIN_COMPARTMENT_AREA_M2,
    }
    created_ids = _persist_children(db, calc, parent, layer_type, pieces, naming_pattern, created_by)
    if parent is not None:
        split_history_id = _write_history(
            db, calc, parent, method, direction, parameters, len(created_ids), naming_pattern, notes, created_by
        )
    else:
        # A root carve has no parent row to satisfy the split history's required
        # parent link; the split itself is still fully recorded in the child
        # rows' naming/index/display order.
        split_history_id = None
    _set_compartment_mode(calc)
    # Keep result_data['compartments'] a live view of the forest_blocks rows we
    # just created — reports, the OP tables and (re-)analysis all read that key,
    # not the DB, to decide block- vs compartment-mode.
    try:
        from .block_reconcile_service import reconcile_compartments_from_db
        reconcile_compartments_from_db(db, calc)
    except Exception:  # noqa: BLE001 -- reconciliation must never fail the divide
        logger.exception("[compartment_divide] result_data compartment reconcile failed")
    geo.bump_geometry_version(calc)
    if parent is not None:
        # C.1 — parent-scoped area invariant: the union of the new children must
        # tile the parent exactly (over-coverage → rollback; divide_equal_area
        # already sanitizes pieces to the parent so under-coverage cannot occur).
        _validate_parent_coverage(db, calc, parent, created_ids)
    db.commit()

    trees_reassigned = 0
    if reassign_trees and parent is not None:
        try:
            from .tree_reassignment import auto_assign_trees_by_location
            result = await auto_assign_trees_by_location(db, parent.id)
            trees_reassigned = result["total_assigned"]
        except (ValueError, Exception) as e:  # ValueError = no compartments edge; keep soft
            logger.warning(f"[compartment_divide] tree reassignment skipped: {e}")

    return {
        "parent_id": str(parent.id) if parent is not None else None,
        "children": created_ids,
        "split_history_id": split_history_id,
        "trees_reassigned": trees_reassigned,
        "warnings": warnings,
        "n_children": len(created_ids),
    }


async def preview_divide_compartment(
    db: Session,
    calc,
    parent_id,
    layer_type: str,
    method: str = "strips",
    n: Optional[int] = None,
    rows: Optional[int] = None,
    cols: Optional[int] = None,
    direction: Optional[str] = None,
    direction_angle: Optional[float] = None,
    naming_pattern: str = "",
    island_counts: Optional[List[int]] = None,
    target_area_sqm: Optional[float] = None,
) -> Dict[str, Any]:
    """Dry-run of :func:`divide_compartment` — validates guards + computes labelled pieces (P13).

    For a multi-island parent the response also carries an ``islands`` breakdown
    (area, suggested count, avg piece, undersized flag) + ``target_area_ha`` /
    ``n_effective`` for the per-island editor (MULTI_ISLAND_DIVIDE_PLAN.md P2).
    When ``target_area_sqm`` is set the divide is a by-area divide (the count /
    multi-island breakdown is bypassed — every parcel divides by area with its
    own last-piece remainder).
    """
    if layer_type not in {"compartments", "sub_compartments"}:
        raise ValueError(f"divide_compartment only supports compartments/sub_compartments, got '{layer_type}'")
    if method not in {"strips", "grid"}:
        raise ValueError(f"unknown divide method: {method}")

    parent = _resolve_parent(db, parent_id, layer_type)
    _guard(db, calc, parent, layer_type)

    if parent is not None:
        parent_geom = geo.as_shapely(parent.geometry)
        exclude_geom = _exclusion_for_parent(db, calc, parent_geom)
    else:
        # FS-4a.5 root compartments preview — same virtual-root source as the
        # commit path, so the ghost overlay shows the exact carve that will land.
        from .forest_units.operations.virtual_root import resolve_divide_source

        parent_geom, exclude_geom = resolve_divide_source(db, calc, None)
        if parent_geom is None:
            raise ValueError("This forest has no boundary to divide.")
    from .forest_units.operations.virtual_root import hole_protect_geom

    protect_geom = hole_protect_geom(db, calc)  # G1, FS-4a.12
    if target_area_sqm is not None:
        parts, counts, alloc = _plan_island_divide(parent_geom, None, island_counts)
        if parts is not None:
            pieces, warnings = geo.divide_multipolygon_equal_area_by_area(
                parent_geom,
                target_area_sqm,
                layer_type=layer_type,
                direction=direction or "vertical",
                min_area_sqm=MIN_COMPARTMENT_AREA_M2,
                direction_angle=direction_angle,
                exclude_geom=exclude_geom,
                protect_geom=protect_geom,
            )
        else:
            pieces, warnings = geo.divide_equal_area_by_area(
                parent_geom,
                target_area_sqm,
                layer_type=layer_type,
                direction=direction or "vertical",
                min_area_sqm=MIN_COMPARTMENT_AREA_M2,
                direction_angle=direction_angle,
                exclude_geom=exclude_geom,
                protect_geom=protect_geom,
            )
    else:
        parts, counts, alloc = _plan_island_divide(parent_geom, n, island_counts)
        if parts is not None:
            pieces, warnings = geo.divide_multipolygon_equal_area(
                parent_geom,
                counts,
                layer_type=layer_type,
                method=method,
                direction=direction or "vertical",
                rows=rows or 2,
                cols=cols or 2,
                min_area_sqm=MIN_COMPARTMENT_AREA_M2,
                direction_angle=direction_angle,
                exclude_geom=exclude_geom,
                protect_geom=protect_geom,
            )
        else:
            pieces, warnings = geo.divide_equal_area(
                parent_geom,
                layer_type=layer_type,
                method=method,
                n=n,
                direction=direction or "vertical",
                rows=rows,
                cols=cols,
                min_area_sqm=MIN_COMPARTMENT_AREA_M2,
                direction_angle=direction_angle,
                exclude_geom=exclude_geom,
                protect_geom=protect_geom,
            )
    if geo.W_DIVIDE_TOLERANCE_EXCEEDED in warnings:
        return {
            "success": False,
            "pieces": [],
            "warnings": warnings,
            "parent_id": str(parent.id) if parent is not None else None,
            "reason": "TOLERANCE_EXCEEDED",
        }
    if len(pieces) < 2:
        return {
            "success": False,
            "pieces": [],
            "warnings": warnings,
            "parent_id": str(parent.id) if parent is not None else None,
            "reason": "TOO_FEW_PIECES",
        }

    labelled = []
    for i, piece in enumerate(pieces, start=1):
        from shapely.geometry import mapping
        sqm = geo.area_sqm(piece)
        labelled.append({
            "geometry": mapping(piece),
            "name": _child_name(parent, layer_type, naming_pattern, i),
            "area_hectares": round(sqm / SQM_PER_HA, 4),
            "area_sqm": round(sqm, 2),
            "index": i,
        })
    result: Dict[str, Any] = {
        "success": True,
        "pieces": labelled,
        "warnings": warnings,
        "parent_id": str(parent.id) if parent is not None else None,
        "total_pieces": len(labelled),
    }
    if parts is not None and alloc is not None:
        target = alloc["target_area"]
        islands = []
        for i, part in enumerate(parts):
            area_ha = geo.area_sqm(part) / SQM_PER_HA
            c = counts[i]
            islands.append({
                "index": i,
                "area_ha": round(area_ha, 4),
                "suggested_count": int(c),
                "avg_piece_ha": round(area_ha / c, 4) if c else 0.0,
                "undersized": bool(area_ha / c < UNDERSIZED_REL * target) if c else False,
            })
        result["islands"] = islands
        result["target_area_ha"] = round(target, 4)
        result["n_effective"] = alloc["n_effective"]
    return result