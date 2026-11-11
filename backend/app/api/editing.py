"""Feature geometry editing API (Phase E-1) — all geometry writes route here.

Single-authority engine: legacy PATCH endpoints (blocks name / update-blocks /
sub-areas) reject the ``geometry`` key at runtime (400) so the validated
pipeline in ``geometry_edit_service`` is never bypassed (review-fix #8).

Routes (E1.2):
  - POST /calculations/{id}/geometry/edit-geometry
  - POST /calculations/{id}/geometry/cut-polygon
  - POST /calculations/{id}/geometry/cut-line
  - POST /calculations/{id}/geometry/divide-equal-areas
  - POST /calculations/{id}/geometry/divide-preview
  - POST /calculations/{id}/geometry/copy-boundary-to-block
  - GET  /calculations/{id}/geometry/delete-guard
  - DELETE /calculations/{id}/boundary
  - GET  /calculations/{id}/geometry/feature   (E3 undo snapshot)
  - POST /calculations/{id}/geometry/restore-feature (E3 undo)

E1.3 locks: structure_locked + map_lifecycle_status are enforced on every
write route.  ``?force=true`` skips the lifecycle status check but NEVER the
structure lock (UI edits never send it).
"""

import copy
import json
import logging
import uuid as uuidlib
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from geoalchemy2.shape import from_shape, to_shape

from ..core.correlation import get_correlation_id
from sqlalchemy import func
from sqlalchemy.orm import Session, attributes

from ..core.database import get_db
from ..core.errors import CalculationErrors
from ..core.exceptions import (
    i18n_error,
    resolve_bare_service_detail,
    resolve_service_detail,
    with_message_np,
)
from ..models.calculation import Calculation
from ..models.forest_block import ForestBlock, child_inherit_kwargs
from ..services.auto_block_service import SOURCE_ERROR_CODE
from ..services.forest_units.model import (
    DEPTH_SUB,
    DEPTH_TOP_BLOCK,
    DEPTH_TOP_COMPARTMENT,
)
from ..models.forest_sub_area import ForestSubArea
from ..models.user import User
from ..models.workspace_layer import WorkspaceLayer
from ..utils.auth import get_current_active_user
from ..utils.single_part_geometry import (
    DEGENERATE_SLIVER_M2,
    explode_and_filter_slivers as _flatten_and_clean_pieces,
)

from ..services import geometry_edit_service as geo
from ..services.geometry_edit_service import (
    SpatialHashIndex,
    W_DIVIDE_TOLERANCE_EXCEEDED,
    W_TOPOLOGY_REJECTED,
)
from ..services.compartment_divide_service import (
    divide_compartment,
    preview_divide_compartment,
)
from ..services.forest_units.operations.divide import (
    divide_blocks,
    preview_divide_blocks,
    layer_of,
)
from ..services import vertex_guard_service as guard
from ..core.sub_area_kinds import is_strip, real_sub_areas
from ..services.sub_area_service import (
    place_sub_area,
    SubAreaPlacementError,
    PLACEMENT_MESSAGES,
)
from ..services.sub_area_reclip_service import (
    W_SUB_AREAS_CLIPPED,
    reclip_sub_areas_to_boundary,
)
from ..services.workspace_cache import invalidate_layers_cache
from ..utils.geometry_utils import (
    calculate_area_geodesic_from_shapely,
    compute_geometry_properties,
)
from ..core.constants import SQM_PER_HA
from ..core.naming_strategies import compartment_serial, block_serial

from app.core.dropped import report_dropped

logger = logging.getLogger(__name__)

router = APIRouter()

# Map lifecycle states that tolerate geometry writes.
EDITABLE_MAP_STATES = {"draft", "submitted", "failed"}

COMPARTMENT_COLOR_FALLBACK = "#2980b9"


# ---------------------------------------------------------------------------
# small auth / guard helpers
# ---------------------------------------------------------------------------


def _get_or_404(db: Session, calculation_id) -> Calculation:
    calc = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calc:
        raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)
    return calc


def _require_owner(calc: Calculation, user: User) -> None:
    if str(calc.user_id) != str(user.id) and user.role.value != "SUPER_ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this calculation",
        )


def _apply_write_guard(calc: Calculation, user: User, force: bool) -> Calculation:
    """E1.3 — structure lock is final (423); lifecycle gate is bypassable via force."""
    _require_owner(calc, user)
    if calc.structure_locked:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=with_message_np(
                {
                    "code": "structure_locked",
                    "structure_locked_at": (
                        str(calc.structure_locked_at)
                        if calc.structure_locked_at
                        else None
                    ),
                },
                "editing.structure_locked",
                preserve_code=True,
            ),
        )
    if not force:
        state = str(getattr(calc, "map_lifecycle_status", "draft"))
        if state not in EDITABLE_MAP_STATES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=with_message_np(
                    {
                        "code": "INVALID_MAP_STATE",
                        "current_state": state,
                    },
                    "editing.invalid_map_state",
                    preserve_code=True,
                    states=sorted(EDITABLE_MAP_STATES),
                    state=state,
                ),
            )
    return calc


def _calc_with_guard(
    db: Session, calculation_id, user: User, force: bool = False
) -> Calculation:
    calc = _get_or_404(db, calculation_id)
    return _apply_write_guard(calc, user, force)


# ---------------------------------------------------------------------------
# feature reads
# ---------------------------------------------------------------------------


def _to_geojson(geo_col) -> Optional[Dict[str, Any]]:
    if geo_col is None:
        return None
    from shapely.geometry import mapping

    try:
        return mapping(to_shape(geo_col))
    except Exception:
        logger.exception(
            "stored geometry unreadable - returning None, so the caller sees "
            "a feature with no shape rather than an error"
        )
        return None


def as_shapely_or_shape(geom):
    """Coerce a GeoJSON dict / shapely geometry into shapely (index-friendly)."""
    from shapely.geometry import shape as shp

    if isinstance(geom, dict):
        try:
            return shp(geom)
        except Exception:
            logger.exception(
                "geometry could not be parsed - returning None, so the caller "
                "sees a feature with no shape rather than an error"
            )
            return None
    return geom


#: The application's own id for the forest boundary. It is a sentinel, not a
#: UUID, so it must never reach a `forest_blocks.id` comparison.
BOUNDARY_FEATURE_ID = "boundary"


def _is_user_group_row_id(value: Any) -> bool:
    """True for a bare row id, False for a legacy `user_group#<id>#<part>` reference.

    P7d addresses a user-group polygon by its ROW id, so this is how the
    write/resolve/merge paths tell "this is a row" from "this is a part inside a
    row". It deliberately does NOT try to parse the id: `UserGroupExtent.id` is an
    INTEGER primary key, so a row id is a bare number and `uuid.UUID` would reject
    every real one. The prefix is the only reliable discriminator.
    """
    if value is None:
        return False
    s = str(value).strip()
    return bool(s) and not s.startswith("user_group#")


def _row_id_of(value: Any) -> int:
    """The integer row id behind a user-group feature id.

    `UserGroupExtent.id` is an Integer, so this coerces rather than parses. A value
    that is not a number at all is a bad request, not a server error - raised as a
    400 here so a nonsense id cannot surface as a 500.
    """
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=400, detail=f"'{value}' is not a user-group row id"
        )


def _structural_uuid(feature_id: str) -> uuidlib.UUID:
    """Validate a structural feature id BEFORE it reaches the database.

    `feature_id` arrives as a raw string from the client. `forest_blocks.id` is
    a UUID column, so anything that is not a UUID used to fail inside psycopg2
    as an `InvalidTextRepresentation` — a 500 whose body, under DEBUG, was the
    full SELECT with every column and parameter in it. Unreadable to the user,
    and a free schema dump to anyone else.

    The one non-UUID that actually shows up is `"boundary"`: the client sends it
    when the forest boundary is the selected feature while a block or
    compartment layer is still the active one. That is a real mismatch, and the
    honest answer is to name it rather than to guess which the user meant —
    silently treating it as the boundary would hand boundary geometry to a code
    path that goes on to save it as a block.
    """
    if feature_id == BOUNDARY_FEATURE_ID:
        raise i18n_error(400, "editing.boundary_is_not_a_division")
    try:
        return uuidlib.UUID(str(feature_id))
    except (ValueError, AttributeError, TypeError):
        raise i18n_error(404, "editing.unknown_feature")


def _boundary_part_index(feature_id: str) -> Optional[int]:
    """`"boundary#2"` / `"2"` → 2; `"boundary"` / `""` / junk → None."""
    s = (feature_id or "").strip()
    if s.startswith("boundary#"):
        s = s[len("boundary#") :]
    if s.isdigit():
        return int(s)
    return None


def _user_group_part_index(feature_id: str) -> Optional[int]:
    """`"user_group#7#2"` → 2; a bare `"user_group#7"` → None (whole extent).

    Mirrors `_boundary_part_index` for the user-group extent: the extent is ONE
    stored row holding a MultiPolygon, so a multi-island boundary is addressed
    per island as `<extent-id>#<part-index>` and edited on its own. A feature_id
    with no part suffix keeps meaning "the whole extent" — that is what a
    single-island extent, and the pre-multipart client, both send.
    """
    s = (feature_id or "").strip()
    marker = "user_group#"
    if not s.startswith(marker):
        return None
    rest = s[len(marker) :]
    # rest is "<extent_id>" or "<extent_id>#<part_index>"
    if "#" not in rest:
        return None
    tail = rest.rsplit("#", 1)[1]
    return int(tail) if tail.isdigit() else None


def _splice_user_group_part(stored, part_index: Optional[int], edited):
    """The extent to store after `edited` replaces island `part_index`.

    The extent is one row holding a MultiPolygon, so editing ONE island must
    leave its neighbours untouched — this replaces that island in place and
    keeps the rest. `part_index is None` (a single-island extent, or a client
    that never split it) means the submitted shape IS the whole extent.

    Returns a plain Polygon or MultiPolygon, which is what the column's
    MULTIPOLYGON typmod needs; a Polygon is wrapped, never stored bare.
    """
    from shapely.geometry import MultiPolygon

    def _as_multipolygon(geom):
        if geom is None:
            return None
        if geom.geom_type == "Polygon":
            return MultiPolygon([geom])
        if geom.geom_type == "MultiPolygon":
            return MultiPolygon(list(geom.geoms))
        raise HTTPException(
            status_code=400,
            detail=f"User group extent cannot hold a {geom.geom_type}",
        )

    if part_index is None:
        return _as_multipolygon(edited)

    stored_mp = _as_multipolygon(stored)
    if stored_mp is None:
        # Nothing stored to splice into: the submitted island is the extent.
        return _as_multipolygon(edited)
    parts = list(stored_mp.geoms)
    if not (0 <= part_index < len(parts)):
        raise HTTPException(status_code=404, detail="User group part not found")

    new_parts = _as_multipolygon(edited)
    replacement = list(new_parts.geoms)
    if not replacement:
        raise HTTPException(status_code=400, detail="User group part is empty")
    # An edited island may itself become several pieces (a cut); splice them all
    # in at that island's position so the untouched islands keep their order.
    parts[part_index : part_index + 1] = replacement
    return MultiPolygon(parts)


def _resolve_feature(db, calc, layer_type: str, feature_id: str) -> Dict[str, Any]:
    if layer_type in STRUCTURAL_LAYERS:
        row = (
            db.query(ForestBlock)
            .filter(
                ForestBlock.id == _structural_uuid(feature_id),
                ForestBlock.calculation_id == calc.id,
            )
            .first()
        )
        if not row:
            raise HTTPException(status_code=404, detail="Forest division not found")
        return {
            "id": str(row.id),
            "name": row.name,
            "geometry": _to_geojson(row.geometry),
        }
    if layer_type == "boundary":
        if getattr(calc, "boundary_geom", None) is None:
            raise HTTPException(status_code=404, detail="Forest boundary is not set")
        gj = _to_geojson(calc.boundary_geom)
        part_count = (
            len(gj["coordinates"]) if gj and gj.get("type") == "MultiPolygon" else 1
        )
        # A multi-island boundary row is addressed as "boundary#<i>" / "<i>" —
        # return that island only so it can be divided on its own (MULTI_ISLAND_
        # DIVIDE_PLAN.md P1). Bare "boundary" (or a single-Polygon boundary)
        # returns the whole geometry.
        idx = _boundary_part_index(feature_id)
        if idx is not None and gj and gj.get("type") == "MultiPolygon":
            if not (0 <= idx < part_count):
                raise HTTPException(status_code=404, detail="Boundary part not found")
            return {
                "id": f"boundary#{idx}",
                "geometry": {"type": "Polygon", "coordinates": gj["coordinates"][idx]},
                "part_index": idx,
                "part_count": part_count,
            }
        return {"id": "boundary", "geometry": gj, "part_count": part_count}
    if layer_type == "sub_areas":
        sa = _find_sub_area(calc, feature_id)
        if sa is None:
            raise HTTPException(status_code=404, detail="Sub-area not found")
        return sa
    if layer_type == "user_group":
        from ..models.user_group import UserGroupExtent

        # P7: each polygon is its own row, so the natural feature id is the plain
        # row id. The legacy `user_group#<extent_id>#<part>` form is still
        # accepted so nothing breaks before the frontend switches over (P7e), and
        # the part-index path is retired in P7d.
        by_row_id = _is_user_group_row_id(feature_id)
        if by_row_id:
            row = (
                db.query(UserGroupExtent)
                .filter(UserGroupExtent.id == _row_id_of(feature_id))
                .filter(UserGroupExtent.calculation_id == calc.id)
                .first()
            )
        else:
            row = (
                db.query(UserGroupExtent)
                .filter(UserGroupExtent.calculation_id == calc.id)
                .first()
            )
        if not row:
            raise HTTPException(status_code=404, detail="User group extent not found")
        from shapely.geometry import mapping as shp_mapping

        # to_shape (geoalchemy2), not shapely's shape(): the column holds a
        # PostGIS element, which shape() cannot read.
        geom_shp = to_shape(row.extent_geometry) if row.extent_geometry else None
        if geom_shp is None:
            raise HTTPException(status_code=404, detail="User group extent not found")
        gj = shp_mapping(geom_shp)
        if by_row_id:
            return {
                "id": str(row.id),
                "name": "User Group Boundary",
                "geometry": gj,
            }
        # A multi-island extent is addressed per island as
        # `user_group#<extent_id>#<part>` (the registry mints one feature per
        # island) and resolves to THAT island alone, so it can be edited or cut
        # on its own -- the same shape of answer `_resolve_feature` gives for
        # `boundary#<i>`. No part suffix = the whole extent.
        idx = _user_group_part_index(feature_id)
        part_count = (
            len(gj["coordinates"])
            if gj.get("type") == "MultiPolygon"
            else 1
        )
        if idx is not None and gj.get("type") == "MultiPolygon":
            if not (0 <= idx < part_count):
                raise HTTPException(status_code=404, detail="User group part not found")
            return {
                "id": f"user_group#{row.id}#{idx}",
                "name": f"User Group Boundary ({idx + 1}/{part_count})",
                "geometry": {"type": "Polygon", "coordinates": gj["coordinates"][idx]},
                "part_index": idx,
                "part_count": part_count,
            }
        # `UserGroupExtent` has no name/area columns -- the label is the same
        # fixed one the registry hands the client.
        return {
            "id": f"user_group#{row.id}",
            "name": "User Group Boundary",
            "geometry": gj,
            "part_count": part_count,
        }
    raise HTTPException(
        status_code=400, detail=f"Unsupported layer_type '{layer_type}'"
    )


def _divide_geometry(
    geometry,
    layer_type: str,
    method: str,
    n,
    direction: str,
    rows,
    cols,
    direction_angle,
    island_counts=None,
    target_area_sqm=None,
):
    """Route a divide to the multi-island path for a MultiPolygon geometry, the
    single-Polygon path otherwise. Used by the generic replace-in-place divide
    branch: boundary/blocks always, and compartments/sub_compartments too when
    self-dividing (splitting an EXISTING compartment/sub-compartment further
    rather than carving a fresh set — see `divide_equal_areas`'s `is_self_divide`
    check). Carving a fresh set from a parent still goes through
    `compartment_divide_service.divide_compartment`.

    ``target_area_sqm`` (user 2026-09-13) — when set, divides by a per-piece
    target area instead of a piece count (method/grid ignored); the LAST piece
    is the remainder. See geometry_edit_service by-area engines.
    """
    from shapely.geometry import MultiPolygon
    from app.services.island_apportionment import allocate_island_counts

    shp = as_shapely_or_shape(geometry)
    if target_area_sqm is None and (n is None or int(n or 0) <= 0):
        # No usable split instruction → a clean 400 before equal_area_strips
        # can crash on `n <= 0` with a TypeError (self-divide preview was 500ing
        # on this because it originally dropped target_area_sqm from the by-area
        # branch while the panel sent count:null). Always a JSON-safe ValueError
        # the routers map via resolve_service_detail.
        raise ValueError(
            "DIVIDE_COUNT_REQUIRED: a piece count or an area-per-piece target is "
            "required to divide."
        )
    if target_area_sqm is not None:
        if isinstance(shp, MultiPolygon) and len(shp.geoms) > 1:
            return geo.divide_multipolygon_equal_area_by_area(
                shp,
                target_area_sqm,
                layer_type=layer_type,
                direction=direction,
                direction_angle=direction_angle,
            )
        return geo.divide_equal_area_by_area(
            geometry,
            target_area_sqm,
            layer_type=layer_type,
            direction=direction,
            direction_angle=direction_angle,
        )
    if isinstance(shp, MultiPolygon) and len(shp.geoms) > 1:
        parts = list(shp.geoms)
        if island_counts and len(island_counts) == len(parts):
            counts = [max(1, int(c)) for c in island_counts]
        else:
            areas_ha = [max(_area_sqm_shapely(p) / SQM_PER_HA, 1e-9) for p in parts]
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
        )
    return geo.divide_equal_area(
        geometry,
        layer_type=layer_type,
        method=method,
        n=n,
        direction=direction,
        rows=rows,
        cols=cols,
        direction_angle=direction_angle,
    )


def _find_sub_area(calc: Calculation, feature_id: str) -> Optional[Dict[str, Any]]:
    for sa in (calc.result_data or {}).get("sub_areas", []):
        if str(sa.get("id")) == str(feature_id):
            return sa
    return None


#: Structural layer → the query filter that belongs to it.
#: VR-1 (D-2): the old filter used `is_compartment`, which is TRUE for both
#: compartments and sub-compartments, so the two layers resolved to the SAME
#: feature set.  That set feeds the R6 neighbour index and the overlap check,
#: so a sub-compartment was validated against its own PARENT compartment — a
#: full containment overlap — and `check_shared_edge_integrity` rejected it
#: with 409 TOPOLOGY_REJECTED every single time.  The same happened to a
#: compartment as soon as it had any sub-compartment.
#: FS-1c.1: migration 094 puts top-level blocks and top-level compartments at the
#: SAME depth (DEPTH_TOP_BLOCK == DEPTH_TOP_COMPARTMENT == 1), so `division_level`
#: alone can no longer tell "blocks" from "compartments" the way it could when
#: blocks sat at 0 - `is_compartment` (the branch, I10) does that job now, and
#: `division_level` only still separates a top-level compartment from a
#: sub-compartment.
LEVEL_FILTERS = {
    "blocks": lambda q: q.filter(
        ForestBlock.is_compartment.isnot(True),
        ForestBlock.division_level == DEPTH_TOP_BLOCK,
    ),
    "sub_blocks": lambda q: q.filter(
        ForestBlock.is_compartment.isnot(True),
        ForestBlock.division_level >= DEPTH_SUB,
    ),
    "compartments": lambda q: q.filter(
        ForestBlock.is_compartment.is_(True),
        ForestBlock.division_level == DEPTH_TOP_COMPARTMENT,
    ),
    "sub_compartments": lambda q: q.filter(
        ForestBlock.is_compartment.is_(True),
        ForestBlock.division_level >= DEPTH_SUB,
    ),
}

#: FS-4a.3: the one membership set for "this layer_type is a structural (forest_blocks)
#: layer" -- replaces ~10 call sites that each spelled out their own
#: ``{"blocks", "compartments", "sub_compartments"}`` literal (never including
#: sub_blocks, since it did not exist). Adding a layer here is now the only place
#: a new structural type needs registering for every generic CRUD/audit/lock path.
STRUCTURAL_LAYERS = frozenset(LEVEL_FILTERS)

