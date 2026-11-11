"""
API endpoints for raster tile generation
Provides XYZ tile service for map visualization
"""
import logging
import math
from app.core.errors import CalculationErrors

logger = logging.getLogger(__name__)
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from ..core.database import get_db
from ..core.constants import SLOPE_CLASS_BANDS, SLOPE_CLASS_NAMES
from ..core.exceptions import i18n_error
from ..services.tile_service import get_tile_service, TileService
from ..models.calculation import Calculation
from ..models.user import User, UserRole
from ..utils.auth import get_current_active_user, get_current_user
from ..utils.authz import require_calculation_access, is_owner_or_admin
from ..utils.tile_token import create_tile_token, tile_token_grants, TILE_TOKEN_TTL_MINUTES


router = APIRouter()

_optional_bearer = HTTPBearer(auto_error=False)


async def require_tile_access(
    calculation_id: str,
    tk: Optional[str] = Query(
        default=None,
        description="Tile token from /calculations/{id}/tile-token. Required "
                    "for <img>-based tile requests, which cannot send headers.",
    ),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_optional_bearer),
    db: Session = Depends(get_db),
) -> None:
    """Authorise a tile request by either credential.

    H2.4 / S1-04. These routes served another community's raster analysis to
    anyone who knew a calculation id. They cannot use the ordinary bearer
    dependency alone, because Leaflet fetches them as images; see
    `utils/tile_token`. A caller presents either a tile token scoped to this
    calculation, or a normal session token belonging to someone entitled to it.
    """
    if tk and tile_token_grants(tk, calculation_id):
        return

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tile access requires a tile token (tk) or a bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await get_current_user(credentials, db)
    require_calculation_access(db, calculation_id, user)


