"""
API endpoints for the Forest Boundary Overlap system (S11).

Provides:
  - Preview (read-only 3-phase overlap resolution)
  - Confirm (save resolved boundary)
  - Dispute filing and DFO resolution
  - Boundary status lifecycle management
  - Audit history
  - Nearby forest queries (200m visibility)
"""

from __future__ import annotations
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, text
from shapely.geometry import mapping, shape, Polygon

from ..core.database import get_db
from ..core.constants import SQM_PER_HA
from ..models.user import User, UserRole
from ..models.calculation import Calculation
from ..models.boundary_audit import ForestBoundaryAudit
from ..models.boundary_dispute import BoundaryDispute, DisputeStatus
from ..schemas.boundary import (
    BoundaryStatus,
    BoundaryStatusUpdate,
    BoundaryStatusResponse,
    PreviewRequest,
    PreviewResponse,
    OverlappingForest,
    ConfirmRequest,
    ConfirmResponse,
    PointsPreviewRequest,
    NearbyRelation,
    DisputeFileRequest,
    DisputeResponse,
    DisputeDetail,
    DisputeResolveRequest,
    DisputeResolveResponse,
    BoundaryAuditEntry,
    AuditListResponse,
    OverlapMethod,
)
from ..services.overlap_resolver import resolve_overlap, ResolutionParams
from ..services.gap_detector import detect_relations, GapParams
from ..core.exceptions import i18n_error
from ..utils.auth import get_current_active_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["boundary"])

SQM_PER_HA_F = float(SQM_PER_HA)


def _get_boundary_permission(calculation: Calculation, user: User) -> bool:
    """Check if user can edit boundary based on status."""
    if user.role == UserRole.SUPER_ADMIN.value:
        return True
    status = calculation.boundary_status or "draft"
    if status == "disputed":
        return False
    if status in ("draft", "validated"):
        return calculation.user_id == user.id
    return False


def _neighbour_outline_map(existing) -> dict[str, dict]:
    """{forest_id: GeoJSON} for the adjoining boundaries the preview map draws."""
    from geoalchemy2.shape import to_shape as _to_shape

    out: dict[str, dict] = {}
    for _calc in existing:
        if _calc.boundary_geom is None:
            continue
        try:
            out[str(_calc.id)] = mapping(_to_shape(_calc.boundary_geom))
        except Exception:  # noqa: BLE001 -- outline is decorative; skip a bad one
            out[str(_calc.id)] = None  # type: ignore[assignment]
    return out


def _overlapping_forests_payload(result, existing) -> list:
    """`OverlappingForest` rows from the resolver + each neighbour's outline."""
    outlines = _neighbour_outline_map(existing)
    rows = []
    for f in result.overlapping_forests:
        row = OverlappingForest(**f)
        geom = outlines.get(str(row.id))
        if geom is not None:
            row = row.model_copy(update={"geometry": geom})  # type: ignore[arg-type]
        rows.append(row)
    return rows


# ============================================================================
# PREVIEW — read-only clip. No gap analysis (2026-08-28 rework).
# ============================================================================


