"""User Group extent and analysis API endpoints.

Endpoints for managing User Group spatial extents (upload, manual
digitization, auto-buffer), performing spatial analysis (land cover,
point-of-interest), and exporting extent data.

See also:
    app.services.user_group_analysis — business logic
    app.schemas.user_group — request/response schemas
"""

from typing import Optional
from uuid import UUID

from app.services.upload.coordinates import far_from_forest_findings
from app.services.upload.findings import upload_error
from app.services.upload.legacy_messages import user_group_findings
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.utils.auth import get_current_user
from app.models.user import User, UserRole
from app.models.calculation import Calculation
from app.schemas.user_group import (
    ExtentResponse,
    ExtentGeoJSONResponse,
    AnalysisResponse,
    UserGroupResults,
    POIResponse,
    ManualExtentRequest,
    LandCoverAnalysisResponse
)
from app.services.user_group_analysis import UserGroupAnalysisService, UserGroupTooLarge
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


def _require_calc_access(db: Session, calculation_id: str, current_user: User) -> Calculation:
    """Ownership gate — a user group extent is scoped to its calculation.

    Mirrors `_require_calculation_access` in workspace.py / the blocks.py /
    forests.py pattern: only the owner (or SUPER_ADMIN) may touch it.
    """
    try:
        calc = db.query(Calculation).filter(Calculation.id == UUID(str(calculation_id))).first()
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="Calculation not found")
    if not calc:
        raise HTTPException(status_code=404, detail="Calculation not found")
    if calc.user_id != current_user.id and current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized to access this calculation")
    return calc


async def _auto_analyze(db: Session, calculation_id: str) -> str:
    """Tell the user what happens next. The analysis itself runs in the background the moment the polygons are
    committed (`user_group_auto_analysis`); here we only check the size limit so a too-large group is told why."""
    try:
        UserGroupAnalysisService(db).assert_area_within_limit(calculation_id)
        return " Analysis is running."
    except UserGroupTooLarge as e:
        return f" Analysis skipped: {e}"
    except Exception as e:  # noqa: BLE001 -- advisory message only
        logger.warning(f"Size check failed for {calculation_id}: {e}")
        return ""