#: FS-4a.3: per-layer fallback chain for ``resolve_parent_shell``'s "no usable
#: ancestor" case (below) -- try these layers, most-specific first, for a containing
#: sibling. Deliberately NOT one flat coarser-to-finer list (the old
#: ``STRUCTURAL_LAYER_ORDER``): blocks and compartments are parallel branches (D1),
#: never one linear depth order, so a single list would offer a sub-compartment
#: a sub-block as a fallback shell candidate and vice versa -- wrong branch, always
#: empty, but not obviously so from the list alone. Each branch's own two-level
#: chain stays exactly what it was; sub_blocks gets the same shape the
#: compartment side already had, scoped to its own branch.
STRUCTURAL_LAYER_FALLBACK = {
    "blocks": (),
    "sub_blocks": ("blocks",),
    "compartments": ("blocks",),  # legacy-mixed-forest catch-all (F5); a plain compartment forest has none to find
    "sub_compartments": ("compartments", "blocks"),
}


def _level_filter(q, layer_type: str):
    """Restrict a ForestBlock query to the rows of one structural layer."""
    f = LEVEL_FILTERS.get(layer_type)
    return f(q) if f else q


def _features_for_store(
    db: Session, calc: Calculation, layer_type: str
) -> List[Dict[str, Any]]:
    if layer_type in STRUCTURAL_LAYERS:
        q = _level_filter(
            db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id),
            layer_type,
        )
        return [
            {"id": str(r.id), "geometry": to_shape(r.geometry)}
            for r in q.all()
            if r.geometry is not None
        ]
    if layer_type == "sub_areas":
        out = []
        # strips are overlays: not neighbours (no shared-vertex propagation, no overlap/gap checks against them)
        for sa in real_sub_areas((calc.result_data or {}).get("sub_areas", [])):
            g = sa.get("geometry")
            if g:
                from shapely.geometry import shape

                try:
                    out.append({"id": str(sa.get("id")), "geometry": shape(g)})
                except Exception:
                    report_dropped(
                        logger,
                        "sub-area",
                        "it is not considered by this operation, as if it did not exist",
                        context=sa.get("id"),
                    )
                    continue
        return out
    if layer_type == "boundary":
        if getattr(calc, "boundary_geom", None) is not None:
            return [{"id": "boundary", "geometry": to_shape(calc.boundary_geom)}]
        return []
    return []


def resolve_parent_shell(
    db: Session, calc: Calculation, layer_type: str, feature_id: str
):
    """The enclosing shell geometry for one structural feature (plan §3.2).

    VR-1 (D-4).  The shell is what makes a vertex LOCKED: blocks are bounded by
    the forest boundary, compartments by their parent block, sub-compartments
    by their parent compartment.

    Two rules the previous frontend-only version got wrong:

    1. **Resolve the parent by ``parent_block_id``, never by spatial guessing.**
       The old code tested whether the child's first vertex / centroid fell
       inside a candidate — wrong for any concave parent.
    2. **Fall back UP the ladder when a level is empty.**  A forest can hold
       compartments with no blocks (a legitimate dimension mode).  Returning
       "no shell" there left NOTHING locked, so a junction of two compartments
       sitting ON the forest boundary became editable — the exact inversion of
       rule 4 (*on the enclosing shell wins over shared*).

    Returns a shapely geometry, or ``None`` only when the calculation has no
    boundary at all.
    """
    boundary = (
        to_shape(calc.boundary_geom)
        if getattr(calc, "boundary_geom", None) is not None
        else None
    )
    if layer_type == "blocks" or layer_type not in STRUCTURAL_LAYERS:
        return boundary

    row = (
        db.query(ForestBlock)
        .filter(
            ForestBlock.id == feature_id,
            ForestBlock.calculation_id == calc.id,
        )
        .first()
    )
    if row is None:
        return boundary

    # Walk up the parent chain; the first ancestor WITH geometry is the shell.
    seen = set()
    parent_id = row.parent_block_id
    while parent_id and str(parent_id) not in seen:
        seen.add(str(parent_id))
        parent = (
            db.query(ForestBlock)
            .filter(
                ForestBlock.id == parent_id,
                ForestBlock.calculation_id == calc.id,
            )
            .first()
        )
        if parent is None:
            break
        if parent.geometry is not None:
            return to_shape(parent.geometry)
        parent_id = parent.parent_block_id

    # No usable ancestor → the next coarser NON-EMPTY level, else the boundary.
    for coarser in STRUCTURAL_LAYER_FALLBACK.get(layer_type, []):
        rows = _level_filter(
            db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id),
            coarser,
        ).all()
        geoms = [to_shape(r.geometry) for r in rows if r.geometry is not None]
        if not geoms:
            continue
        # The containing sibling at that level, if any; otherwise the boundary.
        own = to_shape(row.geometry) if row.geometry is not None else None
        if own is not None:
            for g in geoms:
                try:
                    if g.contains(own) or g.intersection(own).area > own.area * 0.5:
                        return g
                except Exception:  # pragma: no cover - defensive
                    report_dropped(
                        logger,
                        "containment candidate",
                        "it cannot win the parent search, so the feature may end up "
                        "attached to the wrong parent or to none",
                    )
                    continue
        break
    return boundary


def _persist_boundary_geometry(
    db: Session,
    calc: Calculation,
    geometry: Dict[str, Any],
) -> Dict[str, Any]:
    """Write the boundary the FULL way (VR-3 Rule A path).

    `_write_geometry`'s boundary branch sets `boundary_geom` alone, which would
    leave `result_data["geometry"]` and `area_hectares` stale — every report and
    export reads those.  Mirror the authoritative write in
    `blocks.update_boundary_geometry`, and recompute the area geodesically here
    rather than trusting a number from the request.

    No single-block auto-create (as everywhere — C1-C3 / Q5): this path only
    runs when NO structural feature exists, and silently manufacturing a block
    would be a surprising side effect of dragging a vertex.
    """
    from shapely.geometry import shape as shp
    from app.services.boundary_write_service import (
        persist_boundary,
        BoundaryFullyInsideExisting,
    )

    geom_shp = shp(geometry)
    # Delegate to the single boundary-write point (PB-3).  It clips the edited
    # geometry against adjoining forests — a vertex dragged into a neighbour, or
    # an extension that lands inside one, is trimmed back the same way an import
    # is.  No unit is ever auto-created from a boundary write (FS-2.4/FS-2.8).
    try:
        # validate=False: this is the vertex/reshape toolset acting on a
        # boundary that was already checked against the four rules when the
        # forest was created. Re-imposing country-extent / area limits on every
        # drag would trap an edit mid-flow; the establish/import paths
        # (PUT /boundary, upload, draft-convert, merge) are where they run.
        # reclip_sub_areas=False: the caller (edit-geometry) re-clips sub-areas
        # itself and reports what changed -- see reclip_sub_areas_to_boundary below.
        persist_boundary(
            db,
            calc,
            geom_shp,
            validate=False,
            reclip_sub_areas=False,
        )
    except BoundaryFullyInsideExisting:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=409,
            detail="Edited boundary lies entirely within an adjoining forest.",
        )
    db.commit()
    db.refresh(calc)
    return _resolve_feature(db, calc, "boundary", "boundary")


def _stored_geometry(db: Session, calc: Calculation, layer_type: str, feature_id: str):
    """The feature's geometry AS STORED — the guard's reference point.

    Never derived from the request: the client's idea of what is locked is
    exactly what VR-3 declines to trust.
    """
    if layer_type in STRUCTURAL_LAYERS:
        row = (
            db.query(ForestBlock)
            .filter(
                ForestBlock.id == feature_id,
                ForestBlock.calculation_id == calc.id,
            )
            .first()
        )
        return (
            to_shape(row.geometry)
            if row is not None and row.geometry is not None
            else None
        )
    if layer_type == "boundary":
        return (
            to_shape(calc.boundary_geom)
            if getattr(calc, "boundary_geom", None) is not None
            else None
        )
    if layer_type == "user_group":
        from ..models.user_group import UserGroupExtent

        row = (
            db.query(UserGroupExtent)
            .filter(UserGroupExtent.calculation_id == calc.id)
            .first()
        )
        if row and row.extent_geometry:
            # to_shape (geoalchemy2), not shapely's shape(): the column holds a
            # PostGIS element, which shape() cannot read.
            return to_shape(row.extent_geometry)
    return None


def _assert_batch_respects_locks(
    db: Session,
    calc: Calculation,
    layer_type: str,
    feature_id: str,
    geometry: Dict[str, Any],
    shared_moves: List[Dict[str, Any]],
) -> None:
    """VR-3 guard for a whole edit-geometry batch.

    The edited feature AND every shared_moves partner are checked: a
    propagation payload is just as capable of moving a partner's locked vertex
    as a direct edit is, and it is the less obvious route.
    """
    if layer_type not in STRUCTURAL_LAYERS:
        return
    siblings = _features_for_store(db, calc, layer_type)

    def _check(fid: str, submitted: Dict[str, Any]) -> None:
        stored = _stored_geometry(db, calc, layer_type, fid)
        if stored is None:
            return
        try:
            guard.assert_no_locked_vertex_change(
                stored,
                submitted,
                layer_type,
                [f for f in siblings if str(f["id"]) != str(fid)],
                resolve_parent_shell(db, calc, layer_type, fid),
            )
        except guard.LockedVertexError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=with_message_np(
                    {
                        "code": exc.code,
                        "feature_id": str(fid),
                        "locked_indices": exc.indices,
                    },
                    "editing.vertex_locked",
                    preserve_code=True,
                ),
            ) from exc

    _check(feature_id, geometry)
    for m in shared_moves:
        _check(m["feature_id"], m["geometry"])


def _get_index(db: Session, calc: Calculation, layer_type: str) -> SpatialHashIndex:
    idx = SpatialHashIndex()
    for f in _features_for_index(db, calc, layer_type):
        idx.insert(f["id"], f.get("geometry"))
    return idx


def _features_with_propagated(
    db: Session,
    calc: Calculation,
    layer_type: str,
    feature_id: str,
    geometry: Dict[str, Any],
    shared_moves: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], SpatialHashIndex]:
    """Effective neighbour set + index for a D2 shared-vertex move.

    Returns ``(existing, index)`` where every shared-move feature's geometry is
    replaced with its propagated value AND the edited feature's geometry is
    replaced with the submitted one — so R6 validates the *post-move* topology
    (neighbours moved together, no spurious gap/overlap rejection).
    """
    from shapely.geometry import shape as shp

    existing = _features_for_index(db, calc, layer_type)
    # Replace the edited feature's stored geometry with the submitted one.
    updated = []
    for f in existing:
        if str(f.get("id")) == str(feature_id):
            f = dict(f)
            f["geometry"] = as_shapely_or_shape(geometry)
        updated.append(f)

    # Replace each propagated neighbour's stored geometry with its moved value.
    move_by_id = {str(m["feature_id"]): m["geometry"] for m in shared_moves}
    moved = []
    for f in updated:
        fid = str(f.get("id"))
        if fid in move_by_id:
            f = dict(f)
            f["geometry"] = as_shapely_or_shape(move_by_id[fid])
        moved.append(f)

    index = SpatialHashIndex()
    for f in moved:
        index.insert(f["id"], f.get("geometry"))
    return moved, index


def _features_for_index(
    db: Session, calc: Calculation, layer_type: str
) -> List[Dict[str, Any]]:
    return _features_for_store(db, calc, layer_type)


def _serialize(piece):
    from shapely.geometry import mapping

    return mapping(piece)


def _area_sqm_shapely(geom) -> float:
    try:
        sqm, _ = calculate_area_geodesic_from_shapely(geom)
        return float(sqm or 0.0)
    except Exception:
        # The fallback treats a degree as 111,320 m in both axes; at Nepal's
        # latitudes that overstates area by roughly 12%.
        logger.warning(
            "geodesic area failed - falling back to a planar approximation "
            "that overstates area",
            exc_info=True,
        )
        return float(getattr(geom, "area", 0.0) * (111_320.0**2))


def _sync_result_data_block(db, calc, row) -> None:
    rd = calc.result_data or {}
    blocks = rd.get("blocks", [])
    changed = False
    for b in blocks:
        if str(b.get("block_id")) == str(row.id) or str(b.get("id")) == str(row.id):
            b["geometry"] = _to_geojson(row.geometry)
            b["area_hectares"] = round(row.area_hectares or 0, 4)
            changed = True
            break
    if changed:
        calc.result_data = rd
        attributes.flag_modified(calc, "result_data")
        db.add(calc)


def _sync_sub_area_row(db, calc, feature_id, geom_shp, sqm: float) -> None:
    row = (
        db.query(ForestSubArea)
        .filter(
            ForestSubArea.calculation_id == calc.id,
        )
        .filter(ForestSubArea.id == feature_id)
        .first()
    )
    if row:
        row.geometry = from_shape(geom_shp, srid=4326)
        row.area_hectares = round(sqm / SQM_PER_HA, 4)


# ---------------------------------------------------------------------------
# persistence (single-authority writes)
# ---------------------------------------------------------------------------


def _persist_geometry(
    db: Session,
    calc: Calculation,
    layer_type: str,
    feature_id: str,
    geometry: Dict[str, Any],
) -> Dict[str, Any]:
    _write_geometry(db, calc, layer_type, feature_id, geometry)
    geo.bump_geometry_version(calc)
    db.commit()
    db.refresh(calc)
    return _resolve_feature(db, calc, layer_type, feature_id)


def _read_geometry_for_audit(
    db: Session,
    calc: Calculation,
    layer_type: str,
    feature_id: str,
) -> Optional[Dict[str, Any]]:
    """The geometry as it stands, for the audit's `previous` side.

    Never raises: this runs before a write the user asked for, and a failure to
    read the old shape must not refuse the new one.
    """
    try:
        from shapely.geometry import mapping as shp_mapping

        if layer_type == "boundary":
            current = getattr(calc, "boundary_geom", None)
            return shp_mapping(to_shape(current)) if current is not None else None
        if layer_type in STRUCTURAL_LAYERS:
            row = db.query(ForestBlock).filter(ForestBlock.id == feature_id).first()
            geom = getattr(row, "geometry", None) if row else None
            return shp_mapping(to_shape(geom)) if geom is not None else None
        if layer_type == "sub_areas":
            from ..models.forest_sub_area import ForestSubArea

            row = db.query(ForestSubArea).filter(ForestSubArea.id == feature_id).first()
            geom = getattr(row, "geometry", None) if row else None
            return shp_mapping(to_shape(geom)) if geom is not None else None
        if layer_type == "user_group":
            from ..models.user_group import UserGroupExtent

            row = db.query(UserGroupExtent).filter(UserGroupExtent.calculation_id == calc.id).first()
            geom = getattr(row, "extent_geometry", None) if row else None
            return shp_mapping(to_shape(geom)) if geom is not None else None
    except Exception:  # noqa: BLE001 -- reported below; never fails the write
        logger.warning(
            "audit: could not read the previous geometry for %s/%s; the audit "
            "row will record the new shape only",
            layer_type,
            feature_id,
            exc_info=True,
        )
    return None


def _audit_geometry_write(
    db: Session,
    calc: Calculation,
    layer_type: str,
    feature_id: str,
    previous: Optional[Dict[str, Any]],
    new: Optional[Dict[str, Any]],
) -> None:
    """Record one geometry mutation. Never raises.

    **An audit trail that can break the operation it records is worse than no
    audit trail** -- that is the trade S2-68 is about, and it is why this
    swallows and logs rather than propagating. The log line carries the
    correlation id (H3.9), so a missing audit row is still traceable to its
    request.

    The user, address and client type come from the request context (H8.7)
    rather than from arguments: this is four frames below the endpoint, and
    threading them through every caller is exactly the pattern that left the
    table empty.
    """
    try:
        from ..core.request_context import get_identity
        from ..services.audit_service import log_geometry_audit

        identity = get_identity()
        if not identity.user_id:
            # `geometry_audits.user_id` is NOT NULL. A write with no
            # authenticated user should not exist on this path, and inventing
            # one would put a false name on a permanent record.
            logger.warning(
                "audit: no user in the request context for %s/%s; not recording",
                layer_type,
                feature_id,
            )
            return

        log_geometry_audit(
            db=db,
            calculation_id=str(calc.id),
            layer_type=layer_type,
            operation="UPDATE",
            feature_id=str(feature_id) if feature_id else None,
            previous_geometry=previous,
            new_geometry=new,
            user_id=identity.user_id,
            metadata={
                "ip_address": identity.ip_address,
                "client_type": identity.client_type,
                "user_agent": identity.user_agent,
                "correlation_id": get_correlation_id(),
            },
        )
    except Exception:  # noqa: BLE001 -- see the docstring
        logger.error(
            "audit: failed to record the geometry write for %s/%s",
            layer_type,
            feature_id,
            exc_info=True,
        )


def _write_geometry(
    db: Session,
    calc: Calculation,
    layer_type: str,
    feature_id: str,
    geometry: Dict[str, Any],
) -> None:
    """Write one feature's geometry WITHOUT committing (D2 batch helper).

    The caller decides when to commit so a shared-vertex move persists every
    affected feature atomically (one transaction, one geometry_version bump).

    **Every geometry write in this module passes through here** -- all three
    persist helpers call it, and the twelve endpoints call those. That is why
    the audit (H8.7 / S2-68) is taken here rather than at the endpoints: an
    audit that must be remembered per endpoint is the reason `geometry_audits`
    held 0 rows after five months of production use.
    """
    from shapely.geometry import shape as shp

    geom_shp = shp(geometry)

    # H8.7 — capture what is there BEFORE overwriting it. After the write the
    # previous geometry is gone, and an audit trail that cannot say what
    # changed only records that something did.
    _previous = _read_geometry_for_audit(db, calc, layer_type, feature_id)

    if layer_type == "boundary":
        setattr(calc, "boundary_geom", from_shape(geom_shp, srid=4326))
    elif layer_type in STRUCTURAL_LAYERS:
        row = (
            db.query(ForestBlock)
            .filter(
                ForestBlock.id == feature_id,
                ForestBlock.calculation_id == calc.id,
            )
            .first()
        )
        if not row:
            raise HTTPException(status_code=404, detail="Forest division not found")
        sqm = _geometry_sqm(geom_shp)
        row.geometry = from_shape(geom_shp, srid=4326)
        row.area_hectares = round(sqm / SQM_PER_HA, 4)
        row.area_sqm = round(sqm, 2)
        _sync_result_data_block(db, calc, row)
        # FS-4a.10 (G2): a reshaped unit's own sub-units re-clip to its NEW
        # shape -- removed ground trims (or drops) a child, newly uncovered
        # ground becomes a remainder sub-unit. A no-op when `row` has no
        # children. Runs before the audit call below so a reshape's ripple
        # effect on its children lands in the same uncommitted transaction
        # as the parent's own geometry write.
        from ..services.forest_units.operations.reshape import reclip_children

        reclip_children(db, calc, row.id, geom_shp)
    elif layer_type == "sub_areas":
        rd = calc.result_data or {}
        subs = rd.get("sub_areas", [])
        found = False
        for sa in subs:
            if str(sa.get("id")) == str(feature_id):
                # Every sub-area geometry edit (vertex edit, move, edit-geometry, batch)
                # ends here, so this is where the two absolute rules are enforced: inside
                # the forest, and never overlapping another sub-area. An edited sub-area
                # gives way to the others; if nothing valid is left the edit is refused
                # rather than quietly deleting the sub-area.
                try:
                    placement = place_sub_area(
                        db, calc, geom_shp, exclude_id=str(feature_id), category=sa.get("category")
                    )
                except SubAreaPlacementError as exc:
                    raise HTTPException(
                        status_code=400, detail=PLACEMENT_MESSAGES[exc.reason]
                    )
                from shapely.geometry import mapping as _shp_mapping

                geom_shp = placement.geometry
                geometry = _shp_mapping(geom_shp)
                sqm = _area_sqm_shapely(geom_shp)
                sa["geometry"] = geometry
                sa["area_sqm"] = round(sqm, 2)
                sa["area_hectares"] = round(sqm / SQM_PER_HA, 4)
                sa["area_ha"] = round(sqm / SQM_PER_HA, 4)
                found = True
                _sync_sub_area_row(db, calc, feature_id, geom_shp, sqm)
                break
        if not found:
            raise HTTPException(status_code=404, detail="Sub-area not found")
        calc.result_data = rd
        attributes.flag_modified(calc, "result_data")
    elif layer_type == "user_group":
        from ..models.user_group import UserGroupExtent

        geom_shp = shp(geometry)
        # P7d: a feature id may be the plain ROW id, in which case that row IS the
        # feature and its geometry is simply replaced - no part index involved.
        # The legacy `user_group#<id>#<part>` form still splices one island inside
        # a single row, so the frontend keeps working until P7e moves to row ids.
        if _is_user_group_row_id(feature_id):
            row = (
                db.query(UserGroupExtent)
                .filter(UserGroupExtent.id == _row_id_of(feature_id))
                .filter(UserGroupExtent.calculation_id == calc.id)
                .first()
            )
            if not row:
                raise HTTPException(status_code=404, detail="User group extent not found")
            row.extent_geometry = from_shape(_as_mp(geom_shp), srid=4326)
        else:
            row = (
                db.query(UserGroupExtent)
                .filter(UserGroupExtent.calculation_id == calc.id)
                .first()
            )
            if not row:
                raise HTTPException(status_code=404, detail="User group extent not found")
            stored = to_shape(row.extent_geometry) if row.extent_geometry else None
            merged = _splice_user_group_part(
                stored, _user_group_part_index(feature_id), geom_shp
            )
            row.extent_geometry = from_shape(merged, srid=4326)
    else:
        raise HTTPException(
            status_code=400, detail=f"Unsupported layer_type '{layer_type}'"
        )

    _audit_geometry_write(db, calc, layer_type, feature_id, _previous, geometry)