@router.get("/calculations/{calculation_id}/tile-token")
def issue_tile_token(
    calculation_id: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Mint a short-lived tile token for a calculation the caller owns."""
    require_calculation_access(db, calculation_id, current_user)
    return {
        "token": create_tile_token(calculation_id, current_user.id),
        "expires_in": TILE_TOKEN_TTL_MINUTES * 60,
    }


@router.get("/calculations/{calculation_id}/raster-layers")
def list_raster_layers(
    calculation_id: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Read-only raster catalog for a calculation (owner-gated).

    Returns searchable metadata (name, description, source, resolution, year)
    for every raster layer the tile service can render. SSOT: generated from
    TileService.RASTER_METADATA — no frontend catalog duplication.
    """
    calculation = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calculation:
        raise HTTPException(status_code=404, detail="Calculation not found")
    if calculation.user_id != current_user.id and current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Not authorized to access this calculation")

    layers = [
        {
            "id": layer_id,
            "name": meta["name"],
            "description": meta["description"],
            "source": meta.get("source"),
            "resolution": meta.get("resolution"),
            "year": meta.get("year"),
        }
        for layer_id, meta in TileService.RASTER_METADATA.items()
    ]
    return {"layers": layers}


@router.get("/calculations/{calculation_id}/reference-layers")
def list_reference_layers(
    calculation_id: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """The reference-data layers the workspace can show round this forest (rivers, roads, administrative areas, settlements, buildings), with where each comes from."""
    from ..services import reference_layer_service as reference

    require_calculation_access(db, calculation_id, current_user)
    return {"layers": reference.catalogue()}


@router.get("/calculations/{calculation_id}/reference-layers/{layer_key}")
def get_reference_layer(
    calculation_id: str,
    layer_key: str,
    buffer_m: Optional[float] = Query(default=None, ge=0, le=10000, description="How far beyond the forest's bounding box to read, in metres (default 2000)"),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """One reference layer cut to the forest's neighbourhood, as GeoJSON. Read-only shared data; cut at the layer's feature limit and says so (``truncated``)."""
    from ..services import reference_layer_service as reference

    require_calculation_access(db, calculation_id, current_user)
    try:
        return reference.features(db, calculation_id, layer_key, buffer_m)
    except reference.ReferenceLayerError as exc:
        code = {"unknown_layer": 404, "bad_buffer": 422, "no_boundary": 409}.get(exc.code, 400)
        raise HTTPException(status_code=code, detail={"code": exc.code, "message": str(exc)})


@router.get("/calculations/{calculation_id}/tiles/{layer_name}/{z}/{x}/{y}.png")
def get_raster_tile(
    calculation_id: str,
    layer_name: str,
    z: int,
    x: int,
    y: int,
    alpha: int = Query(default=128, ge=0, le=255, description="Transparency (0=transparent, 255=opaque)"),
    db: Session = Depends(get_db),
    _: None = Depends(require_tile_access),
):
    """
    Get a single raster tile for map visualization

    **Tile Coordinates (XYZ format):**
    - **z**: Zoom level (10-16 recommended for Nepal forests)
    - **x**: Tile X coordinate (longitude index)
    - **y**: Tile Y coordinate (latitude index)

    **Available Layers:**
    - `slope` - Terrain slope (0-90°)
    - `aspect` - Slope direction (N, NE, E, SE, S, SW, W, NW, Flat)
    - `dem` - Elevation (Digital Elevation Model)
    - `canopy` - Canopy height (meters)
    - `biomass` - Above-ground biomass (Mg/ha, ESA CCI AGB V6)
    - `nasa_forest_2020` - Forest quality (Primary/Secondary, NASA IPCC Tier 1)
    - `forest_type` - Forest classification (FRTC)
    - `landcover` - Land cover classes (ESA WorldCover)
    - `forest_loss` - Forest loss year (Hansen GFC)
    - `forest_gain` - Forest gain (Hansen GFC, binary)
    - `temperature` - Mean annual temperature (WorldClim)
    - `precipitation` - Annual precipitation (WorldClim)
    - `min_temp_coldest` - Min temperature coldest month (WorldClim)
    - `soil_ph` - Soil pH/acidity (SoilGrids ISRIC)
    - `soil_texture` - Soil texture classification (SoilGrids ISRIC)
    - `soil_carbon` - Soil organic carbon (SoilGrids ISRIC)
    - `soil_fertility` - Soil fertility index (SoilGrids ISRIC)
    - `soil_density` - Bulk density/compaction (SoilGrids ISRIC)
    - `fire` - Fire damage areas (Hansen GFC)
    - `forest_health` - Forest health index (NDVI)

    **Parameters:**
    - **alpha**: Transparency level (default 128 = 50%)

    **Returns:**
    - PNG image (256×256 pixels) with color-coded raster data
    - HTTP 404 if calculation not found
    - HTTP 400 if invalid layer name
    - HTTP 500 if tile generation fails

    **Example:**
    ```
    GET /api/calculations/{calc_id}/tiles/slope/14/12345/6789.png?alpha=128
    ```

    **Caching:**
    - Tiles are cached for 24 hours
    - Cache-Control header set to public
    """
    try:
        tile_service = get_tile_service(db)

        # Use cached version for better performance
        png_bytes = tile_service.get_tile(
            calculation_id=str(calculation_id),
            layer_name=layer_name,
            z=z, x=x, y=y, alpha=alpha,
        )

        return Response(
            content=png_bytes,
            media_type="image/png",
            headers={
                "Cache-Control": "public, max-age=86400",  # Cache for 24 hours
                "Content-Type": "image/png",
            }
        )

    except ValueError as e:
        # Invalid calculation_id or layer_name
        raise HTTPException(status_code=400, detail=str(e))

    except Exception as e:
        # Tile generation failed
        logger.info(f"Tile generation error: {e}")
        logger.exception("Tile generation failed")
        raise HTTPException(status_code=500, detail=f"Tile generation failed: {str(e)}")


@router.get("/calculations/{calculation_id}/user-group-tiles/{layer_name}/{z}/{x}/{y}.png")
def get_user_group_tile(
    calculation_id: str,
    layer_name: str,
    z: int,
    x: int,
    y: int,
    exclude_forest: bool = Query(default=True, description="Exclude forest overlap from visualization"),
    alpha: int = Query(default=180, ge=0, le=255, description="Transparency (0=transparent, 255=opaque)"),
    db: Session = Depends(get_db),
    _: None = Depends(require_tile_access),
):
    """
    Get raster tiles for user group extent with optional forest overlap exclusion

    **Available Layers:**
    - `landcover` - ESA World Cover land use classification (11 classes)
    - `biomass` - Above-ground biomass (Mg/ha, ESA CCI AGB 2022 Nepal)

    **Parameters:**
    - **exclude_forest**: Exclude community forest overlap (default: True)
    - **alpha**: Transparency level (default 180 = 70%)

    **Returns:**
    - PNG image (256×256 pixels) clipped to user group extent

    **Example:**
    ```
    GET /api/calculations/{calc_id}/user-group-tiles/landcover/14/12345/6789.png?exclude_forest=true&alpha=180
    ```

    **Prerequisites:**
    - User group extent must be created for this calculation
    - If exclude_forest=True, community forest boundary must exist

    **Caching:**
    - Tiles are cached for 1 hour
    - Cache varies by exclude_forest parameter
    """
    try:
        tile_service = get_tile_service(db)

        png_bytes = tile_service.get_user_group_tile(
            calculation_id=calculation_id,
            layer_name=layer_name,
            z=z,
            x=x,
            y=y,
            exclude_forest_overlap=exclude_forest,
            alpha=alpha
        )

        return Response(
            content=png_bytes,
            media_type="image/png",
            headers={
                "Cache-Control": "public, max-age=3600",  # Cache for 1 hour
                "Content-Type": "image/png",
            }
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    except Exception as e:
        logger.info(f"User group tile generation error: {e}")
        logger.exception("User group tile generation failed")
        raise HTTPException(status_code=500, detail=f"Tile generation failed: {str(e)}")


@router.get("/calculations/{calculation_id}/hazard-tiles/{layer}/{z}/{x}/{y}.png")
def get_hazard_tile(
    calculation_id: str,
    layer: str,
    z: int,
    x: int,
    y: int,
    alpha: int = Query(default=209, ge=0, le=255),
    area: str = Query(default="forest", pattern="^(forest|user_group)$"),
    db: Session = Depends(get_db),
    _: None = Depends(require_tile_access),
):
    """Hazard & Erosion surface tile for the workspace "Analysis maps" group.

    Reads the CACHED GeoTIFF only; it never computes (tiles arrive in bursts). When nothing is cached for the current
    parameters the tile is transparent and ``X-Hazard-State: not-computed`` says why, so the UI can offer a link to the
    Hazard & Erosion tab instead of an unexplained blank map.
    """
    from uuid import UUID

    from app.services.operational_plan import hazard_tiles as ht

    if layer not in ht.TILE_KEYS:
        raise HTTPException(status_code=404, detail=f"Unknown hazard layer: {layer}")
    try:
        surface = ht.load_surface(db, UUID(calculation_id), layer, area)
    except ValueError:
        raise HTTPException(status_code=404, detail="Calculation not found")
    except ht.NoUserGroup:
        return Response(
            content=ht.empty_tile(), media_type="image/png",
            headers={"Cache-Control": "no-cache", "X-Hazard-State": "no-user-group"},
        )
    if surface is None:
        return Response(
            content=ht.empty_tile(), media_type="image/png",
            headers={"Cache-Control": "no-cache", "X-Hazard-State": "not-computed"},
        )
    return Response(
        content=ht.render_tile(surface, z, x, y, alpha), media_type="image/png",
        headers={
            # the parameter hash IS the version: new parameters -> new ETag -> the browser refetches
            "Cache-Control": "no-cache", "ETag": f'"{surface.params_hash}-{alpha}-{area}-{surface.colour_sig}"', "X-Hazard-State": "ready",
        },
    )


@router.get("/calculations/{calculation_id}/hazard-legend/{layer}")
def get_hazard_legend(
    calculation_id: str,
    layer: str,
    area: str = Query(default="forest", pattern="^(forest|user_group)$"),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Classes this forest actually has (colour, label, hectares, share) for a hazard layer, or
    ``{"state": "not_computed"}``. Cache only, like the tiles."""
    from uuid import UUID

    from app.services.operational_plan import hazard_tiles as ht

    require_calculation_access(db, calculation_id, current_user)
    if layer not in ht.TILE_KEYS:
        raise HTTPException(status_code=404, detail=f"Unknown hazard layer: {layer}")
    try:
        surface = ht.load_surface(db, UUID(calculation_id), layer, area)
    except ht.NoUserGroup:
        return {"state": "no_user_group", "key": layer}
    if surface is None:
        return {"state": "not_computed", "key": layer}
    return ht.legend(surface)


@router.get("/calculations/{calculation_id}/hazard-units")
def get_hazard_unit_summaries(
    calculation_id: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """What each cached hazard map says about every block / compartment (mean soil loss, dominant landslide class,
    unsafe share, ...). Feeds the workspace's automatic labels and attribute-table columns. Cache only."""
    from uuid import UUID

    from app.services.operational_plan import hazard_tiles as ht
    require_calculation_access(db, calculation_id, current_user)
    cid = UUID(calculation_id)
    return ht.all_unit_summaries(db, cid, ht.units_for_summary(db, cid))


@router.get("/calculations/{calculation_id}/hazard-households/{kind}")
def get_hazard_households(
    calculation_id: str,
    kind: str,
    area: str = Query(default="forest", pattern="^(forest|user_group)$"),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Household vulnerability (``households``) or priority-settlement (``settlements``) dots as GeoJSON points,
    scored exactly as on the print maps. Only when the hazard grids are already cached (it never starts a
    computation); household dots carry a score and a priority flag, no identifiers."""
    from uuid import UUID

    from app.services.operational_plan import hazard_households as hh

    require_calculation_access(db, calculation_id, current_user)
    if kind not in hh.KINDS:
        raise HTTPException(status_code=404, detail=f"Unknown kind: {kind}")
    return hh.points(db, UUID(calculation_id), kind, area)


@router.get("/calculations/{calculation_id}/field-glyphs/{kind}")
def get_field_glyphs(
    calculation_id: str,
    kind: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Per-unit field-inventory chart data for the workspace: ``timber-by-size`` (timber m³/ha by tree size class), ``dbh-stems``,
    ``dbh-pie``, ``reverse-j``, ``dbh-waffle``, ``regen-pole-tree``, ``health-radar``, ``timber-firewood``, ``biomass-split``.

    Numbers, class order and colours come from the same functions as each chart's print-map placeholder, with the user's own
    colours laid over them. Reads the stored field-inventory summary only; never computes."""
    from uuid import UUID

    from app.services.operational_plan import field_glyphs as fg

    require_calculation_access(db, calculation_id, current_user)
    if kind not in fg.KINDS:
        raise HTTPException(status_code=404, detail=f"Unknown chart: {kind}")
    return fg.chart(db, UUID(calculation_id), kind)


@router.get("/calculations/{calculation_id}/unit-maps/{spec_key}")
def get_unit_map(
    calculation_id: str,
    spec_key: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Per-unit colours and a dynamic legend for one single-number field-inventory map (``unit__growing_stock`` …), taken from
    the print map's own colour function with the user's colours laid over it. Stored summary only; never computes."""
    from uuid import UUID

    from app.services.operational_plan import unit_maps as um

    require_calculation_access(db, calculation_id, current_user)
    if spec_key not in um.BY_SPEC:
        raise HTTPException(status_code=404, detail=f"Unknown unit map: {spec_key}")
    return um.unit_map(db, UUID(calculation_id), spec_key)


@router.get("/calculations/{calculation_id}/field-inventory-units")
def get_field_inventory_units(
    calculation_id: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Raw per-unit field-inventory numbers (stock, basal area, AAH, MAI, carbon, regeneration, condition …) for the attribute
    table and labels. Stored summary only."""
    from uuid import UUID

    from app.services.operational_plan import unit_maps as um

    require_calculation_access(db, calculation_id, current_user)
    return um.unit_values(db, UUID(calculation_id))


@router.get("/calculations/{calculation_id}/unit-analysis")
def get_unit_analysis(
    calculation_id: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """What "Run analysis" computed for every unit (any level), as ``an_*`` values keyed by unit id, for the attribute tables
    of the unit layers. Stored data only; nothing is computed here."""
    from uuid import UUID

    from app.services.unit_analysis_service import units_payload

    require_calculation_access(db, calculation_id, current_user)
    return units_payload(db, UUID(calculation_id))


@router.get("/calculations/{calculation_id}/attribute-components")
def get_attribute_components(
    calculation_id: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """The "Update attribute" panel: each attribute component (raster analysis, inventory analysis, SFM, hazard & erosion), whether it
    is available for this forest and whether it is up to date. Reads stored state only."""
    from app.services.attribute_components import components_status

    calc = require_calculation_access(db, calculation_id, current_user)
    return {"components": components_status(db, calc)}


class AttributeRunRequest(BaseModel):
    keys: list[str]


@router.post("/calculations/{calculation_id}/attribute-components/run")
async def run_attribute_components(
    calculation_id: str,
    body: AttributeRunRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Run the chosen attribute components that are available (owner or super admin only). One failing never stops the others."""
    from app.services.attribute_components import components_status, run_components

    calc = require_calculation_access(db, calculation_id, current_user)
    if not is_owner_or_admin(calc, current_user):
        raise HTTPException(status_code=403, detail="Only the forest owner can update attributes")
    results = await run_components(db, calc, body.keys)
    return {"results": results, "components": components_status(db, calc)}


@router.get("/calculations/{calculation_id}/field-inventory-report")
def get_field_inventory_report(
    calculation_id: str,
    format: str = Query("json", pattern="^(json|xlsx)$"),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """The field inventory BY SUB-UNIT: one row per undivided unit, a roll-up row for every divided parent, a forest total,
    and the problems found between the stored inventory and the forest's current units (``field_inventory_consistency``).
    ``format=xlsx`` returns the same as a workbook. Stored data only; nothing is computed."""
    from uuid import UUID

    from app.services import field_inventory_consistency as fic
    from app.services import field_inventory_unit_report as rep
    from app.utils.file_export import build_disposition

    calc = require_calculation_access(db, calculation_id, current_user)
    report = rep.build(db, UUID(calculation_id))
    findings = [f.as_dict() for f in fic.check(db, UUID(calculation_id))]
    if format == "xlsx":
        if report["state"] != "ready":
            raise HTTPException(status_code=404, detail="No field inventory to report")
        _name, disposition = build_disposition(getattr(calc, "forest_name", None), "FieldInventory", "SubUnitReport", "xlsx")
        return Response(
            content=rep.to_xlsx(report, findings),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": disposition},
        )
    return {**report, "problems": findings, "has_errors": any(f["severity"] == "error" for f in findings)}


@router.get("/calculations/{calculation_id}/user-group/query")
def query_user_group_point(
    calculation_id: str,
    lat: float = Query(..., description="Latitude (WGS84)", ge=-90, le=90),
    lon: float = Query(..., description="Longitude (WGS84)", ge=-180, le=180),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Get land cover and biomass values at a specific point within user group extent

    **Parameters:**
    - **lat**: Latitude in decimal degrees (WGS84)
    - **lon**: Longitude in decimal degrees (WGS84)

    **Returns:**
    - JSON object with land cover class and biomass value
    - Only returns data if point is within effective area (user group - forest overlap)

    **Example:**
    ```
    GET /api/calculations/{calc_id}/user-group/query?lat=27.7172&lon=85.3240
    ```

    **Response:**
    ```json
    {
      "location": {"lat": 27.7172, "lon": 85.3240},
      "in_effective_area": true,
      "land_cover": {
        "class_code": 10,
        "class_name": "Tree cover"
      },
      "biomass": {
        "value_mg_ha": 150.5,
        "volume_m3_ha": 100.8
      }
    }
    ```
    """
    # H2.4 / S1-04: this route took no credentials and did no ownership
    # check — any calculation id read another community's analysis.
    require_calculation_access(db, calculation_id, current_user)

    try:
        from sqlalchemy import text

        point_wkt = f"POINT({lon} {lat})"

        # Land cover class names
        landcover_names = {
            10: "Tree cover",
            20: "Shrubland",
            30: "Grassland",
            40: "Cropland",
            50: "Built-up",
            60: "Bare / sparse vegetation",
            70: "Snow and ice",
            80: "Permanent water bodies",
            90: "Herbaceous wetland",
            95: "Mangroves",
            100: "Moss and lichen"
        }

        # First check if point is within effective area (user group - forest overlap)
        validation_query = text("""
            WITH user_extent AS (
                SELECT extent_geometry
                FROM public.user_group_extents
                WHERE calculation_id = :calc_id
                ORDER BY created_at DESC
                LIMIT 1
            ),
            forest_boundary AS (
                SELECT boundary_geom
                FROM public.calculations
                WHERE id = :calc_id
            ),
            net_geometry AS (
                SELECT
                    CASE
                        WHEN ST_Intersects(ue.extent_geometry, fb.boundary_geom) THEN
                            ST_Difference(ue.extent_geometry, fb.boundary_geom)
                        ELSE
                            ue.extent_geometry
                    END as net_geom
                FROM user_extent ue, forest_boundary fb
            )
            SELECT ST_Contains(net_geom, ST_GeomFromText(:point, 4326)) as in_effective_area
            FROM net_geometry
        """)

        validation_result = db.execute(
            validation_query,
            {"calc_id": calculation_id, "point": point_wkt}
        ).first()

        if not validation_result or not validation_result.in_effective_area:
            raise HTTPException(
                status_code=400,
                detail="Point is outside effective area (user group extent minus forest overlap)"
            )

        # Query land cover and biomass
        query = text("""
            SELECT
                (SELECT ST_Value(rast, ST_GeomFromText(:point, 4326))
                 FROM rasters.esa_world_cover
                 WHERE ST_Intersects(rast, ST_GeomFromText(:point, 4326))
                 LIMIT 1) as landcover_class,
                (SELECT ST_Value(rast, ST_GeomFromText(:point, 4326))
                 FROM rasters.agb_2022_nepal
                 WHERE ST_Intersects(rast, ST_GeomFromText(:point, 4326))
                 LIMIT 1) as biomass_mg_ha
        """)

        result = db.execute(query, {"point": point_wkt}).first()

        # Process land cover (may be None)
        landcover_class = int(result.landcover_class) if result and result.landcover_class is not None else None
        landcover_name = landcover_names.get(landcover_class, "Unknown") if landcover_class else None

        # Process biomass (may be None)
        biomass_mg_ha = float(result.biomass_mg_ha) if result and result.biomass_mg_ha is not None else None
        volume_m3_ha = round(biomass_mg_ha * 0.67, 2) if biomass_mg_ha and biomass_mg_ha > 0 else None

        return {
            "location": {
                "lat": lat,
                "lon": lon
            },
            "in_effective_area": True,
            "land_cover": {
                "class_code": landcover_class,
                "class_name": landcover_name
            } if landcover_class else None,
            "biomass": {
                "value_mg_ha": round(biomass_mg_ha, 2) if biomass_mg_ha and biomass_mg_ha > 0 else None,
                "volume_m3_ha": volume_m3_ha
            } if biomass_mg_ha and biomass_mg_ha > 0 else None
        }

    except HTTPException:
        raise

    except Exception as e:
        logger.info(f"User group point query error: {e}")
        logger.exception("User group point query failed")
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")


@router.get("/calculations/{calculation_id}/raster-coverage/{layer}")
def raster_coverage(
    calculation_id: str,
    layer: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Is the raster layer ``layer`` usable for this forest? (RS-0.4)

    The natural-feature carve needs four national rasters (NASA forest quality,
    NDVI forest health, ESA WorldCover, DEM). Each is optional on a given
    deployment, and even an installed one may not reach a particular forest. This
    answers that in one cheap query, so a missing raster is reported as a missing
    raster instead of surfacing later as a failed vectorize.

    ``layer`` must be a key of ``TileService.RASTER_TABLES`` -- the same catalog
    the tile endpoint serves from. Use ``GET /api/v1/raster-layers`` to list them.

    **Response:**
    ```json
    {
      "layer": "nasa_forest_2020",
      "table": "rasters.nasa_forest_2020",
      "table_present": true,
      "covered": true,
      "tile_count": 4,
      "has_boundary": true
    }
    ```

    Branch on ``covered``. The fields around it exist to explain a False: a
    missing ``table_present`` means the raster is not installed on this
    deployment, whereas an installed table with ``covered: false`` means the
    forest falls outside the raster's extent. Those need different fixes.
    """
    require_calculation_access(db, calculation_id, current_user)

    calc = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if calc is None:
        raise HTTPException(status_code=404, detail="Calculation not found")

    from ..services.operational_plan.prereq_check import _boundary_wkt
    from ..services.raster_coverage import UnknownRasterLayer
    from ..services.raster_coverage import raster_coverage as _coverage

    # Reuse the existing boundary reader rather than adding a fourth copy of it
    # (prereq_check already has one; so does raster_zonal's callers).
    wkt = _boundary_wkt(db, calc.id)

    try:
        return _coverage(db, wkt, layer)
    except UnknownRasterLayer:
        # A layer this server does not serve is a client mistake (a typo, or a
        # layer not in the catalog) -- 404, and never a raw SQL error.
        raise i18n_error(404, "rasters.unknown_layer", layer=layer)


@router.get("/calculations/{calculation_id}/query")
def query_point(
    calculation_id: str,
    lat: float = Query(..., description="Latitude (WGS84)", ge=-90, le=90),
    lon: float = Query(..., description="Longitude (WGS84)", ge=-180, le=180),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Get all raster values at a specific point

    **Parameters:**
    - **lat**: Latitude in decimal degrees (WGS84)
    - **lon**: Longitude in decimal degrees (WGS84)

    **Returns:**
    - JSON object with all 16 parameter values at the clicked location

    **Example:**
    ```
    GET /api/calculations/{calc_id}/query?lat=27.7172&lon=85.3240
    ```

    **Response:**
    ```json
    {
      "elevation_m": 1350.5,
      "slope_class": 3,
      "slope_class_label": "Steep",
      "slope_class_range": "31-45°",
      "slope_is_nodata": false,
      "aspect_class": 4,
      "aspect_direction": "SE",
      "canopy_height_m": 12.5,
      "biomass_mg_ha": 150.2,
      "temperature_c": 18.5,
      "precipitation_mm": 1500,
      ...
    }
    ```
    """
    # H2.4 / S1-04: this route took no credentials and did no ownership
    # check — any calculation id read another community's analysis.
    require_calculation_access(db, calculation_id, current_user)

    try:
        from sqlalchemy import text

        point_wkt = f"POINT({lon} {lat})"

        # Query only existing rasters at this point. Tree height comes from the
        # local canopy_height5m.tif (below) — the PostGIS rasters.canopy_height*
        # tables are obsolete.
        query = text("""
            SELECT
                (SELECT ST_Value(rast, ST_GeomFromText(:point, 4326)) FROM rasters.dem LIMIT 1) as elevation_m,
                -- Slope and aspect come from the COOKED class rasters, never from
                -- the DEM: rasters.slope_regulation (8BUI, nodata 0) holds class
                -- codes 1-4 and rasters.aspect holds 1-8, so a ST_Value here is a
                -- CLASS. Deriving a slope surface from the DEM (ST_Slope) was
                -- removed on purpose — the classified rasters are the source of
                -- truth (owner decision 2026-09-29).
                (SELECT ST_Value(rast, ST_GeomFromText(:point, 4326))
                   FROM rasters.slope_regulation LIMIT 1) as slope_class,
                (SELECT ST_Value(rast, ST_GeomFromText(:point, 4326)) FROM rasters.aspect LIMIT 1) as aspect_class,
                (SELECT ST_Value(rast, ST_GeomFromText(:point, 4326)) FROM rasters.agb_2022_nepal LIMIT 1) as biomass_mg_ha,
                (SELECT ST_Value(rast, ST_GeomFromText(:point, 4326)) FROM rasters.forest_type LIMIT 1) as forest_type_class
        """)

        result = db.execute(query, {"point": point_wkt}).first()

        if not result:
            raise HTTPException(status_code=404, detail="No data at this location")

        # Tree height from canopy_height5m.tif (uint8 metres, 0 = NoData)
        canopy_height_m = None
        try:
            v = next(_get_canopy_dataset().sample([(lon, lat)]))[0]
            if v is not None and 0 < float(v) <= 80:
                canopy_height_m = round(float(v), 1)
        except Exception:  # noqa: BLE001 -- height is optional in the response
            logger.debug("canopy TIF point sample failed", exc_info=True)

        # Convert aspect class to direction name
        aspect_names = ['Flat', 'N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
        aspect_class = int(result.aspect_class) if result.aspect_class is not None else 0

        # Slope is a CLASS from rasters.slope_regulation, not degrees. The bands
        # are the ones documented in core/constants.py. Reporting the code as
        # "degrees" (this endpoint used to send `slope_degrees`) put a degree
        # sign on a value in 1..4, so the field now carries the class and its
        # band. 0 is the raster's NoData and is surfaced as such.
        slope_class = int(result.slope_class) if result.slope_class is not None else 0
        slope_band = SLOPE_CLASS_BANDS.get(slope_class)
        slope_label = SLOPE_CLASS_NAMES.get(slope_class)

        return {
            "location": {
                "lat": lat,
                "lon": lon
            },
            "elevation_m": round(result.elevation_m, 1) if result.elevation_m is not None else None,
            "slope_class": slope_class or None,
            "slope_class_label": slope_label,
            "slope_class_range": slope_band,
            "slope_is_nodata": slope_class == 0,
            "aspect_class": aspect_class or None,
            "aspect_direction": aspect_names[aspect_class] if 0 <= aspect_class < len(aspect_names) else None,
            "canopy_height_m": canopy_height_m,
            "biomass_mg_ha": round(result.biomass_mg_ha, 1) if result.biomass_mg_ha is not None else None,
            "forest_type_class": int(result.forest_type_class) if result.forest_type_class is not None else None
        }

    except HTTPException:
        raise

    except Exception as e:
        logger.info(f"Point query error: {e}")
        logger.exception("Point query failed")
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")


@router.get("/calculations/{calculation_id}/steep-slope-mask/{z}/{x}/{y}.png")
def get_steep_slope_mask_tile(
    calculation_id: str,
    z: int,
    x: int,
    y: int,
    threshold: int = Query(default=4, ge=1, le=4, description="Slope class threshold (1=all slopes, 2=class 2+, 3=class 3+, 4=class 4 only)"),
    alpha: int = Query(default=180, ge=0, le=255, description="Transparency (0=transparent, 255=opaque)"),
    db: Session = Depends(get_db),
    _: None = Depends(require_tile_access),
):
    """
    Get steep slope mask tile - shows areas with slope ABOVE the threshold
    
    **Purpose:**
    - Helps users visually identify steep slopes for defining protected zones
    - Shows only areas where slope exceeds the threshold (default 30°)
    - Areas above threshold are colored red
    
    **Parameters:**
    - **threshold**: Slope threshold in degrees (default 30). Areas ABOVE this value are shown.
    - **alpha**: Transparency level (default 180 = 70%)
    
    **Returns:**
    - PNG image (256×256 pixels) with steep slopes in red
    - HTTP 404 if calculation not found
    - HTTP 500 if tile generation fails
    
    **Example:**
    ```
    GET /api/calculations/{calc_id}/steep-slope-mask/14/12345/6789.png?threshold=30
    ```
    """
    try:
        from sqlalchemy import text
        import io
        from PIL import Image, ImageDraw
        
        logger.info(f"[SteepSlope] ===== Tile request: calc={calculation_id}, z={z}, x={x}, y={y}, threshold={threshold} =====")
        
        # Get boundary WKT
        boundary_query = text("""
            SELECT ST_AsText(boundary_geom) as wkt
            FROM calculations
            WHERE id = :calc_id
        """)
        
        boundary_result = db.execute(boundary_query, {"calc_id": calculation_id}).first()
        
        if not boundary_result or not boundary_result.wkt:
            raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)
        
        boundary_wkt = boundary_result.wkt
        logger.info(f"[SteepSlope] Boundary WKT length: {len(boundary_wkt)}")
        logger.info(f"[SteepSlope] Boundary WKT sample: {boundary_wkt[:100]}...")
        
        # Convert XYZ to bounds
        n = 2.0 ** z
        lon_min = x / n * 360.0 - 180.0
        lon_max = (x + 1) / n * 360.0 - 180.0
        
        lat_max_rad = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
        lat_max = math.degrees(lat_max_rad)
        
        lat_min_rad = math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n)))
        lat_min = math.degrees(lat_min_rad)
        
        logger.info(f"[SteepSlope] Tile bounds: lon=[{lon_min:.4f}, {lon_max:.4f}], lat=[{lat_min:.4f}, {lat_max:.4f}]")

        # Map threshold to minimum class to display
        if threshold >= 4:
            min_class = 4
        elif threshold == 3:
            min_class = 3
        elif threshold == 2:
            min_class = 2
        else:
            min_class = 1
            
        logger.info(f"[SteepSlope] Showing classes >= {min_class}")
        
        try:
            # Use the exact same grid sampling approach as tile_service
            sample_size = 32
            lon_step = (lon_max - lon_min) / sample_size
            lat_step = (lat_max - lat_min) / sample_size
            
            # Same query as tile_service uses
            query = text("""
                WITH forest_boundary AS (
                    SELECT ST_GeomFromText(:boundary_wkt, 4326) as geom
                ),
                relevant_rasters AS (
                    SELECT r.rast
                    FROM rasters.slope_regulation r, forest_boundary f
                    WHERE ST_Intersects(r.rast, f.geom)
                ),
                grid AS (
                    SELECT
                        i.i as i,
                        j.j as j,
                        :min_lon + (i.i * :lon_step) + (:lon_step / 2.0) as lon,
                        :min_lat + (j.j * :lat_step) + (:lat_step / 2.0) as lat
                    FROM
                        generate_series(0, :sample_size - 1) as i(i),
                        generate_series(0, :sample_size - 1) as j(j)
                )
                SELECT
                    g.i,
                    g.j,
                    ST_Value(r.rast, ST_SetSRID(ST_MakePoint(g.lon, g.lat), 4326)) as val
                FROM grid g
                CROSS JOIN relevant_rasters r
                CROSS JOIN forest_boundary f
                WHERE
                    ST_Contains(f.geom, ST_SetSRID(ST_MakePoint(g.lon, g.lat), 4326))
                    AND ST_Value(r.rast, ST_SetSRID(ST_MakePoint(g.lon, g.lat), 4326)) IS NOT NULL
                LIMIT 2000
            """)
            
            result = db.execute(query, {
                "boundary_wkt": boundary_wkt,
                "min_lon": lon_min,
                "min_lat": lat_min,
                "lon_step": lon_step,
                "lat_step": lat_step,
                "sample_size": sample_size
            }).fetchall()
            
            logger.info(f"[SteepSlope] Grid samples: {len(result)}")
            
            if not result or len(result) == 0:
                logger.info(f"[SteepSlope] No grid data - returning fallback")
                raise ValueError("No grid data found")
            
            # Count by class
            class_counts = {}
            for row in result:
                c = int(row.val) if row.val else 0
                class_counts[c] = class_counts.get(c, 0) + 1
            logger.info(f"[SteepSlope] Class distribution: {class_counts}")
            
            # Convert to list of dicts for the drawing loop
            raster_data = [{'i': row.i, 'j': row.j, 'val': row.val} for row in result]
            
            # Create 256x256 image using same approach as tile_service
            cell_size = 256 // sample_size  # 8
            img = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            
            # Draw each grid cell with reclass logic
            for sample in raster_data:
                i = sample['i']
                j = sample['j']
                val = sample['val']
                
                if val is None:
                    continue
                
                # Reclass: only show cells >= min_class
                if val >= min_class:
                    color = (220, 38, 38, alpha)  # Red
                else:
                    continue  # Skip non-steep cells (transparent)
                
                x1 = i * cell_size
                y1 = (sample_size - 1 - j) * cell_size  # Flip Y axis like tile_service
                x2 = x1 + cell_size
                y2 = y1 + cell_size
                
                draw.rectangle([x1, y1, x2, y2], fill=color)
            
            img_bytes = io.BytesIO()
            img.save(img_bytes, format='PNG')
            img_bytes.seek(0)
            
            logger.info(f"[SteepSlope] Generated PNG with {len(raster_data)} data points, size={len(img_bytes.getvalue())} bytes")
            return Response(
                content=img_bytes.getvalue(),
                media_type="image/png",
                headers={
                    "Cache-Control": "public, max-age=3600",
                    "Content-Type": "image/png",
                }
            )
             
        except Exception as e:
            logger.info(f"[SteepSlope] Query failed: {e}")
            logger.exception("Steep slope query failed")
        
        # Fallback: return empty transparent tile
        img = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='PNG')
        img_bytes.seek(0)
        
        return Response(
            content=img_bytes.getvalue(),
            media_type="image/png",
            headers={
                "Cache-Control": "public, max-age=3600",
                "Content-Type": "image/png",
            }
        )
        
    except HTTPException:
        raise
        
    except Exception as e:
        logger.info(f"Steep slope tile error: {e}")
        logger.exception("Steep slope tile generation failed")
        raise HTTPException(status_code=500, detail=f"Tile generation failed: {str(e)}")


# Cache for canopy height dataset (lazy-loaded from local GeoTIFF)
_canopy_dataset = None


def _get_canopy_dataset():
    global _canopy_dataset
    if _canopy_dataset is None:
        import rasterio
        _canopy_dataset = rasterio.open('D:/forest_management/canopy_height5m.tif')
    return _canopy_dataset


@router.get("/calculations/{calculation_id}/canopy-mask/{z}/{x}/{y}.png")
def get_canopy_mask_tile(
    calculation_id: str,
    z: int,
    x: int,
    y: int,
    alpha: int = Query(default=180, ge=0, le=255, description="Transparency (0=transparent, 255=opaque)"),
    show_red: bool = Query(default=True, alias="red", description="Show red class (no canopy)"),
    show_blue: bool = Query(default=True, alias="blue", description="Show blue class (low canopy 1-15m)"),
    show_green: bool = Query(default=True, alias="green", description="Show green class (tall canopy >15m)"),
    db: Session = Depends(get_db),
    _: None = Depends(require_tile_access),
):
    """
    Get canopy height tile - reads from local canopy_height5m.tif

    Displays 3 reclassified classes (clipped to forest boundary):
      Class 1 (red):   pixel value = 0     (background/nodata)
      Class 2 (blue):  pixel value = 1-15  (low canopy)
      Class 3 (green): pixel value > 15    (tall canopy)

    **Returns:**
    - PNG image (256x256 pixels) with colored canopy classes inside forest boundary
    """
    try:
        from sqlalchemy import text
        import io
        from PIL import Image, ImageDraw
        from shapely.geometry import Point
        from shapely import wkt

        # Get boundary WKT
        boundary_query = text("""
            SELECT ST_AsText(boundary_geom) as wkt
            FROM calculations
            WHERE id = :calc_id
        """)

        boundary_result = db.execute(boundary_query, {"calc_id": calculation_id}).first()

        if not boundary_result or not boundary_result.wkt:
            raise HTTPException(status_code=404, detail=CalculationErrors.NOT_FOUND)

        boundary_wkt = boundary_result.wkt
        boundary_geom = wkt.loads(boundary_wkt)

        ds = _get_canopy_dataset()

        # Convert XYZ to lat/lon bounds
        n = 2.0 ** z
        lon_min = x / n * 360.0 - 180.0
        lon_max = (x + 1) / n * 360.0 - 180.0

        lat_max_rad = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
        lat_max = math.degrees(lat_max_rad)

        lat_min_rad = math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n)))
        lat_min = math.degrees(lat_min_rad)

        sample_size = 32
        cell_size = 256 // sample_size
        lon_step = (lon_max - lon_min) / sample_size
        lat_step = (lat_max - lat_min) / sample_size

        img = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        color_map = {
            1: (255, 0, 0, alpha),    # red   - value=0
            2: (0, 0, 255, alpha),    # blue  - value=1-15
            3: (0, 255, 0, alpha),    # green - value>15
        }

        show_map = {1: show_red, 2: show_blue, 3: show_green}

        for i in range(sample_size):
            for j in range(sample_size):
                lon = lon_min + (i + 0.5) * lon_step
                lat = lat_min + (j + 0.5) * lat_step

                # Skip cells outside forest boundary
                point = Point(lon, lat)
                if not boundary_geom.contains(point):
                    continue

                row, col = ds.index(lon, lat)

                if 0 <= row < ds.height and 0 <= col < ds.width:
                    val = int(ds.read(1, window=((row, row + 1), (col, col + 1)))[0][0])

                    if val == 0:
                        cls = 1
                    elif val <= 15:
                        cls = 2
                    else:
                        cls = 3

                    if not show_map[cls]:
                        continue

                    color = color_map[cls]
                    x1 = i * cell_size
                    y1 = (sample_size - 1 - j) * cell_size
                    x2 = x1 + cell_size
                    y2 = y1 + cell_size
                    draw.rectangle([x1, y1, x2, y2], fill=color)

        img_bytes = io.BytesIO()
        img.save(img_bytes, format='PNG')
        img_bytes.seek(0)

        return Response(
            content=img_bytes.getvalue(),
            media_type="image/png",
            headers={
                "Cache-Control": "public, max-age=3600",
                "Content-Type": "image/png",
            }
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.info(f"[CanopyMask] Error: {e}")
        logger.exception("Canopy mask tile generation failed")
        raise HTTPException(status_code=500, detail=f"Canopy mask tile generation failed: {str(e)}")