@router.post("/calculations/{calculation_id}/user-group/upload", response_model=ExtentResponse)
async def upload_extent_boundary(
    calculation_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Upload extent boundary file (KML, KMZ, Shapefile, GPX, GeoJSON, CSV)
    """
    _require_calc_access(db, calculation_id, current_user)
    try:
        service = UserGroupAnalysisService(db)
        extent = await service.process_uploaded_boundary(
            calculation_id=calculation_id,
            file=file,
            user_id=current_user.id
        )
        return ExtentResponse(
            extent_id=extent.id,
            message="Extent boundary uploaded successfully." + await _auto_analyze(db, calculation_id),
            findings=[f.to_dict() for f in [*service.notes, *far_from_forest_findings(db, calculation_id, getattr(file, "filename", None))]],
        )
    except HTTPException:
        raise  # the coded, bilingual refusals (e.g. user_group.too_large) go to the user as they are
    except ValueError as e:
        raise upload_error(400, *user_group_findings(str(e), getattr(file, "filename", None)))
    except Exception as e:
        logger.exception("Error uploading extent boundary: %s", e)
        raise upload_error(500, *user_group_findings("", getattr(file, "filename", None)))


@router.post("/calculations/{calculation_id}/user-group/import", response_model=ExtentResponse)
async def import_extent_boundary(
    calculation_id: str,
    file: UploadFile = File(...),
    crs_epsg: Optional[int] = Query(default=None),
    gpx_types: Optional[str] = Query(default=None, description="Comma list of GPX sub-types: wpt,trk,rte"),
    lat_col: Optional[str] = Query(default=None, description="CSV/Excel column to use as latitude (overrides auto-detection)"),
    lon_col: Optional[str] = Query(default=None, description="CSV/Excel column to use as longitude (overrides auto-detection)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Import a user-group extent from a file — Forest-Boundary-identical.

    Accepts every format in ``settings.ALLOWED_EXTENSIONS`` (ESRI Shapefile
    zipped **or** bare ``.shp``, KML, KMZ, GeoJSON, GeoPackage, GPX, CSV,
    Excel ``.xlsx``) and any geometry type — point / line / polygon. Points
    (incl. a CSV/Excel coordinate sheet) are hulled into a polygon. Replaces
    the current extent. (Plan D2a.)

    For CSV/Excel files, ``lat_col`` / ``lon_col`` override the auto-detected
    coordinate columns (UP-3.2 column picker).
    """
    _require_calc_access(db, calculation_id, current_user)
    gpx_selection = [t.strip() for t in gpx_types.split(",") if t.strip()] if gpx_types else None
    try:
        service = UserGroupAnalysisService(db)
        extent = await service.create_extent_from_import(
            calculation_id=calculation_id,
            file=file,
            user_id=current_user.id,
            crs_epsg=crs_epsg,
            gpx_selection=gpx_selection,
            lat_col=lat_col,
            lon_col=lon_col,
        )
        return ExtentResponse(
            extent_id=extent.id,
            message="Extent boundary imported successfully." + await _auto_analyze(db, calculation_id),
            findings=[f.to_dict() for f in [*service.notes, *far_from_forest_findings(db, calculation_id, getattr(file, "filename", None))]],
        )
    except HTTPException:
        raise  # the coded, bilingual refusals (e.g. user_group.too_large) go to the user as they are
    except ValueError as e:
        raise upload_error(400, *user_group_findings(str(e), getattr(file, "filename", None)))
    except Exception as e:
        logger.exception("Error importing extent boundary: %s", e)
        raise upload_error(500, *user_group_findings("", getattr(file, "filename", None)))


@router.get(
    "/calculations/{calculation_id}/user-group/extent",
    response_model=ExtentGeoJSONResponse,
)
def get_user_group_extent(
    calculation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Thin read for the workspace layer's ``DataSource.fetch`` — the current
    extent as one GeoJSON Feature payload, or all-null when none exists."""
    _require_calc_access(db, calculation_id, current_user)
    service = UserGroupAnalysisService(db)
    data = service.get_extent_geojson(calculation_id)
    return ExtentGeoJSONResponse(**(data or {}))


@router.get("/calculations/{calculation_id}/user-group/extents")
def list_user_group_extents(
    calculation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """One GeoJSON Feature PER user-group polygon - the workspace layer's read (P7e).

    The singular `/user-group/extent` above is the UNION, which is what the
    analysis and the land cover need. The map layer needs the opposite: a feature
    per stored row, because each row is one polygon and therefore one selectable,
    vertex-editable, cuttable feature with its own attribute row (owner's model,
    2026-09-28).

    Ids are plain row ids, NOT `user_group#<id>#<part>`: with one polygon per row
    there is no part index to carry, and carrying one is what made the client
    re-split a single row and address islands that the database already knew as
    separate rows.
    """
    _require_calc_access(db, calculation_id, current_user)
    service = UserGroupAnalysisService(db)
    features = service.get_extent_features(calculation_id)
    return {
        "features": [
            {
                "type": "Feature",
                "id": f["id"],
                "geometry": f["geometry"],
                "properties": {
                    "id": f["id"],
                    "area_hectares": f["area_hectares"],
                    "source_type": f["source_type"],
                    "buffer_distance_m": f["buffer_distance_m"],
                    "name": "User Group Boundary",
                },
            }
            for f in features
            if f.get("geometry")
        ],
        "count": len(features),
    }


@router.post("/calculations/{calculation_id}/user-group/manual", response_model=ExtentResponse)
async def create_manual_extent(
    calculation_id: str,
    request: ManualExtentRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Create extent from manually digitized polygon
    """
    _require_calc_access(db, calculation_id, current_user)
    try:
        service = UserGroupAnalysisService(db)
        extent = await service.create_manual_extent(
            calculation_id=calculation_id,
            geometry=request.geometry,
            user_id=current_user.id
        )
        return ExtentResponse(
            extent_id=extent.id,
            message="Manual extent created successfully." + await _auto_analyze(db, calculation_id)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating manual extent: {e}")
        raise HTTPException(status_code=500, detail="Failed to create manual extent")


@router.post("/calculations/{calculation_id}/user-group/auto-buffer", response_model=ExtentResponse)
async def create_auto_buffer_extent(
    calculation_id: str,
    buffer_distance: int = Query(default=1000, ge=100, le=5000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Create auto-buffer extent (default 1000m from forest boundary)
    """
    _require_calc_access(db, calculation_id, current_user)
    try:
        service = UserGroupAnalysisService(db)
        extent = await service.create_auto_buffer(
            calculation_id=calculation_id,
            buffer_distance_m=buffer_distance,
            user_id=current_user.id
        )
        return ExtentResponse(
            extent_id=extent.id,
            message=f"Auto-buffer extent created ({buffer_distance}m)." + await _auto_analyze(db, calculation_id)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating auto-buffer extent: {e}")
        raise HTTPException(status_code=500, detail="Failed to create auto-buffer extent")


@router.get("/calculations/{calculation_id}/user-group/analysis-status")
def get_user_group_analysis_status(
    calculation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Where the automatic analysis stands: ``idle`` / ``running`` / ``done`` / ``failed`` / ``skipped`` with its two steps (settlements, land cover).
    Read only, from the status stored with the calculation."""
    from app.services.user_group_auto_analysis import read_status

    calc = _require_calc_access(db, calculation_id, current_user)
    return read_status(calc.result_data)


@router.post("/calculations/{calculation_id}/user-group/analyze", response_model=AnalysisResponse)
async def analyze_user_group(
    calculation_id: str,
    extent_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Run spatial analysis: clip buildings/settlements, calculate statistics
    """
    _require_calc_access(db, calculation_id, current_user)
    try:
        service = UserGroupAnalysisService(db)
        # Re-analyses the WHOLE group (every polygon), whichever extent id was passed.
        results = await service.analyze_all(calculation_id)

        total_buildings = sum(r.get('building_count', 0) for r in results)

        return AnalysisResponse(
            message="Analysis completed successfully",
            settlements_analyzed=len(results),
            total_buildings=total_buildings
        )
    except UserGroupTooLarge as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"Error analyzing user group: {e}")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@router.delete("/calculations/{calculation_id}/user-group/{extent_id}")
def delete_one_user_group_extent(
    calculation_id: str,
    extent_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete ONE user-group polygon, leaving the others (P7e).

    Each polygon is its own row and its own feature, so deleting a feature must
    delete exactly that row. The route without an id below still removes the whole
    group, which is what "clear the user group" means.
    """
    _require_calc_access(db, calculation_id, current_user)
    from app.models.user_group import UserGroupExtent

    row = (
        db.query(UserGroupExtent)
        .filter(UserGroupExtent.id == extent_id)
        .filter(UserGroupExtent.calculation_id == calculation_id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="User group extent not found")
    db.delete(row)
    db.commit()
    return {"deleted_extent_id": extent_id}


@router.get("/calculations/{calculation_id}/user-group/results", response_model=UserGroupResults)
async def get_user_group_results(
    calculation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get analysis results for visualization
    """
    _require_calc_access(db, calculation_id, current_user)
    try:
        service = UserGroupAnalysisService(db)
        results = await service.get_results(calculation_id)

        if not results:
            raise HTTPException(status_code=404, detail="No user group analysis found for this calculation")

        return results
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user group results: {e}")
        raise HTTPException(status_code=500, detail="Failed to get results")


@router.get("/calculations/{calculation_id}/user-group/poi", response_model=POIResponse)
async def get_poi_layers(
    calculation_id: str,
    layer_type: str = Query(default="all", regex="^(all|poi|education|health|rivers)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get optional POI layers for map visualization
    """
    _require_calc_access(db, calculation_id, current_user)
    try:
        service = UserGroupAnalysisService(db)
        poi_data = await service.get_poi_layers(calculation_id, layer_type)
        return poi_data
    except Exception as e:
        logger.error(f"Error getting POI layers: {e}")
        raise HTTPException(status_code=500, detail="Failed to get POI layers")


@router.delete("/calculations/{calculation_id}/user-group")
def delete_user_group_extent(
    calculation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Delete user group extent and all related analysis data
    """
    _require_calc_access(db, calculation_id, current_user)
    try:
        service = UserGroupAnalysisService(db)
        deleted_count = service._delete_existing_extents(calculation_id)

        if deleted_count == 0:
            raise HTTPException(status_code=404, detail="No user group extent found")

        return {
            "message": f"Successfully deleted user group extent and analysis data",
            "deleted_extents": deleted_count
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting user group extent: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete user group extent")


@router.get("/calculations/{calculation_id}/user-group/land-cover", response_model=LandCoverAnalysisResponse)
async def analyze_land_cover(
    calculation_id: str,
    force_refresh: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Analyze land cover and biomass for user group extent

    This endpoint performs comprehensive spatial analysis including:
    - Land use classification (ESA World Cover 10m)
    - Biomass estimation (AGB 2022 Nepal 100m)
    - Community forest overlap exclusion
    - Timber volume calculation

    **Caching:** Results are automatically cached in database for fast retrieval.
    Use `force_refresh=true` to re-run the analysis.

    **Prerequisites:**
    1. Community forest boundary must be uploaded (Analysis tab)
    2. User group extent must be created (Forest User Map tab)

    **Returns:**
    - Area summary (user group, forest overlap, net analysis area)
    - Land cover breakdown by class
    - Biomass and volume statistics
    """
    _require_calc_access(db, calculation_id, current_user)
    try:
        service = UserGroupAnalysisService(db)
        results = await service.analyze_land_cover(calculation_id, force_refresh=force_refresh)
        return results
    except ValueError as e:
        # User-friendly error messages
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error analyzing land cover: {e}")
        raise HTTPException(status_code=500, detail=f"Land cover analysis failed: {str(e)}")


@router.get("/user-group/{extent_id}/export")
async def export_user_group_map(
    extent_id: int,
    format: str = Query(default="pdf", regex="^(pdf|gpkg|geojson|csv)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Export user group map and statistics
    """
    from app.utils.file_export import build_disposition
    from app.models.calculation import Calculation
    from app.models.user_group import UserGroupExtent

    try:
        extent = db.query(UserGroupExtent).filter(UserGroupExtent.id == extent_id).first()
        if not extent:
            raise HTTPException(status_code=404, detail="User group extent not found")
        calc = _require_calc_access(db, str(extent.calculation_id), current_user)
        forest_name = calc.forest_name if calc else None

        service = UserGroupAnalysisService(db)

        if format == "pdf":
            file_path = await service.generate_pdf_report(extent_id)
            media_type = "application/pdf"
        elif format == "gpkg":
            file_path = await service.export_to_gpkg(extent_id)
            media_type = "application/geopackage+sqlite3"
        elif format == "geojson":
            file_path = await service.export_to_geojson(extent_id)
            media_type = "application/geo+json"
        elif format == "csv":
            file_path = await service.export_to_csv(extent_id)
            media_type = "text/csv"
        else:
            raise HTTPException(status_code=400, detail="Invalid format")

        _, disposition = build_disposition(forest_name, "UserGroup", "Map", format)
        return FileResponse(
            file_path,
            media_type=media_type,
            filename=_.replace(" ", "_"),
            headers={"Content-Disposition": disposition}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting user group map: {e}")
        raise HTTPException(status_code=500, detail="Export failed")