def _persist_geometry_batch(
    db: Session,
    calc: Calculation,
    layer_type: str,
    items: List[Tuple[str, Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Persist several features atomically (one commit, one version bump).

    V-2 (D2): a shared-vertex move rewrites the edited feature AND every
    same-level feature that shares the moved vertex in a single transaction.
    Returns the resolved features in input order.
    """
    for feature_id, geometry in items:
        _write_geometry(db, calc, layer_type, str(feature_id), geometry)
    geo.bump_geometry_version(calc)
    db.commit()
    db.refresh(calc)
    return [_resolve_feature(db, calc, layer_type, str(fid)) for fid, _ in items]


# A degenerate-sliver floor for cut/divide output — NOT a "minimum
# meaningful compartment size" policy (that floor is much larger elsewhere),
# just a filter for numerical noise. A client-side geometry operation (e.g.
# the Auto-Block designer's merge-glue trick, or a cut line grazing a
# vertex) can leave the occasional needle-thin fragment thousandths of a m²
# in area but tens-to-hundreds of metres in perimeter — invisible on the
# map, but it inflates the perimeter shown in the attribute table by orders
# of magnitude and, worse, used to get bundled into the SAME MultiPolygon
# geometry column as a real piece instead of being dropped.
# DEGENERATE_SLIVER_M2 / _flatten_and_clean_pieces are imported from
# ..utils.single_part_geometry (top of file) — this used to be a local
# duplicate of that module's explode_and_filter_slivers.


def _replace_feature_with_pieces(
    db: Session,
    calc: Calculation,
    layer_type: str,
    feature_id: str,
    pieces: List[Any],
    warnings: List[str],
) -> List[str]:
    """Replace an existing polygon feature with its cut/divide pieces.

    UE-3.2 — returns the created piece ids (builtin row ids / sub-area ids) so
    the frontend can delete them on UNDO (restore the original = delete pieces
    + restore the source snapshot via restore-feature).
    """
    from shapely.geometry import mapping

    created_ids: List[str] = []

    if layer_type in STRUCTURAL_LAYERS:
        row = (
            db.query(ForestBlock)
            .filter(
                ForestBlock.id == feature_id,
                ForestBlock.calculation_id == calc.id,
            )
            .first()
        )
        if not row:
            raise HTTPException(status_code=404, detail="Forest division not found")
        parent_name = row.name
        parent_block_name = row.block_name or row.name
        comp_code = row.compartment_code
        is_comp = row.is_compartment
        parent_id = row.parent_block_id
        div_level = row.division_level
        # A cut/split/divide changes geometry only — every non-geometric
        # attribute describing this feature's forest/management character
        # (working circle, orientation, style, natural name, dominant
        # slope/aspect/canopy) still describes the same ground, so every
        # piece keeps it unchanged (D-2026-09-15). Captured before delete —
        # child_inherit_kwargs snapshots a plain dict, safe to reuse after.
        # Not a re-derive-per-piece like Auto-Block's own merge does (there,
        # unrelated pieces of possibly different classes are being combined;
        # here, one classified feature is only being cut into smaller parts
        # of itself).
        inherited = child_inherit_kwargs(row)
        inherited["color"] = inherited["color"] or COMPARTMENT_COLOR_FALLBACK
        clean_pieces = _flatten_and_clean_pieces(pieces)
        # D13/FS-4a.7: the new pieces are created (and any existing sub-units
        # of `row` re-homed onto them) BEFORE `row` itself is deleted --
        # `parent_block_id` is ON DELETE CASCADE, so deleting `row` first would
        # silently destroy its children along with it, with no re-homing at
        # all. Creating pieces first, then redistributing, then deleting the
        # old row (whose now-superseded old children the cascade removes)
        # mirrors the "delete old, create new" pattern the parent's own
        # replacement already follows, one level down.
        new_pieces_with_geoms: List[Any] = []
        for i, piece in enumerate(clean_pieces, start=1):
            sqm = _geometry_sqm(piece)
            piece_row = ForestBlock(
                calculation_id=calc.id,
                name=f"{parent_name}-{i}",
                block_name=f"{parent_block_name}-{i}",
                geometry=from_shape(piece, srid=4326),
                area_hectares=round(sqm / SQM_PER_HA, 4),
                area_sqm=round(sqm, 2),
                index=geo.next_block_index(db, calc.id),
                is_compartment=is_comp,
                parent_block_id=parent_id,
                compartment_code=(
                    f"{comp_code}-{i}" if comp_code else f"{parent_name}-{i}"
                ),
                division_level=div_level,
                **inherited,
            )
            db.add(piece_row)
            db.flush()
            # `ForestBlock.id`'s default (uuid.uuid4) is a Python-side default
            # that SQLAlchemy only applies on flush -- reading it beforehand
            # (the bug this replaces) returned the literal string "None" for
            # every piece, silently breaking UNDO (the docstring's whole
            # reason for returning these ids: "so the frontend can delete
            # them on UNDO").
            created_ids.append(str(piece_row.id))
            new_pieces_with_geoms.append((piece_row, piece))

        from ..services.forest_units.operations.reparent import redistribute_children

        created_ids.extend(
            redistribute_children(db, calc, row.id, new_pieces_with_geoms)
        )
        db.delete(row)
        db.flush()
    elif layer_type == "sub_areas":
        rd = calc.result_data or {}
        subs = rd.get("sub_areas", [])
        target = None
        for sa in subs:
            if str(sa.get("id")) == str(feature_id):
                target = sa
                break
        if target is None:
            raise HTTPException(status_code=404, detail="Sub-area not found")
        base = {
            k: v
            for k, v in target.items()
            if k not in {"id", "geometry", "area_sqm", "area_hectares", "area_ha"}
        }
        pieces_rd = []
        # Same invariant as the blocks/compartments branch above: one
        # sub-area row = one selectable map feature, so any MultiPolygon
        # piece must be exploded (and degenerate slivers dropped) into
        # separate rows before it's ever written into result_data — this
        # JSON path bypasses the ForestSubArea ORM model entirely, so the
        # model-level `@validates('geometry')` guard can't catch it here.
        clean_pieces = _flatten_and_clean_pieces(pieces)
        for i, piece in enumerate(clean_pieces, start=1):
            sqm = _geometry_sqm(piece)
            new_sa = dict(base)
            new_sa["id"] = str(uuidlib.uuid4())
            new_sa["name"] = f"{target.get('name', 'Sub-Area')}-{i}"
            new_sa["geometry"] = mapping(piece)
            new_sa["area_sqm"] = round(sqm, 2)
            new_sa["area_hectares"] = round(sqm / SQM_PER_HA, 4)
            new_sa["area_ha"] = round(sqm / SQM_PER_HA, 4)
            pieces_rd.append(new_sa)
            created_ids.append(new_sa["id"])
        subs = [sa for sa in subs if str(sa.get("id")) != str(feature_id)]
        subs.extend(pieces_rd)
        rd["sub_areas"] = subs
        calc.result_data = rd
        attributes.flag_modified(calc, "result_data")
        old = (
            db.query(ForestSubArea)
            .filter(
                ForestSubArea.id == feature_id,
                ForestSubArea.calculation_id == calc.id,
            )
            .first()
        )
        if old:
            db.delete(old)
    elif layer_type == "user_group":
        from ..models.user_group import UserGroupExtent
        from shapely.geometry import MultiPolygon

        clean_pieces = [
            p for p in _flatten_and_clean_pieces(pieces)
            if p is not None and not getattr(p, "is_empty", False) and p.area > 0
        ]
        if not clean_pieces:
            raise HTTPException(status_code=400, detail="Cut produced no valid pieces")

        if _is_user_group_row_id(feature_id):
            # P7d: the row IS the feature, so a cut deletes that row and inserts
            # one row per piece - the owner's "a cut makes its own row". This is
            # the same shape as a block cut, and it is why the part-index
            # machinery exists only for the legacy path below.
            source = (
                db.query(UserGroupExtent)
                .filter(UserGroupExtent.id == _row_id_of(feature_id))
                .filter(UserGroupExtent.calculation_id == calc.id)
                .first()
            )
            if not source:
                raise HTTPException(status_code=404, detail="User group extent not found")
            db.delete(source)
            for part in clean_pieces:
                db.add(
                    UserGroupExtent(
                        calculation_id=calc.id,
                        user_id=source.user_id,
                        extent_geometry=from_shape(
                            MultiPolygon([part]), srid=4326
                        ),
                        source_type=source.source_type,
                        buffer_distance_m=source.buffer_distance_m,
                    )
                )
            # created_ids is filled in by the caller's flush/refresh below.
            created_ids = []
        else:
            # Legacy: one row holding a MultiPolygon, so the pieces become
            # separate parts of THAT row and the registry re-splits them.
            row = (
                db.query(UserGroupExtent)
                .filter(UserGroupExtent.calculation_id == calc.id)
                .first()
            )
            if not row:
                raise HTTPException(status_code=404, detail="User group extent not found")
            cut_shape = MultiPolygon(clean_pieces)
            # Cutting ONE island of a multi-island extent leaves the others exactly
            # as they were: the pieces replace just that island, in place.
            part_index = _user_group_part_index(feature_id)
            stored = to_shape(row.extent_geometry) if row.extent_geometry else None
            row.extent_geometry = from_shape(
                _splice_user_group_part(stored, part_index, cut_shape), srid=4326
            )
            # created_ids stays empty: no rows were created, so an undo of this cut
            # is a pure re-shape (see the user_group branch in undoCutServer).
    else:
        raise HTTPException(
            status_code=400, detail=f"Unsupported layer_type '{layer_type}'"
        )

    from ..services.forest_units.write import structure_write

    with structure_write(db, calc, change=f"edit {layer_type}"):
        pass
    db.commit()
    db.refresh(calc)
    return created_ids


def _persist_boundary_pieces_as_blocks(
    db: Session, calc: Calculation, pieces: List[Any]
) -> List[str]:
    """Boundary divide → each piece stored as a NEW block (user-confirmed R2).

    UE-3.2 — returns the created block ids so boundary-split UNDO can delete
    exactly the pieces stored as blocks (the boundary itself is unchanged).
    """
    created_ids: List[str] = []
    # Same invariant as _replace_feature_with_pieces: one block row = one
    # selectable map feature. Explode here (rather than relying solely on
    # the ForestBlock model's @validates('geometry') guard) so a piece that
    # happens to be a MultiPolygon becomes N clean rows, not a mid-loop
    # MultiPartFeatureError after some pieces are already persisted.
    clean_pieces = _flatten_and_clean_pieces(pieces)
    for i, piece in enumerate(clean_pieces, start=1):
        sqm = _geometry_sqm(piece)
        piece_row = ForestBlock(
            calculation_id=calc.id,
            name=f"Boundary Block {i}",
            geometry=from_shape(piece, srid=4326),
            area_hectares=round(sqm / SQM_PER_HA, 4),
            area_sqm=round(sqm, 2),
            index=geo.next_block_index(db, calc.id),
        )
        db.add(piece_row)
        db.flush()
        # `ForestBlock.id`'s default (uuid.uuid4) is a Python-side default
        # SQLAlchemy only applies on flush -- reading it beforehand (the bug
        # this replaces) returned the literal string "None" for every piece,
        # silently breaking UNDO (this function's whole reason for returning
        # these ids: "so boundary-split UNDO can delete exactly the pieces").
        created_ids.append(str(piece_row.id))
    from ..services.forest_units.write import structure_write

    with structure_write(db, calc, change="split the boundary into blocks"):
        pass
    db.commit()
    db.refresh(calc)
    return created_ids


# ---------------------------------------------------------------------------
# imported-layer feature helpers (UE-1.2) — features live inside
# WorkspaceLayer.layer_data["features"] (GeoJSON), keyed by properties.featureId
# ---------------------------------------------------------------------------


def _resolve_imported_feature(db: Session, calc_id, layer_id: int, feature_id: str):
    """Return (layer, feature_index, feature_dict) for an imported-layer feature.

    Mirrors workspace.py's per-feature lookup but resolves by the stable
    ``properties.featureId`` (the id the frontend registers features under).
    """
    layer = (
        db.query(WorkspaceLayer)
        .filter(
            WorkspaceLayer.id == layer_id,
            WorkspaceLayer.calculation_id == calc_id,
            WorkspaceLayer.deleted_at.is_(None),
        )
        .first()
    )
    if not layer:
        raise HTTPException(status_code=404, detail="Layer not found")
    if not layer.layer_data or not isinstance(layer.layer_data, dict):
        raise HTTPException(status_code=400, detail="Layer has no feature data")
    features = layer.layer_data.get("features", [])
    for i, f in enumerate(features):
        if str(f.get("properties", {}).get("featureId")) == str(feature_id):
            return layer, i, f
    raise HTTPException(
        status_code=404, detail=f"Feature {feature_id} not found in layer"
    )


def _rewrite_imported_features(
    db: Session,
    calc: Calculation,
    layer: WorkspaceLayer,
    new_features: List[Dict[str, Any]],
) -> None:
    """JSONB-safe replace of a layer's feature list + geometry-version bump."""
    new_data = copy.deepcopy(layer.layer_data or {})
    new_data["features"] = new_features
    layer.layer_data = new_data
    layer.feature_count = len(new_features)
    layer.updated_at = func.now()
    invalidate_layers_cache(calc.id)
    geo.bump_geometry_version(calc)
    db.commit()
    db.refresh(calc)


def _persist_imported_geometry(
    db: Session, calc: Calculation, layer_id: int, feature_id: str, geometry
) -> Dict[str, Any]:
    """UE-1.2 vertex/move commit — replace one imported feature's geometry,
    recompute geo_* authoritatively from the stored geometry."""
    from shapely.geometry import mapping, shape as shp

    layer, idx, _ = _resolve_imported_feature(db, calc.id, layer_id, feature_id)
    try:
        new_geom = shp(geometry)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid geometry")
    new_data = copy.deepcopy(layer.layer_data)
    target = new_data["features"][idx]
    target["geometry"] = mapping(new_geom)
    props = {
        k: v
        for k, v in (target.get("properties") or {}).items()
        if not str(k).startswith("geo_")
    }
    props.update(compute_geometry_properties(new_geom))
    target["properties"] = props
    new_data["features"][idx] = target
    layer.layer_data = new_data
    layer.updated_at = func.now()
    invalidate_layers_cache(calc.id)
    geo.bump_geometry_version(calc)
    db.commit()
    db.refresh(calc)
    return target


def _persist_imported_pieces(
    db: Session, calc: Calculation, layer_id: int, feature_id: str, pieces: List[Any]
) -> List[str]:
    """UE-1.2 split commit — replace the source imported feature with N pieces
    (fresh featureIds), recomputing geo_* per piece.

    UE-3.2 — returns the created legacy piece featureIds so imported-split
    UNDO can delete them (the source feature is restored by featureId).
    """
    from shapely.geometry import mapping

    layer, _, source = _resolve_imported_feature(db, calc.id, layer_id, feature_id)
    src_props = source.get("properties") or {}
    base_name = str(src_props.get("name") or src_props.get("label") or "Feature")
    new_data = copy.deepcopy(layer.layer_data)
    feats = new_data["features"]
    feats = [
        f
        for f in feats
        if str(f.get("properties", {}).get("featureId")) != str(feature_id)
    ]
    created_ids: List[str] = []
    for i, piece in enumerate(pieces, start=1):
        sqm = _geometry_sqm(piece)
        props = {k: v for k, v in src_props.items() if not str(k).startswith("geo_")}
        props["featureId"] = f"{feature_id}-piece-{i}"
        props["name"] = f"{base_name}-{i}"
        props.update(compute_geometry_properties(piece))
        props["area_hectares"] = round(sqm / SQM_PER_HA, 4)
        props["area_sqm"] = round(sqm, 2)
        feats.append(
            {"type": "Feature", "geometry": mapping(piece), "properties": props}
        )
        created_ids.append(props["featureId"])
    _rewrite_imported_features(db, calc, layer, feats)
    return created_ids


# ---------------------------------------------------------------------------
# small numeric helpers
# ---------------------------------------------------------------------------


def _geometry_sqm(shapely_geom) -> float:
    try:
        sqm, _ = calculate_area_geodesic_from_shapely(shapely_geom)
        return float(sqm or 0.0)
    except Exception:
        logger.warning(
            "geodesic area failed - falling back to a planar approximation "
            "that overstates area",
            exc_info=True,
        )
        return float(shapely_geom.area) * (111_320.0**2)


# ---------------------------------------------------------------------------
# named endpoints
# ---------------------------------------------------------------------------


@router.post("/calculations/{calculation_id}/geometry/edit-geometry")
def edit_geometry(
    calculation_id,
    payload: Dict[str, Any],
    force: bool = Query(
        False,
        description="server-internal/admin override — bypasses lifecycle, never structure lock",
    ),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """POST {layer_type, feature_id, geometry} → validated + persisted (R1/R6).

    V-2 (D2): an optional ``shared_moves: [{feature_id, geometry}]`` list lets a
    single vertex gesture rewrite the edited feature AND every same-level
    feature sharing the moved vertex in one atomic transaction.  R6 is validated
    against the *propagated* neighbour set (neighbours that moved too), so a
    shared-vertex drag no longer self-rejects.  Returns ``updated_feature_ids``
    so the frontend refreshes every affected feature.
    """
    calc = _calc_with_guard(db, calculation_id, current_user, force=force)
    layer_type = payload.get("layer_type")
    feature_id = str(payload.get("feature_id") or "")
    geometry = payload.get("geometry")
    if not layer_type or not feature_id or not geometry:
        raise HTTPException(
            status_code=400, detail="layer_type, feature_id and geometry are required"
        )
    if layer_type == "boundary":
        # VR-3 / Rule A.  This used to be a flat 400 ("edited via the boundary
        # toolbar"), which meant the rule was checked NOWHERE: the frontend
        # routed boundary edits straight to PUT /boundary, and that endpoint
        # had no structure check either.  Accept the edit here when no
        # structural feature exists, and refuse it with a real code when one
        # does.
        try:
            guard.assert_boundary_editable(db, calc)
        except guard.LockedVertexError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=with_message_np(
                    {"code": exc.code},
                    "editing.boundary_locked_by_structure",
                    preserve_code=True,
                ),
            ) from exc
        saved = _persist_boundary_geometry(db, calc, geometry)
        # VR-6 (D6): a sub-area sticking out past the new edge would keep
        # subtracting land the forest no longer contains from every report.
        reclip = reclip_sub_areas_to_boundary(db, calc, to_shape(calc.boundary_geom))
        boundary_warnings: List[str] = []
        if reclip["clipped"] or reclip["dropped"]:
            db.commit()
            db.refresh(calc)
            boundary_warnings.append(W_SUB_AREAS_CLIPPED)
        return {
            "success": True,
            "feature": saved,
            "warnings": boundary_warnings,
            "sub_areas_clipped": reclip["clipped"],
            "sub_areas_dropped": reclip["dropped"],
        }

    # The id is validated HERE, before anything touches the database. It used
    # to be checked inside `_resolve_feature`, which runs at the *end* of this
    # handler — by then `_assert_batch_respects_locks` had already put the raw
    # string into a `forest_blocks.id` comparison and psycopg2 had raised. The
    # database-error handler catches that safely now, but it can only answer
    # with a generic "that value wasn't usable", and the caller deserves to be
    # told which value and what to do about it.
    if layer_type in STRUCTURAL_LAYERS:
        _structural_uuid(feature_id)
        for _m in payload.get("shared_moves") or []:
            if isinstance(_m, dict) and _m.get("feature_id"):
                _structural_uuid(str(_m["feature_id"]))

    # V-2: optional atomic shared-vertex propagation (D2).  Only structural
    # layers (blocks/compartments/sub_compartments) participate; sub_areas and
    # imported layers keep the single-feature path.  The gate runs for every
    # layer type (imported returns early below) so shared_moves is rejected
    # uniformly.
    shared_moves = payload.get("shared_moves") or []
    if shared_moves:
        # user_group is included deliberately: since P7d each polygon is its own
        # row, so a shared-vertex move is a batch of row writes and
        # `_persist_geometry_batch` already handles it generically. Excluding it
        # meant dragging a vertex shared by two user-group polygons moved only one
        # of them, silently tearing the pair apart - the block behaviour the owner
        # expected, minus the part that keeps neighbours in step.
        if layer_type not in STRUCTURAL_LAYERS and layer_type != "user_group":
            raise HTTPException(
                status_code=400,
                detail=(
                    "shared_moves is only supported for "
                    "blocks/compartments/sub_compartments/user_group"
                ),
            )
        if not isinstance(shared_moves, list):
            raise HTTPException(status_code=400, detail="shared_moves must be a list")
        moves = []
        for m in shared_moves:
            if (
                not isinstance(m, dict)
                or not m.get("feature_id")
                or not m.get("geometry")
            ):
                raise HTTPException(
                    status_code=400,
                    detail="shared_moves items need feature_id + geometry",
                )
            moves.append(
                {"feature_id": str(m["feature_id"]), "geometry": m["geometry"]}
            )
        shared_moves = moves

    if layer_type == "imported":
        # UE-1.2 — imported features live in WorkspaceLayer.layer_data; write
        # straight through (topology/clip safety arrives in UE-3).
        layer_id = int(payload.get("layer_id") or 0)
        if not layer_id:
            raise HTTPException(
                status_code=400, detail="layer_id is required for imported layers"
            )
        saved = _persist_imported_geometry(db, calc, layer_id, feature_id, geometry)
        return {"success": True, "feature": saved, "warnings": []}

    # VR-3 — the rules are enforced HERE, not only by the browser hiding
    # markers.  Every geometry in the batch is checked against what is stored,
    # so undo/redo, a retried request, a stale tab or any other client cannot
    # move a vertex the rules lock.
    _assert_batch_respects_locks(
        db, calc, layer_type, feature_id, geometry, shared_moves
    )

    existing, index = _features_with_propagated(
        db,
        calc,
        layer_type,
        feature_id,
        geometry,
        shared_moves,
    )

    result = geo.validate_geometry_edit(
        geometry,
        layer_type,
        calc,
        existing,
        feature_id=feature_id,
        index=index,
    )
    if W_TOPOLOGY_REJECTED in result.warnings:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=with_message_np(
                {
                    "code": "TOPOLOGY_REJECTED",
                    "warnings": result.warnings,
                },
                "editing.topology_rejected",
                preserve_code=True,
            ),
        )

    # Validate each propagated neighbour against the SAME propagated set so the
    # whole batch is consistent (no gap/overlap anywhere after the atomic write).
    batch = [(feature_id, result.geometry)]
    for m in shared_moves:
        m_res = geo.validate_geometry_edit(
            m["geometry"],
            layer_type,
            calc,
            existing,
            feature_id=m["feature_id"],
            index=index,
        )
        if W_TOPOLOGY_REJECTED in m_res.warnings:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=with_message_np(
                    {
                        "code": "TOPOLOGY_REJECTED",
                        "warnings": m_res.warnings,
                    },
                    "editing.topology_rejected",
                    preserve_code=True,
                ),
            )
        batch.append((m["feature_id"], m_res.geometry))

    warnings = list(result.warnings)

    if len(batch) > 1:
        saved_list = _persist_geometry_batch(db, calc, layer_type, batch)
        # VR-6 (D5): the coverage invariant now runs on the VERTEX path too.
        # It fired only after cut and merge, so a vertex drag could pull a
        # block's edge inward and silently leave the forest boundary untiled —
        # no warning, no auto-heal, no rejection.
        _enforce_invariant_after_edit(db, calc, layer_type, warnings)
        saved = _resolve_feature(db, calc, layer_type, feature_id)
        updated_ids = [str(f["id"]) for f in saved_list]
        return {
            "success": True,
            "feature": saved,
            "warnings": warnings,
            "updated_feature_ids": updated_ids,
            "shared_moves_applied": len(shared_moves),
        }

    saved = _persist_geometry(db, calc, layer_type, feature_id, result.geometry)
    _enforce_invariant_after_edit(db, calc, layer_type, warnings)
    saved = _resolve_feature(db, calc, layer_type, feature_id)
    return {"success": True, "feature": saved, "warnings": warnings}


@router.post("/calculations/{calculation_id}/geometry/cut-polygon")
def cut_polygon(
    calculation_id,
    body: Dict[str, Any],
    force: bool = Query(
        False,
        description="server-internal/admin override — bypasses lifecycle, never structure lock",
    ),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """{layer_type, feature_id, cut_line} → persists 2+ pieces."""
    calc = _calc_with_guard(db, calculation_id, current_user, force=force)
    layer_type = body.get("layer_type")
    feature_id = str(body.get("feature_id") or "")
    cut_line_geom = body.get("cut_line")
    if not layer_type or not feature_id or not cut_line_geom:
        raise HTTPException(
            status_code=400, detail="layer_type, feature_id and cut_line are required"
        )

    if layer_type == "imported":
        layer_id = int(body.get("layer_id") or 0)
        if not layer_id:
            raise HTTPException(
                status_code=400, detail="layer_id is required for imported layers"
            )
        target = {
            "id": feature_id,
            "geometry": _resolve_imported_feature(db, calc.id, layer_id, feature_id)[
                2
            ].get("geometry"),
        }
    else:
        target = _resolve_feature(db, calc, layer_type, feature_id)
    pieces, warnings = geo.cut_polygon(target["geometry"], cut_line_geom)
    if len(pieces) < 2:
        raise HTTPException(
            status_code=400,
            detail="Cut produced fewer than 2 valid pieces (all too small?)",
        )
    piece_ids: List[str] = []
    piece_feature_ids: List[str] = []
    block_ids: List[str] = []
    if layer_type == "imported":
        piece_feature_ids = _persist_imported_pieces(
            db, calc, layer_id, feature_id, pieces
        )
    elif layer_type == "boundary":
        block_ids = _persist_boundary_pieces_as_blocks(db, calc, pieces)
    else:
        piece_ids = _replace_feature_with_pieces(
            db, calc, layer_type, feature_id, pieces, warnings
        )
    _enforce_invariant_after_edit(db, calc, layer_type, warnings)
    return {
        "success": True,
        "pieces": [_serialize(p) for p in pieces],
        "piece_ids": piece_ids,
        "piece_feature_ids": piece_feature_ids if layer_type == "imported" else None,
        "boundary_piece_block_ids": block_ids if layer_type == "boundary" else None,
        "warnings": warnings,
        "boundary_pieces_stored_as": (
            "blocks" if layer_type == "boundary" else layer_type
        ),
    }


@router.post("/calculations/{calculation_id}/geometry/merge-features")
def merge_features(
    calculation_id,
    body: Dict[str, Any],
    force: bool = Query(
        False,
        description="server-internal/admin override — bypasses lifecycle, never structure lock",
    ),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """UE-2.2 — {layer_type, feature_ids, layer_id?} → union N features into ONE.

    Union + make_valid, then (builtin clip layers only) clip to the forest
    boundary; deletes the source features and stores the merged piece.  Runs
    under the standard write guard (423 structure lock / 409 lifecycle).
    """
    calc = _calc_with_guard(db, calculation_id, current_user, force=force)
    layer_type = body.get("layer_type")
    feature_ids = body.get("feature_ids")
    if not layer_type or not isinstance(feature_ids, list) or len(feature_ids) < 2:
        raise HTTPException(
            status_code=400, detail="layer_type and at least 2 feature_ids are required"
        )
    if layer_type == "boundary":
        raise HTTPException(
            status_code=400, detail="boundary merge is not supported via merge-features"
        )

    if layer_type == "imported":
        layer_id = int(body.get("layer_id") or 0)
        if not layer_id:
            raise HTTPException(
                status_code=400, detail="layer_id is required for imported layers"
            )
        return _merge_imported(db, calc, layer_id, feature_ids)
    if layer_type == "sub_areas":
        return _merge_sub_areas(db, calc, feature_ids)
    if layer_type in STRUCTURAL_LAYERS:
        return _merge_blocks(db, calc, layer_type, feature_ids)
    if layer_type == "user_group":
        if all(_is_user_group_row_id(f) for f in feature_ids):
            return _merge_user_group_rows(db, calc, feature_ids)
        return _merge_user_group_parts(db, calc, feature_ids)
    raise HTTPException(
        status_code=400, detail=f"Unsupported layer_type '{layer_type}'"
    )


def _finalise_user_group_row_merge(db: Session, calc: Calculation, kept_rows: List[Any],
                                  merged_count: int, previous: Optional[dict]):
    """Audit a row-based merge, bump the geometry clock, and report the new ids.

    Separate from `_finalise_user_group_merge` because that one reports PART
    references (`user_group#<id>#<n>`), which is exactly the addressing P7d retires.
    Here every id is a plain row id, and the merged row is identified so the client
    can select it without guessing.

    `merged_count` is FEATURES COLLAPSED (rows before minus rows after), which is
    what the legacy merge reported and what the UI shows - not the number of rows
    deleted, which for two rows into one would read as a confusing "2 merged".
    """
    from ..services.audit_service import log_geometry_audit

    merged_row = kept_rows[-1] if kept_rows else None
    merged_id = str(merged_row.id) if merged_row is not None else None
    try:
        log_geometry_audit(
            db=db,
            calculation_id=str(calc.id),
            layer_type="user_group",
            operation="MERGE",
            feature_id=merged_id,
            previous_geometry=previous,
            new_geometry=_to_geojson(merged_row.extent_geometry) if merged_row else None,
            user_id=calc.user_id,
            metadata={"features_collapsed": merged_count, "rows_after": len(kept_rows)},
        )
    except Exception:  # pragma: no cover - audit must not fail the merge
        logger.exception("[editing] user_group row merge audit failed")
    geo.bump_geometry_version(calc)
    db.commit()
    return {
        "success": True,
        "merged": merged_count,
        "merged_id": merged_id,
        "feature_ids": [str(r.id) for r in kept_rows],
    }


def _merge_user_group_rows(db: Session, calc: Calculation, feature_ids: List[str]):
    """Merge whole user-group polygons: N rows become 1 (P7d).

    The inverse of the row-based cut. Because each polygon is its own row and its
    own feature, this is the same shape as merging blocks - delete the sources,
    insert the union - and the attribute table loses exactly the rows the user
    selected. There is no part index to renumber, which is the whole point.

    Only ADJACENT polygons can actually merge: two disjoint ones union to a
    MultiPolygon, which is the same shape that was already stored, so the request
    is accepted, reports `merged: 0` with a reason, and writes NOTHING - not even
    the geometry clock.
    """
    from shapely.geometry import MultiPolygon as _MP
    from shapely.ops import unary_union as _union
    from ..models.user_group import UserGroupExtent

    if len(feature_ids) < 2:
        raise HTTPException(status_code=400, detail="at least 2 feature_ids are required")

    ids = []
    for fid in feature_ids:
        if not _is_user_group_row_id(fid):
            raise HTTPException(
                status_code=400, detail=f"'{fid}' is not a user-group row id"
            )
        ids.append(_row_id_of(fid))

    rows = (
        db.query(UserGroupExtent)
        .filter(UserGroupExtent.id.in_(ids))
        .filter(UserGroupExtent.calculation_id == calc.id)
        .all()
    )
    if len(rows) != len(ids):
        raise HTTPException(status_code=404, detail="User group extent not found")

    previous = _to_geojson(rows[0].extent_geometry)
    shapes = [to_shape(r.extent_geometry) for r in rows if r.extent_geometry is not None]
    shapes = [s for s in shapes if s is not None and not s.is_empty]
    if not shapes:
        raise HTTPException(status_code=400, detail="Nothing to merge")

    # `_union_geometries` carries the same GUARDED point-touch glue the block merge
    # uses: it only glues when `_touch_graph_connected` proves the selected polygons
    # touch within ~1 cm, so a cut that leaves sub-micron shared-edge noise can be
    # re-joined while two genuinely distant polygons still refuse to merge. A plain
    # `unary_union` here demanded EXACT touching and so could not undo a real cut.
    fused = _as_mp(_union_geometries(list(shapes)))
    if len(fused.geoms) == len(shapes):
        # Disjoint selection: the union is the same shape, so nothing changed and
        # nothing is written. Re-serialising an unchanged row would still churn
        # the geometry clock and make the client refetch for no reason.
        return {
            "success": True,
            "merged": 0,
            "feature_ids": [str(r.id) for r in rows],
            "warning": "selected polygons do not touch, so nothing was merged",
        }

    template = rows[0]
    for r in rows:
        db.delete(r)
    db.add(
        UserGroupExtent(
            calculation_id=calc.id,
            user_id=template.user_id,
            extent_geometry=from_shape(_MP(list(fused.geoms)), srid=4326),
            source_type=template.source_type,
            buffer_distance_m=template.buffer_distance_m,
        )
    )
    db.commit()
    kept = (
        db.query(UserGroupExtent)
        .filter(UserGroupExtent.calculation_id == calc.id)
        .order_by(UserGroupExtent.created_at.asc(), UserGroupExtent.id.asc())
        .all()
    )
    return _finalise_user_group_row_merge(db, calc, kept, len(rows) - 1, previous)


def _merge_user_group_parts(db: Session, calc: Calculation, feature_ids: List[str]):
    """Merge selected user-group ISLANDS back into fewer parts of the one extent.

    The extent is a single stored row holding a MultiPolygon, and an "island" is
    just a part of it - so unlike a block merge there are no rows to delete and
    create. Merging is therefore the inverse of the cut: take the selected parts,
    union them, and put the result back where the first selected part was, so the
    islands after it keep their order and their indices as far as the shift allows.

    Only ADJACENT islands can actually merge. Two disjoint parts union to a
    MultiPolygon again, which is the same shape that was already stored, so the
    request is accepted but changes nothing - reported as ``merged: 0`` so the
    caller can say so rather than pretending it worked.
    """
    from shapely.geometry import MultiPolygon as _MP
    from shapely.ops import unary_union as _union
    from ..models.user_group import UserGroupExtent

    if len(feature_ids) < 2:
        raise HTTPException(status_code=400, detail="at least 2 feature_ids are required")

    extent_ids = set()
    for fid in feature_ids:
        s = str(fid or "").strip()
        if not s.startswith("user_group#"):
            raise HTTPException(
                status_code=400, detail=f"'{fid}' is not a user-group island id"
            )
        extent_ids.add(s.split("#", 1)[1].split("#")[0])
    if len(extent_ids) != 1:
        raise HTTPException(
            status_code=400,
            detail="all islands must belong to the one user-group extent",
        )

    row = (
        db.query(UserGroupExtent)
        .filter(UserGroupExtent.calculation_id == calc.id)
        .first()
    )
    if row is None or row.extent_geometry is None:
        raise HTTPException(status_code=404, detail="User group extent not found")

    previous = _to_geojson(row.extent_geometry)
    parts = list(_as_mp(to_shape(row.extent_geometry)).geoms)

    indices: List[int] = []
    for fid in feature_ids:
        idx = _user_group_part_index(str(fid))
        if idx is None:
            raise HTTPException(
                status_code=400,
                detail=f"'{fid}' does not name an island (expected user_group#<id>#<part>)",
            )
        if not (0 <= idx < len(parts)):
            raise HTTPException(status_code=404, detail="User group part not found")
        if idx in indices:
            raise HTTPException(
                status_code=400, detail=f"island {idx} was selected twice"
            )
        indices.append(idx)

    indices.sort()
    chosen = [parts[i] for i in indices]
    fused = _as_mp(_union(chosen))
    before = len(parts)
    kept = [p for i, p in enumerate(parts) if i not in set(indices)]
    # The fused shape goes back at the first selected position, so the islands
    # before it keep their indices exactly. `_as_mp` always yields a MultiPolygon,
    # so splice its PARTS in - nesting a MultiPolygon inside one is not valid.
    insert_at = indices[0]
    kept[insert_at:insert_at] = list(fused.geoms)
    after_parts = kept

    # Only ADJACENT islands actually merge. A disjoint selection unions back to the
    # same shape, so report that and write nothing at all - re-serialising an
    # unchanged extent would still churn the row and the geometry clock.
    merged_count = len(fused.geoms)
    if merged_count == len(chosen):
        return {
            "success": True,
            "merged": 0,
            "feature_ids": [f"user_group#{list(extent_ids)[0]}#{i}" for i in range(len(after_parts))],
            "warning": "selected islands do not touch, so nothing was merged",
        }

    row.extent_geometry = from_shape(_MP(after_parts), srid=4326)
    return _finalise_user_group_merge(
        db, calc, row, before, after_parts, previous=previous
    )


def _as_mp(geom):
    """A stored extent as a MultiPolygon; a bare Polygon is wrapped, never stored bare."""
    from shapely.geometry import MultiPolygon as _MP

    if geom is None:
        return None
    if geom.geom_type == "Polygon":
        return _MP([geom])
    if geom.geom_type == "MultiPolygon":
        return _MP(list(geom.geoms))
    raise HTTPException(
        status_code=400, detail=f"User group extent cannot hold a {geom.geom_type}"
    )


def _finalise_user_group_merge(db: Session, calc: Calculation, row, before: int,
                               after_parts: List[Any], previous: Optional[dict],
                               identity: Any = None):
      """Bump the geometry clock and audit, then report the new island ids.

      Indices after the insertion point have moved, so the ids are re-minted rather
      than patched: a caller holding a pre-merge id must refetch, exactly as it must
      after a cut.
      """
      from ..services.audit_service import log_geometry_audit

      extent_id = str(row.id)
      db.commit()
      try:
          log_geometry_audit(
              db=db,
              calculation_id=str(calc.id),
              layer_type="user_group",
              operation="MERGE",
              feature_id=extent_id,
              previous_geometry=previous,
              new_geometry=_to_geojson(row.extent_geometry),
              user_id=getattr(identity, "user_id", None) or calc.user_id,
              metadata={"islands_before": before, "islands_after": len(after_parts)},
          )
      except Exception:  # pragma: no cover - audit must not fail the merge
          logger.exception("[editing] user_group merge audit failed")
      geo.bump_geometry_version(calc)
      db.commit()
      return {
          "success": True,
          "merged": before - len(after_parts),
          "feature_ids": [f"user_group#{extent_id}#{i}" for i in range(len(after_parts))],
      }


# Tolerances for the "point-touch glue" (user report, 2026-09-12: two
# compartments visually "touching" at exactly one shared corner vertex were
# rejected as "not adjacent" — topologically correct for a plain union [a
# single point can't become a shared edge on its own] but not what a real
# adjoining pair deserves). Deliberately much smaller than Auto-Block's own
# 30m glue tolerance (`autoBlockMerge.ts::unionFamily`), which bridges real
# raster-smoothing gaps between pieces ALREADY KNOWN to be the same family —
# here there is no such guarantee, so only a near-zero-distance touch (a
# corner/point, not a real gap) is glued; anything farther apart still gets
# rejected exactly as before, preserving the "don't silently merge unrelated
# distant features" safety rule.
_POINT_TOUCH_EPSILON_DEG = (
    1e-7  # ~1.1 cm at the equator — floating-point slack, not a real gap
)
_POINT_TOUCH_GLUE_M = 1.0


def _touch_graph_connected(polys: List[Any], epsilon_deg: float) -> bool:
    """True iff every polygon in `polys` is reachable from every other via a
    chain of near-zero-distance touches (each hop ≤ `epsilon_deg` apart).

    N is always small here (a user's merge selection), so a plain O(N²) BFS
    is more than fast enough — no need for a spatial index.
    """
    n = len(polys)
    if n <= 1:
        return True
    seen = [False] * n
    stack = [0]
    seen[0] = True
    count = 1
    while stack:
        i = stack.pop()
        for j in range(n):
            if not seen[j] and polys[i].distance(polys[j]) <= epsilon_deg:
                seen[j] = True
                count += 1
                stack.append(j)
    return count == n


def _union_geometries(polygons: List[Any], warnings: Optional[List[str]] = None):
    """Union + make_valid; collapse a single-part MultiPolygon; 400 on empty.

    Always returns a plain `Polygon` (one real part) or `MultiPolygon`
    (2+ real disjoint parts, for the caller's "reject non-adjoining merge"
    check) — never a `GeometryCollection`. `make_valid` on a near-degenerate
    shared boundary (e.g. two independently-smoothed adjoining pieces
    touching along a spike/pinch) can return `GeometryCollection(Polygon,
    LineString)`: a real polygon plus a zero-area repair remnant. Without
    normalizing that away here, the caller's `geom_type == "MultiPolygon"`
    check never fires (a GeometryCollection isn't a MultiPolygon) and the
    stray remnant used to reach `from_shape()` — surfacing downstream as a
    generic 500, not the intended "not adjoining" 409 (see 2026-09
    single-part-geometry incident).

    If the plain union comes out disconnected but every input genuinely
    touches another (a fully-connected "touch graph" at near-zero distance —
    not necessarily a real shared edge), a small buffer-out/union/buffer-in
    round-trip (`geo.W_POINT_TOUCH_GLUED`, appended to `warnings` when
    supplied) fuses them into one clean polygon instead of rejecting the
    merge outright.
    """
    from shapely.geometry import MultiPolygon
    from shapely.ops import unary_union
    from shapely.validation import make_valid

    from ..services.geom_generalize import meters_to_deg
    from ..utils.single_part_geometry import explode_and_filter_slivers

    cleaned: List[Any] = []
    for p in polygons:
        if p is None:
            raise HTTPException(
                status_code=400, detail="A selected feature has no geometry"
            )
        if not p.is_valid:
            p = make_valid(p)
        cleaned.append(p)
    merged = unary_union(cleaned)
    if getattr(merged, "is_empty", False) or float(merged.area) <= 0:
        raise HTTPException(status_code=400, detail="Merged feature is empty")
    if not merged.is_valid:
        merged = make_valid(merged)

    parts = explode_and_filter_slivers([merged])
    if not parts:
        raise HTTPException(status_code=400, detail="Merged feature is empty")
    if len(parts) == 1:
        return parts[0]

    if len(cleaned) > 1 and _touch_graph_connected(cleaned, _POINT_TOUCH_EPSILON_DEG):
        glue = meters_to_deg(_POINT_TOUCH_GLUE_M)
        glued = unary_union([p.buffer(glue, join_style=1) for p in cleaned]).buffer(
            -glue, join_style=1
        )
        if not glued.is_valid:
            glued = make_valid(glued)
        glued_parts = explode_and_filter_slivers([glued])
        if len(glued_parts) == 1:
            if warnings is not None:
                from ..services.geometry_edit_service import W_POINT_TOUCH_GLUED

                warnings.append(W_POINT_TOUCH_GLUED)
            return glued_parts[0]

    return MultiPolygon(parts)


def _merge_imported(
    db: Session, calc: Calculation, layer_id: int, feature_ids: List[str]
) -> Dict[str, Any]:
    """UE-2.2 imported merge — union N features into one new featureId."""
    from shapely.geometry import mapping, shape as shp

    layer, _, _ = _resolve_imported_feature(db, calc.id, layer_id, feature_ids[0])
    new_data = copy.deepcopy(layer.layer_data)
    feats = new_data["features"]
    wanted = {str(fid) for fid in feature_ids}
    sources = [
        f for f in feats if str(f.get("properties", {}).get("featureId")) in wanted
    ]
    if len(sources) != len(wanted):
        raise HTTPException(
            status_code=404, detail="One or more selected features not found in layer"
        )
    polygons = [shp(s["geometry"]) for s in sources]
    warnings: List[str] = []
    merged = _union_geometries(polygons, warnings)

    # Attribute basis = the LARGEST source feature, same rule as
    # blocks/compartments/sub_areas merge (user report, 2026-09-12). `sources`
    # is filtered from the layer's own feature order, not `feature_ids`'
    # (caller-selection) order, so the tiebreak here is just "whichever this
    # list happens to list first" rather than selection order like the other
    # three merges — a pre-existing property of this function, unchanged.
    base_idx = max(range(len(sources)), key=lambda i: _geometry_sqm(polygons[i]))
    src_props = sources[base_idx].get("properties") or {}
    base_feature_id = str(src_props.get("featureId") or feature_ids[0])
    base_name = str(src_props.get("name") or src_props.get("label") or "Feature")
    props = {k: v for k, v in src_props.items() if not str(k).startswith("geo_")}
    props["featureId"] = f"{base_feature_id}-merged"
    props["name"] = f"{base_name}_merged"
    props["merged_from"] = sorted(wanted)
    props.update(compute_geometry_properties(merged))
    sqm = _geometry_sqm(merged)
    props["area_hectares"] = round(sqm / SQM_PER_HA, 4)
    props["area_sqm"] = round(sqm, 2)
    merged_feat = {"type": "Feature", "geometry": mapping(merged), "properties": props}
    keep = [
        f for f in feats if str(f.get("properties", {}).get("featureId")) not in wanted
    ]
    keep.append(merged_feat)
    _rewrite_imported_features(db, calc, layer, keep)
    return {"success": True, "feature": merged_feat, "warnings": warnings}


def _merge_blocks(
    db: Session, calc: Calculation, layer_type: str, feature_ids: List[str]
) -> Dict[str, Any]:
    """UE-2.2 blocks/compartments/sub_compartments merge → ONE new ForestBlock."""
    # H1.17: order by the caller's selection, not by whatever the planner
    # returns — this query had no ORDER BY, so PostgreSQL was free to return
    # either first, which made a tie in the area-based pick below (two
    # merged features of identical size) nondeterministic too. Selection
    # order is what the user expressed, so it's still the deterministic
    # tiebreak; `base` itself is chosen by area (see below), not by this
    # order.
    ids = [str(fid) for fid in feature_ids]
    rows = (
        db.query(ForestBlock)
        .filter(
            ForestBlock.id.in_(ids),
            ForestBlock.calculation_id == calc.id,
        )
        .all()
    )
    _pos = {fid: i for i, fid in enumerate(ids)}
    rows.sort(key=lambda r: _pos.get(str(r.id), len(ids)))
    if len(rows) < 2:
        raise HTTPException(status_code=404, detail="Forest divisions not found")
    # FS-4a.8 (D1): siblings only -- same parent (both None for a root-level
    # merge) and same branch. A block and a compartment, or a compartment and
    # its own sub-compartment, were never a meaningful "merge these into one
    # unit" request -- no guard caught it before this. "Same parent" already
    # implies "same depth" (a row's depth is always parent.depth + 1, or the
    # top depth when parentless), so no separate depth check is needed.
    parent_ids = {str(r.parent_block_id) if r.parent_block_id else None for r in rows}
    branches = {r.is_compartment for r in rows}
    if len(parent_ids) > 1 or len(branches) > 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=with_message_np(
                {"code": "MERGE_NOT_SIBLINGS"},
                "editing.merge_not_siblings",
                preserve_code=True,
            ),
        )
    polygons = [to_shape(r.geometry) for r in rows if r.geometry is not None]
    if len(polygons) != len(rows):
        raise HTTPException(
            status_code=400, detail="All selected features must have geometry"
        )
    warnings: List[str] = []
    merged = _union_geometries(polygons, warnings)

    if merged.geom_type == "MultiPolygon":
        # Disjoint merge (non-adjacent polygons) would persist one row with
        # several separate polygons — the same block serial split across places
        # (user report, Phase C review). Reject: merge adjacent neighbours only.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=with_message_np(
                {
                    "code": "TOPOLOGY_REJECTED",
                    "warnings": [geo.W_TOPOLOGY_REJECTED],
                },
                "editing.topology_merge_not_adjacent",
                preserve_code=True,
            ),
        )
    if layer_type in geo.CLIP_TO_BOUNDARY_LAYERS:
        clipped, was_clipped, _ = geo.clip_to_forest_boundary(merged, calc)
        if clipped is None:
            # structural merge that no longer touches the forest boundary
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=with_message_np(
                    {
                        "code": "TOPOLOGY_REJECTED",
                        "warnings": [geo.W_TOPOLOGY_REJECTED],
                    },
                    "editing.topology_merge_outside",
                    preserve_code=True,
                ),
            )
        if was_clipped:
            warnings.append(geo.W_CLIPPED_TO_BOUNDARY)
            merged = clipped

    # Attribute basis = the LARGEST of the merged features, not whichever was
    # selected/clicked first (user report, 2026-09-12): the geometry is a
    # plain union regardless (computed above, unaffected by this choice) —
    # only which source's non-geometry attributes (name, natural name,
    # classification, colour, ...) the merged row inherits. `rows`/`polygons`
    # are index-aligned (checked above), and `rows` is already sorted by
    # selection order, so a tie (identical area) deterministically keeps the
    # first-selected feature's attributes, same as the old behaviour.
    base = rows[max(range(len(rows)), key=lambda i: _geometry_sqm(polygons[i]))]
    sqm = _geometry_sqm(merged)
    inherited = child_inherit_kwargs(base)
    inherited["color"] = inherited["color"] or COMPARTMENT_COLOR_FALLBACK
    merged_row = ForestBlock(
        calculation_id=calc.id,
        name=f"{base.name}_merged",
        block_name=f"{base.block_name or base.name}_merged",
        geometry=from_shape(merged, srid=4326),
        area_hectares=round(sqm / SQM_PER_HA, 4),
        area_sqm=round(sqm, 2),
        index=geo.next_block_index(db, calc.id),
        is_compartment=base.is_compartment,
        parent_block_id=base.parent_block_id,
        compartment_code=(
            f"{base.compartment_code}_merged" if base.compartment_code else None
        ),
        division_level=base.division_level,
        **inherited,
    )
    db.add(merged_row)
    db.flush()
    # D13/FS-4a.8: every merged row's existing sub-units re-parent onto the
    # ONE merged row (never split -- the merged shape is the union of the
    # originals, so every child that fit inside its own old parent still
    # fits inside the merged result). `merged_row` must exist (flushed above)
    # before this, and every old row's children must be redistributed BEFORE
    # that old row is deleted -- see reparent.py's own note on why the DB's
    # `ON DELETE CASCADE` cannot be trusted to do this on its own.
    from ..services.forest_units.operations.reparent import redistribute_children

    for r in rows:
        redistribute_children(db, calc, r.id, [(merged_row, merged)])
    for r in rows:
        db.delete(r)
    db.flush()
    _sync_result_data_block(db, calc, merged_row)
    ids = [str(fid) for fid in feature_ids]
    _sync_result_data_pieces_removed(db, calc, ids)
    from ..services.forest_units.write import structure_write

    with structure_write(db, calc, change=f"merge {layer_type}"):
        _enforce_invariant_after_edit(db, calc, layer_type, warnings)
    db.commit()
    db.refresh(calc)
    return {
        "success": True,
        "feature": _resolve_feature(db, calc, layer_type, str(merged_row.id)),
        "warnings": warnings,
    }