@router.post("/forests/boundary/preview", response_model=PreviewResponse)
def preview_boundary(
    request: PreviewRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Clip the proposed boundary against adjoining forests, read-only."""
    from shapely.validation import make_valid as shapely_make_valid

    poly = shape(request.geometry)
    if not poly.is_valid:
        poly = shapely_make_valid(poly)
    if poly.geom_type not in ("Polygon", "MultiPolygon"):
        raise i18n_error(
            400, "boundary.unsupported_geometry_type", geom_type=poly.geom_type
        )

    existing = _get_nearby_forests(db, poly, exclude_id=request.forest_id, radius_m=200)
    result = resolve_overlap(mapping(poly), existing, ResolutionParams())

    return PreviewResponse(
        status=result.status,
        orig_area_ha=round(result.orig_area_ha, 4),
        resolved_area_ha=round(result.resolved_area_ha, 4),
        removed_ha=round(result.removed_ha, 4),
        removed_pct=round(result.removed_pct, 2),
        requires_confirmation=result.requires_confirmation,
        reason=result.reason,
        overlapping_forests=_overlapping_forests_payload(result, existing),
        resolved_geometry=mapping(result.resolved) if result.resolved else None,
        original_geometry=request.geometry,
    )


@router.post("/forests/boundary/parse-file")
async def parse_boundary_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_active_user),
):
    """Parse an uploaded boundary file into a single boundary Feature.

    Runs the boundary through the same Feature-to-Polygon pipeline the
    workspace Layer Import uses (closed line rings, extent lines, and point
    clouds all become polygons), so GeoPackage — which a browser cannot decode
    because it is SQLite — imports exactly like the equivalent KML/SHP/GeoJSON.

    Returns a GeoJSON Feature (``{"type": "Feature", "geometry": ..., "properties": {}}``)
    with the boundary geometry in EPSG:4326. Any read/validation failure returns
    HTTP 400 with a bilingual ``boundary.file_parse_failed`` detail.
    """
    from app.services.file_processor import boundary_feature_from_upload

    try:
        return await boundary_feature_from_upload(file)
    except ValueError as e:
        raise i18n_error(400, "boundary.file_parse_failed", error=str(e))


# ============================================================================
# CONFIRM — Save resolved boundary with row-level locking
# ============================================================================


def _geom_bind(poly):
    """Convert a shapely geometry to a geoalchemy2 Geometry-column bound value.

    geoalchemy2's Geometry column binds a WKTElement/WKBElement (or string),
    not a shapely ``mapping`` dict.  ``from_shape`` yields a WKBElement that
    binds cleanly to the ``ST_GeomFromEWKT``-wrapped audit geometry columns.
    """
    from geoalchemy2.shape import from_shape

    if poly is None:
        return None
    return from_shape(poly, srid=4326)


@router.post(
    "/forests/boundary/confirm", response_model=ConfirmResponse, status_code=201
)
def confirm_boundary(
    request: ConfirmRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Save resolved boundary: creates Calculation + audit record."""
    poly = shape(request.resolved_geometry)
    if not poly.is_valid:
        from shapely.validation import make_valid

        poly = make_valid(poly)
    if poly.geom_type not in ("Polygon", "MultiPolygon"):
        raise i18n_error(400, "boundary.resolved_geometry_must_be_polygon")

    orig = shape(request.original_geometry)

    # Resolve the target calculation: an edit/reshape path carries an existing
    # calculation id (same forest, keep its uuid); a fresh creation has none and
    # a new Calculation is made. Ownership enforced for the edit case.
    calc = None
    if request.calculation_id:
        calc = (
            db.query(Calculation)
            .filter(Calculation.id == request.calculation_id)
            .first()
        )
    elif request.forest_id:
        calc = db.query(Calculation).filter(Calculation.id == request.forest_id).first()
    if calc is not None:
        if (
            calc.user_id != current_user.id
            and current_user.role != UserRole.SUPER_ADMIN.value
        ):
            raise i18n_error(403, "boundary.only_owner_can_edit")

    # Lock nearby forests (for the audit id list + row lock). The clip-only model
    # does NOT re-gate the posted geometry here — persist_boundary clips it
    # against these neighbours, so a hairline sliver from the preview's
    # reproject round-trip is trimmed rather than 409'd. Only a boundary that is
    # ENTIRELY inside existing land raises (BoundaryFullyInsideExisting below).
    existing = _get_nearby_forests(
        db, orig, exclude_id=calc.id if calc else None, radius_m=200, lock=True
    )

    # Create calculation
    if calc is None:
        calc = Calculation(
            user_id=current_user.id,
            forest_name=request.forest_name,
            boundary_status=BoundaryStatus.VALIDATED.value,
            boundary_status_changed_at=datetime.now(timezone.utc),
            boundary_status_changed_by=current_user.id,
            status="completed",
        )
        db.add(calc)
        db.flush()

    # Write geometry through the single boundary-write point (PB-3) — it clips
    # against neighbours again (idempotent here; a race that fully swallows the
    # boundary surfaces as 409).
    from app.services.boundary_write_service import (
        persist_boundary,
        BoundaryFullyInsideExisting,
    )
    from app.services.boundary_validation import BoundaryRulesViolation

    try:
        _w = persist_boundary(db, calc, poly, validate=True)
        poly = shape(_w["geometry"])
    except BoundaryFullyInsideExisting:
        raise i18n_error(409, "boundary.overlap_detected_relock")
    except BoundaryRulesViolation as bv:
        raise HTTPException(status_code=422, detail=bv.detail)

    # Compute area stats geodesically — bare shapely `.area` on 4326 lon/lat is
    # in square degrees, not m², so the old `.area / 10000` recorded audit areas
    # ~1e8x too small.
    _, orig_area = _geodesic_area_ha(orig)
    _, resolved_area = _geodesic_area_ha(poly)
    removed_ha = orig_area - resolved_area
    overlap_ids = [str(f.id) for f in existing]

    # Create audit record
    audit = ForestBoundaryAudit(
        forest_id=calc.id,
        submitted_geometry=_geom_bind(orig),
        submitted_area_ha=round(orig_area, 4),
        submitted_by_user_id=current_user.id,
        resolved_geometry=_geom_bind(poly),
        resolved_area_ha=round(resolved_area, 4),
        overlap_removed_ha=round(removed_ha, 4),
        overlap_with_forest_ids=overlap_ids if overlap_ids else None,
        resolution_method=f"auto_clip_{request.method.value}",
        user_confirmed=True,
        user_confirmed_at=datetime.now(timezone.utc),
    )
    db.add(audit)
    db.flush()
    audit_id = audit.id

    db.commit()

    return ConfirmResponse(
        id=calc.id,
        boundary_status=BoundaryStatus.VALIDATED,
        boundary_geom_updated_at=datetime.now(timezone.utc),
        audit_id=audit_id,
    )


# ============================================================================
# INCLUDE GAP — persist the proposed boundary extended by a chosen gap
# ============================================================================


def _geodesic_area_ha(poly) -> tuple:
    """Return (area_sqm, area_ha) computed geodesically for the given polygon."""
    try:
        from app.utils.geometry_utils import calculate_area_geodesic_from_shapely

        _sqm, _ha = calculate_area_geodesic_from_shapely(poly)
        return _sqm, _ha
    except Exception:  # pragma: no cover - defensive fallback
        logger.warning(
            "geodesic area failed - falling back to a planar approximation "
            "that overstates area", exc_info=True,
        )
        return poly.area, poly.area / SQM_PER_HA_F


@router.post("/forests/boundary/points-preview", response_model=PreviewResponse)
def points_preview(
    request: PointsPreviewRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Preview from an ordered list of {lat, lng} points."""
    if len(request.points) < 3:
        raise i18n_error(400, "boundary.at_least_3_points")

    coords = [(p["lng"], p["lat"]) for p in request.points]
    if coords[0] != coords[-1]:
        coords.append(coords[0])
    try:
        poly = Polygon(coords)
        if not poly.is_valid:
            from shapely.validation import make_valid

            poly = make_valid(poly)
    except Exception as e:
        raise i18n_error(400, "boundary.invalid_polygon", error=e)

    existing = _get_nearby_forests(db, poly, radius_m=200)
    result = resolve_overlap(mapping(poly), existing, ResolutionParams())

    return PreviewResponse(
        status=result.status,
        orig_area_ha=round(result.orig_area_ha, 4),
        resolved_area_ha=round(result.resolved_area_ha, 4),
        removed_ha=round(result.removed_ha, 4),
        removed_pct=round(result.removed_pct, 2),
        requires_confirmation=result.requires_confirmation,
        reason=result.reason,
        overlapping_forests=_overlapping_forests_payload(result, existing),
        resolved_geometry=mapping(result.resolved) if result.resolved else None,
        original_geometry=mapping(poly),
    )


# ============================================================================
# BOUNDARY STATUS MANAGEMENT
# ============================================================================


@router.patch(
    "/forests/{forest_id}/boundary-status", response_model=BoundaryStatusResponse
)
def update_boundary_status(
    forest_id: UUID,
    request: BoundaryStatusUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Change boundary status. SUPER_ADMIN only."""
    if current_user.role != UserRole.SUPER_ADMIN.value:
        raise i18n_error(403, "boundary.only_dfo_can_change_status")

    calc = db.query(Calculation).filter(Calculation.id == forest_id).first()
    if not calc:
        raise i18n_error(404, "boundary.forest_not_found")

    calc.boundary_status = request.status.value
    calc.boundary_status_changed_at = datetime.now(timezone.utc)
    calc.boundary_status_changed_by = current_user.id
    db.commit()

    return BoundaryStatusResponse(
        id=calc.id,
        boundary_status=request.status,
        boundary_status_changed_at=calc.boundary_status_changed_at,
        boundary_status_changed_by=calc.boundary_status_changed_by,
        boundary_geom_updated_at=calc.updated_at,
    )


# ============================================================================
# AUDIT HISTORY
# ============================================================================


@router.get("/forests/{forest_id}/boundary-audits", response_model=AuditListResponse)
def list_boundary_audits(
    forest_id: UUID,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Paginated audit history for a forest."""
    calc = db.query(Calculation).filter(Calculation.id == forest_id).first()
    if not calc:
        raise i18n_error(404, "boundary.forest_not_found")

    query = (
        db.query(ForestBoundaryAudit)
        .filter(ForestBoundaryAudit.forest_id == forest_id)
        .order_by(ForestBoundaryAudit.created_at.desc())
    )

    total = query.count()
    audits = query.offset(offset).limit(limit).all()

    return AuditListResponse(
        audits=[
            BoundaryAuditEntry(
                id=a.id,
                forest_id=a.forest_id,
                submitted_area_ha=a.submitted_area_ha,
                resolved_area_ha=a.resolved_area_ha,
                overlap_removed_ha=a.overlap_removed_ha,
                overlap_with_forest_ids=a.overlap_with_forest_ids,
                resolution_method=a.resolution_method,
                user_confirmed=a.user_confirmed,
                dispute_id=a.dispute_id,
                dfo_reason_np=a.dfo_reason_np,
                gap_included_ha=a.gap_included_ha,
                gap_forest_ids=a.gap_forest_ids,
                dispute_reason_type=a.dispute_reason_type,
                created_at=a.created_at,
            )
            for a in audits
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


# ============================================================================
# NEARBY FORESTS (200m visibility)
# ============================================================================


@router.get("/forests/{forest_id}/nearby")
def get_nearby_forests(
    forest_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Return forests within 200m of the given forest."""
    calc = db.query(Calculation).filter(Calculation.id == forest_id).first()
    if not calc or not calc.boundary_geom:
        raise i18n_error(404, "boundary.forest_or_boundary_not_found")

    from geoalchemy2.shape import to_shape as _to_shape

    proposed_shape = _to_shape(calc.boundary_geom)
    nearby = (
        db.query(Calculation)
        .filter(
            Calculation.id != forest_id,
            Calculation.boundary_geom.isnot(None),
            func.ST_DWithin(
                Calculation.boundary_geom.cast(Geography),
                # calc.boundary_geom is a loaded WKBElement (no .cast()); rebuild
                # the comparison geometry from its WKT.
                func.ST_GeomFromText(proposed_shape.wkt, 4326).cast(Geography),
                200.0,
            ),
        )
        .all()
    )
    rel_by_id = {
        str(r.id): r
        for r in detect_relations(mapping(proposed_shape), nearby, GapParams())
    }

    results = []
    for n in nearby:
        geom = db.scalar(func.ST_AsGeoJSON(n.boundary_geom))
        rel = rel_by_id.get(str(n.id))
        # Geodesic (UTM) area — bare `.area` on a 4326 geometry is square degrees.
        n_area_ha = 0.0
        if n.boundary_geom is not None:
            try:
                n_area_ha = round(_geodesic_area_ha(_to_shape(n.boundary_geom))[1], 4)
            except Exception:  # noqa: BLE001 -- area is display-only; 0 on failure
                logger.warning("nearby: area calc failed for forest %s", n.id)
        results.append(
            {
                "id": str(n.id),
                "name": n.forest_name or "",
                "boundary_status": n.boundary_status or "draft",
                "geometry": json.loads(geom) if geom else None,
                "area_ha": n_area_ha,
                "overlap_ha": round(rel.overlap_ha, 4) if rel else 0,
                "gap_ha": round(rel.gap_ha, 4) if rel else 0,
                "gap_shape": rel.gap_shape if rel else "none",
                "gap_size": rel.gap_size if rel else "none",
                "adjacent": bool(rel.adjacent) if rel else False,
            }
        )

    return {"forests": results, "count": len(results)}


# ============================================================================
# DISPUTE FILING
# ============================================================================


@router.post("/forests/boundary/dispute", response_model=DisputeResponse)
def file_dispute(
    request: DisputeFileRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """File a boundary dispute against a validated forest.

    ``dispute_reason_type`` is ``overlap`` (default, legacy) or ``gap``.

      - overlap: the filer's own forest overlaps the target; BOTH are set to
        disputed (existing behaviour, unchanged).
      - gap:     the filer's forest sits just outside the target with an
        unclaimed band between them; only the TARGET is flagged -- the filer is
        not claiming the target's land, merely the gap strip -- and the disputed
        band geometry is stored for the DFO to review.
    """
    target = db.query(Calculation).filter(Calculation.id == request.forest_id).first()
    if not target:
        raise i18n_error(404, "boundary.forest_not_found")
    if target.boundary_status != BoundaryStatus.VALIDATED.value:
        raise i18n_error(400, "boundary.only_validated_can_be_disputed")

    reason_type = request.dispute_reason_type or "overlap"
    if reason_type not in ("overlap", "gap"):
        raise i18n_error(400, "boundary.invalid_dispute_reason_type")

    # The filer's own forest is the one the current user owns that either
    # overlaps the target (legacy) or lies adjacent with a gap to it.
    own = (
        db.query(Calculation)
        .filter(
            Calculation.user_id == current_user.id,
            Calculation.boundary_geom.isnot(None),
        )
        .all()
    )

    from geoalchemy2.shape import to_shape as _to_shape

    target_shape = _to_shape(target.boundary_geom) if target.boundary_geom else None
    gap_geometry_val = None

    filer_forest = None
    if reason_type == "gap":
        best = None
        best_gap_ha = Decimal("0")
        for f in own:
            f_shape = _to_shape(f.boundary_geom) if f.boundary_geom else None
            if f_shape is None:
                continue
            rel = detect_relations(
                mapping(f_shape),
                [target],
                GapParams(),
            )
            r = next((x for x in rel if x.id == str(target.id)), None)
            if r is not None and r.gap_ha > best_gap_ha:
                best = f
                best_gap_ha = r.gap_ha
                gap_geometry_val = r.gap_polygon
        filer_forest = best
    else:
        # Legacy overlap trigger: filer's forest must ST_Intersects the target.
        filer_forest = next(
            (
                f
                for f in own
                if f.id != target.id
                and _to_shape(f.boundary_geom).intersects(target_shape)
            ),
            None,
        )

    if not filer_forest:
        if reason_type == "gap":
            raise i18n_error(400, "boundary.no_gap_forest_found")
        raise i18n_error(400, "boundary.no_overlapping_forest_found")

    old_status_1 = target.boundary_status
    old_status_2 = filer_forest.boundary_status
    # A pure-gap dispute only flags the target; the filer is NOT claiming the
    # other's land, so their own boundary stays untouched.
    target.boundary_status = BoundaryStatus.DISPUTED.value
    target.boundary_status_changed_at = datetime.now(timezone.utc)
    target.boundary_status_changed_by = current_user.id
    if reason_type == "overlap":
        filer_forest.boundary_status = BoundaryStatus.DISPUTED.value
        filer_forest.boundary_status_changed_at = datetime.now(timezone.utc)
        filer_forest.boundary_status_changed_by = current_user.id

    # Compute overlap geometry (legacy path only)
    t_geom = db.scalar(func.ST_AsBinary(target.boundary_geom))
    f_geom = db.scalar(func.ST_AsBinary(filer_forest.boundary_geom))
    overlap_shape = None
    if t_geom and f_geom:
        from shapely import wkb

        t_shape = wkb.loads(bytes(t_geom))
        f_shape = wkb.loads(bytes(f_geom))
        overlap_shape = (
            t_shape.intersection(f_shape)
            if not (t_shape is None or f_shape is None)
            else None
        )

    dispute = BoundaryDispute(
        filed_by_user_id=current_user.id,
        forest_id_1=target.id,
        forest_id_2=filer_forest.id,
        dispute_reason_np=request.reason_np,
        forest_1_boundary=target.boundary_geom,
        forest_2_proposed=filer_forest.boundary_geom,
        overlap_area=(
            func.ST_GeomFromText(overlap_shape.wkt, 4326)
            if overlap_shape and not overlap_shape.is_empty
            else None
        ),
        gap_geometry=(
            func.ST_GeomFromText(gap_geometry_val.wkt, 4326)
            if gap_geometry_val and not gap_geometry_val.is_empty
            else None
        ),
        dispute_reason_type=reason_type,
        status=DisputeStatus.OPEN,
    )
    db.add(dispute)
    db.flush()

    # Create audit records
    audited = [(target, old_status_1)]
    if reason_type == "overlap":
        audited.append((filer_forest, old_status_2))
    for f, old_status in audited:
        audit = ForestBoundaryAudit(
            forest_id=f.id,
            submitted_by_user_id=current_user.id,
            resolution_method="dispute_filed",
            dispute_id=dispute.id,
            dispute_reason_type=reason_type,
        )
        db.add(audit)

    db.commit()
    return DisputeResponse(dispute_id=dispute.id, status=dispute.status.value)


# ============================================================================
# ADMIN — List disputes
# ============================================================================


@router.get("/admin/boundary-disputes")
def list_disputes(
    status_filter: Optional[str] = Query(None, alias="status"),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """List boundary disputes. SUPER_ADMIN only."""
    if current_user.role != UserRole.SUPER_ADMIN.value:
        raise i18n_error(403, "boundary.only_dfo_access")

    query = db.query(BoundaryDispute).order_by(BoundaryDispute.created_at.desc())
    if status_filter:
        query = query.filter(BoundaryDispute.status == status_filter)

    disputes = query.all()
    return [
        {
            "id": d.id,
            "forest_id_1": str(d.forest_id_1),
            "forest_id_2": str(d.forest_id_2),
            "status": d.status.value if hasattr(d.status, "value") else d.status,
            "created_at": d.created_at,
        }
        for d in disputes
    ]


# ============================================================================
# ADMIN — Get dispute detail
# ============================================================================


@router.get("/admin/boundary-disputes/{dispute_id}", response_model=DisputeDetail)
def get_dispute_detail(
    dispute_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Get full dispute detail with geometries. SUPER_ADMIN only."""
    if current_user.role != UserRole.SUPER_ADMIN.value:
        raise i18n_error(403, "boundary.only_dfo_access")

    dispute = db.query(BoundaryDispute).filter(BoundaryDispute.id == dispute_id).first()
    if not dispute:
        raise i18n_error(404, "boundary.dispute_not_found")

    def _geom_to_geojson(geom_col):
        if geom_col is None:
            return None
        raw = db.scalar(func.ST_AsGeoJSON(geom_col))
        return json.loads(raw) if raw else None

    return DisputeDetail(
        id=dispute.id,
        forest_id_1=dispute.forest_id_1,
        forest_id_2=dispute.forest_id_2,
        dispute_reason_np=dispute.dispute_reason_np,
        status=(
            dispute.status.value if hasattr(dispute.status, "value") else dispute.status
        ),
        forest_1_boundary=_geom_to_geojson(dispute.forest_1_boundary),
        forest_2_proposed=_geom_to_geojson(dispute.forest_2_proposed),
        forest_2_clipped=_geom_to_geojson(dispute.forest_2_clipped),
        overlap_area=_geom_to_geojson(dispute.overlap_area),
        gap_geometry=_geom_to_geojson(dispute.gap_geometry),
        dispute_reason_type=dispute.dispute_reason_type or "overlap",
        created_at=dispute.created_at,
        updated_at=dispute.updated_at,
        assigned_to_dfo_id=dispute.assigned_to_dfo_id,
        resolution_type=dispute.resolution_type,
        resolution_notes_np=dispute.resolution_notes_np,
    )


# ============================================================================
# ADMIN — Resolve dispute
# ============================================================================


@router.post(
    "/admin/boundary-disputes/{dispute_id}/resolve",
    response_model=DisputeResolveResponse,
)
def resolve_dispute(
    dispute_id: int,
    request: DisputeResolveRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """DFO resolves dispute: edits one forest, sets both to approved."""
    if current_user.role != UserRole.SUPER_ADMIN.value:
        raise i18n_error(403, "boundary.only_dfo_access")

    dispute = db.query(BoundaryDispute).filter(BoundaryDispute.id == dispute_id).first()
    if not dispute:
        raise i18n_error(404, "boundary.dispute_not_found")
    if dispute.status in (DisputeStatus.RESOLVED, DisputeStatus.DISMISSED):
        raise i18n_error(400, "boundary.dispute_already_resolved")

    target = db.query(Calculation).filter(Calculation.id == request.forest_id).first()
    if not target:
        raise i18n_error(404, "boundary.forest_not_found")

    other_id = (
        dispute.forest_id_1 if dispute.forest_id_2 == target.id else dispute.forest_id_2
    )
    other = db.query(Calculation).filter(Calculation.id == other_id).first()

    # Update target boundary
    poly = shape(request.new_boundary)
    if not poly.is_valid:
        from shapely.validation import make_valid

        poly = make_valid(poly)

    db.execute(
        text(
            "UPDATE public.calculations SET boundary_geom = ST_GeomFromText(:wkt, 4326) WHERE id = :id"
        ),
        {"wkt": poly.wkt, "id": str(target.id)},
    )
    # The boundary was just replaced: sub-areas must still lie inside it.
    from app.services.sub_area_reclip_service import reclip_after_boundary_write

    reclip_after_boundary_write(db, target, poly)

    # Set both to approved
    target.boundary_status = BoundaryStatus.APPROVED.value
    target.boundary_status_changed_at = datetime.now(timezone.utc)
    target.boundary_status_changed_by = current_user.id
    if other:
        other.boundary_status = BoundaryStatus.APPROVED.value
        other.boundary_status_changed_at = datetime.now(timezone.utc)
        other.boundary_status_changed_by = current_user.id

    # Update dispute
    dispute.status = DisputeStatus.RESOLVED
    dispute.resolved_by_user_id = current_user.id
    dispute.resolution_type = request.resolution_type
    dispute.resolution_notes_np = request.reason_np
    dispute.resolved_at = datetime.now(timezone.utc)

    # Create audit records
    for f in [target, other]:
        if f:
            audit = ForestBoundaryAudit(
                forest_id=f.id,
                submitted_by_user_id=current_user.id,
                resolved_geometry=_geom_bind(poly) if f.id == target.id else None,
                resolution_method="dfo_resolve",
                dispute_id=dispute.id,
                dfo_user_id=current_user.id,
                dfo_reason_np=request.reason_np,
            )
            db.add(audit)

    db.commit()
    return DisputeResolveResponse(
        dispute_id=dispute.id,
        status=DisputeStatus.RESOLVED.value,
        forest_1_status=BoundaryStatus.APPROVED,
        forest_2_status=BoundaryStatus.APPROVED,
    )


# ============================================================================
# Helpers
# ============================================================================

import json

from geoalchemy2 import Geography


def _get_nearby_forests(
    db: Session,
    geom_shape,
    exclude_id: Optional[UUID] = None,
    radius_m: float = 200,
    lock: bool = False,
) -> list:
    """Query forests within `radius_m` of `geom_shape` using ST_DWithin."""
    wkt = geom_shape.wkt
    query = db.query(Calculation).filter(
        Calculation.boundary_geom.isnot(None),
        func.ST_DWithin(
            Calculation.boundary_geom.cast(Geography),
            func.ST_GeomFromText(wkt, 4326).cast(Geography),
            radius_m,
        ),
    )
    if exclude_id:
        query = query.filter(Calculation.id != exclude_id)

    if lock:
        query = query.with_for_update()

    return query.all()
