"""
Workspace import endpoints — layer CRUD for the MapWorkspace TOC.
"""

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
    UploadFile,
    File,
    Form,
    Request,
)
from sqlalchemy.orm import Session
from sqlalchemy import func
from sqlalchemy.orm.attributes import flag_modified
from typing import Any, Dict, Optional, List
from uuid import UUID
import logging
import json
import datetime as _dt

from ..core.database import get_db
from ..core.idempotent_route import IdempotentRoute
from ..core.config import settings
from ..core.feature_flags import feature_flags
from ..core.exceptions import i18n_error, resolve_service_detail
from ..core.naming_strategies import compartment_serial
from ..models.user import User, UserRole
from ..models.calculation import Calculation
from ..services.forest_units.model import (
    DEPTH_SUB,
    DEPTH_TOP_BLOCK,
    DEPTH_TOP_COMPARTMENT,
)
from ..models.workspace_layer import (
    DRAFT_STATUS_DISCARDED,
    WorkspaceLayer,
    DRAFT_STATUS_ACTIVE,
    DRAFT_STATUS_SYNCING,
    DRAFT_STATUS_FINALIZED,
    DRAFT_STATUS_VALIDATION_FAILED,
)
from ..utils.auth import get_current_active_user
from ..utils.db import atomic_transaction
from pydantic import BaseModel
import copy

from ..middleware.rate_limit import (
    import_limiter,
    digitize_limiter,
    digitize_bulk_limiter,
)
from ..services.workspace_cache import (
    cache_layers_list,
    get_cached_layers,
    invalidate_layers_cache,
)
from shapely.geometry import (
    mapping as shapely_mapping,
    Point,
    LineString,
    Polygon,
    MultiPolygon,
)
from ..utils.geometry_utils import (
    calculate_area_geodesic_from_shapely,
    compute_geometry_properties,
    strip_geo_fields,
)
from ..services.file_processor import (
    process_uploaded_file,
    validate_feature_count,
    validate_vertex_count,
    validate_area_limit,
    validate_first_layer,
    validate_layer_distance,
    extract_gpx_metadata,
    process_geometry_list,
    feature_to_polygon,
    PolygonizeConfig,
)
from ..core.constants import (
    IMPORT_PURPOSE_SUB_AREAS,
    IMPORT_PURPOSE_POLYGON_AUTO_BUFFER,
    IMPORT_PURPOSE_BLOCKS,
    IMPORT_PURPOSE_BOUNDARY,
    IMPORT_PURPOSE_USER_GROUP_BOUNDARY,
)
from ..services.geometry_sanitizer import (
    sanitize_geometry,
    GeometrySanitizationError,
)
from ..schemas.digitize import (
    DigitizeLayerCreate,
    FeatureBulkRequest,
    FinalizeRequest,
)
from ..services.digitize_audit_service import (
    record_digitize_audit,
    list_digitize_audit,
    geometry_hash_of,
)
from ..services.digitize_metrics_service import (
    increment_finalize_result,
    observe_finalize_duration,
    finalize_duration_timer,
    increment_draft_create,
)
from shapely.geometry import shape as shapely_shape

logger = logging.getLogger(__name__)

router = APIRouter(route_class=IdempotentRoute)


def _unit_code(target_type: str, n: int) -> str:
    """compartment_code for an imported unit: C<N> for a compartment, SC<N> for a
    sub-compartment (the CompartmentNamingStrategy formats) - not `compartment-N`."""
    return (
        f"SC{n}"
        if target_type in ("sub_compartments", "sub_compartment")
        else compartment_serial(n)
    )


def _require_calculation_access(
    db: Session, calculation_id: UUID, current_user: User
) -> Calculation:
    """Ownership gate — workspace layers are scoped to a calculation.

    Mirrors the access-control pattern used across blocks.py / forests.py /
    geometry.py: only the calculation owner (or SUPER_ADMIN) may read or
    modify a calculation's imported layers.
    """
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calculation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Calculation not found"
        )
    if (
        calculation.user_id != current_user.id
        and current_user.role != UserRole.SUPER_ADMIN
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this calculation",
        )
    return calculation


CRS_OPTIONS = [
    {"epsg": 4326, "label": "WGS 84 (Lat/Lon)", "labelNp": "डब्लुजीएस ८४"},
    {"epsg": 32644, "label": "UTM Zone 44N", "labelNp": "युटिएम जोन ४४ उत्तर"},
    {"epsg": 32645, "label": "UTM Zone 45N", "labelNp": "युटिएम जोन ४५ उत्तर"},
]


# ---------------------------------------------------------------------------
# On-screen digitizing (GD Phase 1.2)
# ---------------------------------------------------------------------------


def _require_digitize_enabled() -> None:
    """Feature-flag gate (Gap 12.1): 404 when digitizing is disabled."""
    if not feature_flags.is_enabled("digitize_v1"):
        raise HTTPException(
            status_code=404, detail="On-screen digitizing is not enabled"
        )


def _get_digitize_layer(
    db: Session, calculation_id: UUID, layer_id: int
) -> WorkspaceLayer:
    """Fetch a non-deleted digitize layer scoped to a calculation."""
    layer = (
        db.query(WorkspaceLayer)
        .filter(
            WorkspaceLayer.id == layer_id,
            WorkspaceLayer.calculation_id == calculation_id,
            WorkspaceLayer.deleted_at.is_(None),
        )
        .first()
    )
    if not layer:
        raise HTTPException(status_code=404, detail="Layer not found")
    return layer


def _calc_bbox(db: Session, calculation: Calculation) -> Optional[list]:
    """Return [min_lon, min_lat, max_lon, max_lat] for the calculation boundary,
    or None when the boundary is not set (bounds check is skipped in that case —
    the authoritative 10 km ST_DWithin validator runs at finalize)."""
    if not calculation or not calculation.boundary_geom:
        return None
    try:
        bounds = calculation.boundary_geom.bounds  # shapely (minx, miny, maxx, maxy)
        return list(bounds)
    except Exception:
        logger.warning(
            "boundary bounds unavailable for calculation %s - the map will open "
            "at the default extent instead of the forest",
            calculation.id,
            exc_info=True,
        )
        return None


def _feature_count_of(layer: WorkspaceLayer) -> int:
    if not layer.layer_data or not isinstance(layer.layer_data, dict):
        return 0
    return len(layer.layer_data.get("features", []))


def _server_assign_feature_id(feature: dict, idx: int) -> str:
    """Server-assigned stable featureId (Gap 1.4). Never trust client IDs."""
    import uuid

    fid = f"digitize-{uuid.uuid4().hex[:12]}"
    props = dict(feature.get("properties") or {})
    props["featureId"] = fid
    feature["properties"] = props
    return fid


def _inject_provenance(feature: dict, user_id, client_version: str = "1.0") -> dict:
    """Server-injected _provenance (Gap 1.3). Client-supplied _provenance is stripped."""
    props = {
        k: v for k, v in (feature.get("properties") or {}).items() if k != "_provenance"
    }
    props["_provenance"] = {
        "source": "digitize",
        "created_at": func.now().__str__(),
        "created_by": str(user_id),
        "client_version": client_version,
    }
    feature["properties"] = props
    return feature


@router.post("/workspace/{calculation_id}/digitize-layers")
def create_digitize_layer(
    calculation_id: UUID,
    body: DigitizeLayerCreate,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Create a new draft digitize-layer (Gap 1.1: draft_status=ACTIVE).

    Purpose-validated, ownership-checked, duplicate-guarded, rate-limited and
    feature-flagged. The draft is a plain WorkspaceLayer (is_draft=True) so the
    existing imported-layer rendering/persistence path is reused unchanged.
    """
    _require_digitize_enabled()
    digitize_limiter.check(current_user.id)
    _require_calculation_access(db, calculation_id, current_user)

    purpose = body.purpose.strip()
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="Layer name cannot be empty")
    if len(name) > 255:
        raise HTTPException(status_code=422, detail="Layer name exceeds 255 characters")

    # Purpose validation (SSOT: constants.py)
    from ..core.constants import IMPORT_PURPOSE_ALL, IMPORT_PURPOSE_SUB_AREAS

    if purpose not in IMPORT_PURPOSE_ALL:
        raise HTTPException(status_code=400, detail=f"Unknown purpose: {purpose}")

    # Blocks-first rule (same as import)
    try:
        validate_first_layer(db, calculation_id, purpose)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Duplicate draft guard: one draft per purpose per calculation (409)
    existing = (
        db.query(WorkspaceLayer)
        .filter(
            WorkspaceLayer.calculation_id == calculation_id,
            WorkspaceLayer.purpose == purpose,
            WorkspaceLayer.deleted_at.is_(None),
            WorkspaceLayer.draft_status.in_(
                [
                    DRAFT_STATUS_ACTIVE,
                    DRAFT_STATUS_SYNCING,
                    DRAFT_STATUS_VALIDATION_FAILED,
                ]
            ),
        )
        .first()
    )
    if existing:
        raise i18n_error(
            409,
            "imports.duplicate_draft",
            purpose=purpose,
        )

    from ..services.purpose_geometry_rules import allowed_geometry_types

    allowed = allowed_geometry_types(purpose)
    geometry_types = sorted(allowed)

    layer = WorkspaceLayer(
        calculation_id=calculation_id,
        name=name,
        purpose=purpose,
        source_format="digitize",
        feature_count=0,
        geometry_types=geometry_types,
        layer_data={"type": "FeatureCollection", "features": []},
        layer_metadata={"crs": "EPSG:4326", "source": "digitize"},
        is_draft=True,
        draft_status=DRAFT_STATUS_ACTIVE,
        created_by=current_user.id,
    )

    with atomic_transaction(db, f"digitize_create {purpose}"):
        db.add(layer)
        db.flush()
        record_digitize_audit(
            db,
            calculation_id=calculation_id,
            layer_id=layer.id,
            user_id=current_user.id,
            action="create_draft",
            feature_count_delta=0,
        )
        db.flush()

    invalidate_layers_cache(calculation_id)

    logger.info(
        "digitize_action",
        extra={
            "calculation_id": str(calculation_id),
            "layer_id": layer.id,
            "user_id": str(current_user.id),
            "action": "create_draft",
            "purpose": purpose,
            "feature_count": 0,
            "geometry_types": geometry_types,
            "ip_address": request.client.host if request.client else None,
        },
    )
    increment_draft_create(purpose)

    return {
        "id": layer.id,
        "name": layer.name,
        "purpose": layer.purpose,
        "draft_status": DRAFT_STATUS_ACTIVE,
        "feature_count": 0,
        "geometry_types": geometry_types,
        "is_draft": True,
    }


@router.post("/workspace/{calculation_id}/digitize-layers/{layer_id}/features/bulk")
def bulk_digitize_features(
    calculation_id: UUID,
    layer_id: int,
    body: FeatureBulkRequest,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Bulk upsert/delete features on a digitize layer (Gaps 2.1, 1.4, 2.2, 6.2).

    - Max 50 features per request (chunks of 25 on the client).
    - Server assigns final featureIds; response maps clientTempId → featureId.
    - Idempotency-Key header dedups retried flushes (`IdempotentRoute`, H2.17).
    - Each geometry is sanitized (vertex cap / bounds / precision) before store.
    - Digitized features must stay within the draft's draft_status=ACTIVE/SYNCING.
    """
    _require_digitize_enabled()
    digitize_bulk_limiter.check(current_user.id)
    calc = _require_calculation_access(db, calculation_id, current_user)
    layer = _get_digitize_layer(db, calculation_id, layer_id)

    # GD 2.4 (review #4): mode='append' targets existing non-draft layers;
    # draft mode (default) keeps the ACTIVE/SYNCING guard. Both share the
    # bulk write path (server-assigned featureIds, idempotency, sanitization).
    append_mode = body.mode == "append"
    if append_mode:
        if layer.draft_status == DRAFT_STATUS_DISCARDED:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot append to a discarded layer",
            )
        # Non-admin append rules: edits require the map lifecycle to permit them.
        if calc.map_lifecycle_status in ("locked", "calculating", "failed"):
            raise HTTPException(
                status_code=423,
                detail={
                    "error": "map_locked",
                    "message": "Map is locked or a calculation is in progress — no edits permitted",
                    "code": "map.locked.append",
                },
                headers={"X-Locked-Reason": calc.map_lifecycle_status},
            )
    elif layer.draft_status not in (DRAFT_STATUS_ACTIVE, DRAFT_STATUS_SYNCING):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot modify a layer in state '{layer.draft_status}' — "
            f"finalized/discarded layers are read-only",
        )

    # Idempotency is applied by the router's `IdempotentRoute` class, not
    # here (H2.17). It used to be two hand-written call sites, which is why
    # the other 84 mobile-facing writes had none.

    calc_bbox = _calc_bbox(db, calc)

    new_data = copy.deepcopy(
        layer.layer_data or {"type": "FeatureCollection", "features": []}
    )
    features = new_data.get("features", [])
    mapping: dict = {}
    upsert_count = 0
    delete_count = 0

    for payload in body.features:
        if payload.operation == "delete":
            # clientTempId doubles as the featureId to delete for delete ops
            target_fid = payload.clientTempId
            before = len(features)
            features = [
                f
                for f in features
                if f.get("properties", {}).get("featureId") != target_fid
            ]
            if len(features) != before:
                delete_count += 1
            mapping[payload.clientTempId] = target_fid
            continue

        # Upsert
        feature = dict(payload.feature) if payload.feature else None
        if not feature:
            raise HTTPException(status_code=400, detail="Upsert requires a feature")
        geom = feature.get("geometry")
        if not geom:
            raise HTTPException(status_code=400, detail="Feature has no geometry")

        # Gap 6.2: sanitize BEFORE anything else (vertex cap / bounds / precision)
        try:
            geom = sanitize_geometry(geom, calc_bbox)
        except GeometrySanitizationError as e:
            raise HTTPException(status_code=400, detail=str(e))
        feature["geometry"] = geom

        # Allowed geometry per purpose (SSOT)
        from ..services.purpose_geometry_rules import allowed_geometry_types

        allowed = allowed_geometry_types(layer.purpose)
        gtype = geom.get("type")
        base = gtype
        if gtype and gtype.startswith("Multi"):
            base = gtype[len("Multi") :]
        if base not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"Geometry type '{gtype}' not allowed for purpose '{layer.purpose}'",
            )

        # Strip geo_* + tamper-proof properties, recompute geo_* from geometry
        try:
            shp = shapely_shape(geom)
            clean = strip_geo_fields(dict(feature.get("properties") or {}))
            clean.update(compute_geometry_properties(shp))
        except Exception:
            logger.warning(
                "geometry properties unavailable for a feature - area and "
                "perimeter will be missing from it",
                exc_info=True,
            )
            clean = strip_geo_fields(dict(feature.get("properties") or {}))

        feature["properties"] = clean

        # Server-assigned featureId (Gap 1.4)
        fid = _server_assign_feature_id(feature, len(features))
        # Provenance (Gap 1.3)
        feature = _inject_provenance(feature, current_user.id)

        features.append(feature)
        mapping[payload.clientTempId] = fid
        upsert_count += 1

    new_data["features"] = features
    layer.layer_data = new_data
    layer.feature_count = len(features)
    layer.updated_at = func.now()

    invalidate_layers_cache(calculation_id)

    with atomic_transaction(db, f"digitize_bulk {layer_id}"):
        record_digitize_audit(
            db,
            calculation_id=calculation_id,
            layer_id=layer_id,
            user_id=current_user.id,
            action="append_feature" if append_mode else "add_feature",
            feature_count_delta=upsert_count - delete_count,
            geometry_hash=geometry_hash_of(
                [dict(p.feature) for p in body.features if p.operation != "delete"]
            ),
        )
        db.flush()

    result = {
        "mapping": mapping,
        "feature_count": len(features),
        "upserted": upsert_count,
        "deleted": delete_count,
    }
    logger.info(
        "digitize_action",
        extra={
            "calculation_id": str(calculation_id),
            "layer_id": layer_id,
            "user_id": str(current_user.id),
            "action": "add_feature",
            "feature_count": len(features),
            "geometry_types": sorted(
                {f.get("geometry", {}).get("type") for f in features}
            ),
            "upserted": upsert_count,
            "deleted": delete_count,
        },
    )

    return result