def _sync_result_data_pieces_removed(
    db: Session, calc: Calculation, feature_ids: List[str]
) -> None:
    """Remove merged block entries from calc.result_data['blocks']."""
    rd = calc.result_data or {}
    blocks = rd.get("blocks", [])
    removed = {str(fid) for fid in feature_ids}
    kept = [
        b
        for b in blocks
        if str(b.get("block_id")) not in removed and str(b.get("id")) not in removed
    ]
    if len(kept) != len(blocks):
        rd["blocks"] = kept
        calc.result_data = rd
        attributes.flag_modified(calc, "result_data")
        db.add(calc)


def _enforce_invariant_after_edit(
    db: Session,
    calc: Calculation,
    layer_type: str,
    warnings: List[str],
    level: Optional[str] = None,
) -> None:
    """Boundary≡Blocks invariant (plan BLOCK_BOUNDARY_INVARIANT, E.2–E.6).

    After any blocks/compartments/boundary edit, silently auto-fill uncovered
    boundary area as a Remainder Block/Compartment. Raises 409 TOPOLOGY_REJECTED
    when over-coverage is detected (the caller's transaction is rolled back,
    i.e. the edit is rejected).
    """
    from ..services.block_area_invariant_service import enforce_block_coverage

    if level is None:
        if layer_type == "boundary":
            level = "blocks"
        elif layer_type in ("blocks", "compartments"):
            level = layer_type
        else:
            return  # sub_compartments/sub_areas/imported: no boundary-level invariant
    try:
        result = enforce_block_coverage(db, calc, level=level)
    except ValueError as e:
        code = str(e)
        if code == "TOPOLOGY_REJECTED":
            warnings.append(geo.W_TOPOLOGY_REJECTED)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=with_message_np(
                    {
                        "code": "TOPOLOGY_REJECTED",
                        "warnings": [geo.W_TOPOLOGY_REJECTED],
                    },
                    "editing.topology_overlap_area",
                    preserve_code=True,
                ),
            )
        raise
    if result.get("remainder_added"):
        if result.get("gap_ha", 0) > 0:
            warnings.append(
                "REMAINDER_COMPARTMENT_ADDED"
                if level == "compartments"
                else "REMAINDER_BLOCK_ADDED"
            )
        db.commit()