@router.post("/workspace/{calculation_id}/digitize-layers/{layer_id}/finalize")
async def finalize_digitize_layer(
    calculation_id: UUID,
    layer_id: int,
    body: FinalizeRequest,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Finalize a digitize draft (Gap 2.4: async 202 + polling; sync fallback).

    Enqueues the arq job `finalize_digitize_layer` and returns 202. The job runs
    the full import validation chain (process_geometry_list + validators), then
    flips draft_status → FINALIZED or VALIDATION_FAILED (with last_validation_error).
    For tiny layers (<10 features) when the worker is unavailable, runs sync and
    returns 200 directly. Idempotency-Key dedups repeated calls.
    """
    _require_digitize_enabled()
    digitize_limiter.check(current_user.id)
    _require_calculation_access(db, calculation_id, current_user)
    layer = _get_digitize_layer(db, calculation_id, layer_id)

    if layer.draft_status != DRAFT_STATUS_ACTIVE:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot finalize a layer in state '{layer.draft_status}'",
        )

    feature_count = _feature_count_of(layer)
    if feature_count == 0:
        raise HTTPException(status_code=400, detail="Layer has no features to finalize")

    # Try arq worker; fall back to sync for small layers.
    try:
        from arq import create_pool
        from arq.connections import RedisSettings
        from ..core.redis_config import redis_dsn

        # Mark SYNCING so the worker + poll endpoint observe the transition
        layer.draft_status = DRAFT_STATUS_SYNCING
        layer.updated_at = func.now()
        with atomic_transaction(db, f"digitize_finalize_enqueue {layer_id}"):
            db.flush()

        pool = await create_pool(RedisSettings.from_dsn(redis_dsn()))
        task_id = await pool.enqueue_job(
            "finalize_digitize_layer",
            str(calculation_id),
            layer_id,
            str(current_user.id),
            _queue_name="arq:calculation",
        )
        await pool.close()
        logger.info(
            "digitize_action",
            extra={
                "calculation_id": str(calculation_id),
                "layer_id": layer_id,
                "user_id": str(current_user.id),
                "action": "finalize_initiated",
                "task_id": str(task_id),
                "async": True,
            },
        )
        increment_finalize_result("queued")
        return {"task_id": str(task_id), "status": "queued", "poll_interval_s": 2}
    except Exception as e:  # noqa: BLE001 — worker down → sync fallback
        logger.warning("[digitize] arq enqueue failed (%s) — sync finalize fallback", e)
        # Restore ACTIVE so the caller can retry / the sync path can run
        layer.draft_status = DRAFT_STATUS_ACTIVE
        layer.updated_at = func.now()
        db.commit()
        if feature_count >= 10:
            raise HTTPException(
                status_code=503,
                detail="Background finalize unavailable; layer too large for sync path",
            )

    # Sync fallback for small layers (<10 features)
    with finalize_duration_timer():
        try:
            _run_digitize_finalize(db, layer, current_user)
            increment_finalize_result("succeeded")
            result = {
                "task_id": None,
                "status": "succeeded",
                "poll_interval_s": 0,
                "feature_count": layer.feature_count,
                "geometry_types": layer.geometry_types,
                "draft_status": DRAFT_STATUS_FINALIZED,
            }
        except ValueError as e:
            layer.draft_status = DRAFT_STATUS_VALIDATION_FAILED
            layer.last_validation_error = {"message": str(e), "rule": "finalize"}
            db.commit()
            increment_finalize_result("validation_failed")
            logger.warning(
                "digitize_validation_failed",
                extra={
                    "calculation_id": str(calculation_id),
                    "layer_id": layer_id,
                    "user_id": str(current_user.id),
                    "rule": "finalize",
                    "error_message": str(e),
                    "feature_count": layer.feature_count,
                },
            )
            result = {
                "task_id": None,
                "status": "validation_failed",
                "poll_interval_s": 0,
                "last_validation_error": layer.last_validation_error,
                "draft_status": DRAFT_STATUS_VALIDATION_FAILED,
            }
    return result


def _run_digitize_finalize(
    db: Session, layer: WorkspaceLayer, current_user: User
) -> None:
    """Run the full import validation chain on a digitize layer and finalize it.

    Shared by the arq job (worker) and the sync fallback. Raises ValueError on
    validation failure (caller persists draft_status=VALIDATION_FAILED).
    """
    if not layer.layer_data or not isinstance(layer.layer_data, dict):
        raise ValueError("Layer has no feature data")
    features = layer.layer_data.get("features", [])
    if not features:
        raise ValueError("No features to finalize")

    # Convert features → shapely geometries + attributes
    geometries = []
    attributes = []
    for f in features:
        geom = f.get("geometry")
        if not geom:
            continue
        try:
            geometries.append(shapely_shape(geom))
        except Exception as e:
            raise ValueError(f"Invalid geometry: {e}")
        attributes.append(dict(f.get("properties") or {}))

    if not geometries:
        raise ValueError("No valid geometries found")

    # Validation chain (mirrors import endpoint workspace.py:138-145)
    validate_feature_count(geometries)
    validate_vertex_count(geometries)
    validate_area_limit(geometries)
    validate_first_layer(db, layer.calculation_id, layer.purpose)
    validate_layer_distance(db, layer.calculation_id, geometries)

    # Purpose geometry conversion (polygonise/auto-buffer) — SSOT file_processor
    processed_geom, metadata = process_geometry_list(
        geometries, attributes, purpose=layer.purpose
    )

    # Rebuild layer_data with processed geometry + geo_* + stable featureIds
    from shapely.geometry import mapping as _shapely_mapping

    new_features = []
    single = [processed_geom]
    for i, g in enumerate(single):
        clean = strip_geo_fields(dict(attributes[i] if i < len(attributes) else {}))
        clean.update(compute_geometry_properties(g))
        clean["featureId"] = f"finalized-{layer.id}-{i}"
        new_features.append(
            {
                "type": "Feature",
                "geometry": _shapely_mapping(g),
                "properties": clean,
            }
        )

    new_data = {"type": "FeatureCollection", "features": new_features}
    layer.layer_data = new_data
    layer.feature_count = len(new_features)
    layer.geometry_types = list(set(g.geom_type for g in [processed_geom]))
    layer.is_draft = False
    layer.draft_status = DRAFT_STATUS_FINALIZED
    layer.last_validation_error = None
    layer.updated_at = func.now()

    invalidate_layers_cache(layer.calculation_id)

    with atomic_transaction(db, f"digitize_finalize {layer.id}"):
        record_digitize_audit(
            db,
            calculation_id=layer.calculation_id,
            layer_id=layer.id,
            user_id=current_user.id if current_user else None,
            action="finalize",
            feature_count_delta=len(new_features),
            geometry_hash=geometry_hash_of(new_features),
        )
        db.flush()


@router.get("/workspace/{calculation_id}/digitize-layers/{layer_id}/finalize-status")
def digitize_finalize_status(
    calculation_id: UUID,
    layer_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Poll finalize status (Gap 2.4). The layer's draft_status IS the state."""
    _require_digitize_enabled()
    _require_calculation_access(db, calculation_id, current_user)
    layer = _get_digitize_layer(db, calculation_id, layer_id)

    if layer.draft_status == DRAFT_STATUS_FINALIZED:
        return {
            "status": "succeeded",
            "feature_count": layer.feature_count,
            "geometry_types": layer.geometry_types,
            "draft_status": DRAFT_STATUS_FINALIZED,
        }
    if layer.draft_status == DRAFT_STATUS_VALIDATION_FAILED:
        return {
            "status": "validation_failed",
            "last_validation_error": layer.last_validation_error,
            "draft_status": DRAFT_STATUS_VALIDATION_FAILED,
        }
    if layer.draft_status == DRAFT_STATUS_SYNCING:
        return {"status": "processing", "draft_status": DRAFT_STATUS_SYNCING}
    return {
        "status": "queued",
        "draft_status": layer.draft_status or DRAFT_STATUS_ACTIVE,
    }


@router.get("/workspace/{calculation_id}/digitize-layers/{layer_id}/audit")
def digitize_audit_log(
    calculation_id: UUID,
    layer_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Return the digitize audit trail for a layer (Gap 6.1 / Task 1.4.4).

    Owner/editor only (same ownership gate as the rest of the digitize API).
    Newest-first; bounded by limit=200.
    """
    _require_digitize_enabled()
    _require_calculation_access(db, calculation_id, current_user)

    entries = list_digitize_audit(
        db,
        calculation_id=calculation_id,
        layer_id=layer_id,
        limit=200,
    )
    logger.info(
        "digitize_action",
        extra={
            "calculation_id": str(calculation_id),
            "layer_id": layer_id,
            "user_id": str(current_user.id),
            "action": "audit_read",
            "entry_count": len(entries),
        },
    )
    return {"layer_id": layer_id, "entries": entries}


@router.get("/workspace/crs-options")
async def get_crs_options():
    """Return available CRS options for CSV/XLSX import."""
    return CRS_OPTIONS


@router.post("/workspace/{calculation_id}/import-layer")
async def import_layer(
    calculation_id: UUID,
    file: UploadFile = File(...),
    purpose: Optional[str] = Form(None),
    custom_name: Optional[str] = Form(None),
    crs_epsg: Optional[int] = Form(None),
    gpx_types: Optional[str] = Form(None),
    replace_existing: bool = Form(False),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Import a new layer into the workspace.

    Validation chain (in order):
    1. File exists
    2. Extension in ALLOWED_EXTENSIONS
    3. Per-file size ≤ WORKSPACE_IMPORT_MAX_FILE_SIZE_MB
    4. Cumulative size ≤ WORKSPACE_IMPORT_MAX_CUMULATIVE_SIZE_MB
    5. Parse → process_uploaded_file()
    6. validate_geometry_types()
    7. validate_feature_count()
    8. validate_vertex_count()
    9. validate_first_layer() — Block/Comp required first
    10. validate_area_limit()
    11. validate_layer_distance() — 10 km via PostGIS
    12. Duplicate check → 409 if exists without replace_existing
    13. Create WorkspaceLayer record
    """
    # Rate limit: max 5 imports per minute per user
    import_limiter.check(current_user.id)

    # Ownership: importing into someone else's calculation is not permitted
    _require_calculation_access(db, calculation_id, current_user)

    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    gpx_selection = None
    if gpx_types:
        gpx_selection = [t.strip() for t in gpx_types.split(",") if t.strip()]

    # Step 1–2: Extension validation (inside process_uploaded_file)
    # Step 3: Per-file size check happens inside process_uploaded_file

    # Step 4: Cumulative size check
    existing_layers = (
        db.query(func.coalesce(func.sum(WorkspaceLayer.file_size_bytes), 0))
        .filter(
            WorkspaceLayer.calculation_id == calculation_id,
            WorkspaceLayer.deleted_at.is_(None),
        )
        .scalar()
        or 0
    )

    # Process before check — we need file size from process_uploaded_file
    try:
        geometries, attributes, metadata = await process_uploaded_file(
            file, crs_epsg=crs_epsg, gpx_selection=gpx_selection, purpose=purpose
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=resolve_service_detail(str(e)))

    logger.info(
        f"import_layer: parsed {len(geometries)} geometries from {file.filename}, purpose={purpose}"
    )

    # Swapped-lat/lon guard (Nepal-scoped): a point layer whose longitude values
    # sit in Nepal's latitude range (and vice versa) is almost certainly a swap
    # accident. Auto-fix it here so a 'Skip / Assign Purpose Later' import never
    # stores the layer at the edge of the globe, and flag it for the UI.
    _pts = []
    for _g in geometries:
        _t = getattr(_g, "geom_type", "")
        if _t == "Point":
            _pts.append(_g)
        elif _t == "MultiPoint":
            _pts.extend(list(getattr(_g, "geoms", []) or []))
    if len(_pts) >= 2:
        import numpy as _np
        from app.services.validators.coordinate_detector import (
            CoordinateDetector as _CDet,
        )

        _xs = _np.asarray([p.x for p in _pts], dtype=float)
        _ys = _np.asarray([p.y for p in _pts], dtype=float)
        if _CDet().detect_crs(_xs, _ys).get("error") == "coordinates_swapped":
            from shapely.geometry import MultiPoint as _fix_mpt

            _fixed = []
            for _g in geometries:
                _t = getattr(_g, "geom_type", "")
                if _t == "Point":
                    _fixed.append(Point(_g.y, _g.x))
                elif _t == "MultiPoint":
                    _fixed.append(_fix_mpt([(p.y, p.x) for p in _g.geoms]))
                else:
                    _fixed.append(_g)
            geometries = _fixed
            metadata["swapped_fixed"] = True
            metadata.setdefault("non_kml_warnings", []).append(
                "Latitude and longitude values appear to be swapped — automatically corrected."
            )
            logger.info("import_layer: auto-fixed swapped lat/lon coordinates")

    file_size = metadata.get("file_size_bytes", 0)
    max_cumulative = settings.WORKSPACE_IMPORT_MAX_CUMULATIVE_SIZE_MB * 1024 * 1024
    if existing_layers + file_size > max_cumulative:
        raise HTTPException(
            status_code=413,
            detail=f"Cumulative import size exceeds {settings.WORKSPACE_IMPORT_MAX_CUMULATIVE_SIZE_MB}MB limit",
        )

    # Step 6–10: Validators
    try:
        validate_feature_count(geometries)
        validate_vertex_count(geometries)
        validate_area_limit(geometries)
        if purpose is not None:
            validate_first_layer(db, calculation_id, purpose)
        validate_layer_distance(db, calculation_id, geometries)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=resolve_service_detail(str(e)))

    # Step 11: Duplicate check — only enforced for admin purposes (blocks, boundary)
    # Non-admin purposes (other, roads, water, inventory, etc.) allow multiple layers
    # Also skip duplicate check when purpose is None (unassigned layers)
    _UNIQUE_PURPOSES = {"blocks", "boundary"}
    if purpose is not None and not replace_existing and purpose in _UNIQUE_PURPOSES:
        existing = (
            db.query(WorkspaceLayer)
            .filter(
                WorkspaceLayer.calculation_id == calculation_id,
                WorkspaceLayer.purpose == purpose,
                WorkspaceLayer.deleted_at.is_(None),
            )
            .first()
        )
        if existing:
            raise i18n_error(
                409,
                "imports.duplicate_purpose",
                purpose=purpose,
            )

    # Step 12–13: Create WorkspaceLayer record
    name = custom_name or file.filename or "Imported Layer"
    geometry_types = list(set(g.geom_type for g in geometries))

    # Build GeoJSON FeatureCollection from parsed geometries + attributes.
    # Every feature gets geo_* derived properties auto-computed from its geometry
    # (single source of truth) plus a stable featureId for map<->table sync.
    # For any polygon-purpose (POLYGON_AUTO_BUFFER set), Feature-to-Polygon runs up
    # front so the stored layer is always pure polygons (one per feature), using the
    # shared engine. sub_areas keeps its existing wrapper (identical behaviour +
    # category detection); the other polygon purposes use the engine directly.
    source_features = []
    if purpose in IMPORT_PURPOSE_POLYGON_AUTO_BUFFER:
        if purpose == IMPORT_PURPOSE_SUB_AREAS:
            from ..services.sub_area_service import (
                polygonise_sub_area_geometries,
                _last_import_warnings,
            )

            polygonised = polygonise_sub_area_geometries(geometries, attributes)
            metadata["polygonised"] = True
            metadata["sub_area_import_warnings"] = _last_import_warnings()
        else:
            from ..services.file_processor import feature_to_polygon, PolygonizeConfig

            config = PolygonizeConfig(
                snap_tolerance_m=20.0,
                allow_point_hull=True,
                alpha=None,
                island_cluster_m=100.0,
                name_prefix=purpose.replace("_", " ").title(),
            )
            polygonised, poly_warnings = feature_to_polygon(
                geometries, attributes, config
            )
            metadata["polygonised"] = True
            metadata["geometry_import_warnings"] = poly_warnings
        for shp, attrs in polygonised:
            source_features.append((shp, attrs))
    else:
        for i, geom in enumerate(geometries):
            attrs = attributes[i] if i < len(attributes) else {}
            source_features.append((geom, attrs))

    fc_features = []
    for i, (geom, attrs) in enumerate(source_features):
        try:
            # Strip any geo_* keys the source file may contain (tamper-proof),
            # then recompute them authoritatively from the geometry.
            clean_attrs = strip_geo_fields(dict(attrs))
            geo_props = compute_geometry_properties(geom)
            clean_attrs.update(geo_props)
            if not clean_attrs.get("featureId"):
                clean_attrs["featureId"] = f"imported-{i}"
            fc_features.append(
                {
                    "type": "Feature",
                    "geometry": shapely_mapping(geom),
                    "properties": clean_attrs,
                }
            )
        except Exception:
            logger.warning(
                "imported feature %s kept without derived geometry properties",
                i,
                exc_info=True,
            )
            clean_attrs = strip_geo_fields(dict(attrs))
            clean_attrs["featureId"] = f"imported-{i}"
            fc_features.append(
                {
                    "type": "Feature",
                    "geometry": shapely_mapping(geom),
                    "properties": clean_attrs,
                }
            )

    logger.info(
        f"import_layer: built FeatureCollection with {len(fc_features)} features"
    )
    if purpose == IMPORT_PURPOSE_SUB_AREAS:
        metadata["feature_count"] = len(fc_features)
    feature_collection = {
        "type": "FeatureCollection",
        "features": fc_features,
    }

    gpx_extra = {}
    if gpx_selection:
        gpx_extra = extract_gpx_metadata(geometries, attributes)

    invalidate_layers_cache(calculation_id)

    with atomic_transaction(db, f"import_layer {calculation_id} {purpose}"):
        if replace_existing:
            filters = [
                WorkspaceLayer.calculation_id == calculation_id,
                WorkspaceLayer.purpose == purpose,
                WorkspaceLayer.deleted_at.is_(None),
            ]
            if custom_name:
                filters.append(WorkspaceLayer.name == custom_name)
            existing_layer = db.query(WorkspaceLayer).filter(*filters).first()
            if existing_layer:
                existing_layer.deleted_at = func.now()

        import warnings

        non_kml_warnings = metadata.get("non_kml_warnings", [])

        layer = WorkspaceLayer(
            calculation_id=calculation_id,
            name=name,
            purpose=purpose,
            source_format=metadata.get("source_format", ""),
            feature_count=metadata.get("feature_count", 0),
            file_size_bytes=file_size,
            geometry_types=geometry_types,
            layer_data=feature_collection,
            layer_metadata={
                "crs_epsg": crs_epsg or 4326,
                "gpx_metadata": gpx_extra,
                **metadata,
            },
            is_draft=True,
            created_by=current_user.id,
        )
        db.add(layer)
        db.flush()

    return {
        "id": layer.id,
        "name": layer.name,
        "feature_count": layer.feature_count,
        "geometry_types": layer.geometry_types,
        "warnings": non_kml_warnings if non_kml_warnings else None,
        "swapped_fixed": bool(metadata.get("swapped_fixed")),
    }


@router.get("/workspace/{calculation_id}/import-layers")
def list_layers(
    calculation_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Return all active workspace layers for a calculation."""
    _require_calculation_access(db, calculation_id, current_user)

    cached = get_cached_layers(calculation_id)
    if cached is not None:
        return cached

    layers = (
        db.query(WorkspaceLayer)
        .filter(
            WorkspaceLayer.calculation_id == calculation_id,
            WorkspaceLayer.deleted_at.is_(None),
        )
        .order_by(WorkspaceLayer.created_at)
        .all()
    )

    result = [
        {
            "id": layer.id,
            "name": layer.name,
            "purpose": layer.purpose,
            "source_format": layer.source_format,
            "feature_count": layer.feature_count,
            "file_size_bytes": layer.file_size_bytes,
            "geometry_types": layer.geometry_types,
            "is_draft": layer.is_draft,
            "created_at": layer.created_at.isoformat() if layer.created_at else None,
        }
        for layer in layers
    ]

    cache_layers_list(calculation_id, result)
    return result


@router.get("/workspace/{calculation_id}/import-layers/{layer_id}/features")
def get_import_layer_features(
    calculation_id: UUID,
    layer_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Return the GeoJSON FeatureCollection for a specific imported layer."""
    _require_calculation_access(db, calculation_id, current_user)

    layer = (
        db.query(WorkspaceLayer)
        .filter(
            WorkspaceLayer.id == layer_id,
            WorkspaceLayer.calculation_id == calculation_id,
            WorkspaceLayer.deleted_at.is_(None),
        )
        .first()
    )

    if not layer:
        raise HTTPException(status_code=404, detail="Layer not found")

    if not layer.layer_data:
        return {"type": "FeatureCollection", "features": []}

    return layer.layer_data


class ExportLayerGpkgRequest(BaseModel):
    """The features of one workspace layer, as the workspace shows them (GeoJSON, WGS 84), and the layer's name."""

    layer_name: str
    features: List[Dict[str, Any]]


@router.post("/workspace/{calculation_id}/export-geopackage")
def export_layer_geopackage(
    calculation_id: UUID,
    body: ExportLayerGpkgRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """One workspace layer as a GeoPackage (.gpkg) - exactly the features and columns the layer shows.

    The file is named `{Forest}_{Layer}_Spatial_{YYYYMMDD}.gpkg`. A layer that mixes points, lines and polygons becomes one file with a
    GeoPackage layer for each kind. 400 when no feature has a geometry, 413 when the layer is too large for one request.
    """
    from fastapi.responses import Response

    from ..services.layer_gpkg_export import (
        MAX_FEATURES,
        NothingToExport,
        TooManyFeatures,
        build_geopackage,
        safe_layer_name,
    )
    from ..utils.file_export import build_disposition

    calculation = _require_calculation_access(db, calculation_id, current_user)
    try:
        content = build_geopackage(body.features, body.layer_name)
    except NothingToExport:
        raise HTTPException(status_code=400, detail="This layer has no features with a geometry to export.")
    except TooManyFeatures:
        raise HTTPException(
            status_code=413,
            detail=f"This layer has more than {MAX_FEATURES:,} features; export it in parts.",
        )
    _, disposition = build_disposition(calculation.forest_name, safe_layer_name(body.layer_name), "Spatial", "gpkg")
    return Response(content=content, media_type="application/geopackage+sqlite3", headers={"Content-Disposition": disposition})


class DuplicateLayerRequest(BaseModel):
    source_layer_id: int
    new_name: str


@router.post("/workspace/{calculation_id}/import-layers/duplicate")
def duplicate_layer(
    calculation_id: UUID,
    body: DuplicateLayerRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Duplicate a workspace layer (deep copy)."""
    _require_calculation_access(db, calculation_id, current_user)

    source = (
        db.query(WorkspaceLayer)
        .filter(
            WorkspaceLayer.id == body.source_layer_id,
            WorkspaceLayer.calculation_id == calculation_id,
            WorkspaceLayer.deleted_at.is_(None),
        )
        .first()
    )

    if not source:
        raise HTTPException(status_code=404, detail="Source layer not found")

    invalidate_layers_cache(calculation_id)

    with atomic_transaction(db, f"duplicate_layer {body.source_layer_id}"):
        dup = WorkspaceLayer(
            calculation_id=source.calculation_id,
            name=body.new_name,
            purpose=source.purpose,
            source_format=source.source_format,
            feature_count=source.feature_count,
            file_size_bytes=source.file_size_bytes,
            geometry_types=source.geometry_types,
            layer_data=source.layer_data,
            layer_metadata=source.layer_metadata,
            is_draft=source.is_draft,
            created_by=current_user.id,
        )
        db.add(dup)
        db.flush()
        dup_id = dup.id

    return {
        "id": dup_id,
        "name": body.new_name,
        "feature_count": source.feature_count,
        "geometry_types": source.geometry_types,
    }


class RenameLayerRequest(BaseModel):
    name: str


@router.patch("/workspace/{calculation_id}/import-layers/{layer_id}")
def rename_layer(
    calculation_id: UUID,
    layer_id: int,
    body: RenameLayerRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Rename a workspace layer.

    Deliberately name-only: `purpose` and all other metadata are immutable via
    this endpoint. Renaming a layer must never change its purpose — the two are
    independent, separately-stored fields on WorkspaceLayer.
    """
    _require_calculation_access(db, calculation_id, current_user)

    name = (body.name or "").strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Layer name cannot be empty",
        )
    if len(name) > 255:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Layer name exceeds 255 characters",
        )

    layer = (
        db.query(WorkspaceLayer)
        .filter(
            WorkspaceLayer.id == layer_id,
            WorkspaceLayer.calculation_id == calculation_id,
            WorkspaceLayer.deleted_at.is_(None),
        )
        .first()
    )

    if not layer:
        raise HTTPException(status_code=404, detail="Layer not found")

    old_name = layer.name
    layer.name = name
    # Force timestamp change to guarantee the UPDATE is emitted.
    layer.updated_at = func.now()

    invalidate_layers_cache(calculation_id)

    with atomic_transaction(db, f"rename_layer {layer_id}"):
        db.flush()

    return {
        "id": layer.id,
        "name": layer.name,
        "old_name": old_name,
        "purpose": layer.purpose,
    }


@router.delete("/workspace/{calculation_id}/import-layers/{layer_id}")
def delete_layer(
    calculation_id: UUID,
    layer_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Soft-delete a workspace layer."""
    _require_calculation_access(db, calculation_id, current_user)

    layer = (
        db.query(WorkspaceLayer)
        .filter(
            WorkspaceLayer.id == layer_id,
            WorkspaceLayer.calculation_id == calculation_id,
            WorkspaceLayer.deleted_at.is_(None),
        )
        .first()
    )

    if not layer:
        raise HTTPException(status_code=404, detail="Layer not found")

    # Gap 6.1 / Task 1.4.4: drafts inherit calculation membership — only the
    # creator may discard a digitize layer; other calculation editors can
    # append + finalize but not delete. Fallback: if created_by is missing
    # (legacy row) the calc owner can discard.
    if layer.source_format == "digitize":
        if layer.created_by is None:
            is_owner = (
                db.query(Calculation)
                .filter(Calculation.id == layer.calculation_id)
                .first()
                .user_id
                == current_user.id
            )
            if not (is_owner or current_user.role == UserRole.SUPER_ADMIN):
                raise HTTPException(
                    status_code=403,
                    detail="Only the layer creator can discard a digitize layer",
                )
        elif layer.created_by != current_user.id:
            raise HTTPException(
                status_code=403,
                detail="Only the layer creator can discard a digitize layer",
            )

    invalidate_layers_cache(calculation_id)

    with atomic_transaction(db, f"delete_layer {layer_id}"):
        layer.deleted_at = func.now()
        if layer.source_format == "digitize":
            record_digitize_audit(
                db,
                calculation_id=calculation_id,
                layer_id=layer_id,
                user_id=current_user.id,
                action="discard",
                feature_count_delta=-layer.feature_count,
                geometry_hash=geometry_hash_of(
                    (layer.layer_data or {}).get("features", [])
                    if isinstance(layer.layer_data, dict)
                    else []
                ),
            )
            db.flush()

    invalidate_layers_cache(calculation_id)

    return {"id": layer.id, "deleted": True}


class UpdateFeaturePropertiesRequest(BaseModel):
    properties: dict


@router.patch(
    "/workspace/{calculation_id}/import-layers/{layer_id}/features/{feature_index}"
)
def update_import_layer_feature(
    calculation_id: UUID,
    layer_id: int,
    feature_index: int,
    body: UpdateFeaturePropertiesRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Update properties of a single feature within an imported layer."""
    _require_calculation_access(db, calculation_id, current_user)

    layer = (
        db.query(WorkspaceLayer)
        .filter(
            WorkspaceLayer.id == layer_id,
            WorkspaceLayer.calculation_id == calculation_id,
            WorkspaceLayer.deleted_at.is_(None),
        )
        .first()
    )

    if not layer:
        raise HTTPException(status_code=404, detail="Layer not found")

    if not layer.layer_data or not isinstance(layer.layer_data, dict):
        raise HTTPException(status_code=400, detail="Layer has no feature data")

    features = layer.layer_data.get("features", [])
    if feature_index < 0 or feature_index >= len(features):
        raise HTTPException(
            status_code=404, detail=f"Feature index {feature_index} not found"
        )

    # Deep copy to break ALL reference chains — shallow dict() + in-place list
    # mutation causes SQLAlchemy's JSON comparator to see equal values and ELIDE the UPDATE.
    new_data = copy.deepcopy(layer.layer_data)
    updated_feature = copy.deepcopy(new_data["features"][feature_index])
    updated_props = copy.deepcopy(updated_feature.get("properties", {}))

    # Strip geo_* from incoming properties (tamper-proof) — these are always
    # derived from geometry server-side and never client-editable.
    incoming = strip_geo_fields(dict(body.properties))
    updated_props.update(incoming)

    # If the client sent a new geometry (inside properties), apply it to the
    # feature geometry, then recompute geo_* authoritatively from the geometry.
    if "geometry" in incoming and isinstance(incoming["geometry"], dict):
        try:
            from shapely.geometry import shape, mapping as _mapping

            new_geom = shape(incoming["geometry"])
            updated_feature["geometry"] = _mapping(new_geom)
        except Exception:
            # Swallowing this discarded the edit and still answered 200: the
            # client saw its change accepted and the stored geometry never
            # moved. A geometry the client sent that shapely cannot read is a
            # bad request, and saying so is the whole fix.
            logger.warning(
                "rejected unparseable geometry for layer %s feature %s",
                layer_id,
                feature_index,
                exc_info=True,
            )
            # POSTPONED 2026-08-25 (H3.4). The log line above stays; the 400 is
            # off at the user's request until H3.4 is retested. Restoring it is
            # this block, uncommented — the message is deliberately fixed rather
            # than interpolated from `exc` (H3.11: no internal detail in a
            # response; the traceback is in the log). See HARDENING_TRACKER 3.4.
            #
            #   raise HTTPException(
            #       status_code=400,
            #       detail="The geometry sent for this feature could not be read.",
            #   ) from exc
            #
            # Until then the old behaviour stands: the edit is discarded and the
            # endpoint still answers 200. The log line is what makes that
            # visible now, which it was not before.
            pass

    # Always recompute geo_* from the authoritative stored geometry.
    try:
        from shapely.geometry import shape

        feat_geom = updated_feature.get("geometry")
        if feat_geom:
            geo_props = compute_geometry_properties(shape(feat_geom))
            updated_props.update(geo_props)
    except Exception:
        # The geo_* fields are derived, not client-supplied, so a failure here
        # would otherwise leave the PREVIOUS geometry's area and perimeter
        # attached to the new one - a wrong number that looks like a real one.
        # Drop them instead: honestly absent beats quietly stale.
        logger.exception(
            "could not recompute geo_* for layer %s feature %s - stale derived "
            "fields dropped rather than left attached to the new geometry",
            layer_id,
            feature_index,
        )
        # POSTPONED 2026-08-25 (H3.4). Re-enable with:
        #   updated_props = strip_geo_fields(updated_props)
        # which drops the PREVIOUS geometry's area/perimeter rather than
        # leaving them attached to the new one. Off until H3.4 is retested.

    updated_feature["properties"] = updated_props
    new_data["features"][feature_index] = updated_feature
    layer.layer_data = new_data
    # Force timestamp change to guarantee dirty state regardless of JSON comparison
    layer.updated_at = func.now()

    invalidate_layers_cache(calculation_id)

    with atomic_transaction(db, f"update_feature {layer_id}[{feature_index}]"):
        db.flush()

    return {"feature_index": feature_index, "properties": updated_props}


@router.delete(
    "/workspace/{calculation_id}/import-layers/{layer_id}/features/{feature_index}"
)
def delete_import_layer_feature(
    calculation_id: UUID,
    layer_id: int,
    feature_index: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """E3 — delete ONE feature from an imported/finalized layer (per-row delete).

    Mutates layer_data.features in place (JSONB-safe deep copy + forced
    updated_at) so the change always persists. Returns the deleted feature so
    the frontend can restore it for undo.
    """
    _require_calculation_access(db, calculation_id, current_user)

    layer = (
        db.query(WorkspaceLayer)
        .filter(
            WorkspaceLayer.id == layer_id,
            WorkspaceLayer.calculation_id == calculation_id,
            WorkspaceLayer.deleted_at.is_(None),
        )
        .first()
    )
    if not layer:
        raise HTTPException(status_code=404, detail="Layer not found")
    if not layer.layer_data or not isinstance(layer.layer_data, dict):
        raise HTTPException(status_code=400, detail="Layer has no feature data")

    features = layer.layer_data.get("features", [])
    if feature_index < 0 or feature_index >= len(features):
        raise HTTPException(
            status_code=404, detail=f"Feature index {feature_index} not found"
        )

    new_data = copy.deepcopy(layer.layer_data)
    deleted_feature = copy.deepcopy(new_data["features"][feature_index])
    del new_data["features"][feature_index]
    layer.layer_data = new_data
    layer.feature_count = len(new_data["features"])
    layer.updated_at = func.now()

    invalidate_layers_cache(calculation_id)

    with atomic_transaction(db, f"delete_feature {layer_id}[{feature_index}]"):
        db.flush()

    return {
        "feature_index": feature_index,
        "feature_count": len(new_data["features"]),
        "deleted_feature": deleted_feature,
    }


class RestoreImportFeatureRequest(BaseModel):
    feature: dict
    feature_id: Optional[str] = None
    feature_index: Optional[int] = None


@router.post("/workspace/{calculation_id}/import-layers/{layer_id}/features/restore")
def restore_import_layer_feature(
    calculation_id: UUID,
    layer_id: int,
    body: RestoreImportFeatureRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """E3 — undo: re-insert ONE feature to an imported/finalized layer.

    The stored feature (original properties incl. featureId + geometry) is
    re-inserted at its ORIGINAL index when `feature_index` is supplied (stable
    redo), otherwise appended at the END. If a feature with the same featureId
    already exists it is skipped (idempotent).
    """
    _require_calculation_access(db, calculation_id, current_user)

    layer = (
        db.query(WorkspaceLayer)
        .filter(
            WorkspaceLayer.id == layer_id,
            WorkspaceLayer.calculation_id == calculation_id,
            WorkspaceLayer.deleted_at.is_(None),
        )
        .first()
    )
    if not layer:
        raise HTTPException(status_code=404, detail="Layer not found")
    if not body.feature or not body.feature.get("geometry"):
        raise HTTPException(status_code=400, detail="Feature has no geometry")

    new_data = copy.deepcopy(
        layer.layer_data or {"type": "FeatureCollection", "features": []}
    )
    features = new_data.get("features", [])

    restored = copy.deepcopy(body.feature)
    # Preserve the original featureId (or the server-assigned one from the delete snapshot).
    fid = body.feature.get("properties", {}).get("featureId") or body.feature_id
    if fid:
        restored["properties"] = {
            **(restored.get("properties") or {}),
            "featureId": fid,
        }
    if fid and any(
        (f.get("properties", {}) or {}).get("featureId") == fid for f in features
    ):
        return {"feature_count": len(features), "already_restored": True}

    if body.feature_index is not None and 0 <= body.feature_index <= len(features):
        features.insert(body.feature_index, restored)
    else:
        features.append(restored)
    new_data["features"] = features
    layer.layer_data = new_data
    layer.feature_count = len(features)
    layer.updated_at = func.now()

    invalidate_layers_cache(calculation_id)

    with atomic_transaction(db, f"restore_feature {layer_id}"):
        db.flush()

    return {"feature_count": len(features), "feature_id": fid}


@router.post("/workspace/{calculation_id}/import-layers/recompute-geo")
def recompute_imported_layers_geo(
    calculation_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Backfill geo_* derived properties for ALL imported layers in a calculation.

    Brings legacy layers (imported before backend auto-computation existed) up
    to date without re-importing. Safe to call any time — only rewrites geo_*
    keys, leaves every other property untouched. Follows the JSONB-safe
    reassignment pattern (new dict + forced updated_at) so changes always
    persist.
    """
    _require_calculation_access(db, calculation_id, current_user)

    layers = (
        db.query(WorkspaceLayer)
        .filter(
            WorkspaceLayer.calculation_id == calculation_id,
            WorkspaceLayer.deleted_at.is_(None),
        )
        .all()
    )

    per_layer = {}
    total_features = 0
    changed_layers = 0

    for layer in layers:
        if not layer.layer_data or not isinstance(layer.layer_data, dict):
            continue
        new_data = copy.deepcopy(layer.layer_data)
        features = new_data.get("features", [])
        layer_changed = False
        for feature in features:
            props = feature.get("properties")
            geom = feature.get("geometry")
            if not props or not geom:
                continue
            try:
                from shapely.geometry import shape

                geo_props = compute_geometry_properties(shape(geom))
                clean = strip_geo_fields(dict(props))
                clean.update(geo_props)
                feature["properties"] = clean
                layer_changed = True
            except Exception as e:
                logger.warning(f"Failed to recompute geo for {layer.name} feature: {e}")
        if layer_changed:
            layer.layer_data = new_data
            layer.updated_at = func.now()
            per_layer[layer.name] = len(features)
            total_features += len(features)
            changed_layers += 1

    if changed_layers:
        invalidate_layers_cache(calculation_id)
        with atomic_transaction(db, f"recompute_geo {calculation_id}"):
            db.flush()

    return {
        "success": True,
        "layers_updated": changed_layers,
        "features_updated": total_features,
        "per_layer": per_layer,
    }


@router.post("/workspace/{calculation_id}/import-layers/{layer_id}/convert-to-builtin")
def convert_imported_to_builtin(
    calculation_id: UUID,
    layer_id: int,
    request: dict,  # { "target_type": "blocks" }
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Convert an imported layer to a builtin layer type (blocks, compartments, etc.).

    Takes the features from an imported layer and creates the corresponding
    ForestBlock/ForestCompartment/etc. records. The imported layer is archived (soft-deleted).
    """
    try:
        from app.models.workspace_layer import WorkspaceLayer
        from app.models.forest_block import ForestBlock
        from shapely.geometry import shape, mapping
        from shapely import wkt as shapely_wkt
        from app.core.constants import SQM_PER_HA
        from app.utils.geometry_utils import (
            calculate_area_geodesic,
            calculate_area_geodesic_from_shapely,
        )
        from app.api.forests import (
            calculate_block_breakdown,
            calculate_total_excluded_area,
            calculate_block_excluded_areas,
        )
        import uuid

        target_type = request.get("target_type", "blocks")
        logger.info(
            f"convert-to-builtin: calc={calculation_id}, layer={layer_id}, target_type={target_type}"
        )

        calculation = _require_calculation_access(db, calculation_id, current_user)

        layer = (
            db.query(WorkspaceLayer)
            .filter(
                WorkspaceLayer.id == layer_id,
                WorkspaceLayer.calculation_id == calculation_id,
                WorkspaceLayer.deleted_at.is_(None),
            )
            .first()
        )

        if not layer:
            logger.warning(f"convert-to-builtin: layer {layer_id} not found")
            raise HTTPException(status_code=404, detail="Layer not found")

        logger.info(
            f"convert-to-builtin: layer found, purpose={layer.purpose}, feature_count={layer.feature_count}"
        )
        logger.info(
            f"convert-to-builtin: layer_data keys={list(layer.layer_data.keys()) if layer.layer_data and isinstance(layer.layer_data, dict) else 'none'}"
        )

        if not layer.layer_data or not isinstance(layer.layer_data, dict):
            logger.warning(f"convert-to-builtin: layer has no data")
            raise HTTPException(status_code=400, detail="Layer has no data")

        features = layer.layer_data.get("features", [])
        logger.info(f"convert-to-builtin: features count={len(features)}")
        if not features:
            raise HTTPException(status_code=400, detail="Layer has no features")

        # Log first few features for debugging
        for idx, feat in enumerate(features[:5]):
            has_geom = "geometry" in feat
            geom_type = feat.get("geometry", {}).get("type") if has_geom else "none"
            logger.info(
                f"convert-to-builtin: feature {idx} - has_geom={has_geom}, type={geom_type}"
            )

        # Verify purpose matches target_type (for admin purposes)
        if target_type in ("blocks", "block") and layer.purpose not in (
            "blocks",
            "block",
        ):
            logger.warning(
                f"convert-to-builtin: layer purpose '{layer.purpose}' doesn't match target_type '{target_type}'"
            )
            raise HTTPException(
                status_code=400,
                detail=f"Layer purpose '{layer.purpose}' cannot be converted to '{target_type}'",
            )
        if target_type in ("compartments", "compartment") and layer.purpose not in (
            "compartments",
            "compartment",
        ):
            logger.warning(
                f"convert-to-builtin: layer purpose '{layer.purpose}' doesn't match target_type '{target_type}'"
            )
            raise HTTPException(
                status_code=400,
                detail=f"Layer purpose '{layer.purpose}' cannot be converted to '{target_type}'",
            )
        if target_type in (
            "sub_compartments",
            "sub_compartment",
        ) and layer.purpose not in ("sub_compartments", "sub_compartment"):
            logger.warning(
                f"convert-to-builtin: layer purpose '{layer.purpose}' doesn't match target_type '{target_type}'"
            )
            raise HTTPException(
                status_code=400,
                detail=f"Layer purpose '{layer.purpose}' cannot be converted to '{target_type}'",
            )
        if target_type in (
            "sub_blocks",
            "sub_block",
        ) and layer.purpose not in ("sub_blocks", "sub_block"):
            logger.warning(
                f"convert-to-builtin: layer purpose '{layer.purpose}' doesn't match target_type '{target_type}'"
            )
            raise HTTPException(
                status_code=400,
                detail=f"Layer purpose '{layer.purpose}' cannot be converted to '{target_type}'",
            )

        # A sub-area is a zone within the forest — clipped to (boundary ∪ blocks).
        # Refuse the import until that extent exists (same boundary-first rule as
        # the draw path and tree-inventory import). blocks/compartments count.
        if target_type in ("sub_areas", "sub_area"):
            from app.services.sub_area_service import has_forest_extent

            if not has_forest_extent(db, calculation):
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "boundary_required",
                        "message": "Draw or import the forest boundary (or blocks) before importing a sub-area.",
                        "message_np": "उप-क्षेत्र आयात गर्नुअघि वनको सीमा (वा ब्लक) कोर्नुहोस् वा आयात गर्नुहोस्।",
                    },
                )

        # Boundary target (G4 latent-fix): merge imported polygons into the forest
        # boundary via derive_boundary_from_polygons + the updateBoundaryGeometry
        # write path. Early-return: boundary replaces only boundary state, so the
        # compartment replace/backup machinery (below) is skipped entirely.
        if target_type == "boundary":
            from geoalchemy2.shape import from_shape as _bnd_fs
            from shapely.geometry import shape as _bnd_shape
            from app.services.file_processor import (
                derive_boundary_from_polygons,
                feature_to_polygon,
                PolygonizeConfig,
            )

            _shapes = []
            for _feat in features:
                _g = _feat.get("geometry")
                if not _g:
                    continue
                try:
                    _s = (
                        _bnd_shape(_g)
                        if not isinstance(_g, str)
                        else shapely_wkt.loads(_g)
                    )
                    if not _s.is_empty:
                        _shapes.append(_s)
                except Exception:
                    # Dropping a shape here shrinks the union it feeds, and the
                    # caller cannot tell a small union from an incomplete one.
                    logger.exception(
                        "boundary component dropped from the union - the "
                        "resulting extent is smaller than the real one"
                    )
                    continue
            if not _shapes:
                raise HTTPException(
                    status_code=400,
                    detail="No valid geometry features to convert to boundary",
                )
            # Swapped-lat/lon guard for native point features: if the detector
            # reports a coordinate swap (lon values sitting in Nepal's latitude
            # range and vice versa), swap them back automatically so the boundary
            # lands in Nepal instead of the wrong corner of the globe.
            _swapped_fixed = False
            from shapely.geometry import MultiPoint as _bnd_mpt

            _point_geoms = []
            for _s in _shapes:
                if _s.geom_type == "Point":
                    _point_geoms.append(_s)
                elif _s.geom_type == "MultiPoint":
                    _point_geoms.extend(list(_s.geoms))
            if _point_geoms:
                import numpy as _np
                from app.services.validators.coordinate_detector import (
                    CoordinateDetector as _bnd_cdet,
                )

                _xs = _np.asarray([g.x for g in _point_geoms], dtype=float)
                _ys = _np.asarray([g.y for g in _point_geoms], dtype=float)
                if (
                    _bnd_cdet().detect_crs(_xs, _ys).get("error")
                    == "coordinates_swapped"
                ):
                    _swapped_fixed = True
                    _fixed_shapes = []
                    for _s in _shapes:
                        if _s.geom_type == "Point":
                            _fixed_shapes.append(Point(_s.y, _s.x))
                        elif _s.geom_type == "MultiPoint":
                            _fixed_shapes.append(
                                _bnd_mpt([(g.y, g.x) for g in _s.geoms])
                            )
                        else:
                            _fixed_shapes.append(_s)
                    _shapes = _fixed_shapes
            # Point / line / mixed layers are polygonised by the unified engine,
            # so a custom point import can be assigned to the boundary later
            # (points -> hull -> polygon). This mirrors the at-import behaviour
            # (process_geometry_list polygon-purposes) and polygon-from-points.
            _poly_feats, _poly_warn = feature_to_polygon(
                _shapes,
                [{} for _ in _shapes],
                PolygonizeConfig(
                    allow_point_hull=True,
                    alpha=None,
                    name_prefix="Boundary",
                    island_cluster_m=1e9,
                ),
            )
            _poly_geoms = [
                g for g, _ in _poly_feats if g is not None and not g.is_empty
            ]
            if not _poly_geoms:
                logger.warning(
                    f"convert-to-builtin: polygonise produced no polygon (warn={_poly_warn})"
                )
                raise HTTPException(
                    status_code=400,
                    detail="Points are collinear or too close together — cannot form a boundary polygon",
                )
            _merged = derive_boundary_from_polygons(_poly_geoms)
            if _merged is None or _merged.is_empty:
                raise HTTPException(
                    status_code=400,
                    detail="Imported features produced no boundary polygon",
                )
            if _merged.area <= 1e-9:
                raise HTTPException(
                    status_code=400,
                    detail="Imported features produce a zero-area boundary",
                )

            # PF-3 provisional gate for boundary import: if the proposed boundary adjoins/overlaps
            # another CF and the caller did not set confirmed=true, return the preview without writing.
            # The frontend will surface BoundaryOverlapPreviewPanel and, on user decision, call
            # confirm/include-gap (which writes via the shared persist_boundary). Fast path (no relations) writes directly.
            if not request.get("confirmed"):
                try:
                    from shapely.geometry import mapping as _bnd_mapping
                    from geoalchemy2 import Geography as _BndGeography
                    from sqlalchemy import func as _bnd_func
                    from decimal import Decimal as _BndDecimal
                    from uuid import UUID as _BndUUID
                    from app.services.gap_detector import (
                        detect_relations as _bnd_detect,
                        GapParams as _BndGapParams,
                    )
                    from app.schemas.boundary import (
                        GapForest as _BndGapForest,
                        OverlappingForest as _BndOverlappingForest,
                    )
                    from app.models.calculation import Calculation as _BndCalc

                    wkt = _merged.wkt
                    existing = (
                        db.query(_BndCalc)
                        .filter(
                            _BndCalc.boundary_geom.isnot(None),
                            _bnd_func.ST_DWithin(
                                _BndCalc.boundary_geom.cast(_BndGeography),
                                _bnd_func.ST_GeomFromText(wkt, 4326).cast(
                                    _BndGeography
                                ),
                                200,
                            ),
                            _BndCalc.id != calculation_id,
                        )
                        .all()
                    )
                    relations = _bnd_detect(
                        _bnd_mapping(_merged),
                        existing,
                        _BndGapParams(adjacency_m=200, min_fragment_ha=0.001),
                    )
                    has = any(
                        float(r.overlap_ha or 0) > 0 for r in relations
                    )  # clip-only: overlap gates the review, gaps do not
                    if has:
                        _bnd_by_id: dict[str, dict] = {}
                        for _c in existing:
                            if _c.boundary_geom is not None:
                                try:
                                    from geoalchemy2.shape import (
                                        to_shape as _bnd_to_shape,
                                    )

                                    _bnd_by_id[str(_c.id)] = _bnd_mapping(
                                        _bnd_to_shape(_c.boundary_geom)
                                    )
                                except Exception:
                                    logger.warning(
                                        "boundary-overlap preview: neighbour %s geometry "
                                        "unreadable - overlay omits it",
                                        _c.id,
                                        exc_info=True,
                                    )
                                    _bnd_by_id[str(_c.id)] = None  # type: ignore[assignment]
                        gaps = []
                        gap_total = _BndDecimal("0")
                        for r in relations:
                            gap_geom = None
                            if r.gap_polygon is not None and not r.gap_polygon.is_empty:
                                gap_geom = _bnd_mapping(r.gap_polygon)
                            gaps.append(
                                _BndGapForest(
                                    id=_BndUUID(r.id),
                                    name=r.name,
                                    name_np=r.name_np,
                                    overlap_ha=_BndDecimal(str(r.overlap_ha)),
                                    gap_ha=_BndDecimal(str(r.gap_ha)),
                                    gap_shape=r.gap_shape,
                                    gap_size=r.gap_size,
                                    gap_geometry=gap_geom,
                                    adjacent=r.adjacent,
                                    geometry=_bnd_by_id.get(str(r.id)),
                                )
                            )
                            gap_total += _BndDecimal(str(r.gap_ha))
                        gap_total = round(gap_total, 4)
                        overlapping = []
                        for r in relations:
                            if float(r.overlap_ha or 0) > 0:
                                overlapping.append(
                                    _BndOverlappingForest(
                                        id=_BndUUID(r.id),
                                        name=r.name,
                                        name_np=r.name_np,
                                        overlap_ha=_BndDecimal(str(r.overlap_ha)),
                                        forest_area_ha=_BndDecimal("0"),
                                        gap_ha=_BndDecimal(str(r.gap_ha)),
                                        gap_shape=r.gap_shape,
                                        gap_size=r.gap_size,
                                        adjacent=r.adjacent,
                                        geometry=_bnd_by_id.get(str(r.id)),
                                    )
                                )
                        return {
                            "needs_overlap_review": True,
                            "provisional": True,
                            "overlapping_forests": [
                                o.model_dump(mode="json") for o in overlapping
                            ],
                            "gaps": [g.model_dump(mode="json") for g in gaps],
                            "gap_total_ha": float(gap_total),
                            "preview_geometry": _bnd_mapping(_merged),
                        }
                except HTTPException:
                    raise
                except Exception as e:
                    logger.warning(
                        f"[convert-to-builtin] preview gate failed, falling through to write: {e}"
                    )

            _ar = calculation.result_data or {}
            _ar["geometry"] = mapping(_merged)
            _, _area_ha = calculate_area_geodesic_from_shapely(_merged)
            _ar["area_hectares"] = round(_area_ha, 4)
            calculation.result_data = _ar
            calculation.boundary_geom = _bnd_fs(_merged, srid=4326)
            flag_modified(calculation, "result_data")
            from app.services.boundary_pieces_service import sync_boundary_pieces

            sync_boundary_pieces(db, calculation, _merged)
            # A new boundary: sub-areas already on record must lie inside it.
            from app.services.sub_area_reclip_service import reclip_after_boundary_write

            reclip_after_boundary_write(db, calculation, _merged)
            _n_blocks = (
                db.query(ForestBlock)
                .filter(
                    ForestBlock.calculation_id == calculation_id,
                    ForestBlock.is_compartment != True,
                    ForestBlock.division_level == DEPTH_TOP_BLOCK,
                )
                .count()
            )
            if _n_blocks == 0:
                from app.utils.single_part_geometry import (
                    explode_and_filter_slivers as _bd_explode,
                )

                _bd_parts = _bd_explode([_merged])
                for _bd_i, _bd_part in enumerate(_bd_parts):
                    _bd_sqm, _bd_ha = calculate_area_geodesic_from_shapely(_bd_part)
                    db.add(
                        ForestBlock(
                            calculation_id=calculation_id,
                            name=f"B{_bd_i + 1}"
                            if len(_bd_parts) > 1
                            else "B1",
                            geometry=func.ST_GeomFromText(
                                shapely_wkt.dumps(_bd_part), 4326
                            ),
                            area_hectares=round(_bd_ha, 4),
                            index=_bd_i,
                            division_level=DEPTH_TOP_BLOCK,
                            is_compartment=False,
                            is_locked=False,
                        )
                    )
            layer.deleted_at = func.now()
            layer.updated_at = func.now()
            db.commit()
            calculation.geometry_version = (calculation.geometry_version or 0) + 1
            db.commit()
            logger.info(
                f"convert-to-builtin: boundary set from imported layer {layer_id}"
            )
            return {
                "success": True,
                "feature_id": None,
                "target_type": "boundary",
                "geometry": mapping(_merged),
                "area_hectares": round(_area_ha, 4),
                "swapped_fixed": _swapped_fixed,
            }

        # Replace-safety (U-5/Task 5.3): compartments/sub-compartments imports REPLACE
        # the derived state. A pre-flight gate requires explicit confirmation before
        # any write, and a snapshot backup is kept so a wrong-file import is restorable.
        # FS-4a.19: sub_blocks joins the replace family — a sub-block import replaces
        # the derived block-branch rows below the top-level blocks.
        from app.core.constants import IMPORT_PURPOSE_REPLACE

        target_is_compartment_replace = target_type in (
            "compartments",
            "compartment",
            "sub_compartments",
            "sub_compartment",
            "sub_blocks",
            "sub_block",
        )
        confirm = bool(request.get("confirm", False))
        if target_is_compartment_replace:
            from geoalchemy2.shape import to_shape as g_to_shape

            n_sub_blocks = 0
            if target_type in ("sub_blocks", "sub_block"):
                # FS-4a.19: block-branch mirror of sub-compartments — derived rows
                # are the non-compartment rows at or below the sub level.
                derived = (
                    db.query(ForestBlock)
                    .filter(
                        ForestBlock.calculation_id == calculation_id,
                        ForestBlock.is_compartment == False,
                        ForestBlock.division_level >= DEPTH_SUB,
                    )
                    .all()
                )
                _need_block = (
                    db.query(ForestBlock)
                    .filter(
                        ForestBlock.calculation_id == calculation_id,
                        ForestBlock.is_compartment == False,
                        ForestBlock.division_level == DEPTH_TOP_BLOCK,
                    )
                    .count()
                )
                if _need_block == 0:
                    raise HTTPException(
                        status_code=400,
                        detail="At least one block must exist before importing sub-blocks",
                    )
            elif target_type in ("sub_compartments", "sub_compartment"):
                derived = (
                    db.query(ForestBlock)
                    .filter(
                        ForestBlock.calculation_id == calculation_id,
                        ForestBlock.is_compartment == True,
                        ForestBlock.division_level >= DEPTH_SUB,
                    )
                    .all()
                )
                # FS-1c.1: missing `is_compartment` guard - migration 094 puts top-level blocks
                # at this same depth, so without it a block-only forest would wrongly appear to
                # already have a compartment (I10).
                _need_compartment = (
                    db.query(ForestBlock)
                    .filter(
                        ForestBlock.calculation_id == calculation_id,
                        ForestBlock.is_compartment == True,
                        ForestBlock.division_level == DEPTH_TOP_COMPARTMENT,
                    )
                    .count()
                )
                if _need_compartment == 0:
                    raise HTTPException(
                        status_code=400,
                        detail="At least one compartment must exist before importing sub-compartments",
                    )
            else:
                derived = (
                    db.query(ForestBlock)
                    .filter(
                        ForestBlock.calculation_id == calculation_id,
                        ForestBlock.is_compartment == True,
                    )
                    .all()
                )
            # FS-4a.19: the compartment-branch filter keeps only compartment rows
            # (blocks at the same depth must not count — I10). Sub-block replaces
            # keep the non-compartment derived rows instead.
            if target_type in ("sub_blocks", "sub_block"):
                n_sub_blocks = len(derived)
                n_comp = 0
                n_sub = 0
            else:
                derived = [d for d in derived if d.is_compartment]
                n_comp = sum(1 for d in derived if (d.division_level or 0) == DEPTH_TOP_COMPARTMENT)
                n_sub = sum(1 for d in derived if (d.division_level or 0) >= DEPTH_SUB)

            # Cascade flags: existing sub-compartments falling outside the NEW
            # imported compartment boundaries are flagged (never silently orphaned).
            cascade_flags = []
            if target_type in ("compartments", "compartment") and n_sub:
                from shapely.ops import unary_union as _uu

                new_shapes = []
                for _feat in features:
                    _g = _feat.get("geometry")
                    if not _g:
                        continue
                    try:
                        _s = (
                            shape(_g)
                            if not isinstance(_g, str)
                            else shapely_wkt.loads(_g)
                        )
                        if not _s.is_empty:
                            new_shapes.append(_s)
                    except Exception:
                        logger.exception(
                            "replacement component dropped from the union - the "
                            "resulting extent is smaller than the real one"
                        )
                        continue
                if new_shapes:
                    _new_union = _uu(new_shapes)
                    for _d in derived:
                        if (getattr(_d, "division_level", 0) or 0) >= DEPTH_SUB:
                            try:
                                _ds = g_to_shape(_d.geometry)
                                if _ds.is_empty or not _new_union.covers(
                                    _ds.representative_point()
                                ):
                                    cascade_flags.append(str(_d.id))
                            except Exception:
                                # A division that cannot be read is not flagged,
                                # so the pre-flight tells the user fewer children
                                # will be orphaned than actually will be.
                                logger.exception(
                                    "cascade check skipped division %s - the "
                                    "replace pre-flight may understate what it "
                                    "orphans",
                                    getattr(_d, "id", "?"),
                                )

            if (n_comp + n_sub + n_sub_blocks) > 0 and not confirm:
                logger.info(
                    f"convert-to-builtin: pre-flight confirm required for {target_type} (replace {n_comp} compartments, {n_sub} sub-compartments, {n_sub_blocks} sub-blocks)"
                )
                return {
                    "success": False,
                    "needs_confirmation": True,
                    "replace_summary": {
                        "compartments": n_comp,
                        "sub_compartments": n_sub,
                        "sub_blocks": n_sub_blocks,
                        "cascade_flags": cascade_flags,
                    },
                    "message": f"This will replace {n_comp} compartment(s), {n_sub} sub-compartment(s) and {n_sub_blocks} sub-block(s). Proceed?",
                    "target_type": target_type,
                }

            # Snapshot backup (never hard-delete): store the derived geometry rows in
            # result_data JSONB under a reserved key for undo/rollback.
            if derived:
                backup_items = []
                for _d in derived:
                    try:
                        backup_items.append(
                            {
                                "id": str(_d.id),
                                "name": _d.name,
                                "division_level": _d.division_level,
                                "parent_block_id": (
                                    str(_d.parent_block_id)
                                    if _d.parent_block_id
                                    else None
                                ),
                                "is_locked": bool(_d.is_locked),
                                "color": _d.color,
                                "child_count": _d.child_count,
                                "display_order": _d.display_order,
                                "area_hectares": _d.area_hectares,
                                "geometry": json.loads(
                                    db.query(func.ST_AsGeoJSON(_d.geometry).label("gj"))
                                    .first()
                                    .gj
                                    or "null"
                                ),
                            }
                        )
                    except Exception as e:
                        logger.warning(
                            f"convert-to-builtin: backup row {_d.id} failed: {e}"
                        )
                _rd = calculation.result_data or {}
                _backups = _rd.get("_geometry_import_backups") or []
                _backups.append(
                    {
                        "target_type": target_type,
                        "purpose": layer.purpose,
                        "created_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                        "items": backup_items,
                    }
                )
                _rd["_geometry_import_backups"] = _backups
                calculation.result_data = _rd
                flag_modified(calculation, "result_data")
                logger.info(
                    f"convert-to-builtin: backed up {len(backup_items)} derived rows before {target_type} replace"
                )

        created_count = 0
        total_area = 0.0
        # P7/R4: post-import validation counters surfaced in the response.
        import_warnings = {
            "imported": 0,
            "clipped": 0,
            "removed": 0,
            "overlapped": 0,
            "dropped_unclosed": 0,
        }
        removed_count = 0
        # U-3/Task 3.2 diagnostics: per-step geometry census for the KML repro.
        diag = {
            "parsed": 0,
            "empty": 0,
            "parse_failed": 0,
            "clipped_away": 0,
            "overlapped_away": 0,
            "zero_area_skipped": 0,
        }

        # Clear existing blocks once before adding new ones (overwrite behavior)
        if target_type in ("blocks", "block"):
            db.query(ForestBlock).filter(
                ForestBlock.calculation_id == calculation_id
            ).delete()
            db.flush()

        # Replace derived compartments/sub-compartments (U-5/Task 5.2 replace
        # semantics): after the T5.3 backup above, drop the derived rows so the
        # imported prepared polygons become the truth.
        if target_type in ("compartments", "compartment"):
            db.query(ForestBlock).filter(
                ForestBlock.calculation_id == calculation_id,
                ForestBlock.is_compartment == True,
            ).delete(synchronize_session=False)
            db.flush()
        elif target_type in ("sub_compartments", "sub_compartment"):
            db.query(ForestBlock).filter(
                ForestBlock.calculation_id == calculation_id,
                ForestBlock.is_compartment == True,
                ForestBlock.division_level >= DEPTH_SUB,
            ).delete(synchronize_session=False)
            db.flush()
        elif target_type in ("sub_blocks", "sub_block"):
            # FS-4a.19: block-branch replace — drop the non-compartment derived
            # rows at/below the sub level so the imported polygons become the truth.
            db.query(ForestBlock).filter(
                ForestBlock.calculation_id == calculation_id,
                ForestBlock.is_compartment == False,
                ForestBlock.division_level >= DEPTH_SUB,
            ).delete(synchronize_session=False)
            db.flush()

        for idx, feature in enumerate(features):
            geom = feature.get("geometry")
            if not geom:
                logger.warning(
                    f"convert-to-builtin: feature {idx} has no geometry, keys={list(feature.keys())}"
                )
                diag["parse_failed"] += 1
                continue
            diag["parsed"] += 1

            try:
                # Handle both GeoJSON dict and WKT string
                if isinstance(geom, str):
                    # WKT string - parse with shapely
                    geom_shape = shapely_wkt.loads(geom)
                else:
                    # GeoJSON dict - parse with shapely.shape
                    geom_shape = shape(geom)

                if geom_shape.is_empty:
                    logger.warning(
                        f"convert-to-builtin: feature {idx} geometry is empty"
                    )
                    diag["empty"] += 1
                    continue

                # U-3/Task 3.2: log geometry census (valid / type / area / crs-like
                # extent) at parse time so a KML "No valid geometries" is diagnosable.
                try:
                    logger.info(
                        f"convert-to-builtin: feature {idx} type={geom_shape.geom_type} "
                        f"valid={getattr(geom_shape, 'is_valid', None)} "
                        f"minx={(geom_shape.bounds[0] if not geom_shape.is_empty else None)} "
                        f"miny={(geom_shape.bounds[1] if not geom_shape.is_empty else None)} "
                        f"maxx={(geom_shape.bounds[2] if not geom_shape.is_empty else None)} "
                        f"maxy={(geom_shape.bounds[3] if not geom_shape.is_empty else None)} "
                        f"area_deg={geom_shape.area if not geom_shape.is_empty else 0}"
                    )
                except Exception:  # noqa: BLE001,S110 -- diagnostic only, must not fail the import
                    pass

                # Calculate geodesic area
                area_sqm, area_hectares = calculate_area_geodesic_from_shapely(
                    geom_shape
                )
                area_hectares = round(area_hectares, 4)

                # Zero-area (point/line/degenerate) geometries can never become a
                # ForestBlock: `forest_blocks` enforces CHECK (area_hectares > 0).
                if (
                    geom_shape.geom_type not in ("Polygon", "MultiPolygon")
                    or area_hectares <= 0
                ):
                    logger.warning(
                        f"convert-to-builtin: feature {idx} type={geom_shape.geom_type} "
                        f"area_ha={area_hectares} cannot form a block/compartment — skipped"
                    )
                    diag["zero_area_skipped"] += 1
                    import_warnings["zero_area"] = (
                        import_warnings.get("zero_area", 0) + 1
                    )
                    continue

                # Get name from properties
                props = feature.get("properties", {})
                name = (
                    props.get("name")
                    or props.get("Name")
                    or props.get("NAME")
                    or f"{target_type.rstrip('s').title()} {idx + 1}"
                )

                if target_type in ("blocks", "block"):
                    # One row = one selectable map feature (single_part_geometry.py):
                    # a source MultiPolygon (or a clip that splits into several
                    # disjoint substantial islands) becomes N ForestBlock rows,
                    # never a single MultiPolygon row.
                    from app.utils.single_part_geometry import (
                        explode_and_filter_slivers as _bk_explode,
                    )

                    _bk_parts = _bk_explode([geom_shape])
                    if not _bk_parts:
                        diag["zero_area_skipped"] += 1
                        import_warnings["zero_area"] = (
                            import_warnings.get("zero_area", 0) + 1
                        )
                        continue
                    for _bk_i, _bk_part in enumerate(_bk_parts):
                        _bk_sqm, _bk_ha = calculate_area_geodesic_from_shapely(
                            _bk_part
                        )
                        _bk_ha = round(_bk_ha, 4)
                        _bk_name = (
                            f"{name} {_bk_i + 1}"
                            if len(_bk_parts) > 1
                            else name
                        )
                        _bk_block = ForestBlock(
                            calculation_id=calculation_id,
                            name=_bk_name,
                            geometry=func.ST_GeomFromText(
                                shapely_wkt.dumps(_bk_part), 4326
                            ),
                            area_hectares=_bk_ha,
                            index=created_count,
                            division_level=DEPTH_TOP_BLOCK,
                            is_compartment=False,
                        )
                        db.add(_bk_block)
                        created_count += 1
                        total_area += _bk_ha

                if target_type in (
                    "compartments",
                    "compartment",
                    "sub_compartments",
                    "sub_compartment",
                    "sub_blocks",
                    "sub_block",
                ):
                    # Imported prepared compartments become the truth: they replace the
                    # derived compartments/sub-compartments for this workspace (backed up
                    # above in T5.3). Each imported polygon becomes a compartment
                    # (a top-level compartment) or sub-compartment (one level deeper).
                    # FS-4a.19: sub-block imports are the block-branch mirror — each
                    # imported polygon becomes a sub-block under its containing block.
                    from app.services.sub_area_service import clip_to_region

                    # Containment region:
                    #  - compartments clip to boundary ∪ blocks (like sub-areas)
                    #  - sub-compartments clip to the union of existing compartments
                    #  - sub-blocks clip to the union of existing top-level blocks
                    region_components = []
                    is_sub_comp = target_type in ("sub_compartments", "sub_compartment")
                    is_sub_block = target_type in ("sub_blocks", "sub_block")
                    if is_sub_block:
                        # FS-4a.19: block-branch parent lookup — top-level blocks are
                        # the containment region AND the parent candidates.
                        _block_rows = (
                            db.query(ForestBlock)
                            .filter(
                                ForestBlock.calculation_id == calculation_id,
                                ForestBlock.division_level == DEPTH_TOP_BLOCK,
                                ForestBlock.is_compartment == False,
                            )
                            .all()
                        )
                        for _blk_row in _block_rows:
                            try:
                                region_components.append(g_to_shape(_blk_row.geometry))
                            except Exception:
                                logger.exception(
                                    "block %s dropped from the clip region "
                                    "- sub-blocks over it will be clipped away",
                                    getattr(_blk_row, "id", "?"),
                                )
                    elif not is_sub_comp:
                        if calculation.boundary_geom is not None:
                            region_components.append(calculation.boundary_geom)
                        for _b in (calculation.result_data or {}).get("blocks", []):
                            _bg = _b.get("geometry")
                            if _bg:
                                try:
                                    region_components.append(shape(_bg))
                                except Exception:
                                    # A block missing from the clip region means
                                    # features over it get clipped away as if it
                                    # were outside the forest.
                                    logger.exception(
                                        "block dropped from the clip region - "
                                        "features over it will be clipped away"
                                    )
                    else:
                        _parent_rows = (
                            db.query(ForestBlock)
                            .filter(
                                ForestBlock.calculation_id == calculation_id,
                                ForestBlock.division_level == DEPTH_TOP_COMPARTMENT,
                                ForestBlock.is_compartment == True,
                            )
                            .all()
                        )
                        for _comp_row in _parent_rows:
                            try:
                                region_components.append(g_to_shape(_comp_row.geometry))
                            except Exception:
                                logger.exception(
                                    "compartment %s dropped from the clip region "
                                    "- sub-compartments over it will be clipped "
                                    "away",
                                    getattr(_comp_row, "id", "?"),
                                )
                    _clipped_geojson, _clipped_flag = clip_to_region(
                        mapping(geom_shape), region_components
                    )
                    if _clipped_geojson is None:
                        logger.warning(
                            f"convert-to-builtin: {target_type} feature {idx} fully outside region — removed"
                        )
                        import_warnings["removed"] += 1
                        diag["clipped_away"] += 1
                        continue
                    _store_shape = (
                        shape(_clipped_geojson) if _clipped_flag else geom_shape
                    )
                    # One row = one selectable map feature (single_part_geometry.py):
                    # a source MultiPolygon (or a clip that splits the feature into
                    # several disjoint substantial islands) becomes N ForestBlock rows,
                    # never a single MultiPolygon row. Each part gets its own parent
                    # lookup so sub-blocks/sub-compartments still attach correctly.
                    from app.utils.single_part_geometry import (
                        explode_and_filter_slivers as _ctb_explode,
                    )

                    _store_parts = _ctb_explode([_store_shape])
                    if not _store_parts:
                        logger.warning(
                            f"convert-to-builtin: {target_type} feature {idx} has no "
                            "substantial area after sliver filtering — removed"
                        )
                        import_warnings["removed"] += 1
                        diag["clipped_away"] += 1
                        continue
                    for _sp_i, _store_part in enumerate(_store_parts):
                        _part_area_sqm, _part_area_ha = (
                            calculate_area_geodesic_from_shapely(_store_part)
                        )
                        _part_area_ha = round(_part_area_ha, 4)
                        # Compartments/sub-blocks clip to region components already;
                        # per-part name/code carry the part index so multi-row
                        # explosions stay distinguishable in the attribute table.
                        _part_name = (
                            f"{name} {_sp_i + 1}"
                            if len(_store_parts) > 1
                            else name
                        )
                        new_block = ForestBlock(
                            calculation_id=calculation_id,
                            name=_part_name,
                            geometry=func.ST_GeomFromText(
                                shapely_wkt.dumps(_store_part), 4326
                            ),
                            area_hectares=_part_area_ha,
                            index=created_count,
                            division_level=DEPTH_SUB
                            if (is_sub_comp or is_sub_block)
                            else DEPTH_TOP_COMPARTMENT,
                            is_compartment=not is_sub_block,
                            is_locked=False,
                            compartment_code=None
                            if is_sub_block
                            else (
                                _unit_code(target_type, idx + 1)
                                if len(_store_parts) == 1
                                else f"{_unit_code(target_type, idx + 1)}-{_sp_i + 1}"
                            ),
                        )
                        # Sub-compartments attach to their containing compartment;
                        # sub-blocks attach to their containing top-level block.
                        if is_sub_comp or is_sub_block:
                            _rep_pt = _store_part.representative_point()
                            _parent_id = None
                            _parent_rows = (
                                _block_rows if is_sub_block else _parent_rows
                            )
                            for _parent_row in _parent_rows:
                                try:
                                    if g_to_shape(_parent_row.geometry).covers(_rep_pt):
                                        _parent_id = _parent_row.id
                                        break
                                except Exception:
                                    # Skipping a candidate can leave parent_block_id
                                    # NULL on a sub-unit that does have a
                                    # parent, detaching it from the hierarchy.
                                    logger.exception(
                                        "parent lookup skipped %s %s - the "
                                        "sub-unit may be stored unparented",
                                        "block" if is_sub_block else "compartment",
                                        getattr(_parent_row, "id", "?"),
                                    )
                                    continue
                            new_block.parent_block_id = _parent_id
                        db.add(new_block)
                        created_count += 1
                        total_area += _part_area_ha
                        import_warnings["imported"] += 1

                if target_type in ("sub_areas", "sub_area"):
                    # Sub-areas are stored in result_data, not a separate model
                    from datetime import datetime, timezone
                    from shapely.ops import unary_union
                    from app.utils.geometry_utils import compute_geometry_properties

                    # Placement (inside the forest, never overlapping another sub-area) is decided
                    # in ONE place -- place_sub_area -- for every writer. Features imported in this
                    # same run are already in result_data, so each one gives way to those before it.
                    from app.services.sub_area_service import (
                        place_sub_area,
                        SubAreaPlacementError,
                    )

                    blocks_for_breakdown = (calculation.result_data or {}).get(
                        "blocks", []
                    )
                    try:
                        _placement = place_sub_area(db, calculation, geom_shape)
                    except SubAreaPlacementError as _exc:
                        import_warnings["removed"] += 1
                        removed_count += 1
                        if _exc.reason == "covered":
                            import_warnings["overlapped"] += 1
                            diag["overlapped_away"] += 1
                            logger.warning(
                                f"convert-to-builtin: sub-area feature {idx} overlaps existing and left nothing - removed"
                            )
                        else:
                            diag["clipped_away"] += 1
                            logger.warning(
                                f"convert-to-builtin: sub-area feature {idx} not placeable ({_exc.reason}) - removed"
                            )
                        continue
                    geom_shape = _placement.geometry
                    if _placement.clipped_to_forest:
                        import_warnings["clipped"] += 1
                    if _placement.overlap_removed:
                        import_warnings["overlapped"] += 1

                    # Compute block breakdown (on the clipped geometry)
                    block_breakdown = calculate_block_breakdown(
                        mapping(geom_shape), blocks_for_breakdown
                    )

                    # Determine primary block
                    primary_block_id = None
                    primary_block_name = None
                    if block_breakdown:
                        primary = max(block_breakdown, key=lambda x: x.get("area", 0))
                        primary_block_id = primary.get("blockId")
                        primary_block_name = primary.get("blockName")

                    # Get category from properties or default, validating against the enum
                    from app.schemas.forest import SubAreaCategory
                    from app.services.sub_area_service import auto_detect_category

                    valid_categories = SubAreaCategory.valid_categories()
                    raw_category = auto_detect_category(props)
                    if raw_category not in valid_categories:
                        logger.warning(
                            f"convert-to-builtin: feature {idx} has invalid category '{raw_category}', defaulting to 'protected'"
                        )
                        category = "protected"
                    else:
                        category = raw_category
                    is_excluded = (
                        props.get("is_excluded") or props.get("isExcluded") or False
                    )

                    # Recompute area from the (possibly clipped) geometry
                    area_sqm, area_hectares = calculate_area_geodesic_from_shapely(
                        geom_shape
                    )
                    area_hectares = round(area_hectares, 4)

                    sub_area_id = str(uuid.uuid4())
                    new_sub_area = {
                        "id": sub_area_id,
                        "name": name,
                        "category": category,
                        "geometry": mapping(geom_shape),
                        "area_sqm": round(area_sqm, 4),
                        "area_hectares": area_hectares,
                        "blockId": primary_block_id,
                        "blockName": primary_block_name,
                        "blockBreakdown": block_breakdown,
                        "isExcluded": is_excluded,
                        "created_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                    }

                    # Initialize sub_areas array if needed
                    result_data = calculation.result_data or {}
                    if "sub_areas" not in result_data:
                        result_data["sub_areas"] = []

                    if _placement.pending_boundary_clip:
                        # No forest yet: clipped to the boundary the moment one goes live.
                        new_sub_area["pending_boundary_clip"] = True

                    result_data["sub_areas"].append(new_sub_area)
                    result_data["sub_areas_count"] = len(result_data["sub_areas"])
                    import_warnings["imported"] += 1

                    # Recalculate excluded area
                    excluded_total = calculate_total_excluded_area(
                        result_data["sub_areas"]
                    )
                    result_data["excluded_area_hectares"] = round(excluded_total, 4)

                    # Recalculate effective area
                    total_area_calc = result_data.get("area_hectares", 0)
                    result_data["effective_area_hectares"] = round(
                        total_area_calc - excluded_total, 4
                    )

                    # Recalculate per-block excluded/effective areas
                    blocks = result_data.get("blocks", [])
                    block_excluded_map = calculate_block_excluded_areas(
                        blocks, result_data["sub_areas"]
                    )
                    for block in blocks:
                        block_id = block.get("block_id")
                        block_excluded = block_excluded_map.get(block_id, 0.0)
                        block["excluded_area_hectares"] = round(block_excluded, 4)
                        original_area = block.get("area_hectares", 0)
                        block["effective_area_hectares"] = round(
                            original_area - block_excluded, 4
                        )

                    result_data["blocks"] = blocks
                    calculation.result_data = result_data
                    flag_modified(calculation, "result_data")

                    created_count += 1
                    total_area += new_sub_area["area_hectares"]

            except Exception as e:
                logger.error(
                    f"convert-to-builtin: Failed to convert feature {idx}: {e}",
                    exc_info=True,
                )
                continue

        if created_count == 0:
            logger.warning(
                f"convert-to-builtin: No valid geometries to convert, features={len(features)}, "
                f"diag={diag}, import_warnings={import_warnings}"
            )
            # U-3/Task 3.2: surface the actual cause instead of a bare 400 so the
            # KML "No valid geometries" failure is diagnosable (not the empty-clip
            # theory — clip_to_region returns unchanged for empty regions).
            if diag["clipped_away"] > 0 and diag["clipped_away"] >= diag["parsed"]:
                detail = (
                    "All imported geometries fall entirely outside the forest boundary/blocks "
                    "and were removed. Check the file's coordinate system or that it covers "
                    "the existing boundary."
                )
            elif diag["empty"] > 0:
                detail = "Imported geometries are empty (no usable coordinates)."
            elif diag["overlapped_away"] > 0:
                detail = "All imported geometries overlap existing sub-areas entirely and left nothing."
            else:
                detail = "No valid geometries to convert"
            raise HTTPException(status_code=400, detail=detail)

        # Soft-delete the imported layer
        layer.deleted_at = func.now()
        layer.updated_at = func.now()

        db.commit()

        # U-6 auto-derive forest boundary (invariant C) + single-block forest (E)
        # + naming guard (T6.7), all inside one atomic transaction (T6.5) so a
        # mid-way failure never leaves partial derived state.
        _boundary_derived_this_import = False
        from app.utils.db import atomic_transaction

        with atomic_transaction(
            db, f"convert-to-builtin auto-derive calc={calculation_id}"
        ):
            if (
                target_type in ("blocks", "block", "compartments", "compartment")
                and calculation.boundary_geom is None
            ):
                from geoalchemy2.shape import to_shape as _der_to_shape
                from app.services.file_processor import derive_boundary_from_polygons

                bc_rows = (
                    db.query(ForestBlock)
                    .filter(
                        ForestBlock.calculation_id == calculation_id,
                    )
                    .all()
                )
                _poly_shapes = []
                for _br in bc_rows:
                    if target_type in ("blocks", "block"):
                        # FS-1c.1: migration 094 puts top-level compartments at the same depth as
                        # top-level blocks, so the branch (is_compartment) must be checked too (I10).
                        if (
                            not getattr(_br, "is_compartment", False)
                            and (getattr(_br, "division_level", 0) or 0)
                            == DEPTH_TOP_BLOCK
                        ):
                            try:
                                _poly_shapes.append(_der_to_shape(_br.geometry))
                            except Exception:
                                # The boundary is DERIVED from these polygons.
                                # One dropped here is one missing from the
                                # forest outline, and nothing downstream knows.
                                logger.exception(
                                    "block %s dropped from the derived boundary "
                                    "- the forest outline will be missing it",
                                    getattr(_br, "id", "?"),
                                )
                                continue
                    else:
                        try:
                            _poly_shapes.append(_der_to_shape(_br.geometry))
                        except Exception:
                            logger.exception(
                                "division %s dropped from the derived boundary "
                                "- the forest outline will be missing it",
                                getattr(_br, "id", "?"),
                            )
                            continue
                _boundary = derive_boundary_from_polygons(_poly_shapes)
                if _boundary is not None and not _boundary.is_empty:
                    from geoalchemy2.shape import from_shape as _der_from_shape

                    boundary_name = (
                        calculation.forest_name or "Auto-derived Boundary"
                    )  # T6.7 name guard
                    calculation.boundary_geom = _der_from_shape(_boundary, srid=4326)
                    from app.services.boundary_pieces_service import sync_boundary_pieces

                    sync_boundary_pieces(db, calculation, _boundary)
                    _ar = calculation.result_data or {}
                    _ar["geometry"] = mapping(_boundary)
                    _ar["boundary_name"] = boundary_name
                    calculation.result_data = _ar
                    flag_modified(calculation, "result_data")
                    _boundary_derived_this_import = True
                    from app.services.sub_area_reclip_service import (
                        reclip_after_boundary_write,
                    )

                    reclip_after_boundary_write(db, calculation, _boundary)
                    logger.info(
                        f"convert-to-builtin: auto-derived boundary for calc {calculation_id} (name={boundary_name})"
                    )

            # T6.3 single-block forest: REMOVED (FS-2.4/FS-2.8 + C1-C3 / Q5 —
            # "no automatic single block for a new forest"). Importing / deriving
            # a boundary never silently mints a block; the first unit is the
            # user's explicit choice (createSingleBlock, whole-forest
            # auto-create, root-divide, or a blocks import target).

        # BLOCK_BOUNDARY_INVARIANT (E.5): after blocks/compartments import, enforce
        # total block area ≡ boundary area — reject over-coverage, silently
        # auto-fill uncovered boundary area as a Remainder Block/Compartment.
        #
        # If the boundary was AUTO-DERIVED from these very imported polygons
        # (no boundary existed before this import), the imported blocks already
        # define the forest boundary and trivially cover it — skip enforcement
        # so a heal-buffer micro-shrink never trips a 409 TOPOLOGY_REJECTED.
        if (
            target_type in ("blocks", "block", "compartments", "compartment")
            and not _boundary_derived_this_import
        ):
            from app.services.block_area_invariant_service import enforce_block_coverage

            try:
                _inv_result = enforce_block_coverage(
                    db,
                    calculation,
                    level=(
                        "compartments"
                        if target_type in ("compartments", "compartment")
                        else "blocks"
                    ),
                )
                if _inv_result.get("remainder_added"):
                    import_warnings["remainder_added"] = 1
                    logger.info(
                        f"convert-to-builtin: remainder {'compartment' if target_type in ('compartments', 'compartment') else 'block'} "
                        f"auto-added for uncovered boundary area ({_inv_result.get('gap_ha', 0):.4f} ha)"
                    )
            except ValueError as _ve:
                if str(_ve) == "TOPOLOGY_REJECTED":
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={
                            "code": "TOPOLOGY_REJECTED",
                            "message": "Import rejected: imported blocks/compartments would exceed the forest boundary area (overlapping or over-coverage).",
                        },
                    )
                raise

        # Bump geometry version to trigger frontend layer refresh
        calculation = (
            db.query(Calculation).filter(Calculation.id == calculation_id).first()
        )
        if calculation:
            calculation.geometry_version = (calculation.geometry_version or 0) + 1
            db.commit()

        # Update calculation result_data with new blocks
        calculation = (
            db.query(Calculation).filter(Calculation.id == calculation_id).first()
        )
        if calculation and calculation.result_data:
            # Re-fetch all blocks
            from app.models.forest_block import ForestBlock

            all_blocks = (
                db.query(ForestBlock)
                .filter(ForestBlock.calculation_id == calculation_id)
                .all()
            )

            blocks_for_result = []
            for block in all_blocks:
                geojson_result = db.query(
                    func.ST_AsGeoJSON(block.geometry).label("geojson")
                ).first()
                from app.utils.geometry_utils import compute_geometry_properties

                if geojson_result and geojson_result.geojson:
                    try:
                        geom_shape = shape(json.loads(geojson_result.geojson))
                        geo_props = compute_geometry_properties(geom_shape)
                    except Exception:
                        logger.warning(
                            "derived geometry properties unavailable - area and "
                            "perimeter omitted for this feature",
                            exc_info=True,
                        )
                        geo_props = {}
                else:
                    geo_props = {}

                blocks_for_result.append(
                    {
                        "id": str(block.id),
                        "block_index": block.index,
                        "block_name": block.name,
                        "area_hectares": round(block.area_hectares, 4),
                        "geometry": (
                            json.loads(geojson_result.geojson)
                            if geojson_result and geojson_result.geojson
                            else None
                        ),
                        **geo_props,
                    }
                )

            calculation.result_data["blocks"] = blocks_for_result
            flag_modified(calculation, "result_data")
            db.commit()

        return {
            "success": True,
            "created": created_count,
            "total_area_hectares": round(total_area, 4),
            "target_type": target_type,
            "import_summary": import_warnings,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"convert-to-builtin: Unexpected error: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Conversion failed: {str(e)}")


class PolygonFromPointsRequest(BaseModel):
    """Case E interactive: points picked on the map → polygon via the shared engine."""

    points: List[List[float]]  # [[lng, lat], ...]
    target_type: str = (
        "blocks"  # blocks | compartments | sub_compartments | sub_blocks | sub_areas | boundary
    )
    name: Optional[str] = None


@router.post("/workspace/{calculation_id}/polygon-from-points")
def polygon_from_points(
    calculation_id: UUID,
    request: PolygonFromPointsRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Case E (interactive): user clicks N points on the map → shared engine's
    case-D hull path (concave hull, island clustering) → one polygon stored on
    the requested built-in polygon layer.

    Guards (Task 4.1): require >= 3 distinct non-collinear points; auto-close
    the ring; a degenerate result (zero area) is rejected with a clear reason.
    The result is appended (not replacing) using the same storage branch as
    import-to-builtin for the chosen purpose.
    """
    try:
        from app.models.forest_block import ForestBlock
        from app.utils.geometry_utils import calculate_area_geodesic_from_shapely
        from shapely import wkt as shapely_wkt
        import uuid

        calculation = _require_calculation_access(db, calculation_id, current_user)

        pts = request.points or []
        if len(pts) < 3:
            raise HTTPException(
                status_code=400, detail="Need at least 3 points to create a polygon"
            )

        # Deduplicate exact-coincident clicks and drop NaN/None values.
        clean = []
        seen = set()
        for p in pts:
            if not isinstance(p, (list, tuple)) or len(p) < 2:
                continue
            lng, lat = float(p[0]), float(p[1])
            key = (round(lng, 8), round(lat, 8))
            if key in seen:
                continue
            seen.add(key)
            clean.append(Point(lng, lat))
        if len(clean) < 3:
            raise HTTPException(
                status_code=400,
                detail="Need at least 3 distinct points to create a polygon",
            )

        # Collinearity guard (Task 4.1: non-collinear points). Build a closed
        # ring from the clicks; if it's degenerate we fall back to the shared
        # case-D hull engine, which is also collinearity-safe.
        ring = LineString([(pt.x, pt.y) for pt in clean] + [(clean[0].x, clean[0].y)])
        hull = None
        if ring.length > 0 and ring.is_valid:
            candidate = Polygon(list(ring.coords))
            if candidate.is_valid and candidate.area > 1e-12:
                hull = candidate
        if hull is None:
            # Fall back to the shared case-D concave-hull engine.
            config = PolygonizeConfig(
                allow_point_hull=True, alpha=None, name_prefix="Polygon"
            )
            features, _warnings = feature_to_polygon(
                clean, [dict() for _ in clean], config
            )
            candidates = [g for g, _ in features if g is not None and not g.is_empty]
            if not candidates:
                raise HTTPException(
                    status_code=400,
                    detail="Could not build a polygon from the given points",
                )
            hull = max(candidates, key=lambda g: g.area)

        if hull.is_empty or hull.area <= 1e-9:
            raise HTTPException(
                status_code=400,
                detail="Points are collinear or too close together — cannot form a polygon",
            )

        name = (request.name or "Polygon").strip() or "Polygon"
        target = request.target_type

        area_sqm, area_hectares = calculate_area_geodesic_from_shapely(hull)
        area_hectares = round(area_hectares, 4)

        created_id = None

        # ---- Store into the target built-in layer (append semantics) ----
        if target == "boundary":
            # Same write path as updateBoundaryGeometry (forests.py:4217): set
            # boundary_geom via geoalchemy2 from_shape (WKB, avoids WKT round-trip),
            # geodesic area + result_data.geometry, single-block auto-create.
            from geoalchemy2.shape import from_shape as _bnd_from_shape

            calculation.boundary_geom = _bnd_from_shape(hull, srid=4326)
            from app.services.boundary_pieces_service import sync_boundary_pieces

            sync_boundary_pieces(db, calculation, hull)
            result_data = calculation.result_data or {}
            result_data["geometry"] = shapely_mapping(hull)
            result_data["area_hectares"] = area_hectares
            calculation.result_data = result_data
            flag_modified(calculation, "result_data")
            from app.services.sub_area_reclip_service import reclip_after_boundary_write

            reclip_after_boundary_write(db, calculation, hull)
            n_blocks = (
                db.query(ForestBlock)
                .filter(
                    ForestBlock.calculation_id == calculation_id,
                    ForestBlock.is_compartment != True,
                    ForestBlock.division_level == DEPTH_TOP_BLOCK,
                )
                .count()
            )
            if n_blocks == 0 and not hull.is_empty:
                from app.utils.single_part_geometry import (
                    explode_and_filter_slivers as _bnd_explode,
                )

                _bnd_parts = _bnd_explode([hull])
                for _bp_i, _bnd_part in enumerate(_bnd_parts):
                    _bp_sqm, _bp_ha = calculate_area_geodesic_from_shapely(_bnd_part)
                    db.add(
                        ForestBlock(
                            calculation_id=calculation_id,
                            name=f"B{_bp_i + 1}"
                            if len(_bnd_parts) > 1
                            else "B1",
                            geometry=func.ST_GeomFromText(
                                shapely_wkt.dumps(_bnd_part), 4326
                            ),
                            area_hectares=round(_bp_ha, 4),
                            index=_bp_i,
                            division_level=DEPTH_TOP_BLOCK,
                            is_compartment=False,
                            is_locked=False,
                        )
                    )
            created_id = None
        elif target in ("sub_areas", "sub_area"):
            from datetime import datetime, timezone
            from shapely.ops import unary_union

            result_data = calculation.result_data or {}
            if "sub_areas" not in result_data:
                result_data["sub_areas"] = []
            # Inside the forest and never overlapping another sub-area: place_sub_area.
            from app.services.sub_area_service import (
                place_sub_area,
                SubAreaPlacementError,
                PLACEMENT_MESSAGES,
            )

            try:
                _placement = place_sub_area(db, calculation, hull)
            except SubAreaPlacementError as _exc:
                raise HTTPException(
                    status_code=400, detail=PLACEMENT_MESSAGES[_exc.reason]
                )
            new_geom = _placement.geometry
            sub_area_id = str(uuid.uuid4())
            new_sub_area = {
                "id": sub_area_id,
                "name": name,
                "category": "protected",
                "geometry": shapely_mapping(new_geom),
                "area_sqm": round(calculate_area_geodesic_from_shapely(new_geom)[0], 4),
                "area_hectares": round(
                    calculate_area_geodesic_from_shapely(new_geom)[1], 4
                ),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            if _placement.pending_boundary_clip:
                new_sub_area["pending_boundary_clip"] = True
            result_data["sub_areas"].append(new_sub_area)
            result_data["sub_areas_count"] = len(result_data["sub_areas"])
            calculation.result_data = result_data
            flag_modified(calculation, "result_data")
            created_id = sub_area_id
        else:
            # Unit layers (blocks / compartments / sub-blocks / sub-compartments). A drawn polygon is
            # CARVED, never just inserted: it goes through the same operation as Paste (D12), which
            # clips it to its shell (forest boundary, or the parent unit), takes the ground from the
            # neighbours it overlaps (a divided neighbour re-clips its own children), refuses a
            # wrong-branch or same-place shape, and completes a partly-covered parent with a remainder
            # sub-unit. Owner rule 2026-10-03: sub-compartment total = compartment total = forest
            # boundary area, always. (This path used to insert raw rows: overlap, area outside the
            # boundary, parentless sub-units -- found by tests/structure/test_unit_coverage_invariant.)
            from app.services.forest_units.operations.paste import (
                ERR_SAME_PLACE as _ERR_SAME_PLACE,
                ERR_STREAM_EMPTY_REQUIRED as _ERR_STREAM,
                apply_paste as _apply_paste,
                parent_for_drawn_polygon as _parent_for_polygon,
            )

            _layer = {
                "blocks": "blocks", "block": "blocks",
                "compartments": "compartments", "compartment": "compartments",
                "sub_blocks": "sub_blocks", "sub_block": "sub_blocks",
                "sub_compartments": "sub_compartments", "sub_compartment": "sub_compartments",
            }.get(target, "blocks")
            try:
                # a sub layer's polygon is carved out of the unit it starts in (None for top level)
                _parent_id = _parent_for_polygon(db, calculation, _layer, hull)
                _res = _apply_paste(db, calculation, _layer, _parent_id, [shapely_mapping(hull)])
            except ValueError as _exc:
                _code = str(_exc)
                raise HTTPException(
                    status_code=409 if _code in (_ERR_SAME_PLACE, _ERR_STREAM) else 400,
                    detail=resolve_service_detail(_code),
                )
            _created = _res["new_pieces"]
            if request.name and request.name.strip():
                for _i, _piece in enumerate(_created, start=1):
                    _row = db.query(ForestBlock).filter(ForestBlock.id == _piece["id"]).first()
                    if _row is not None:
                        _row.name = _row.block_name = (
                            name if len(_created) == 1 else f"{name} {_i}"
                        )
            created_id = _created[0]["id"] if _created else None
            _total_abs = sum(float(_p["area_hectares"]) for _p in _created)
            if _total_abs > 0:
                area_hectares = round(_total_abs, 4)

        db.commit()

        calculation = (
            db.query(Calculation).filter(Calculation.id == calculation_id).first()
        )
        if calculation:
            calculation.geometry_version = (calculation.geometry_version or 0) + 1
            db.commit()

        return {
            "success": True,
            "feature_id": created_id,
            "target_type": target,
            "geometry": shapely_mapping(hull),
            "area_hectares": area_hectares,
            "name": name,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"polygon-from-points: {e}", exc_info=True)
        raise HTTPException(
            status_code=400, detail=f"Could not create polygon from points: {e}"
        )


@router.post("/workspace/{calculation_id}/boundary/preview-mapping")
async def boundary_preview_mapping(
    calculation_id: UUID,
    file: UploadFile = File(...),
    crs_epsg: Optional[int] = Form(None),
    mapping: Optional[str] = Form(None),
    fix_swap: Optional[str] = Form(None),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Preview column mapping + Nepal-extent validation for a boundary point file.

    Mirrors inventory.preview_column_mapping (inventory.py:224) but scoped to
    {LONGITUDE, LATITUDE} and the workspace boundary purpose. Returns the
    transformed 4326 points so the frontend can render a ghost preview.
    Accepts an optional `mapping` JSON form field ({csv_col: std_col}) to
    re-run with a user-corrected mapping (from ColumnMappingPreview), and an
    optional `fix_swap` form field to auto-swap lat/lon values the user has
    confirmed are accidentally swapped.
    """
    from app.api.inventory import read_upload_file

    _require_calculation_access(db, calculation_id, current_user)
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")
    ext = (file.filename.rsplit(".", 1)[-1] or "").lower()
    if ext not in ("csv", "xlsx", "txt"):
        raise HTTPException(
            status_code=400, detail="Boundary point file must be CSV, XLSX or TXT"
        )

    try:
        content = await file.read()
        df = read_upload_file(content, file.filename, nrows=None)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error reading file: {str(e)}")
    if len(df) == 0:
        raise HTTPException(status_code=400, detail="File is empty")

    try:
        return _build_boundary_preview_response(
            df, file.filename, crs_epsg, mapping, fix_swap=bool(fix_swap)
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Could not preview boundary points: {type(e).__name__}: {e}",
        )


def _build_boundary_preview_response(df, filename, crs_epsg, mapping, fix_swap=False):
    """Shared builder for boundary_preview_mapping (isolated so unexpected
    parsing/transform errors surface as a readable 400 instead of a 500)."""
    from app.api.inventory import convert_numpy_types
    from app.utils.column_mapper import ColumnMapper
    from app.services.validators.coordinate_detector import CoordinateDetector
    from app.services.file_processor import _parse_coordinate
    from pyproj import Transformer

    # ---- Column mapping (auto OR user-supplied) ----
    mapper = ColumnMapper()
    required = {"LONGITUDE", "LATITUDE"}
    auto_result = mapper.auto_map_columns(df.columns.tolist())
    mapped = auto_result["mapped"]  # {csv_col: std_col}
    confidence = auto_result["confidence"]  # {csv_col: score}
    if mapping:
        import json as _json

        mapped = _json.loads(mapping)
        confidence = {c: 100 for c in mapped}

    # std_col -> csv_col reverse lookup
    lon_col = next((c for c, s in mapped.items() if s == "LONGITUDE"), None)
    lat_col = next((c for c, s in mapped.items() if s == "LATITUDE"), None)
    needs_user_input = not (lon_col and lat_col)
    csv_columns = df.columns.tolist()
    import numpy as _np

    sample_data = df.head(5).replace({_np.nan: None}).to_dict("records")

    response_base = {
        "success": True,
        "filename": filename,
        "total_rows": len(df),
        "csv_columns": csv_columns,
        "sample_data": convert_numpy_types(sample_data),
        "mapping": mapped,
        "confidence": confidence,
        "unmapped_columns": auto_result["unmapped"],
        "missing_required": list(required - set(mapped.values())),
        "duplicates": auto_result["duplicates"],
        "required_columns": ["LONGITUDE", "LATITUDE"],
        "optional_columns": [],
        "needs_user_input": needs_user_input,
    }
    if needs_user_input:
        response_base["detected_crs"] = None
        response_base["points_4326"] = []
        return convert_numpy_types(response_base)

    # Parse coordinate columns robustly: accept decimal degrees and DMS
    # ("27°12'34.5\"N", "27 12 34.5", "27:12:34.5"). Non-numeric cells raise a
    # clear 400 instead of an unhandled ValueError → 500.
    def _coerce_column(col, axis_name):
        raw = df[col].tolist()
        parsed = [_parse_coordinate(v) for v in raw]
        bad = [(i + 2, raw[i]) for i, p in enumerate(parsed) if p is None]
        if bad:
            rows = ", ".join(f"row {i}" for i, _ in bad[:5])
            detail = (
                f"Could not parse {axis_name} coordinates in column '{col}' "
                f"({rows}{'…' if len(bad) > 5 else ''}). "
                "Use decimal degrees (e.g. 27.51234) or DMS (e.g. 27°12'34.5\"N)."
            )
            raise HTTPException(status_code=400, detail=detail)
        return parsed

    x_vals = _coerce_column(lon_col, "longitude")
    y_vals = _coerce_column(lat_col, "latitude")
    import numpy as _np

    x_arr = _np.asarray(x_vals, dtype=float)
    y_arr = _np.asarray(y_vals, dtype=float)

    # ---- the coordinate system a template declares (column ``coordinate_system_epsg``); an explicit choice by the user still wins ----
    from app.services.upload.coordinates import declared_system

    _declared = declared_system(df)
    if _declared["mixed"]:
        raise HTTPException(status_code=400, detail=f"The file declares more than one coordinate system ({', '.join(map(str, _declared['values']))}). Use one value on every row.")
    if _declared["unsupported"] and not crs_epsg:
        raise HTTPException(status_code=400, detail=f"EPSG:{_declared['unsupported'][0]} is not supported yet. Use 4326 (degrees), 32644 (UTM zone 44N) or 32645 (UTM zone 45N).")
    if not crs_epsg and _declared["epsg"]:
        crs_epsg = _declared["epsg"]
    response_base["declared_epsg"] = _declared["epsg"]

    # ---- CRS detection (user override wins) ----
    detector = CoordinateDetector()
    swapped_fixed = False
    if crs_epsg:
        crs = crs_epsg
    else:
        detected = detector.detect_crs(x_arr, y_arr)
        # Swapped columns (lat/lon values in the wrong columns) are the classic
        # accident. Ask the user first; on `fix_swap` swap the values back and
        # proceed exactly as if the columns were correct.
        if detected.get("error") == "coordinates_swapped":
            if fix_swap:
                x_arr, y_arr = y_arr, x_arr
                x_vals, y_vals = y_vals, x_vals
                swapped_fixed = True
                detected = detector.detect_crs(x_arr, y_arr)
                crs = (
                    detected.get("epsg")
                    if isinstance(detected.get("epsg"), int)
                    else None
                )
                crs = crs or 4326
            else:
                _swap_msg = detected.get(
                    "message", "X and Y coordinates appear to be swapped"
                )
                _swap_hint = detected.get(
                    "suggestion", "Please swap longitude and latitude columns"
                )
                response_base["swap_detected"] = True
                response_base["swap_message"] = f"{_swap_msg}. {_swap_hint}"
                response_base["points_4326"] = []
                response_base["detected_crs"] = None
                return convert_numpy_types(response_base)
        else:
            crs = (
                detected.get("epsg") if isinstance(detected.get("epsg"), int) else None
            )
            crs = crs or 4326

    # ---- Nepal-extent validation (issues list; empty == valid) ----
    issues = detector.validate_coordinates(x_arr, y_arr, epsg=crs)
    if issues:
        first = issues[0]
        raise HTTPException(
            status_code=400,
            detail=f"Coordinates outside Nepal's extent (row {first.get('row', '?')}): {first.get('message', 'out of bounds')}",
        )

    # ---- Transform to 4326 ----
    points_4326 = []
    if crs != 4326:
        transformer = Transformer.from_crs(f"EPSG:{crs}", "EPSG:4326", always_xy=True)
        for x, y in zip(x_vals, y_vals):
            lng, lat = transformer.transform(x, y)
            points_4326.append({"lng": round(lng, 8), "lat": round(lat, 8)})
    else:
        points_4326 = [
            {"lng": round(float(x), 8), "lat": round(float(y), 8)}
            for x, y in zip(x_vals, y_vals)
        ]

    response_base["detected_crs"] = crs
    response_base["points_4326"] = points_4326
    if swapped_fixed:
        response_base["swapped_fixed"] = True

    # A survey station with one mistyped digit: the file is in walking order, so a station whose two legs are far longer than the file's own typical
    # leg and which adds a large detour is flagged, with the single-digit repairs that put it back (VALIDATION_TRACKER.md, C4). Advice only: nothing changes.
    try:
        import re
        import numpy as _npy
        from app.services.upload.station_typos import analyse_stations

        def _typed(cell):
            if cell is None or (isinstance(cell, float) and _npy.isnan(cell)):
                return None
            text_ = str(cell).strip() if isinstance(cell, str) else _npy.format_float_positional(float(cell), trim="-")
            return text_ if re.fullmatch(r"-?\d+(\.\d+)?", text_) else None

        x_col, y_col = (lat_col, lon_col) if swapped_fixed else (lon_col, lat_col)
        to_lonlat = None
        if crs != 4326:
            _t = Transformer.from_crs(f"EPSG:{crs}", "EPSG:4326", always_xy=True)
            to_lonlat = lambda a, b: _t.transform(a, b)  # noqa: E731 -- a one-line adapter
        response_base["station_issues"] = analyse_stations(
            list(map(float, x_arr)), list(map(float, y_arr)),
            [_typed(c) for c in df[x_col].tolist()], [_typed(c) for c in df[y_col].tolist()],
            units="deg" if crs == 4326 else "m", closed=True, to_lonlat=to_lonlat,
        )
    except Exception:  # noqa: BLE001 -- advice only: the preview itself must not fail because the typo check did
        logger.warning("boundary preview: station typo check failed for %s", filename, exc_info=True)
        response_base["station_issues"] = []
    return convert_numpy_types(response_base)


class GeometryImportBackupRestoreRequest(BaseModel):
    """Restore the most recent geometry-import backup (undo a wrong-file import)."""

    target_type: Optional[str] = "compartments"


@router.post("/workspace/{calculation_id}/geometry-import-backup/restore")
def restore_geometry_import_backup(
    calculation_id: UUID,
    body: GeometryImportBackupRestoreRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Restore the most recent geometry-import backup for the given target_type
    (compartments, sub_compartments, or sub_blocks). This undoes an accidental
    wrong-file import by re-creating the derived ForestBlock rows captured at
    convert time.

    U-5/Task 5.3 undo/rollback: backups are never hard-deleted; a wrong-file
    import can always be restored from `result_data["_geometry_import_backups"]`.
    """
    try:
        from app.models.workspace_layer import WorkspaceLayer
        from app.models.forest_block import ForestBlock
        from shapely.geometry import shape as _restore_shape
        from shapely import wkt as _restore_wkt

        calculation = _require_calculation_access(db, calculation_id, current_user)
        target_type = body.target_type or "compartments"
        if target_type not in (
            "compartments",
            "sub_compartments",
            "sub_blocks",
        ):
            raise HTTPException(
                status_code=400,
                detail="target_type must be 'compartments', 'sub_compartments' or 'sub_blocks'",
            )
        is_sub_blocks = target_type == "sub_blocks"

        result_data = calculation.result_data or {}
        backups = result_data.get("_geometry_import_backups") or []
        # Find the newest backup for this target_type (economics: restore the latest).
        matching = [b for b in backups if b.get("target_type") == target_type]
        if not matching:
            raise HTTPException(
                status_code=404,
                detail=f"No backup found for target_type '{target_type}'",
            )
        backup = matching[-1]
        items = backup.get("items") or []
        if not items:
            raise HTTPException(
                status_code=404, detail="Backup is empty (nothing to restore)"
            )

        # Undo the replace: drop current imported rows for that target, then
        # re-create from the backup snapshot.
        if target_type == "compartments":
            db.query(ForestBlock).filter(
                ForestBlock.calculation_id == calculation_id,
                ForestBlock.is_compartment == True,
            ).delete(synchronize_session=False)
        elif is_sub_blocks:
            db.query(ForestBlock).filter(
                ForestBlock.calculation_id == calculation_id,
                ForestBlock.is_compartment == False,
                ForestBlock.division_level >= DEPTH_SUB,
            ).delete(synchronize_session=False)
        else:
            db.query(ForestBlock).filter(
                ForestBlock.calculation_id == calculation_id,
                ForestBlock.is_compartment == True,
                ForestBlock.division_level >= DEPTH_SUB,
            ).delete(synchronize_session=False)
        db.flush()

        restored = 0
        # Compartments/sub-blocks first, then deeper sub-rows, so parent links resolve.
        items_sorted = sorted(items, key=lambda it: it.get("division_level") or 0)
        _id_map = {}
        for it in items_sorted:
            geom = it.get("geometry")
            if not geom:
                continue
            try:
                g = _restore_shape(geom)
                if g.is_empty:
                    continue
                area_ha = it.get("area_hectares") or round(
                    calculate_area_geodesic_from_shapely(g)[1], 4
                )
                new_row = ForestBlock(
                    calculation_id=calculation_id,
                    name=it.get("name") or "Restored",
                    geometry=func.ST_GeomFromText(_restore_wkt.dumps(g), 4326),
                    area_hectares=round(area_ha, 4),
                    index=restored,
                    division_level=it.get("division_level") or 1,
                    is_compartment=not is_sub_blocks,
                    is_locked=bool(it.get("is_locked")),
                    color=it.get("color"),
                    child_count=it.get("child_count") or 0,
                    display_order=it.get("display_order") or 0,
                    compartment_code=(
                        None
                        if is_sub_blocks
                        else _unit_code(target_type, restored + 1)
                    ),
                )
                parent_id = it.get("parent_block_id")
                db.add(new_row)
                db.flush()
                _id_map[str(it.get("id"))] = new_row.id
                restored += 1
            except Exception as e:
                logger.warning(f"restore backup row failed: {e}")
                continue

        # Re-link sub-compartments to restored parents by original id.
        for it in items_sorted:
            parent_orig = it.get("parent_block_id")
            if parent_orig and parent_orig in _id_map:
                row = (
                    db.query(ForestBlock)
                    .filter(
                        ForestBlock.calculation_id == calculation_id,
                        ForestBlock.name == it.get("name"),
                        ForestBlock.display_order == it.get("display_order"),
                    )
                    .first()
                )
                if row is not None:
                    row.parent_block_id = _id_map[parent_orig]

        if restored == 0:
            raise HTTPException(
                status_code=400, detail="Backup contained no restorable geometries"
            )

        db.commit()
        calculation.geometry_version = (calculation.geometry_version or 0) + 1
        db.commit()

        return {
            "success": True,
            "restored": restored,
            "target_type": target_type,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"restore-geometry-import-backup: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Restore failed: {e}")