def _merge_sub_areas(
    db: Session, calc: Calculation, feature_ids: List[str]
) -> Dict[str, Any]:
    """UE-2.2 sub_areas merge — union N result_data sub-areas into ONE."""
    from shapely.geometry import mapping, shape as shp

    rd = calc.result_data or {}
    subs = rd.get("sub_areas", [])
    wanted = {str(fid) for fid in feature_ids}
    sources = [sa for sa in subs if str(sa.get("id")) in wanted]
    if len(sources) != len(wanted):
        raise HTTPException(
            status_code=404, detail="One or more selected sub-areas not found"
        )
    if len({sa.get("category") for sa in sources if is_strip(sa)}) > 1 or (
        any(is_strip(sa) for sa in sources) and not all(is_strip(sa) for sa in sources)
    ):
        # a strip is an overlay, a zone is not: merging one into the other would turn a fire line into land use (or back)
        raise HTTPException(status_code=400, detail="A strip can only be merged with a strip of the same kind")
    polygons = [shp(sa["geometry"]) for sa in sources]
    warnings: List[str] = []
    merged = _union_geometries(polygons, warnings)

    # Attribute basis = the LARGEST source sub-area, same rule as
    # blocks/compartments merge (user report, 2026-09-12) — `sources` order
    # is the caller's selection order, so a tie keeps the first-selected.
    base_source = sources[
        max(range(len(sources)), key=lambda i: _geometry_sqm(polygons[i]))
    ]
    base = {
        k: v
        for k, v in base_source.items()
        if k not in {"id", "geometry", "area_sqm", "area_hectares", "area_ha"}
    }
    sqm = _geometry_sqm(merged)
    new_sa = dict(base)
    new_sa["id"] = str(uuidlib.uuid4())
    new_sa["name"] = f"{base_source.get('name', 'Sub-Area')}_merged"
    new_sa["geometry"] = mapping(merged)
    new_sa["area_sqm"] = round(sqm, 2)
    new_sa["area_hectares"] = round(sqm / SQM_PER_HA, 4)
    new_sa["area_ha"] = round(sqm / SQM_PER_HA, 4)
    keep = [sa for sa in subs if str(sa.get("id")) not in wanted]
    keep.append(new_sa)
    rd["sub_areas"] = keep
    calc.result_data = rd
    attributes.flag_modified(calc, "result_data")
    try:
        [uuidlib.UUID(str(fid)) for fid in feature_ids]
        old = (
            db.query(ForestSubArea)
            .filter(
                ForestSubArea.id.in_([str(fid) for fid in feature_ids]),
                ForestSubArea.calculation_id == calc.id,
            )
            .all()
        )
        for o in old:
            db.delete(o)
    except (ValueError, TypeError):
        # sub-area ids in result_data may predate the ForestSubArea table row
        # (non-UUID ids) — the JSONB rewrite is authoritative either way.
        pass
    geo.bump_geometry_version(calc)
    db.commit()
    db.refresh(calc)
    return {
        "success": True,
        "feature": _resolve_feature(db, calc, "sub_areas", str(new_sa["id"])),
        "warnings": warnings,
    }


@router.post("/calculations/{calculation_id}/geometry/cut-line")
def cut_line(
    calculation_id,
    body: Dict[str, Any],
    force: bool = Query(
        False,
        description="server-internal/admin override — bypasses lifecycle, never structure lock",
    ),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """{layer_type, feature_id, split_point} → split a LineString at a point."""
    calc = _calc_with_guard(db, calculation_id, current_user, force=force)
    layer_type = body.get("layer_type")
    feature_id = str(body.get("feature_id") or "")
    split = body.get("split_point")
    if not layer_type or not feature_id or not split:
        raise HTTPException(
            status_code=400,
            detail="layer_type, feature_id and split_point are required",
        )
    target = _resolve_feature(db, calc, layer_type, feature_id)
    parts, warnings = geo.cut_line(target["geometry"], split)
    if len(parts) < 2:
        raise HTTPException(status_code=400, detail="Cut produced fewer than 2 pieces")
    return {
        "success": True,
        "pieces": [_serialize(p) for p in parts],
        "warnings": warnings,
    }


@router.post("/calculations/{calculation_id}/geometry/divide-equal-areas")
async def divide_equal_areas(
    calculation_id,
    body: Dict[str, Any],
    force: bool = Query(
        False,
        description="server-internal/admin override — bypasses lifecycle, never structure lock",
    ),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """{layer_type, feature_id, method, direction, count, rows, cols} → replace.

    Layer gate R2: boundary/blocks/sub_blocks/compartments/sub_compartments.
    Boundary division stores pieces as *blocks* (user-confirmed).

    FS-4a.5 routing — three shapes, decided per layer_type + the resolved
    feature row:
      * ROOT divide (no ``feature_id``): carve the forest boundary itself into
        the first top-level set — ``blocks`` → ``operations.divide``,
        ``compartments`` → the compartment shim (both refuse once ANY unit row
        exists).
      * parent-kept carve: ``sub_blocks`` on a top-level block (→ divide_blocks),
        ``compartments`` on a block, ``sub_compartments`` on a compartment
        (→ divide_compartment) — a FRESH set of children is minted under the
        parent and the parent row is KEPT.
      * self-divide: the selected feature is ALREADY of ``layer_type`` (an
        existing sub-block on the sub_blocks layer) — split THAT one in place
        via the generic replace path below, which preserves branch/depth.
        ``boundary`` and ``blocks`` use the same generic path.
    """
    calc = _calc_with_guard(db, calculation_id, current_user, force=force)
    layer_type = body.get("layer_type")
    if layer_type not in geo.DIVIDE_ALLOWED_LAYERS:
        raise HTTPException(
            status_code=400,
            detail=f"Divide is not allowed for layer '{layer_type}' (R2)",
        )
    feature_id = str(body.get("feature_id") or "")

    # --- root divides (FS-4a.5) -------------------------------------------------
    if not feature_id:
        if layer_type in ("sub_blocks", "sub_compartments"):
            raise HTTPException(
                status_code=400,
                detail="Sub-units cannot be carved from the forest root — divide a block (or compartment) first, then sub-divide it.",
            )
        if layer_type == "blocks":
            try:
                result = await divide_blocks(
                    db,
                    calc,
                    parent_id=None,
                    method=body.get("method", "strips"),
                    n=body.get("count") or body.get("n"),
                    rows=body.get("rows"),
                    cols=body.get("cols"),
                    direction=body.get("direction", "vertical"),
                    direction_angle=body.get("direction_angle"),
                    naming_pattern=body.get("naming_pattern", ""),
                )
            except ValueError as exc:
                raise HTTPException(
                    status_code=400, detail=resolve_service_detail(str(exc))
                )
            return {
                "success": True,
                "parent_id": None,
                "children": result["children"],
                "split_history_id": None,
                "trees_reassigned": 0,
                "warnings": result["warnings"],
                "n_children": result["n_children"],
                "boundary_pieces_stored_as": "blocks",
            }
        if layer_type == "compartments":
            try:
                result = await divide_compartment(
                    db,
                    calc=calc,
                    parent_id=None,
                    layer_type="compartments",
                    method=body.get("method", "strips"),
                    n=body.get("count") or body.get("n"),
                    rows=body.get("rows"),
                    cols=body.get("cols"),
                    direction=body.get("direction", "vertical"),
                    direction_angle=body.get("direction_angle"),
                    naming_pattern=body.get("naming_pattern", ""),
                    reassign_trees=bool(body.get("reassign_trees", False)),
                    notes=body.get("notes"),
                    created_by=getattr(current_user, "id", "unknown"),
                    island_counts=body.get("island_counts"),
                    target_area_sqm=body.get("target_area_sqm"),
                )
            except ValueError as exc:
                raise HTTPException(
                    status_code=400, detail=resolve_service_detail(str(exc))
                )
            return {
                "success": True,
                "parent_id": result["parent_id"],
                "children": result["children"],
                "split_history_id": result["split_history_id"],
                "trees_reassigned": result["trees_reassigned"],
                "warnings": result["warnings"],
                "n_children": result["n_children"],
                "boundary_pieces_stored_as": "compartments",
            }

    # --- feature-based routing --------------------------------------------------
    row = None
    if layer_type in STRUCTURAL_LAYERS:
        row = (
            db.query(ForestBlock)
            .filter(
                ForestBlock.id == _structural_uuid(feature_id),
                ForestBlock.calculation_id == calc.id,
            )
            .first()
        )

    if layer_type == "sub_blocks":
        if row is None:
            raise HTTPException(status_code=404, detail="Forest division not found")
        own = layer_of(row)
        if own in ("compartments", "sub_compartments"):
            raise HTTPException(
                status_code=400,
                detail=resolve_service_detail(
                    "NOT_A_BLOCK: Can only sub-divide a block."
                ),
            )
        if own == "blocks":
            # parent-kept: carve this top-level block into sub-blocks.
            try:
                result = await divide_blocks(
                    db,
                    calc,
                    parent_id=feature_id,
                    method=body.get("method", "strips"),
                    n=body.get("count") or body.get("n"),
                    rows=body.get("rows"),
                    cols=body.get("cols"),
                    direction=body.get("direction", "vertical"),
                    direction_angle=body.get("direction_angle"),
                    naming_pattern=body.get("naming_pattern", ""),
                )
            except ValueError as exc:
                raise HTTPException(
                    status_code=400, detail=resolve_service_detail(str(exc))
                )
            return {
                "success": True,
                "parent_id": result["parent_id"],
                "children": result["children"],
                "split_history_id": None,
                "trees_reassigned": 0,
                "warnings": result["warnings"],
                "n_children": result["n_children"],
                "boundary_pieces_stored_as": "sub_blocks",
            }
        # own == "sub_blocks": self-divide the selected sub-block in place.
        target = _resolve_feature(db, calc, layer_type, feature_id)
    elif layer_type in ("compartments", "sub_compartments"):
        if row is None or layer_of(row) != layer_type:
            # parent-kept: carve a FRESH set of children under the parent one
            # level up (the root case above already returned).
            try:
                result = await divide_compartment(
                    db,
                    calc=calc,
                    parent_id=feature_id,
                    layer_type=layer_type,
                    method=body.get("method", "strips"),
                    n=body.get("count") or body.get("n"),
                    rows=body.get("rows"),
                    cols=body.get("cols"),
                    direction=body.get("direction", "vertical"),
                    direction_angle=body.get("direction_angle"),
                    naming_pattern=body.get("naming_pattern", ""),
                    reassign_trees=bool(body.get("reassign_trees", False)),
                    notes=body.get("notes"),
                    created_by=getattr(current_user, "id", "unknown"),
                    island_counts=body.get("island_counts"),
                    target_area_sqm=body.get("target_area_sqm"),
                )
            except ValueError as exc:
                raise HTTPException(
                    status_code=400, detail=resolve_service_detail(str(exc))
                )
            return {
                "success": True,
                "parent_id": result["parent_id"],
                "children": result["children"],
                "split_history_id": result["split_history_id"],
                "trees_reassigned": result["trees_reassigned"],
                "warnings": result["warnings"],
                "n_children": result["n_children"],
                "boundary_pieces_stored_as": layer_type,
            }
        # self-divide: the selected compartment/sub-compartment itself.
        target = _resolve_feature(db, calc, layer_type, feature_id)
    else:
        # boundary / blocks — generic replace-in-place.
        target = _resolve_feature(db, calc, layer_type, feature_id)

    try:
        pieces, warnings = _divide_geometry(
            target["geometry"],
            layer_type=layer_type,
            method=body.get("method", "strips"),
            n=body.get("count") or body.get("n"),
            direction=body.get("direction", "vertical"),
            rows=body.get("rows"),
            cols=body.get("cols"),
            direction_angle=body.get("direction_angle"),
            island_counts=body.get("island_counts"),
            target_area_sqm=body.get("target_area_sqm"),
        )
    except ValueError as exc:
        # e.g. a multi-island boundary reaching the single-Polygon path — 400,
        # not a 500 (MULTI_ISLAND_DIVIDE_PLAN.md P1).
        raise HTTPException(status_code=400, detail=resolve_service_detail(str(exc)))
    if W_DIVIDE_TOLERANCE_EXCEEDED in warnings:
        raise HTTPException(
            status_code=400,
            detail="Equal-area division violates ±5% tolerance — no change made",
        )
    if len(pieces) < 2:
        raise HTTPException(
            status_code=400, detail="Division produced fewer than 2 valid pieces"
        )

    if layer_type == "boundary":
        _persist_boundary_pieces_as_blocks(db, calc, pieces)
    else:
        _replace_feature_with_pieces(db, calc, layer_type, feature_id, pieces, warnings)

    return {
        "success": True,
        "pieces": [_serialize(p) for p in pieces],
        "warnings": warnings,
        "boundary_pieces_stored_as": (
            "blocks" if layer_type == "boundary" else layer_type
        ),
        # A self-divided compartment/sub-compartment reaches this generic
        # branch too (see `is_self_divide` above) and its success toast reads
        # these two fields, same as the parent-child divide_compartment
        # response — "trees_reassigned" is always 0 here because self-divide
        # (unlike divide_compartment) never reassigns tree points.
        "n_children": len(pieces),
        "trees_reassigned": 0,
    }


@router.post("/calculations/{calculation_id}/geometry/divide-preview")
async def divide_preview(
    calculation_id,
    body: Dict[str, Any],
    force: bool = Query(
        False,
        description="server-internal/admin override — bypasses lifecycle, never structure lock",
    ),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Dry-run equal-area division — no persist, same response shape.

    Routed identically to ``divide_equal_areas`` (FS-4a.5): root divides,
    parent-kept carves, and self-divides must preview EXACTLY what commit will
    do, or the divide panel 400s/ghosts wrongly before the user ever reaches
    "commit".
    """
    calc = _calc_with_guard(db, calculation_id, current_user, force=force)
    layer_type = body.get("layer_type")
    if layer_type not in geo.DIVIDE_ALLOWED_LAYERS:
        raise HTTPException(
            status_code=400,
            detail=f"Divide is not allowed for layer '{layer_type}' (R2)",
        )
    feature_id = str(body.get("feature_id") or "")

    # --- root divides ---------------------------------------------------------
    if not feature_id:
        if layer_type in ("sub_blocks", "sub_compartments"):
            raise HTTPException(
                status_code=400,
                detail="Sub-units cannot be carved from the forest root — divide a block (or compartment) first, then sub-divide it.",
            )
        if layer_type == "blocks":
            try:
                result = await preview_divide_blocks(
                    db,
                    calc,
                    parent_id=None,
                    method=body.get("method", "strips"),
                    n=body.get("count") or body.get("n"),
                    rows=body.get("rows"),
                    cols=body.get("cols"),
                    direction=body.get("direction", "vertical"),
                    direction_angle=body.get("direction_angle"),
                    naming_pattern=body.get("naming_pattern", ""),
                )
            except ValueError as exc:
                raise HTTPException(
                    status_code=400, detail=resolve_service_detail(str(exc))
                )
            return {
                "success": result["success"],
                "pieces": result["pieces"],
                "warnings": result["warnings"],
                "total_pieces": result["total_pieces"],
                "parent_id": result["parent_id"],
            }
        if layer_type == "compartments":
            try:
                result = await preview_divide_compartment(
                    db,
                    calc=calc,
                    parent_id=None,
                    layer_type="compartments",
                    method=body.get("method", "strips"),
                    n=body.get("count") or body.get("n"),
                    rows=body.get("rows"),
                    cols=body.get("cols"),
                    direction=body.get("direction", "vertical"),
                    direction_angle=body.get("direction_angle"),
                    naming_pattern=body.get("naming_pattern", ""),
                    island_counts=body.get("island_counts"),
                    target_area_sqm=body.get("target_area_sqm"),
                )
            except ValueError as exc:
                raise HTTPException(
                    status_code=400, detail=resolve_service_detail(str(exc))
                )
            resp = {
                "success": result["success"],
                "pieces": result["pieces"],
                "warnings": result["warnings"],
                "total_pieces": len(result["pieces"]),
                "parent_id": result["parent_id"],
            }
            for k in ("islands", "target_area_ha", "n_effective"):
                if k in result:
                    resp[k] = result[k]
            return resp

    # --- feature-based routing --------------------------------------------------
    row = None
    preview_labelled = False
    if layer_type in STRUCTURAL_LAYERS:
        row = (
            db.query(ForestBlock)
            .filter(
                ForestBlock.id == _structural_uuid(feature_id),
                ForestBlock.calculation_id == calc.id,
            )
            .first()
        )

    if layer_type == "sub_blocks":
        if row is None:
            raise HTTPException(status_code=404, detail="Forest division not found")
        own = layer_of(row)
        if own in ("compartments", "sub_compartments"):
            raise HTTPException(
                status_code=400,
                detail=resolve_service_detail(
                    "NOT_A_BLOCK: Can only sub-divide a block."
                ),
            )
        if own == "blocks":
            # parent-kept: preview carving this top-level block into sub-blocks.
            try:
                result = await preview_divide_blocks(
                    db,
                    calc,
                    parent_id=feature_id,
                    method=body.get("method", "strips"),
                    n=body.get("count") or body.get("n"),
                    rows=body.get("rows"),
                    cols=body.get("cols"),
                    direction=body.get("direction", "vertical"),
                    direction_angle=body.get("direction_angle"),
                    naming_pattern=body.get("naming_pattern", ""),
                )
            except ValueError as exc:
                raise HTTPException(
                    status_code=400, detail=resolve_service_detail(str(exc))
                )
            return {
                "success": result["success"],
                "pieces": result["pieces"],
                "warnings": result["warnings"],
                "total_pieces": result["total_pieces"],
                "parent_id": result["parent_id"],
            }
        # own == "sub_blocks": self-divide the selected sub-block in place.
        target = _resolve_feature(db, calc, layer_type, feature_id)
        preview_labelled = True
    elif layer_type in ("compartments", "sub_compartments"):
        if row is None or layer_of(row) != layer_type:
            # parent-kept: carve a FRESH set of children under the parent one
            # level up (the root case above already returned).
            try:
                result = await preview_divide_compartment(
                    db,
                    calc=calc,
                    parent_id=feature_id,
                    layer_type=layer_type,
                    method=body.get("method", "strips"),
                    n=body.get("count") or body.get("n"),
                    rows=body.get("rows"),
                    cols=body.get("cols"),
                    direction=body.get("direction", "vertical"),
                    direction_angle=body.get("direction_angle"),
                    naming_pattern=body.get("naming_pattern", ""),
                    island_counts=body.get("island_counts"),
                    target_area_sqm=body.get("target_area_sqm"),
                )
            except ValueError as exc:
                raise HTTPException(
                    status_code=400, detail=resolve_service_detail(str(exc))
                )
            resp = {
                "success": result["success"],
                "pieces": result["pieces"],
                "warnings": result["warnings"],
                "total_pieces": len(result["pieces"]),
                "parent_id": result["parent_id"],
            }
            # multi-island: pass through the per-island breakdown (P2)
            for k in ("islands", "target_area_ha", "n_effective"):
                if k in result:
                    resp[k] = result[k]
            return resp
        # self-divide: the selected compartment/sub-compartment itself.
        target = _resolve_feature(db, calc, layer_type, feature_id)
        preview_labelled = True
    else:
        # boundary / blocks — generic replace-in-place.
        target = _resolve_feature(db, calc, layer_type, feature_id)
    try:
        pieces, warnings = _divide_geometry(
            target["geometry"],
            layer_type=layer_type,
            method=body.get("method", "strips"),
            n=body.get("count", body.get("n")),
            direction=body.get("direction", "vertical"),
            rows=body.get("rows"),
            cols=body.get("cols"),
            direction_angle=body.get("direction_angle"),
            island_counts=body.get("island_counts"),
            target_area_sqm=body.get("target_area_sqm"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=resolve_service_detail(str(exc)))

    if preview_labelled and row is not None:
        # Label pieces the same way `_replace_feature_with_pieces` will
        # actually name them on commit, so the ghost preview shows the real
        # outcome (name + area) rather than bare geometry — the divide panel
        # (built against the parent-child divide_compartment response shape)
        # reads p.name/p.geometry/p.area_hectares per piece to draw and
        # label the ghost overlay; without this it silently drew nothing.
        parent_name = row.name
        labelled = []
        for i, piece in enumerate(pieces, start=1):
            sqm = _area_sqm_shapely(piece)
            labelled.append(
                {
                    "geometry": _serialize(piece),
                    "name": f"{parent_name}-{i}",
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
            "parent_id": str(row.id),
        }

    return {
        "success": True,
        "pieces": [_serialize(p) for p in pieces],
        "warnings": warnings,
        "total_pieces": len(pieces),
    }


@router.post("/calculations/{calculation_id}/geometry/paste-units")
def paste_units(
    calculation_id,
    body: Dict[str, Any],
    force: bool = Query(
        False,
        description="server-internal/admin override — bypasses lifecycle, never structure lock",
    ),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """{layer_type, parent_id, features, preview} -> paste copied feature(s)
    into a unit layer (D12, FS-4a.11).

    ``layer_type`` is one of the four structural layers. ``parent_id`` is
    required for ``sub_blocks``/``sub_compartments`` (which block/compartment
    the pasted sub-unit(s) land under) and must be omitted/null for
    ``blocks``/``compartments`` (a top-level paste has no parent -- it draws
    from the virtual root, D6). ``features`` is a list of GeoJSON geometries
    (NOT Features -- the caller already stripped attributes per
    ``lib/featureClipboard.ts::cleanProperties``; every pasted unit's own
    attributes come from ``child_inherit_kwargs``, matching every other
    freshly-minted child in this package, never from the copied source row).
    ``preview`` (default ``false``) rehearses without persisting.

    A whole-paste refusal (wrong/missing parent, locked target, cross-stream,
    same-place) is a 400/409 with the service's own code (D12). An
    individual pasted feature with no usable ground after clipping is
    silently skipped, not a whole-request failure -- ``skipped`` in the
    response says how many.
    """
    calc = _calc_with_guard(db, calculation_id, current_user, force=force)
    layer_type = body.get("layer_type")
    if layer_type not in ("blocks", "sub_blocks", "compartments", "sub_compartments"):
        raise HTTPException(
            status_code=400,
            detail=f"Paste is not allowed for layer '{layer_type}'",
        )
    parent_id = body.get("parent_id")
    raw_features = body.get("features")
    if not isinstance(raw_features, list) or not raw_features:
        raise HTTPException(status_code=400, detail="features is required")
    preview = bool(body.get("preview", False))

    from ..services.forest_units.operations.paste import (
        ERR_SAME_PLACE,
        ERR_STREAM_EMPTY_REQUIRED,
        apply_paste,
        preview_paste,
    )

    try:
        if preview:
            result = preview_paste(db, calc, layer_type, parent_id, raw_features)
        else:
            result = apply_paste(db, calc, layer_type, parent_id, raw_features)
    except ValueError as exc:
        code = str(exc)
        status_code = 409 if code in (ERR_SAME_PLACE, ERR_STREAM_EMPTY_REQUIRED) else 400
        raise HTTPException(status_code=status_code, detail=resolve_service_detail(code))

    if not preview:
        geo.bump_geometry_version(calc)
        db.commit()

    return {"success": True, "preview": preview, **result}


@router.post("/calculations/{calculation_id}/geometry/copy-boundary-to-block")
def copy_boundary_to_block(
    calculation_id,
    body: Dict[str, Any],
    force: bool = Query(
        False,
        description="server-internal/admin override — bypasses lifecycle, never structure lock",
    ),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """D4 — clone boundary_geom → new ForestBlock(s), bump version."""
    calc = _calc_with_guard(db, calculation_id, current_user, force=force)
    spec = geo.clone_boundary_to_block_spec(calc)
    if spec is None:
        raise HTTPException(status_code=404, detail="Forest boundary is not set")
    geom, attrs = spec
    from ..services.forest_units.write import structure_write
    # One row = one selectable map feature (single_part_geometry.py): a
    # boundary that genuinely consists of several disjoint substantial parts
    # (island archipelagos) becomes one block per part, never a single
    # MultiPolygon row (which the ORM @validates('geometry') guard would
    # reject with MultiPartFeatureError).
    from app.utils.single_part_geometry import (
        explode_and_filter_slivers as _ctb_explode,
    )

    _parts = _ctb_explode([geom])
    if not _parts:
        raise HTTPException(status_code=400, detail="Forest boundary has no substantial area")
    _created_ids: list = []
    _total_ha = 0.0
    for _pi, _part in enumerate(_parts):
        _sqm = geo.area_sqm(_part)
        _ha = round(_sqm / SQM_PER_HA, 4)
        row = ForestBlock(
            calculation_id=calc.id,
            name=(body.get("name") or attrs["name"])
            if len(_parts) == 1
            else f"{body.get('name') or attrs['name']} {_pi + 1}",
            geometry=from_shape(_part, srid=4326),
            area_hectares=_ha,
            area_sqm=round(_sqm, 2),
            index=geo.next_block_index(db, calc.id),
        )
        with structure_write(db, calc, change="create one block from the boundary"):
            db.add(row)
            db.flush()
        _created_ids.append(str(row.id))
        _total_ha += _ha
    db.commit()
    db.refresh(calc)
    return {
        "success": True,
        "block": {
            "id": _created_ids[0],
            "name": (body.get("name") or attrs["name"])
            if len(_parts) == 1
            else f"{body.get('name') or attrs['name']} 1",
            "area_hectares": round(_total_ha, 4),
        },
        "created_ids": _created_ids,
    }


@router.get("/calculations/{calculation_id}/geometry/delete-guard")
def delete_guard(
    calculation_id,
    layer_type: str = Query(...),
    feature_id: str = Query(...),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """R5 — returns {layer_type, feature_id, blocked, reasons[]}."""
    calc = _get_or_404(db, calculation_id)
    _require_owner(calc, current_user)
    return geo.check_delete_guard(db, calc, layer_type, feature_id)


# ---------------------------------------------------------------------------
# E3 undo — single-row snapshot + restore (R5: exactly 1 row, no cascade)
# ---------------------------------------------------------------------------


@router.get("/calculations/{calculation_id}/geometry/feature")
def feature_snapshot(
    calculation_id,
    layer_type: str = Query(...),
    feature_id: str = Query(...),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """E3 — capture a full snapshot of ONE row before it is deleted (undo).

    Returns the complete row payload (id, attributes, geometry) so the frontend
    can restore exactly one feature. Compartment/sub-compartment rows are
    independent (R5): the snapshot never includes child rows.
    """
    calc = _get_or_404(db, calculation_id)
    _require_owner(calc, current_user)

    if layer_type in STRUCTURAL_LAYERS:
        row = (
            db.query(ForestBlock)
            .filter(
                ForestBlock.id == feature_id,
                ForestBlock.calculation_id == calc.id,
            )
            .first()
        )
        if not row:
            raise HTTPException(status_code=404, detail="Forest division not found")
        geometry = _to_geojson(row.geometry) or _serialize(to_shape(row.geometry))
        return {
            "layer_type": layer_type,
            "feature_id": str(row.id),
            "snapshot": {
                "id": str(row.id),
                "name": row.name,
                "geometry": geometry,
                "area_hectares": row.area_hectares,
                "area_sqm": row.area_sqm,
                "index": row.index,
                "is_compartment": bool(row.is_compartment),
                "parent_block_id": (
                    str(row.parent_block_id) if row.parent_block_id else None
                ),
                "compartment_code": row.compartment_code,
                "division_level": row.division_level,
                "color": row.color,
                "is_locked": bool(row.is_locked),
                "child_count": row.child_count,
                "display_order": row.display_order,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            },
        }

    if layer_type == "sub_areas":
        sa = _find_sub_area(calc, feature_id)
        if sa is None:
            raise HTTPException(status_code=404, detail="Sub-area not found")
        return {
            "layer_type": layer_type,
            "feature_id": feature_id,
            "snapshot": sa,
        }

    if layer_type == "boundary":
        if getattr(calc, "boundary_geom", None) is None:
            raise HTTPException(status_code=404, detail="Forest boundary is not set")
        return {
            "layer_type": layer_type,
            "feature_id": "boundary",
            "snapshot": {
                "geometry": _to_geojson(calc.boundary_geom),
                "area_hectares": getattr(calc, "area_hectares", 0) or 0,
            },
        }

    if layer_type == "user_group":
        from ..models.user_group import UserGroupExtent

        row = (
            db.query(UserGroupExtent)
            .filter(UserGroupExtent.calculation_id == calc.id)
            .first()
        )
        if not row:
            raise HTTPException(status_code=404, detail="User group extent not found")
        # Geometry IS the row: UserGroupExtent stores no name/area column, and
        # source_type / buffer_distance_m record HOW the extent was produced --
        # a reshape leaves them alone, so they need no snapshot to restore.
        return {
            "layer_type": layer_type,
            "feature_id": f"user_group#{row.id}",
            "snapshot": {
                "id": f"user_group#{row.id}",
                "name": "User Group Boundary",
                "geometry": _to_geojson(row.extent_geometry),
            },
        }

    raise HTTPException(
        status_code=400, detail=f"Unsupported layer_type '{layer_type}'"
    )


class RestoreFeatureRequest(BaseModel):
    layer_type: str
    feature_id: str
    snapshot: Dict[str, Any]


@router.post("/calculations/{calculation_id}/geometry/restore-feature")
def restore_feature(
    calculation_id,
    body: RestoreFeatureRequest,
    force: bool = Query(
        False,
        description="server-internal/admin override — bypasses lifecycle, never structure lock",
    ),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """E3 — undo restore of exactly the deleted row (R5; no cascade).

    blocks / compartments / sub_compartments → re-insert ForestBlock row with
    the ORIGINAL id (safe: R4 guard already removed any inventory FKs; the id
    is free so FKs into it are re-valid not orphaned).
    sub_areas → re-append to result_data + recompute excluded/effective areas.
    boundary → restore boundary_geom.
    """
    calc = _apply_write_guard(_get_or_404(db, calculation_id), current_user, force)
    snap = body.snapshot
    layer_type = body.layer_type

    if layer_type in STRUCTURAL_LAYERS:
        geom = snap.get("geometry")
        if not geom:
            raise HTTPException(status_code=400, detail="Snapshot is missing geometry")
        from shapely.geometry import shape as _shp

        sqm = snap.get("area_sqm") or 0
        if not sqm:
            sqm = _geometry_sqm(_shp(geom))
        row = ForestBlock(
            id=body.feature_id,
            calculation_id=calc.id,
            name=snap.get("name") or "Unnamed",
            geometry=_wkb_from_shape(geom),
            area_hectares=float(snap.get("area_hectares") or (sqm / SQM_PER_HA) or 0),
            area_sqm=round(sqm, 2),
            index=int(snap.get("index") or 0),
            is_compartment=bool(snap.get("is_compartment")),
            parent_block_id=snap.get("parent_block_id") or None,
            compartment_code=snap.get("compartment_code"),
            division_level=int(snap.get("division_level") or DEPTH_TOP_BLOCK),
            color=snap.get("color"),
            is_locked=bool(snap.get("is_locked")),
            child_count=int(snap.get("child_count") or 0),
            display_order=int(snap.get("display_order") or 0),
        )
        db.add(row)
        db.flush()
        # child_count on the (re-created) parent is semantics-only; leaf restore
        # never resurrects children so leave as-is rather than cascade-correct.
        # Put back = win the ground back. Deleting the unit made the area invariant fill the hole
        # with a Remainder; without this the restored unit sits on top of it (overlap).
        from ..services.forest_units.operations.paste import take_ground_for_restored

        take_ground_for_restored(db, calc, row)
        _sync_result_data_block(db, calc, row)
        geo.bump_geometry_version(calc)
        db.commit()
        return {"success": True, "layer_type": layer_type, "feature_id": str(row.id)}

    if layer_type == "sub_areas":
        sa_id = str(body.feature_id)
        result_data = calc.result_data or {}
        sub_areas = list(result_data.get("sub_areas", []))
        # avoid duplicates on double-restore
        if any(str(s.get("id")) == sa_id for s in sub_areas):
            return {
                "success": True,
                "layer_type": layer_type,
                "feature_id": sa_id,
                "already_restored": True,
            }
        restored = dict(snap)
        restored["id"] = sa_id
        sub_areas_area = restored.get("area_hectares") or restored.get("area")
        restored["area_hectares"] = float(sub_areas_area or 0)
        # Undo must not break the rules the delete had put out of reach: another
        # sub-area may have been drawn over this ground since, or the forest may
        # have changed. Place the restored shape like any other.
        _restored_geom = restored.get("geometry")
        if _restored_geom:
            from shapely.geometry import shape as _shp, mapping as _shp_mapping

            try:
                _placed = place_sub_area(db, calc, _shp(_restored_geom))
            except SubAreaPlacementError as exc:
                raise HTTPException(
                    status_code=409,
                    detail=PLACEMENT_MESSAGES[exc.reason]
                    + " -- it can no longer be restored there",
                )
            if _placed.clipped_to_forest or _placed.overlap_removed:
                _sqm = _area_sqm_shapely(_placed.geometry)
                restored["geometry"] = _shp_mapping(_placed.geometry)
                restored["area_sqm"] = round(_sqm, 2)
                restored["area_hectares"] = round(_sqm / SQM_PER_HA, 4)
                if "area_ha" in restored:
                    restored["area_ha"] = restored["area_hectares"]
            if _placed.pending_boundary_clip:
                restored["pending_boundary_clip"] = True
        sub_areas.append(restored)

        result_data["sub_areas"] = sub_areas
        result_data["sub_areas_count"] = len(sub_areas)
        from .forests import (
            calculate_total_excluded_area,
            calculate_block_excluded_areas,
        )

        excluded_total = calculate_total_excluded_area(result_data["sub_areas"])
        result_data["excluded_area_hectares"] = round(excluded_total, 4)
        total_area = result_data.get("area_hectares", 0)
        result_data["effective_area_hectares"] = round(total_area - excluded_total, 4)
        blocks = result_data.get("blocks", [])
        block_excluded_map = calculate_block_excluded_areas(
            blocks, result_data["sub_areas"]
        )
        for block in blocks:
            block_id = block.get("block_id")
            block["excluded_area_hectares"] = round(
                block_excluded_map.get(block_id, 0.0), 4
            )
            original_area = block.get("area_hectares", 0)
            block["effective_area_hectares"] = round(
                original_area - block["excluded_area_hectares"], 4
            )
        result_data["blocks"] = blocks

        calc.result_data = result_data
        attributes.flag_modified(calc, "result_data")
        geo.bump_geometry_version(calc)
        db.commit()
        return {"success": True, "layer_type": layer_type, "feature_id": sa_id}

    if layer_type == "boundary":
        geom = snap.get("geometry")
        if not geom:
            raise HTTPException(status_code=400, detail="Snapshot is missing geometry")
        from shapely.geometry import shape as shp

        _restored_shape = shp(geom)
        calc.boundary_geom = from_shape(_restored_shape, srid=4326)

        from app.services.boundary_pieces_service import sync_boundary_pieces

        sync_boundary_pieces(db, calc, _restored_shape)

        # Undoing a boundary edit can bring back a SMALLER boundary than the
        # current one: sub-areas must still lie inside whichever one is live.
        _reclip = reclip_sub_areas_to_boundary(db, calc, _restored_shape)
        geo.bump_geometry_version(calc)
        db.commit()
        return {
            "success": True,
            "layer_type": layer_type,
            "feature_id": "boundary",
            "sub_areas_clipped": _reclip["clipped"],
            "sub_areas_dropped": _reclip["dropped"],
        }

    if layer_type == "user_group":
        from ..models.user_group import UserGroupExtent
        from shapely.geometry import shape as shp

        geom = snap.get("geometry")
        if not geom:
            raise HTTPException(status_code=400, detail="Snapshot is missing geometry")
        row = (
            db.query(UserGroupExtent)
            .filter(UserGroupExtent.calculation_id == calc.id)
            .first()
        )
        if not row:
            raise HTTPException(status_code=404, detail="User group extent not found")
        # Undo only ever RE-SHAPES the one extent: a new extent may have been
        # drawn since, and that is exactly what this puts back. Polygon -> the
        # MULTIPOLYGON column typmod, same coercion the edit path applies.
        restored = shp(geom)
        from shapely.geometry import MultiPolygon

        if restored.geom_type == "Polygon":
            restored = MultiPolygon([restored])
        row.extent_geometry = from_shape(restored, srid=4326)
        geo.bump_geometry_version(calc)
        db.commit()
        return {
            "success": True,
            "layer_type": layer_type,
            "feature_id": f"user_group#{row.id}",
        }

    raise HTTPException(
        status_code=400, detail=f"Unsupported section restore layer_type '{layer_type}'"
    )


def _wkb_from_shape(geom):
    from shapely.geometry import shape as shp

    return from_shape(shp(geom), srid=4326)


def _geometry_sqm(geom_shp):
    sqm, _ = calculate_area_geodesic_from_shapely(geom_shp)
    return float(sqm or 0.0)


@router.delete(
    "/calculations/{calculation_id}/boundary", status_code=status.HTTP_204_NO_CONTENT
)
def delete_boundary(
    calculation_id,
    force: bool = Query(
        False,
        description="server-internal/admin override — bypasses lifecycle, never structure lock",
    ),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Layer-level boundary delete.  Blocks (children) keep their geometry.

    Guard (user rule, 2026-08-12): when ANY dependent layer data exists
    (blocks / compartments / sub-compartments / sub-areas), the boundary is
    NOT deleted — those layers are clipped to the boundary, so removing it
    would orphan them.  Deletion is only allowed when no other layer data
    exists.  ``force=true`` (server-internal/admin) bypasses the guard.
    """
    calc = _calc_with_guard(db, calculation_id, current_user, force=force)

    if not force:
        existing_block = (
            db.query(ForestBlock.id)
            .filter(ForestBlock.calculation_id == calc.id)
            .first()
        )
        # a strip is derived from the boundary, so it never blocks deleting it (it goes with it, below)
        sub_areas = real_sub_areas((calc.result_data or {}).get("sub_areas") or [])
        if existing_block is not None:
            raise HTTPException(
                status_code=409,
                detail=with_message_np(
                    {"code": "HAS_CHILD_LAYERS"},
                    "editing.has_child_layers",
                    preserve_code=True,
                ),
            )
        if sub_areas:
            raise HTTPException(
                status_code=409,
                detail=with_message_np(
                    {"code": "HAS_CHILD_LAYERS"},
                    "editing.has_child_layers_variant",
                    preserve_code=True,
                ),
            )

    calc.boundary_geom = None

    from app.models.forest_boundary_piece import ForestBoundaryPiece as _FBP

    db.query(_FBP).filter(_FBP.calculation_id == calc.id).delete()

    # result_data.geometry / area_hectares are the SSOT the UI, reports and
    # exports read (and the boundary layer's fetch falls back to them). Leaving
    # them set makes a deleted boundary reappear on the next refresh.
    rd = dict(calc.result_data or {})
    changed = False
    for _k in ("geometry", "area_hectares", "boundary_name"):
        if _k in rd:
            rd.pop(_k, None)
            changed = True
    if any(is_strip(sa) for sa in rd.get("sub_areas") or []):
        rd["sub_areas"] = real_sub_areas(rd.get("sub_areas"))
        rd["sub_areas_count"] = len(rd["sub_areas"])
        changed = True
    if changed:
        calc.result_data = rd
        from sqlalchemy.orm.attributes import flag_modified

        flag_modified(calc, "result_data")
    geo.bump_geometry_version(calc)
    db.commit()


# ---------------------------------------------------------------------------
# Auto-Block generation from the MMU natural-feature layer (plan §3)
# ---------------------------------------------------------------------------


class AutoBlockCommitRequest(BaseModel):
    """Stage-2 payload: level + the accepted serial/merged block geometries."""

    level: str = (
        "blocks"  # "blocks" (top-level, not compartment) | "compartments" (top-level compartment)
    )
    blocks: List[Dict[str, Any]] = []
    # Same sliver floor the preview used (m²). When set, any part of a committed
    # merge below the floor is folded into the block's largest part instead of
    # persisting as its own below-threshold row (see `commit_blocks`).
    sliver_area_m2: Optional[float] = None
    # RS-2.16 (P2.5): which Auto-Block source produced these pieces -- creates
    # a new, unpromoted `raster_layers` row rather than the old forest-global
    # commit. Same vocabulary as the preview request's `source`.
    source: str = "mmu"


class AutoBlockPreviewRequest(BaseModel):
    """Stage-1 payload: optional target-N for a server-side merge plan and the
    optional sliver floor (m², default = SSOT 1 ha for MMU / ~1000 m² for
    the raster/TIF sources) for dropping/absorbing tiny pieces at auto-block
    creation time. For the `canopy` source only: ``nodata_min_m2`` is the
    threshold (default 1 ha) above which a contiguous no-data patch (a river,
    sandbank, settlement or large sensor gap) is carved as its own "no-data"
    block rather than absorbed into a neighbouring forest block. `source`
    picks the carve basis: `mmu` (rivers & ridges, default), `slope`
    (slope-class breaks, कार्यविधि §15.2), `aspect` (compass direction,
    rasters.aspect), `canopy` (canopy-height structure class,
    canopy_height5m.tif) or `nasa_quality` (NASA 2020 forest-quality class,
    rasters.nasa_forest_2020, fallback when the boundary has no tree-cover
    canopy layer). ``force_absorb_orphans`` merges sub-threshold pieces
    even if they have no touching neighbour (into the largest remaining piece
    by area)."""

    level: str = "blocks"
    source: str = "mmu"
    desired_n: Optional[int] = None
    sliver_area_m2: Optional[float] = None
    nodata_min_m2: Optional[float] = None
    force_absorb_orphans: bool = False
    # `landcover` source only (RS-9.2/D24): ESA codes to group as "forest" in
    # Mode A. Omitted/None keeps the default (10, 20) = Tree cover + Shrubland.
    # Passing the full ESA code tuple is Mode B (every class its own group).
    forest_classes: Optional[List[int]] = None
    # `dem` source only (RS-9.3): how many equal-elevation-interval bands to
    # cut, computed from THIS forest's own min/max. Omitted/None defaults to 3.
    elevation_bands: Optional[int] = None
    # `union_fusion` source only (RS-10.3b, owner question 2026-10-01):
    # which OPTIONAL attributes to pixel-fuse alongside the always-included
    # slope gate -- any subset of "aspect"/"forest_type"/"nasa_quality"/
    # "forest_health"/"landcover"/"dem". Omitted/None fuses all of them
    # (the original RS-10.3 behaviour).
    fusion_sources: Optional[List[str]] = None
    # `union_fusion` source only: attach canopy per final piece (the same
    # zonal call union_zonal uses) or skip it. Omitted/None defaults True.
    fusion_include_canopy: Optional[bool] = None


@router.post("/calculations/{calculation_id}/auto-blocks/preview")
def auto_blocks_preview(
    calculation_id,
    body: AutoBlockPreviewRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Stage 1 — clip `base.mmu` to the forest boundary (server-side only).

    Returns descending pieces (serial + natural_name) + adjacency edges + meta
    WITHOUT writing.  Refuses 409 BLOCKS_EXIST when any block/compartment
    already exists (user-confirmed replace semantics, plan D5).
    """
    calc = _calc_with_guard(db, calculation_id, current_user, force=False)
    from ..services.auto_block_service import (
        check_compartment_sampling_mutex,
        resolve_root_scope,
        resolve_source_fn,
    )

    if calc.boundary_geom is None:
        raise i18n_error(409, "blocks.no_boundary")

    # RS-2.16 owner report, 2026-10-01: this preview-stage check was never
    # updated when the commit-stage one was narrowed to legacy-only — it was
    # STILL counting every row unconditionally, so the dialogue refused a
    # second source's preview ("Blocks/compartments already exist") even
    # though nothing was promoted and nothing was visible anywhere. The
    # dialogue calls preview live as soon as it opens/the source changes,
    # before any Commit click, which is exactly why the error appeared there
    # and not at commit time.
    from ..services.auto_block_service import _promoted_or_legacy_blocks_exist

    if _promoted_or_legacy_blocks_exist(db, calc):
        raise i18n_error(409, "blocks.blocks_exist")

    if body.level not in {"blocks", "compartments"}:
        raise i18n_error(400, "blocks.bad_level")
    # Tell the user now, not after they have designed the split and hit Commit.
    try:
        check_compartment_sampling_mutex(db, calc, body.level)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=resolve_service_detail(str(exc)))
    # One registry, one resolver, one error (RS-0.3): the four preview functions
    # used to be duplicated into a function-local dict here, which meant a new
    # source could be registered in `auto_block_service` and silently rejected
    # here. `resolve_source_fn` also makes this endpoint's rejection byte-identical
    # to the divide-preview/commit rejections, which the three used to differ on.
    try:
        preview_fn = resolve_source_fn(body.source)
    except ValueError as e:
        if str(e) == "bad_source":
            raise i18n_error(400, "blocks.bad_source")
        raise
    try:
        # FS-4a.6: the whole-forest auto-create works from the virtual root
        # shell (boundary minus private land, protection punched out), the same
        # source the equal-area root carve uses.
        scope, _excluded = resolve_root_scope(db, calc)
    except ValueError as e:
        if str(e) == "no_boundary":
            raise i18n_error(409, "blocks.no_boundary")
        # `resolve_root_scope` also raises `no_coverage_in_feature` when the
        # virtual root shell is empty after private land / protection are
        # punched out -- a bare token that must resolve to `blocks.*`.
        raise HTTPException(
            status_code=400,
            detail=resolve_bare_service_detail(str(e)),
        )
    try:
        kwargs = dict(
            level=body.level,
            desired_n=body.desired_n,
            sliver_area_m2=body.sliver_area_m2,
            force_absorb_orphans=body.force_absorb_orphans,
            scope=scope,
        )
        if body.source == "canopy" and body.nodata_min_m2 is not None:
            kwargs["nodata_min_m2"] = body.nodata_min_m2
        if body.source == "landcover" and body.forest_classes is not None:
            kwargs["forest_classes"] = tuple(body.forest_classes)
        if body.source == "dem" and body.elevation_bands is not None:
            kwargs["elevation_bands"] = body.elevation_bands
        if body.source == "union_fusion":
            if body.fusion_sources is not None:
                kwargs["sources"] = body.fusion_sources
            if body.fusion_include_canopy is not None:
                kwargs["include_canopy"] = body.fusion_include_canopy
        result = preview_fn(db, calc, **kwargs)
    except ValueError as e:
        # A bare coverage token (`no_slope_coverage`, `no_nasa_quality_coverage`,
        # ...) must resolve to its `blocks.*` registry entry, not surface the raw
        # snake_case string to the user in both languages.
        raise HTTPException(
            status_code=400,
            detail=resolve_bare_service_detail(str(e)),
        )
    return {
        "ok": True,
        "meta": result["meta"],
        "pieces": result["pieces"],
        "edges": result["edges"],
    }


@router.post("/calculations/{calculation_id}/auto-blocks/commit")
def auto_blocks_commit(
    calculation_id,
    body: AutoBlockCommitRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Stage 2 — persist the accepted serial/merged blocks as forest_blocks.

    Refuses 409 BLOCKS_EXIST when any block/compartment exists (plan D5).
    """
    calc = _calc_with_guard(db, calculation_id, current_user, force=False)
    from ..services.auto_block_service import (
        _promoted_or_legacy_blocks_exist,
        commit_blocks,
        resolve_root_scope,
    )

    if calc.boundary_geom is None:
        raise i18n_error(409, "blocks.no_boundary")

    # RS-2.16, narrowed 2026-10-01 (owner report): only pre-P2.5 legacy rows
    # refuse now. Neither an unpromoted trial layer NOR an already-promoted
    # one blocks a new source from being carved -- comparing several sources
    # before deciding which (if any) to assign is the actual workflow, not a
    # one-shot choice made at carve time.
    if _promoted_or_legacy_blocks_exist(db, calc):
        raise i18n_error(409, "blocks.blocks_exist")

    if body.level not in {"blocks", "compartments"}:
        raise i18n_error(400, "blocks.bad_level")
    if not body.blocks:
        raise i18n_error(400, "blocks.empty_blocks")

    try:
        scope, excluded = resolve_root_scope(db, calc)
    except ValueError as e:
        if str(e) == "no_boundary":
            raise i18n_error(409, "blocks.no_boundary")
        raise

    try:
        created = commit_blocks(
            db, calc, body.blocks, level=body.level,
            sliver_area_m2=body.sliver_area_m2, scope=scope,
            source=body.source,
        )
    except ValueError as e:
        code = str(e)
        if code == "BLOCKS_EXIST":
            raise i18n_error(409, "blocks.blocks_exist")
        if code.startswith("SAMPLING_MUTEX:"):
            raise HTTPException(status_code=400, detail=resolve_service_detail(code))
        raise HTTPException(
            status_code=400,
            detail=resolve_bare_service_detail(code),
        )

    # BLOCK_BOUNDARY_INVARIANT (E.6): auto-fill any uncovered boundary area as a
    # Remainder Block/Compartment so total area always equals the boundary.
    # FS-4a.6: the whole-forest auto-create now resolves its shell from the
    # virtual root; when private land / protection units shape that shell, the
    # boundary-tiled remainder would mint rows ON them. The scope-aware coverage
    # invariant is FS-3.1's own work; here the carved shell is kept exactly.
    from ..services.block_area_invariant_service import enforce_block_coverage
    from ..models.raster_layer import RasterLayer

    # RS-2.16: scope the coverage fill-in to the layer this commit just
    # created, not every row at this level for the calculation -- see
    # `enforce_block_coverage`'s docstring for why co-mingling layers here
    # would be wrong once more than one can exist at once.
    _layer = (
        db.query(RasterLayer)
        .filter(RasterLayer.calculation_id == calc.id, RasterLayer.source == body.source)
        .order_by(RasterLayer.created_at.desc())
        .first()
    )
    _layer_id = _layer.id if _layer is not None else None

    try:
        if excluded:
            _inv = {
                "remainder_added": False,
                "gap_ha": 0.0,
                "union_ha": 0.0,
                "boundary_ha": 0.0,
                "warnings": [],
            }
        else:
            _inv = enforce_block_coverage(
                db, calc, level=body.level, raster_layer_id=_layer_id
            )
    except ValueError as e:
        if str(e) == "TOPOLOGY_REJECTED":
            raise HTTPException(
                status_code=409,
                detail=with_message_np(
                    {"code": "TOPOLOGY_REJECTED"},
                    "editing.topology_auto_overlap",
                    preserve_code=True,
                ),
            )
        raise

    return {"ok": True, "blocks": created, "invariant": _inv}


# ---------------------------------------------------------------------------
# Auto-Block layers (RS-2.16/2.17, P2.5) - list, promote, demote. See
# auto_block_service.list_layers / promote_layer / demote_layer for the model.
#
# Path is `auto-block-layers`, NOT `raster-layers` -- `GET
# /calculations/{id}/raster-layers` already exists in tiles.py, for the
# unrelated raster TILE catalog (DEM/slope/NDVI/... as basemap overlays, not
# these carved-geometry layers). Colliding with it cost a live debugging
# session: the frontend silently got the tile catalog back (ids like "slope",
# not UUIDs), and promoting one sent a non-UUID string into
# `RasterLayer.id == layer_id`, which Postgres rejected with a DataError --
# surfaced to the user as the generic "wasn't in a form the system could use"
# message, nothing pointing at the real cause. Never reuse a path this close
# to an existing one without grepping for it first.
# ---------------------------------------------------------------------------


@router.get("/calculations/{calculation_id}/auto-block-layers")
def list_raster_layers(
    calculation_id,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Every Auto-Block layer for this forest — for the layer panel."""
    calc = _calc_with_guard(db, calculation_id, current_user, force=False)
    from ..services.auto_block_service import list_layers

    return {"layers": list_layers(db, calc)}


@router.get("/calculations/{calculation_id}/auto-block-layers/{layer_id}/features")
def get_auto_block_layer_features(
    calculation_id,
    layer_id,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Owner directive 2026-10-01 — an Auto-Block layer renders on the map
    and in the attribute table exactly like a built-in layer: its own
    geometry, its own name, and only its own classification column."""
    calc = _calc_with_guard(db, calculation_id, current_user, force=False)
    from ..services.auto_block_service import layer_features

    try:
        features = layer_features(db, calc, layer_id)
    except ValueError as e:
        if str(e) == "LAYER_NOT_FOUND":
            raise i18n_error(404, "blocks.layer_not_found")
        raise
    return {"features": features}


@router.get("/calculations/{calculation_id}/auto-block-layers/{layer_id}/eligible-parents")
def list_eligible_parents_for_layer(
    calculation_id,
    layer_id,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Candidates for "Assign to existing unit…" (RS-2.17 sub-unit assignment):
    every top-level block/compartment that has not already been divided.
    Which branch (sub-blocks vs sub-compartments) follows automatically from
    which parent is picked — a block's children are sub-blocks, a
    compartment's are sub-compartments — so this returns both kinds in one
    list rather than asking the caller to choose a branch first.
    """
    calc = _calc_with_guard(db, calculation_id, current_user, force=False)
    from ..services.forest_units.queries import promoted_or_unlayered

    # Only REAL structure can be a parent: an unpromoted trial layer's rows
    # (including this layer's own) are overlays, not blocks/compartments.
    rows = (
        promoted_or_unlayered(
            db.query(ForestBlock).filter(
                ForestBlock.calculation_id == calc.id,
                ForestBlock.division_level == DEPTH_TOP_BLOCK,  # == DEPTH_TOP_COMPARTMENT: both branches start at the same depth
                ForestBlock.child_count == 0,
            )
        )
        .order_by(ForestBlock.is_compartment, ForestBlock.index)
        .all()
    )
    return {
        "parents": [
            {
                "id": str(r.id),
                "name": r.block_name or r.name,
                "is_compartment": bool(r.is_compartment),
                "area_hectares": r.area_hectares,
            }
            for r in rows
        ]
    }


class AssignLayerAsChildrenRequest(BaseModel):
    parent_id: str
    sliver_area_m2: Optional[float] = None


@router.post("/calculations/{calculation_id}/auto-block-layers/{layer_id}/assign-children")
def assign_auto_block_layer_as_children(
    calculation_id,
    layer_id,
    body: AssignLayerAsChildrenRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """RS-2.17 sub-unit assignment (owner directive 2026-10-01): promote one
    Auto-Block layer's pieces as the children of one existing parent
    block/compartment (sub-blocks or sub-compartments, matching the parent's
    own branch) — the mechanism the owner confirmed: pick one parent, the
    whole layer becomes its children, same shape as the existing
    divide-one-feature flow."""
    calc = _calc_with_guard(db, calculation_id, current_user, force=False)
    from ..services.auto_block_service import promote_layer_as_children

    try:
        result = promote_layer_as_children(
            db, calc, layer_id, body.parent_id, sliver_area_m2=body.sliver_area_m2,
        )
    except ValueError as e:
        code = str(e)
        if code == "LAYER_NOT_FOUND":
            raise i18n_error(404, "blocks.layer_not_found")
        if code == "EMPTY_LAYER":
            raise i18n_error(400, "blocks.empty_blocks")
        if code == "NO_OVERLAP":
            raise i18n_error(400, "blocks.no_coverage_in_feature")
        raise _auto_divide_error(e)
    return result


class PromoteLayerRequest(BaseModel):
    as_level: str  # "blocks" | "compartments"
    force: bool = False  # switch away from another already-promoted layer


@router.post("/calculations/{calculation_id}/auto-block-layers/{layer_id}/promote")
def promote_raster_layer(
    calculation_id,
    layer_id,
    body: PromoteLayerRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """RS-2.17 — make ``layer_id`` the forest's real blocks/compartments.

    409 ``blocks.promoted_layer_exists`` when another layer already holds
    that role and ``force`` was not set (the "offers to switch" UX, D51).
    """
    calc = _calc_with_guard(db, calculation_id, current_user, force=False)
    from ..services.auto_block_service import promote_layer

    try:
        result = promote_layer(db, calc, layer_id, body.as_level, force=body.force)
    except ValueError as e:
        code = str(e)
        if code == "LAYER_NOT_FOUND":
            raise i18n_error(404, "blocks.layer_not_found")
        if code == "LEGACY_BLOCKS_EXIST":
            raise i18n_error(409, "blocks.legacy_blocks_exist")
        if code == "PROMOTED_LAYER_EXISTS":
            raise i18n_error(409, "blocks.promoted_layer_exists")
        if code == "EMPTY_LAYER":
            raise i18n_error(409, "blocks.empty_layer")
        if code == "bad_level":
            raise i18n_error(400, "blocks.bad_level")
        if code.startswith("SAMPLING_MUTEX:"):
            raise HTTPException(status_code=400, detail=resolve_service_detail(code))
        raise
    return {"ok": True, "layer": result}


@router.delete("/calculations/{calculation_id}/auto-block-layers/{layer_id}")
def delete_auto_block_layer(
    calculation_id,
    layer_id,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Owner report 2026-10-01: "I can not remove auto created layer. Make it
    deletable." Refuses 409 on a promoted layer — demote it first."""
    calc = _calc_with_guard(db, calculation_id, current_user, force=False)
    from ..services.auto_block_service import delete_layer

    try:
        result = delete_layer(db, calc, layer_id)
    except ValueError as e:
        code = str(e)
        if code == "LAYER_NOT_FOUND":
            raise i18n_error(404, "blocks.layer_not_found")
        if code == "PROMOTED_CANNOT_DELETE":
            raise i18n_error(409, "blocks.promoted_cannot_delete")
        raise
    return result


@router.post("/calculations/{calculation_id}/auto-block-layers/{layer_id}/demote")
def demote_raster_layer(
    calculation_id,
    layer_id,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """RS-2.17 — return a promoted layer to being a non-counting overlay."""
    calc = _calc_with_guard(db, calculation_id, current_user, force=False)
    from ..services.auto_block_service import demote_layer

    try:
        result = demote_layer(db, calc, layer_id)
    except ValueError as e:
        if str(e) == "LAYER_NOT_FOUND":
            raise i18n_error(404, "blocks.layer_not_found")
        raise
    return {"ok": True, "layer": result}


# ---------------------------------------------------------------------------
# Elevation backfill (RS-2.19) — existing blocks predate the always-on
# elevation attribute; measure first, write only when the owner asks
# (RASTER_SOURCES_TRACKER.md P2.5 consequence 4).
# ---------------------------------------------------------------------------


@router.get("/calculations/{calculation_id}/elevation-backfill/preview")
def elevation_backfill_preview(
    calculation_id,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Read-only: what would be written for every unit missing elevation.
    Never writes — see the apply endpoint below."""
    calc = _calc_with_guard(db, calculation_id, current_user, force=False)
    from ..services.elevation_service import compute_elevation_for_blocks, dem_available

    if not dem_available(db):
        return {"dem_available": False, "units": []}

    rows = (
        db.query(ForestBlock)
        .filter(
            ForestBlock.calculation_id == calc.id,
            ForestBlock.elevation_mean_m.is_(None),
        )
        .all()
    )
    stats = compute_elevation_for_blocks(db, [r.id for r in rows])
    return {
        "dem_available": True,
        "units": [
            {"id": str(r.id), "name": r.block_name or r.name, **stats[str(r.id)]}
            for r in rows
            if str(r.id) in stats
        ],
    }


@router.post("/calculations/{calculation_id}/elevation-backfill/apply")
def elevation_backfill_apply(
    calculation_id,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Write min/mean/max elevation onto every unit still missing it (does
    NOT touch `dominant_elevation_zone` — that is relative to the whole
    forest and is set at carve time, not by this one-off backfill)."""
    calc = _calc_with_guard(db, calculation_id, current_user, force=False)
    from ..services.elevation_service import apply_elevation, dem_available

    if not dem_available(db):
        return {"ok": True, "updated": 0, "dem_available": False}

    rows = (
        db.query(ForestBlock)
        .filter(
            ForestBlock.calculation_id == calc.id,
            ForestBlock.elevation_mean_m.is_(None),
        )
        .all()
    )
    apply_elevation(db, rows)
    updated = sum(1 for r in rows if r.elevation_mean_m is not None)
    db.commit()
    return {"ok": True, "updated": updated, "dem_available": True}


# ---------------------------------------------------------------------------
# Divide ONE selected feature by a natural basis (river/ridge, slope, aspect,
# canopy) - the per-feature sibling of the two whole-forest endpoints above.
# ---------------------------------------------------------------------------


class AutoDividePreviewRequest(BaseModel):
    """Same knobs as the whole-forest preview. ``level`` (optional) names the
    children the client is asking for; it must equal the level the parent's
    BRANCH infers (block -> ``sub_blocks``, compartment -> ``sub_compartments``,
    FS-4a.6) or the request is a 400 ``blocks.bad_level``. Defaults to the
    inferred level."""

    source: str = "mmu"
    level: Optional[str] = None
    desired_n: Optional[int] = None
    sliver_area_m2: Optional[float] = None
    nodata_min_m2: Optional[float] = None
    force_absorb_orphans: bool = False


class AutoDivideCommitRequest(BaseModel):
    source: str = "mmu"
    level: Optional[str] = None
    blocks: List[Dict[str, Any]] = []
    sliver_area_m2: Optional[float] = None


def _auto_divide_error(exc: ValueError) -> HTTPException:
    code = str(exc)
    if code == SOURCE_ERROR_CODE:
        return i18n_error(400, "blocks.bad_source")
    if code == "bad_level":
        return i18n_error(400, "blocks.bad_level")
    if (
        ":" in code
    ):  # a guard message with a service prefix (PARENT_NOT_FOUND:, DIVISION_ONCE_ONLY:, SAMPLING_MUTEX:, DIVISION_TOO_FEW:, ...)
        return HTTPException(status_code=400, detail=resolve_service_detail(code))
    return HTTPException(
        status_code=400,
        detail=resolve_bare_service_detail(code),
    )


@router.post("/calculations/{calculation_id}/blocks/{parent_id}/auto-divide/preview")
def auto_divide_preview(
    calculation_id,
    parent_id,
    body: AutoDividePreviewRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Preview dividing one block / compartment along river-ridge, slope, aspect or canopy
    breaks. Writes nothing. Every divide guard applies (once-only, sampling mutex, lock).
    """
    calc = _calc_with_guard(db, calculation_id, current_user, force=False)
    from ..services.auto_block_service import preview_children

    try:
        result = preview_children(
            db,
            calc,
            parent_id,
            source=body.source,
            desired_n=body.desired_n,
            sliver_area_m2=body.sliver_area_m2,
            force_absorb_orphans=body.force_absorb_orphans,
            nodata_min_m2=body.nodata_min_m2,
            level=body.level,
        )
    except ValueError as e:
        raise _auto_divide_error(e)
    return {
        "ok": True,
        "meta": result["meta"],
        "pieces": result["pieces"],
        "edges": result["edges"],
    }


@router.post("/calculations/{calculation_id}/blocks/{parent_id}/auto-divide/commit")
def auto_divide_commit(
    calculation_id,
    parent_id,
    body: AutoDivideCommitRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Persist the accepted pieces as children of the parent (guards re-checked)."""
    calc = _calc_with_guard(db, calculation_id, current_user, force=False)
    from ..services.auto_block_service import commit_children, is_valid_source

    if not is_valid_source(body.source):
        raise i18n_error(400, "blocks.bad_source")
    if not body.blocks:
        raise i18n_error(400, "blocks.empty_blocks")
    try:
        done = commit_children(
            db,
            calc,
            parent_id,
            body.blocks,
            source=body.source,
            sliver_area_m2=body.sliver_area_m2,
            created_by=current_user.id,
            level=body.level,
        )
    except ValueError as e:
        db.rollback()
        raise _auto_divide_error(e)
    return {"ok": True, **done}


# ---------------------------------------------------------------------------
# Draw-new-block (plan BLOCK_BOUNDARY_INVARIANT, E.7) — explicit "New Block /
# New Compartment" polygon draw entry point.
# ---------------------------------------------------------------------------


class DrawBlockRequest(BaseModel):
    """E.7 — {level, name?, geometry} for a user-drawn block/compartment."""

    level: str = (
        "blocks"  # "blocks" (top-level, not compartment) | "compartments" (top-level compartment)
    )
    name: Optional[str] = None
    geometry: Dict[str, Any]  # GeoJSON geometry


@router.post("/calculations/{calculation_id}/blocks/draw")
def draw_block(
    calculation_id,
    body: DrawBlockRequest,
    force: bool = Query(
        False,
        description="server-internal/admin override — bypasses lifecycle, never structure lock",
    ),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """E.7 — persist a user-drawn block/compartment clipped to the boundary.

    - ``clip_and_validate_block`` clips the polygon to the boundary and rejects
      ``OUTSIDE_BOUNDARY`` (drawn fully outside) / ``TOPOLOGY_REJECTED``
      (material overlap with an existing block).
    - ``enforce_block_coverage`` then silently auto-fills any boundary area the
      draw still leaves uncovered (Remainder Block/Compartment).
    """
    calc = _calc_with_guard(db, calculation_id, current_user, force=force)
    if body.level not in {"blocks", "compartments"}:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "BAD_LEVEL",
                "message": "level must be 'blocks' or 'compartments'.",
            },
        )
    from shapely.geometry import shape as shp
    from shapely import make_valid
    from ..services.block_area_invariant_service import (
        _level_rows,
        clip_and_validate_block,
        enforce_block_coverage,
    )

    try:
        geom = make_valid(shp(body.geometry))
    except Exception:
        raise HTTPException(
            status_code=400,
            detail=with_message_np(
                {"code": "invalid_geometry"},
                "editing.geometry_parse_failed",
                preserve_code=True,
            ),
        )

    # Existing same-level shapes → overlap rejection baseline.
    existing = _level_rows(db, str(calc.id), body.level)
    existing_shapes = [r.geometry for r in existing]

    info: Dict[str, Any] = {}
    try:
        clipped, info = clip_and_validate_block(
            geom, calc, existing_shapes, level=body.level
        )
    except ValueError as e:
        code = str(e)
        if code == "OUTSIDE_BOUNDARY":
            raise HTTPException(
                status_code=400,
                detail=with_message_np(
                    {"code": "OUTSIDE_BOUNDARY", "warnings": info.get("warnings", [])},
                    "editing.drawn_outside_boundary",
                    preserve_code=True,
                ),
            )
        if code == "TOPOLOGY_REJECTED":
            raise HTTPException(
                status_code=409,
                detail=with_message_np(
                    {"code": "TOPOLOGY_REJECTED", "warnings": info.get("warnings", [])},
                    "editing.drawn_overlap",
                    preserve_code=True,
                ),
            )
        raise HTTPException(
            status_code=400,
            detail=with_message_np(
                {"code": code, "message": code}, code, fallback_to_self=True
            ),
        )

    from ..core.constants import SQM_PER_HA

    sqm = geo.area_sqm(clipped)
    idx = geo.next_block_index(db, calc.id)
    is_comp = body.level == "compartments"
    serial = compartment_serial(idx) if is_comp else block_serial(idx)
    row = ForestBlock(
        calculation_id=calc.id,
        name=body.name or serial,
        block_name=body.name or serial,
        natural_name=None,
        geometry=from_shape(clipped, srid=4326),
        area_hectares=round(sqm / SQM_PER_HA, 4),
        area_sqm=round(sqm, 2),
        index=idx,
        is_compartment=is_comp,
        division_level=DEPTH_TOP_COMPARTMENT if is_comp else DEPTH_TOP_BLOCK,
    )
    db.add(row)
    db.flush()

    try:
        inv = enforce_block_coverage(db, calc, level=body.level)
    except ValueError as e:
        if str(e) == "TOPOLOGY_REJECTED":
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail=with_message_np(
                    {"code": "TOPOLOGY_REJECTED"},
                    "editing.drawn_exceeds_boundary",
                    preserve_code=True,
                ),
            )
        raise

    from ..services.forest_units.write import structure_write

    with structure_write(db, calc, change=f"draw a new {body.level}"):
        pass
    db.commit()
    db.refresh(row)
    return {
        "success": True,
        "level": body.level,
        "block": {
            "id": str(row.id),
            "name": row.name,
            "block_name": row.block_name,
            "natural_name": row.natural_name,
            "area_hectares": row.area_hectares,
            "index": row.index,
        },
        "clipped": info.get("clipped", False),
        "removed_ha": info.get("removed_ha", 0.0),
        "warnings": info.get("warnings", []),
        "invariant": inv,
    }
