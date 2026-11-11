"""User Group spatial analysis and extent management.
# business: CFMG — user group extent boundaries for community forest

Service for User Group Map analysis: handles extent creation from
uploaded GeoJSON, spatial analysis (point-in-polygon, area computation),
building footprint tracking, and data export for the OP document.

Main class:
    UserGroupAnalysisService — provides all extent CRUD and analysis ops.

See also:
    app.api.user_group — API endpoints consuming this service
    app.models.user_group.UserGroupExtent — spatial model for extents
"""

from sqlalchemy.orm import Session
from sqlalchemy import text
from app.core.constants import SQM_PER_HA
from app.models.user_group import UserGroupExtent, UserGroupBuilding
from app.models.calculation import Calculation
from app.utils.safe_archive import safe_extract
from fastapi import UploadFile
import tempfile
import os
import json
from typing import List, Dict, Any, Optional
from uuid import UUID
import logging
from app.core.errors import CalculationErrors

logger = logging.getLogger(__name__)


class UserGroupTooLarge(ValueError):
    """The user group is bigger than the analysis limit (constants.USER_GROUP_MAX_ANALYSIS_AREA_HA)."""

    def __init__(self, area_ha: float, limit_ha: float):
        self.area_ha = area_ha
        self.limit_ha = limit_ha
        super().__init__(
            f"User group area {area_ha:,.0f} ha exceeds the {limit_ha:,.0f} ha analysis limit. "
            "Draw a smaller boundary."
        )


class UserGroupAnalysisService:
    """
    Service for User Group Map analysis
    Handles extent creation, spatial analysis, and data export
    """

    def __init__(self, db: Session):
        self.db = db
        self.notes: list = []  # findings about what was noticed and fixed while reading a file (UP-3); the API returns them

    def _forest_bbox(self, calculation_id: str):
        """(lon_min, lat_min, lon_max, lat_max) of the forest boundary, to tell UTM zone 44 from 45; None when there is no boundary."""
        row = self.db.execute(
            text("SELECT ST_XMin(boundary_geom), ST_YMin(boundary_geom), ST_XMax(boundary_geom), ST_YMax(boundary_geom) FROM calculations WHERE id = :c"),
            {"c": str(calculation_id)},
        ).first()
        return tuple(float(v) for v in row) if row and row[0] is not None else None

    def _persist_extent(
        self,
        calculation_id: str,
        extent_geometry,
        user_id: UUID,
        source_type: str,
        buffer_distance_m: Optional[int] = None,
        replace: bool = True,
    ) -> UserGroupExtent:
        """Insert one user-group polygon as its own row (P7).

        `extent_geometry` may be a WKT string or a shapely geometry.

        `replace=True` is the old single-row behaviour: clear any prior extent,
        then insert. `replace=False` APPENDS, which is what a manual draw and a
        file import now do - the owner's model is one polygon per row, so drawing
        a second boundary ADDS a feature instead of destroying the first.

        That distinction matters beyond convenience: `user_group_buildings.extent_id`
        is `ondelete="CASCADE"`, so the old always-replace silently deleted the
        previous boundary's ANALYSIS along with the row. Appending ends that
        data loss. Auto-buffer keeps `replace=True` because it derives a buffer
        from the whole group and is not a second user-authored boundary.

        Every workspace-facing creator routes through here, so this stays the one
        place the invariant is expressed.
        """
        from shapely.geometry import MultiPolygon
        from shapely import force_2d
        from shapely import wkt as _wkt

        geom = extent_geometry
        if isinstance(geom, str):
            geom = _wkt.loads(geom)
        geom = force_2d(geom)
        if geom.geom_type == "Polygon":
            geom = MultiPolygon([geom])
        geom_wkt = geom.wkt

        from app.services.user_group_size_guard import ensure_candidate_within_limit

        ensure_candidate_within_limit(self.db, calculation_id, geom, replace=replace)  # D2: before the delete below commits
        if replace:
            self._delete_existing_extents(calculation_id)

        extent = UserGroupExtent(
            calculation_id=UUID(calculation_id),
            user_id=user_id,
            extent_geometry=geom_wkt,
            source_type=source_type,
            buffer_distance_m=buffer_distance_m,
        )
        self.db.add(extent)
        self.db.commit()
        self.db.refresh(extent)
        return extent

    def _persist_extent_parts(
        self,
        calculation_id: str,
        multi_polygon,
        user_id: UUID,
        source_type: str,
        replace: bool = True,
    ) -> List[UserGroupExtent]:
        """Persist a MultiPolygon as ONE ROW PER separated part (P7a).

        An import of three separated polygons is three user-group features with
        three attribute rows - not one row holding a 3-part MultiPolygon. The
        importers resolve to a single (Multi)Polygon for validation, then this
        splits it back out, so the importers do not each have to learn the rule.
        """
        from shapely.geometry import MultiPolygon as _MP

        if multi_polygon is None or multi_polygon.is_empty:
            return []
        # Owner decision D2: refuse an over-limit group BEFORE anything is deleted or written (the delete below commits).
        from app.services.user_group_size_guard import ensure_candidate_within_limit

        ensure_candidate_within_limit(self.db, calculation_id, multi_polygon, replace=replace)
        if multi_polygon.geom_type == "Polygon":
            parts: List[Any] = [multi_polygon]
        else:
            parts = list(getattr(multi_polygon, "geoms", []))
        rows: List[UserGroupExtent] = []
        for part in parts:
            if part is None or part.is_empty:
                continue
            rows.append(
                self._persist_extent(
                    calculation_id,
                    _MP([part]) if part.geom_type == "Polygon" else part,
                    user_id,
                    source_type=source_type,
                    replace=replace and not rows,
                )
            )
        return rows

    def _polygonise_extent(self, geometries: list):
        """Point / line / polygon shapely list → one (Multi)Polygon extent.

        Reuses the Forest-Boundary engine (`feature_to_polygon` + point-hull +
        `derive_boundary_from_polygons`) so a CSV/Excel point sheet, a GPS
        track, or a shapefile of polygons all resolve the same way (plan D2a).
        """
        from app.services.file_processor import (
            feature_to_polygon,
            PolygonizeConfig,
            derive_boundary_from_polygons,
        )

        shapes = [g for g in (geometries or []) if g is not None and not g.is_empty]
        if not shapes:
            raise ValueError("File contains no usable geometry")

        poly_feats, _warn = feature_to_polygon(
            shapes,
            [{} for _ in shapes],
            PolygonizeConfig(
                allow_point_hull=True,
                alpha=None,
                name_prefix="User Group",
                island_cluster_m=1e9,
            ),
        )
        poly_geoms = [g for g, _ in poly_feats if g is not None and not g.is_empty]
        if not poly_geoms:
            raise ValueError(
                "Points are collinear or too close together — cannot form a user-group polygon"
            )
        merged = derive_boundary_from_polygons(poly_geoms)
        if merged is None or merged.is_empty or merged.area <= 1e-12:
            raise ValueError("Imported features produced no user-group polygon")
        return merged

    # ------------------------------------------------------------------
    # Reading the extents (P7b)
    # ------------------------------------------------------------------
    # A calculation can hold SEVERAL user-group polygons, one row each (P7a).
    # These helpers are the only sanctioned way to read them, because the idiom
    # they replace - `.order_by(created_at.desc()).first()` - was a latest-wins
    # shortcut that, once more than one row exists, silently picks an ARBITRARY
    # polygon and produces a wrong answer rather than an error.
    #
    # Owner's decision (2026-09-28): rows are a storage and display concern, so
    # the ANALYSIS stays a single computation over the UNION of the polygons.
    #
    # The per-polygon readers further down (`..._for_extent(extent_id)`) take an
    # explicit extent_id and are unaffected: they were always about ONE row.

    def get_extents(self, calculation_id: str) -> List[UserGroupExtent]:
        """Every user-group polygon for the calculation, in a stable order.

        Stable = creation order then id, so an attribute table or a diff of two
        reads gets the same order both times. The old code sorted by
        `created_at DESC` and took ONE, which had no stable-order guarantee at
        all once two rows shared a timestamp.
        """
        return list(
            self.db.query(UserGroupExtent)
            .filter(UserGroupExtent.calculation_id == UUID(calculation_id))
            .order_by(UserGroupExtent.created_at.asc(), UserGroupExtent.id.asc())
            .all()
        )

    def get_union_extent_geometry(self, calculation_id: str):
        """The union of every user-group polygon, or None when there are none.

        This is what the analysis operates on. Disjoint polygons union to a
        MultiPolygon, which is the correct "whole user group" shape - a group
        spread over two areas is still one group, and the owner asked for one
        analysis over the union.
        """
        from shapely.geometry import MultiPolygon
        from shapely.ops import unary_union
        from geoalchemy2.shape import to_shape

        shapes = []
        for row in self.get_extents(calculation_id):
            if row.extent_geometry is None:
                continue
            geom = to_shape(row.extent_geometry)
            if geom is None or geom.is_empty:
                continue
            shapes.append(geom)
        if not shapes:
            return None
        if len(shapes) == 1:
            return shapes[0]
        merged = unary_union(shapes)
        if merged.geom_type == "GeometryCollection":
            polys = []
            for g in merged.geoms:
                if g.geom_type == "Polygon":
                    polys.append(g)
                elif g.geom_type == "MultiPolygon":
                    polys.extend(g.geoms)
            if not polys:
                return None
            merged = MultiPolygon(polys)
        return merged

    def get_extent_features(self, calculation_id: str) -> List[Dict[str, Any]]:
        """One GeoJSON Feature PER stored polygon - the attribute-table view (P7e).

        Each row is a feature, so three separated polygons are three features and
        the table lists three rows. The id is the plain row id, NOT a synthetic
        `user_group#<id>#<part>`: with one polygon per row there is no part index
        to carry, which is what retires the P6 machinery.

        A row holding a single island is unwrapped from the column's MULTIPOLYGON
        to a plain Polygon, so one feature really is one shape and the frontend
        never has to split a row into parts. A row that genuinely holds several
        parts (the user drew one) is left as the MultiPolygon it is.
        """
        if not self.get_extents(calculation_id):
            return []
        rows = self.db.execute(
            text(
                "SELECT id, ST_AsGeoJSON(extent_geometry) AS g, "
                "ST_Area(geography(extent_geometry)) / :sqm_per_ha AS area, "
                "source_type, buffer_distance_m "
                "FROM public.user_group_extents "
                "WHERE calculation_id = :cid AND extent_geometry IS NOT NULL "
                "ORDER BY created_at ASC, id ASC"
            ),
            {"cid": str(calculation_id), "sqm_per_ha": SQM_PER_HA},
        ).all()
        feats: List[Dict[str, Any]] = []
        for r in rows:
            geometry = None
            if r[1]:
                geometry = json.loads(r[1])
                if (
                    isinstance(geometry, dict)
                    and geometry.get("type") == "MultiPolygon"
                    and len(geometry.get("coordinates") or []) == 1
                ):
                    # One part in a MULTIPOLYGON column: hand back the Polygon.
                    geometry = {
                        "type": "Polygon",
                        "coordinates": geometry["coordinates"][0],
                    }
            feats.append(
                {
                    "id": str(r[0]),
                    "area_hectares": round(r[2], 4) if r[2] is not None else None,
                    "source_type": r[3],
                    "buffer_distance_m": r[4],
                    "geometry": geometry,
                }
            )
        return feats

    def get_extent_geojson(self, calculation_id: str) -> Optional[Dict[str, Any]]:
        """The whole user group - the UNION of every polygon - as one Feature.

        Kept as ONE feature because the analysis is one computation over the
        union (P7c). The per-polygon rows are `get_extent_features`.

        The union and its area are aggregated by PostGIS rather than summed in
        Python: `ST_Union` then `ST_Area(geography(...))` stays geodesic, and two
        polygons that happen to overlap count once instead of twice.
        """
        row = self.db.execute(
            text(
                "SELECT ST_AsGeoJSON(ST_Multi(ST_Union(extent_geometry))) AS g, "
                "ST_Area(geography(ST_Union(extent_geometry))) / :sqm_per_ha AS area, "
                "COUNT(*) AS n "
                "FROM public.user_group_extents "
                "WHERE calculation_id = :cid AND extent_geometry IS NOT NULL"
            ),
            {"cid": str(calculation_id), "sqm_per_ha": SQM_PER_HA},
        ).first()
        if not row or row[0] is None:
            return None
        extents = self.get_extents(calculation_id)
        return {
            "extent_id": str(extents[0].id) if extents else None,
            "extent_ids": [str(e.id) for e in extents],
            "polygon_count": int(row[2] or 0),
            "source_type": extents[0].source_type if extents else None,
            "buffer_distance_m": extents[0].buffer_distance_m if extents else None,
            "area_hectares": round(row[1], 4) if row[1] is not None else None,
            "geometry": json.loads(row[0]),
        }

    async def create_extent_from_import(
        self,
        calculation_id: str,
        file: "UploadFile",
        user_id: UUID,
        crs_epsg: Optional[int] = None,
        gpx_selection: Optional[list] = None,
        lat_col: Optional[str] = None,
        lon_col: Optional[str] = None,
    ) -> UserGroupExtent:
        """Import an extent from any supported file — Forest-Boundary-identical.

        SHP (zipped or bare `.shp`), KML, KMZ, GeoJSON, GeoPackage, GPX, CSV,
        Excel `.xlsx`; point / line / polygon. Reuses `process_uploaded_file`
        (magic-byte + CRS + `safe_extract`) and the polygonise engine, then
        replaces the current extent (plan D2a).

        For CSV/Excel files, ``lat_col`` / ``lon_col`` override the auto-detected
        coordinate columns (UP-3.2 column picker).
        """
        from app.services.file_processor import process_uploaded_file
        from shapely.geometry import Point, MultiPoint

        try:
            geometries, _attrs, _meta = await process_uploaded_file(
                file, crs_epsg=crs_epsg, gpx_selection=gpx_selection,
                purpose="user_group_boundary",
                lat_col=lat_col, lon_col=lon_col,
            )
        except ValueError as exc:
            # UP-3.1: coordinates in UTM metres (no CRS stated) used to be refused with "not in Nepal". When exactly one UTM zone puts them in
            # Nepal (the forest boundary decides between two), convert them: the conversion is certain, the user's work is not lost, and the
            # response says what we did.
            fixed = await self._retry_with_detected_utm(
                exc, calculation_id, file, gpx_selection, crs_epsg,
                lat_col=lat_col, lon_col=lon_col,
            )
            if fixed is None:
                raise
            geometries, _attrs, _meta = fixed

        # Swapped lat/lon guard for point layers (mirrors workspace import).
        pts = []
        for g in geometries:
            t = getattr(g, "geom_type", "")
            if t == "Point":
                pts.append(g)
            elif t == "MultiPoint":
                pts.extend(list(getattr(g, "geoms", []) or []))
        if len(pts) >= 2:
            import numpy as _np
            from app.services.validators.coordinate_detector import CoordinateDetector
            xs = _np.asarray([p.x for p in pts], dtype=float)
            ys = _np.asarray([p.y for p in pts], dtype=float)
            if CoordinateDetector().detect_crs(xs, ys).get("error") == "coordinates_swapped":
                fixed = []
                for g in geometries:
                    t = getattr(g, "geom_type", "")
                    if t == "Point":
                        fixed.append(Point(g.y, g.x))
                    elif t == "MultiPoint":
                        fixed.append(MultiPoint([(p.y, p.x) for p in g.geoms]))
                    else:
                        fixed.append(g)
                geometries = fixed
                from app.services.upload.findings import finding as _finding

                self.notes.append(_finding("coordinates.swapped_fixed", file=getattr(file, "filename", None)))

        merged = self._polygonise_extent(geometries)
        # P7a: a file with three separated polygons is THREE user-group
        # features with three attribute rows, not one row holding a 3-part
        # MultiPolygon. `_persist_extent_parts` splits the validated
        # MultiPolygon back out, so the importers do not each learn the rule.
        rows = self._persist_extent_parts(
            calculation_id, merged, user_id, source_type="uploaded", replace=True
        )
        if not rows:
            raise ValueError("Imported features produced no user-group polygon")
        return rows[0]

    async def _retry_with_detected_utm(
        self, exc: Exception, calculation_id: str, file, gpx_selection, crs_epsg,
        lat_col=None, lon_col=None,
    ):
        from app.services.file_processor import process_uploaded_file
        from app.services.upload.coordinates import diagnose
        from app.services.upload.findings import finding

        import re as _re

        m = _re.search(r"longitude ([-\d.]+)\.\.([-\d.]+), latitude ([-\d.]+)\.\.([-\d.]+);", str(exc))
        if crs_epsg is not None or "not in Nepal" not in str(exc) or not m:
            return None
        # the message quotes the extent AS READ (as if degrees): for UTM metres those numbers are the metres themselves
        x0, x1, y0, y1 = (float(v) for v in m.groups())
        d = diagnose([x0, x1], [y0, y1], reference_bbox=self._forest_bbox(calculation_id))
        if d["kind"] != "utm":
            return None
        await file.seek(0)
        result = await process_uploaded_file(
            file, crs_epsg=d["epsg"], gpx_selection=gpx_selection,
            purpose="user_group_boundary", lat_col=lat_col, lon_col=lon_col,
        )
        self.notes.append(finding("coordinates.utm_converted", found=d["zone"], file=getattr(file, "filename", None)))
        return result

    def _delete_existing_extents(self, calculation_id: str) -> int:
        """
        Delete all existing extents for this calculation
        CASCADE will automatically delete related user_group_buildings
        Returns: number of extents deleted
        """
        try:
            deleted_count = self.db.query(UserGroupExtent).filter(
                UserGroupExtent.calculation_id == UUID(calculation_id)
            ).delete()
            self.db.commit()
            logger.info(f"Deleted {deleted_count} existing extents for calculation {calculation_id}")
            return deleted_count
        except Exception as e:
            logger.error(f"Error deleting existing extents: {e}")
            self.db.rollback()
            return 0

    async def process_uploaded_boundary(
        self,
        calculation_id: str,
        file: UploadFile,
        user_id: UUID
    ) -> UserGroupExtent:
        """
        Process uploaded boundary file and create extent
        Supports: KML, KMZ, Shapefile, GPX, GeoJSON, CSV
        # constraint: boundary upload supports KML, KMZ, Shapefile, GPX, GeoJSON, CSV
        """
        # Check if extent already exists
        existing = self.db.query(UserGroupExtent).filter(
            UserGroupExtent.calculation_id == UUID(calculation_id)
        ).first()
        if existing:
            raise ValueError("User Group extent already exists. Please delete it first before uploading a new one.")

        # Save uploaded file temporarily
        temp_dir = tempfile.mkdtemp()
        file_ext = file.filename.lower().split('.')[-1]
        file_path = os.path.join(temp_dir, file.filename)

        try:
            # Save file
            with open(file_path, "wb") as f:
                content = await file.read()
                f.write(content)

            # Process based on file type
            if file_ext in ['kml', 'kmz']:
                geometry_wkt = self._process_kml(file_path)
            elif file_ext == 'zip':  # Shapefile
                geometry_wkt = self._process_shapefile(file_path)
            elif file_ext == 'gpx':
                geometry_wkt = self._process_gpx(file_path)
            elif file_ext in ['geojson', 'json']:
                geometry_wkt = self._process_geojson(file_path)
            elif file_ext == 'csv':
                geometry_wkt = self._process_csv(file_path)
            else:
                raise ValueError(f"Unsupported file format: {file_ext}")

            # Create extent record
            extent = UserGroupExtent(
                calculation_id=UUID(calculation_id),
                user_id=user_id,
                extent_geometry=geometry_wkt,
                source_type='uploaded'
            )
            self.db.add(extent)
            self.db.commit()
            self.db.refresh(extent)

            return extent

        finally:
            # Cleanup temp files
            if os.path.exists(file_path):
                os.remove(file_path)
            if os.path.exists(temp_dir):
                os.rmdir(temp_dir)

    def _process_kml(self, file_path: str) -> str:
        """Process KML/KMZ file and return WKT"""
        try:
            import geopandas as gpd
            from shapely.geometry import MultiPolygon
            from shapely import force_2d

            # Try reading KML with geopandas
            # geopandas can use fiona or pyogrio backend
            try:
                gdf = gpd.read_file(file_path, driver='KML')
            except Exception:
                logger.warning(
                    "KML driver failed for %s - retrying with driver auto-detection",
                    file_path, exc_info=True,
                )
                # If KML driver fails, try without specifying driver
                gdf = gpd.read_file(file_path)

            gdf = gdf.to_crs('EPSG:4326')

            # Combine all geometries
            geometry = gdf.geometry.unary_union

            # Force 2D (remove Z dimension if present)
            geometry = force_2d(geometry)

            # Ensure MultiPolygon
            if geometry.geom_type == 'Polygon':
                geometry = MultiPolygon([geometry])

            return geometry.wkt

        except Exception as e:
            logger.error(f"Error processing KML: {e}")
            raise ValueError(f"Failed to process KML file: {str(e)}")

    def _process_shapefile(self, zip_path: str) -> str:
        """Process Shapefile (ZIP) and return WKT"""
        try:
            import zipfile
            import geopandas as gpd
            from shapely.geometry import MultiPolygon
            from shapely import force_2d

            temp_dir = tempfile.mkdtemp()

            # Extract ZIP.
            #
            # H2.9 / S3-10: this was a bare extractall() with no checks of any
            # kind — an uploaded shapefile archive containing ../../app/main.py
            # would have been written straight over the application.
            safe_extract(zip_path, temp_dir)

            # Find .shp file
            shp_files = [f for f in os.listdir(temp_dir) if f.endswith('.shp')]
            if not shp_files:
                raise ValueError("No .shp file found in ZIP")

            shp_path = os.path.join(temp_dir, shp_files[0])

            # Read shapefile
            gdf = gpd.read_file(shp_path)
            gdf = gdf.to_crs('EPSG:4326')

            # Combine geometries
            geometry = gdf.geometry.unary_union

            # Force 2D (remove Z dimension if present)
            geometry = force_2d(geometry)

            if geometry.geom_type == 'Polygon':
                geometry = MultiPolygon([geometry])

            return geometry.wkt

        except Exception as e:
            logger.error(f"Error processing Shapefile: {e}")
            raise ValueError(f"Failed to process Shapefile: {str(e)}")

    def _process_gpx(self, file_path: str) -> str:
        """Process GPX track file - convert to polygon"""
        try:
            import geopandas as gpd
            from shapely.geometry import MultiPolygon
            from shapely import force_2d

            # Read GPX tracks
            gdf = gpd.read_file(file_path, layer='tracks')
            gdf = gdf.to_crs('EPSG:4326')

            # Convert LineString to Polygon using convex hull
            geometry = gdf.geometry.unary_union.convex_hull

            # Force 2D (remove Z dimension if present)
            geometry = force_2d(geometry)

            if geometry.geom_type == 'Polygon':
                geometry = MultiPolygon([geometry])

            return geometry.wkt

        except Exception as e:
            logger.error(f"Error processing GPX: {e}")
            raise ValueError(f"Failed to process GPX file: {str(e)}")

    def _process_geojson(self, file_path: str) -> str:
        """Process GeoJSON file"""
        try:
            import geopandas as gpd
            from shapely.geometry import MultiPolygon
            from shapely import force_2d

            gdf = gpd.read_file(file_path)
            gdf = gdf.to_crs('EPSG:4326')

            geometry = gdf.geometry.unary_union

            # Force 2D (remove Z dimension if present)
            geometry = force_2d(geometry)

            if geometry.geom_type == 'Polygon':
                geometry = MultiPolygon([geometry])

            return geometry.wkt

        except Exception as e:
            logger.error(f"Error processing GeoJSON: {e}")
            raise ValueError(f"Failed to process GeoJSON file: {str(e)}")

    def _process_csv(self, file_path: str, lat_col: Optional[str] = None, lon_col: Optional[str] = None) -> str:
        """Process CSV with coordinates - convert to polygon"""
        try:
            import pandas as pd
            from shapely.geometry import Polygon, MultiPolygon, Point
            from shapely import force_2d

            df = pd.read_csv(file_path)

            # Use provided column names or auto-detect
            if not lat_col or not lon_col:
                for col in df.columns:
                    col_lower = col.lower()
                    if col_lower in ['lat', 'latitude', 'y', 'अक्षांश']:
                        lat_col = col
                    if col_lower in ['lon', 'long', 'longitude', 'x', 'देशान्तर']:
                        lon_col = col

            if not lat_col or not lon_col:
                raise ValueError("CSV must have lat/lon columns")

            # Create polygon from points
            points = [(row[lon_col], row[lat_col]) for _, row in df.iterrows()]

            if len(points) < 3:
                raise ValueError("Need at least 3 points to create a polygon")

            polygon = Polygon(points)

            # Force 2D (should already be 2D, but just in case)
            polygon = force_2d(polygon)

            geometry = MultiPolygon([polygon])

            return geometry.wkt

        except Exception as e:
            logger.error(f"Error processing CSV: {e}")
            raise ValueError(f"Failed to process CSV file: {str(e)}")

    async def create_manual_extent(
        self,
        calculation_id: str,
        geometry: Dict[str, Any],
        user_id: UUID,
        source_type: str = "manual",
    ) -> UserGroupExtent:
        """Add a digitized polygon as ANOTHER user-group feature (P7a).

        This used to replace the single extent, so drawing a second boundary
        silently destroyed the first - and, through the CASCADE on
        `user_group_buildings.extent_id`, its analysis too. The owner's model
        is one polygon per row, so this now APPENDS: drawing twice gives two
        rows and two attribute entries.
        """
        try:
            from shapely.geometry import shape

            geom = shape(geometry)
            if geom.is_empty:
                raise ValueError("Empty geometry")
            return self._persist_extent(
                calculation_id, geom, user_id,
                source_type=source_type, replace=False,
            )

        except Exception as e:
            logger.error(f"Error creating manual extent: {e}")
            raise

    async def create_auto_buffer(
        self,
        calculation_id: str,
        buffer_distance_m: int,
        user_id: UUID
    ) -> UserGroupExtent:
        """Create auto-buffer extent from forest boundary. Replaces the current
        extent (single-feature layer — plan D1)."""
        # constraint: buffer distance default 1000m, configurable
        try:
            # Get forest boundary
            calc = self.db.query(Calculation).filter(
                Calculation.id == UUID(calculation_id)
            ).first()

            if not calc:
                raise ValueError(CalculationErrors.NOT_FOUND)

            # Create buffer using PostGIS (in meters using UTM)
            # Convert boundary_geom to GeoJSON
            boundary_geojson_query = text("""
                SELECT ST_AsGeoJSON(boundary_geom)
                FROM public.calculations
                WHERE id = :calc_id
            """)
            boundary_geojson = self.db.execute(
                boundary_geojson_query,
                {'calc_id': str(calc.id)}
            ).first()[0]

            query = text("""
                SELECT ST_AsText(
                    ST_Transform(
                        ST_Buffer(
                            ST_Transform(ST_GeomFromGeoJSON(:geom), 32645),  -- NOTE: UTM 45N (32645) for Nepal, transform back to WGS84 after buffer
                            :distance
                        ),
                        4326  -- Convert back to WGS84
                    )
                ) as buffered_geom
            """)

            result = self.db.execute(query, {
                'geom': boundary_geojson,
                'distance': buffer_distance_m
            }).first()

            buffered_geom_wkt = result[0]

            return self._persist_extent(
                calculation_id, buffered_geom_wkt, user_id,
                source_type="auto_buffer", buffer_distance_m=buffer_distance_m,
            )

        except Exception as e:
            logger.error(f"Error creating auto-buffer: {e}")
            raise

    def _invalidate_group_caches(self, calculation_id: str) -> None:
        """The polygons changed, so everything derived from their union is stale: the land-cover result
        (cached on the calculation), the OP data cache and the rendered usergroup map."""
        cid = UUID(str(calculation_id))
        try:
            calc = self.db.query(Calculation).filter(Calculation.id == cid).first()
            if calc is not None and calc.result_data and "user_group_land_cover" in calc.result_data:
                fresh = dict(calc.result_data)  # JSONB: assign a new dict, in-place mutation is lost
                fresh.pop("user_group_land_cover", None)
                calc.result_data = fresh
            from app.models.op_data_cache import OpDataCache
            self.db.query(OpDataCache).filter(OpDataCache.calculation_id == cid).delete(synchronize_session=False)
            self.db.commit()
        except Exception as e:  # noqa: BLE001 -- a stale cache is recoverable; the analysis must still run
            self.db.rollback()
            logger.warning(f"Could not clear user-group caches for {calculation_id}: {e}")
        try:
            # the hazard / soil-loss grids span the forest AND the user group, so their cached GeoTIFFs are stale too
            from app.services.operational_plan import landslide_susceptibility, soil_erosion

            landslide_susceptibility.clear_cache(cid)  # one shared directory: also covers slope stability
            soil_erosion.clear_cache(cid)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Could not clear the hazard / soil caches for {calculation_id}: {e}")
        try:
            from app.services.management_plan_docx.plan_map_service import clear_map_cache
            clear_map_cache(calculation_id=cid, layer_name="usergroup")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Could not clear the usergroup map cache for {calculation_id}: {e}")

    def assert_area_within_limit(self, calculation_id: str) -> float:
        """Raise `UserGroupTooLarge` when the group's total area exceeds the analysis limit.

        Area is the geodesic area of the union of every polygon, in hectares.
        """
        from app.core.constants import USER_GROUP_MAX_ANALYSIS_AREA_HA

        area_ha = self.db.execute(
            text("""
                SELECT COALESCE(ST_Area(ST_Union(extent_geometry)::geography), 0) / 10000.0
                FROM public.user_group_extents
                WHERE calculation_id = :cid AND extent_geometry IS NOT NULL
            """),
            {"cid": str(calculation_id)},
        ).scalar() or 0.0
        if area_ha > USER_GROUP_MAX_ANALYSIS_AREA_HA:
            raise UserGroupTooLarge(float(area_ha), USER_GROUP_MAX_ANALYSIS_AREA_HA)
        return float(area_ha)

    async def analyze_all(self, calculation_id: str) -> List[Dict[str, Any]]:
        """Analyse EVERY polygon of the group and replace all previous results.

        Called automatically after a boundary is drawn, imported, uploaded or
        buffered, so nobody has to press "Analyze". Old results are cleared first:
        `analyze_user_group` returns early (leaving them behind) when a polygon
        holds no buildings, which would otherwise show a stale analysis.
        """
        extents = self.get_extents(calculation_id)
        if not extents:
            return []
        self.assert_area_within_limit(calculation_id)
        self._invalidate_group_caches(calculation_id)
        try:
            self.db.query(UserGroupBuilding).filter(
                UserGroupBuilding.extent_id.in_([e.id for e in extents])
            ).delete(synchronize_session=False)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        results: List[Dict[str, Any]] = []
        for e in extents:
            results.extend(await self.analyze_user_group(calculation_id, e.id))
        return results

    async def analyze_user_group(
        self,
        calculation_id: str,
        extent_id: int
    ) -> List[Dict[str, Any]]:
        """
        Main analysis:
        1. Clip buildings and settlements
        2. Assign buildings to nearest settlement
        3. Calculate statistics
        4. Calculate direction from forest centroid
        # business: spatial analysis pipeline: clip → assign → calculate → save
        """
        import time
        analysis_start = time.time()

        try:
            logger.info(f"🔍 Starting User Group analysis for extent_id={extent_id}")

            # Get extent
            step_start = time.time()
            extent = self.db.query(UserGroupExtent).filter(
                UserGroupExtent.id == extent_id
            ).first()

            if not extent:
                raise ValueError("Extent not found")
            logger.info(f"  ✓ Get extent: {time.time() - step_start:.3f}s")

            # Get forest centroid
            step_start = time.time()
            calc = self.db.query(Calculation).filter(
                Calculation.id == UUID(calculation_id)
            ).first()

            # Convert boundary_geom to use directly in ST_Centroid
            forest_centroid_query = text("""
                SELECT ST_AsText(ST_Centroid(boundary_geom)) as centroid
                FROM public.calculations
                WHERE id = :calc_id
            """)
            forest_centroid = self.db.execute(
                forest_centroid_query,
                {'calc_id': str(calc.id)}
            ).first()[0]
            logger.info(f"  ✓ Get forest centroid: {time.time() - step_start:.3f}s")

            # Get extent geometry as WKT text for spatial queries
            step_start = time.time()
            extent_wkt_query = text("""
                SELECT ST_AsText(extent_geometry)
                FROM public.user_group_extents
                WHERE id = :extent_id
            """)
            extent_wkt = self.db.execute(
                extent_wkt_query,
                {'extent_id': extent.id}
            ).first()[0]
            logger.info(f"  ✓ Get extent WKT: {time.time() - step_start:.3f}s")

            # Clip buildings and settlements
            step_start = time.time()
            buildings = self._clip_buildings(extent_wkt)
            logger.info(f"  ✓ Clip buildings: {time.time() - step_start:.3f}s (found {len(buildings)} buildings)")

            step_start = time.time()
            settlements = self._clip_settlements(extent_wkt)
            logger.info(f"  ✓ Clip settlements: {time.time() - step_start:.3f}s (found {len(settlements)} settlements)")

            # If no buildings found at all, return early
            if not buildings:
                logger.warning("No buildings found within extent")
                return []

            # If no settlements found, create a virtual settlement for all buildings
            if not settlements:
                logger.info("No settlements found within extent - creating virtual 'User Group Area' settlement")
                # Calculate centroid of all buildings as virtual settlement location
                avg_lon = sum(b['centroid_lon'] for b in buildings) / len(buildings)
                avg_lat = sum(b['centroid_lat'] for b in buildings) / len(buildings)

                settlements = [{
                    'id': -1,  # Virtual settlement ID
                    'name': 'User Group Area',
                    'geometry': json.dumps({
                        'type': 'Point',
                        'coordinates': [avg_lon, avg_lat]
                    }),
                    'lon': avg_lon,
                    'lat': avg_lat
                }]

            # Assign buildings to settlements
            step_start = time.time()
            building_settlement_map = self._assign_buildings_to_settlements(
                buildings, settlements
            )
            logger.info(f"  ✓ Assign buildings to settlements: {time.time() - step_start:.3f}s ({len(buildings)} × {len(settlements)} calculations)")

            # Calculate statistics per settlement
            step_start = time.time()
            results = []

            # Clear existing analysis results for this extent
            self.db.query(UserGroupBuilding).filter(
                UserGroupBuilding.extent_id == extent_id
            ).delete()

            for settlement in settlements:
                settlement_buildings = [
                    b for b in buildings
                    if building_settlement_map.get(b['id']) == settlement['id']
                ]

                building_count = len(settlement_buildings)
                total_area = sum(b['area_m2'] for b in settlement_buildings)

                # Categorize buildings by size
                # Small: < 50 m², Medium: 50-150 m², Large: > 150 m²
                small_count = sum(1 for b in settlement_buildings if b['area_m2'] < 50)
                medium_count = sum(1 for b in settlement_buildings if 50 <= b['area_m2'] <= 150)
                large_count = sum(1 for b in settlement_buildings if b['area_m2'] > 150)
                avg_building_size = total_area / building_count if building_count > 0 else 0

                # Calculate direction from forest centroid
                direction = self._calculate_direction(
                    forest_centroid,
                    settlement['geometry']
                )

                # Convert building polygons to points (centroids)
                building_points = [
                    {
                        'lat': b['centroid_lat'],
                        'lon': b['centroid_lon'],
                        'area': b['area_m2']
                    }
                    for b in settlement_buildings
                ]

                # Create settlement location point
                settlement_point = f"POINT({settlement['lon']} {settlement['lat']})"

                # Save to database
                user_group_building = UserGroupBuilding(
                    extent_id=extent_id,
                    settlement_id=settlement['id'],
                    settlement_name=settlement['name'],
                    building_count=building_count,
                    total_building_area_m2=total_area,
                    direction_from_forest=direction,
                    buildings_geojson=building_points,
                    settlement_location=settlement_point
                )
                self.db.add(user_group_building)

                results.append({
                    'settlement_name': settlement['name'],
                    'building_count': building_count,
                    'total_area_m2': total_area,
                    'small_buildings': small_count,
                    'medium_buildings': medium_count,
                    'large_buildings': large_count,
                    'avg_building_size_m2': avg_building_size,
                    'direction': direction
                })

            logger.info(f"  ✓ Calculate statistics: {time.time() - step_start:.3f}s")

            step_start = time.time()
            self.db.commit()
            logger.info(f"  ✓ Save to database: {time.time() - step_start:.3f}s")

            total_time = time.time() - analysis_start
            logger.info(f"✅ User Group analysis completed in {total_time:.2f}s")

            return results

        except Exception as e:
            self.db.rollback()
            logger.error(f"❌ Error analyzing user group: {e}")
            raise

    def _clip_buildings(self, extent_geom: str) -> List[Dict[str, Any]]:
        """Query buildings within extent"""
        try:
            query = text(f"""
                SELECT
                    b.objectid,
                    ST_AsGeoJSON(b.shape) as geometry,
                    ST_Area(b.shape::geography) as area_m2,
                    ST_X(ST_Centroid(b.shape)) as centroid_lon,
                    ST_Y(ST_Centroid(b.shape)) as centroid_lat
                FROM buildings.building b
                WHERE ST_Intersects(b.shape, ST_GeomFromText(:extent, 4326))
                LIMIT {SQM_PER_HA}
            """)

            results = self.db.execute(query, {'extent': extent_geom}).fetchall()

            return [
                {
                    'id': r[0],
                    'geometry': r[1],
                    'area_m2': float(r[2]) if r[2] else 0.0,
                    'centroid_lon': float(r[3]),
                    'centroid_lat': float(r[4])
                }
                for r in results
            ]

        except Exception as e:
            logger.error(f"Error clipping buildings: {e}")
            self.db.rollback()
            return []

    def _clip_settlements(self, extent_geom: str) -> List[Dict[str, Any]]:
        """Query settlements within extent"""
        try:
            query = text("""
                SELECT
                    s.objectid,
                    s.vil_name,
                    ST_AsGeoJSON(s.shape) as geometry,
                    s.x as lon,
                    s.y as lat
                FROM admin.settlement s
                WHERE ST_Intersects(s.shape, ST_GeomFromText(:extent, 4326))
                LIMIT 1000
            """)

            results = self.db.execute(query, {'extent': extent_geom}).fetchall()

            return [
                {
                    'id': r[0],
                    'name': r[1] or f'Settlement {r[0]}',
                    'geometry': r[2],
                    'lon': float(r[3]) if r[3] else 0.0,
                    'lat': float(r[4]) if r[4] else 0.0
                }
                for r in results
            ]

        except Exception as e:
            logger.error(f"Error clipping settlements: {e}")
            self.db.rollback()
            return []

    def _assign_buildings_to_settlements(
        self,
        buildings: List[Dict],
        settlements: List[Dict]
    ) -> Dict[int, int]:
        # constraint: building-to-settlement assignment uses centroid distance (degrees)
        """Assign each building to nearest settlement"""
        if not buildings or not settlements:
            return {}

        try:
            # Use PostGIS for efficient nearest neighbor
            building_ids = [str(b['id']) for b in buildings]
            building_geoms = [b['geometry'] for b in buildings]
            settlement_ids = [str(s['id']) for s in settlements]
            settlement_geoms = [s['geometry'] for s in settlements]

            # For simplicity, use a lateral join approach
            mapping = {}
            for building in buildings:
                min_distance = float('inf')
                nearest_settlement = None

                for settlement in settlements:
                    # Simple distance calculation (could be optimized)
                    from math import sqrt
                    dx = building['centroid_lon'] - settlement['lon']
                    dy = building['centroid_lat'] - settlement['lat']
                    distance = sqrt(dx*dx + dy*dy)

                    if distance < min_distance:
                        min_distance = distance
                        nearest_settlement = settlement['id']

                if nearest_settlement:
                    mapping[building['id']] = nearest_settlement

            return mapping

        except Exception as e:
            logger.error(f"Error assigning buildings to settlements: {e}")
            return {}

    def _calculate_direction(
        self,
        forest_centroid_wkt: str,
        settlement_geom_json: str
    ) -> str:
        """Calculate compass direction from forest to settlement"""
        try:
            query = text("""
                SELECT
                    CASE
                        WHEN degrees(ST_Azimuth(
                            ST_GeomFromText(:forest_centroid, 4326),
                            ST_GeomFromGeoJSON(:settlement_geom)
                        )) BETWEEN 337.5 AND 360
                            OR degrees(ST_Azimuth(
                                ST_GeomFromText(:forest_centroid, 4326),
                                ST_GeomFromGeoJSON(:settlement_geom)
                            )) BETWEEN 0 AND 22.5 THEN 'N'
                        WHEN degrees(ST_Azimuth(
                            ST_GeomFromText(:forest_centroid, 4326),
                            ST_GeomFromGeoJSON(:settlement_geom)
                        )) BETWEEN 22.5 AND 67.5 THEN 'NE'
                        WHEN degrees(ST_Azimuth(
                            ST_GeomFromText(:forest_centroid, 4326),
                            ST_GeomFromGeoJSON(:settlement_geom)
                        )) BETWEEN 67.5 AND 112.5 THEN 'E'
                        WHEN degrees(ST_Azimuth(
                            ST_GeomFromText(:forest_centroid, 4326),
                            ST_GeomFromGeoJSON(:settlement_geom)
                        )) BETWEEN 112.5 AND 157.5 THEN 'SE'
                        WHEN degrees(ST_Azimuth(
                            ST_GeomFromText(:forest_centroid, 4326),
                            ST_GeomFromGeoJSON(:settlement_geom)
                        )) BETWEEN 157.5 AND 202.5 THEN 'S'
                        WHEN degrees(ST_Azimuth(
                            ST_GeomFromText(:forest_centroid, 4326),
                            ST_GeomFromGeoJSON(:settlement_geom)
                        )) BETWEEN 202.5 AND 247.5 THEN 'SW'
                        WHEN degrees(ST_Azimuth(
                            ST_GeomFromText(:forest_centroid, 4326),
                            ST_GeomFromGeoJSON(:settlement_geom)
                        )) BETWEEN 247.5 AND 292.5 THEN 'W'
                        ELSE 'NW'
                    END as direction
            """)

            result = self.db.execute(query, {
                'forest_centroid': forest_centroid_wkt,
                'settlement_geom': settlement_geom_json
            }).first()

            return result[0] if result else 'Unknown'

        except Exception as e:
            logger.error(f"Error calculating direction: {e}")
            return 'Unknown'

    async def get_results(self, calculation_id: str) -> Optional[Dict[str, Any]]:
        """Get all analysis results for visualization"""
        try:
            # Get the extents. EVERY polygon, not the latest one: a group
            # made of several polygons is still one group (P7c).
            extents = self.get_extents(calculation_id)

            if not extents:
                return None

            # Buildings are keyed to the polygon that contains them, so a
            # group spanning several polygons has its buildings spread
            # across several `extent_id`s. Filtering on the one 'latest' row
            # dropped the rest - with a single extent that read happened to be
            # right, which is exactly why it survived.
            buildings = self.db.query(UserGroupBuilding).filter(
                UserGroupBuilding.extent_id.in_([e.id for e in extents])
            ).all()

            # Get forest boundary
            calc = self.db.query(Calculation).filter(
                Calculation.id == UUID(calculation_id)
            ).first()

            # The extent geometry as GeoJSON - the UNION of every polygon, so a
            # group made of several polygons renders as one whole group (P7b).
            # ST_Multi keeps the response a MultiPolygon: ST_Union of a single row
            # reduces to a Polygon, which would change the existing contract.
            extent_geojson_query = text("""
                SELECT ST_AsGeoJSON(ST_Multi(ST_Union(extent_geometry)))
                FROM public.user_group_extents
                WHERE calculation_id = :cid AND extent_geometry IS NOT NULL
            """)
            extent_geojson = self.db.execute(
                extent_geojson_query,
                {'cid': str(calculation_id)}
            ).first()[0]

            # Convert forest boundary_geom to GeoJSON
            forest_boundary_query = text("""
                SELECT ST_AsGeoJSON(boundary_geom)
                FROM public.calculations
                WHERE id = :calc_id
            """)
            forest_boundary_geojson = self.db.execute(
                forest_boundary_query,
                {'calc_id': str(calc.id)}
            ).first()[0]

            return {
                'extent_id': extents[0].id,
                'extent_geometry': json.loads(extent_geojson),
                'forest_boundary': json.loads(forest_boundary_geojson),
                'settlements': [
                    self._enrich_settlement_with_categories(b)
                    for b in buildings
                ],
                'buildings': [
                    building_point
                    for b in buildings
                    if b.buildings_geojson
                    for building_point in b.buildings_geojson
                ]
            }

        except Exception as e:
            logger.error(f"Error getting results: {e}")
            return None

    def _enrich_settlement_with_categories(self, building_record: UserGroupBuilding) -> Dict[str, Any]:
        """Calculate building size categories from the buildings_geojson field"""
        # Extract building areas from the geojson
        building_areas = []
        if building_record.buildings_geojson:
            building_areas = [b.get('area', 0) for b in building_record.buildings_geojson]

        # Categorize: Small < 50 m², Medium 50-150 m², Large > 150 m²
        small_count = sum(1 for area in building_areas if area < 50)
        medium_count = sum(1 for area in building_areas if 50 <= area <= 150)
        large_count = sum(1 for area in building_areas if area > 150)

        total_area = float(building_record.total_building_area_m2) if building_record.total_building_area_m2 else 0
        avg_size = total_area / building_record.building_count if building_record.building_count > 0 else 0

        return {
            'settlement_id': building_record.settlement_id,
            'settlement_name': building_record.settlement_name,
            'building_count': building_record.building_count,
            'total_area_m2': total_area,
            'small_buildings': small_count,
            'medium_buildings': medium_count,
            'large_buildings': large_count,
            'avg_building_size_m2': round(avg_size, 2),
            'direction_from_forest': building_record.direction_from_forest,
            'lat': self._get_point_lat(building_record.settlement_location),
            'lon': self._get_point_lon(building_record.settlement_location)
        }

    def _get_point_lat(self, point_geom) -> Optional[float]:
        """Extract latitude from point geometry (handles both WKT and WKBElement)"""
        if not point_geom:
            return None
        try:
            from geoalchemy2.shape import to_shape
            point = to_shape(point_geom)
            return float(point.y)
        except Exception:
            logger.exception(
                "settlement latitude unreadable - the row will be written with no "
                "coordinates"
            )
            return None

    def _get_point_lon(self, point_geom) -> Optional[float]:
        """Extract longitude from point geometry (handles both WKT and WKBElement)"""
        if not point_geom:
            return None
        try:
            from geoalchemy2.shape import to_shape
            point = to_shape(point_geom)
            return float(point.x)
        except Exception:
            logger.exception(
                "settlement longitude unreadable - the row will be written with "
                "no coordinates"
            )
            return None

    async def get_poi_layers(
        self,
        calculation_id: str,
        layer_type: str = "all"
    ) -> Dict[str, List]:
        """Get POI layers for visualization"""
        # business: POI layers from infrastructure schema (education, health, rivers, poi)
        # why: land cover analysis clipped to extent boundary
        try:
            # The layers are clipped to the WHOLE user group, so query within
            # the UNION of every polygon (P7b).
            extent_wkt = self.db.execute(
                text("""
                    SELECT ST_AsText(ST_Union(extent_geometry))
                    FROM public.user_group_extents
                    WHERE calculation_id = :cid AND extent_geometry IS NOT NULL
                """),
                {'cid': str(calculation_id)},
            ).first()[0]

            if not extent_wkt:
                return {}

            poi_data = {}

            # POI layer
            if layer_type in ['all', 'poi']:
                poi_query = text("""
                    SELECT
                        COALESCE(name, name_en) as name,
                        amenity,
                        ST_X(geom) as lon,
                        ST_Y(geom) as lat
                    FROM infrastructure.poi
                    WHERE ST_Intersects(geom, ST_GeomFromText(:extent, 4326))
                    LIMIT 500
                """)
                poi_results = self.db.execute(
                    poi_query,
                    {'extent': extent_wkt}
                ).fetchall()
                poi_data['poi'] = [
                    {
                        'name': r[0] or 'Unknown',
                        'type': r[1],
                        'lon': float(r[2]),
                        'lat': float(r[3])
                    }
                    for r in poi_results
                ]

            # Education facilities
            if layer_type in ['all', 'education']:
                edu_query = text("""
                    SELECT
                        name,
                        ST_X(geom) as lon,
                        ST_Y(geom) as lat
                    FROM infrastructure.education_facilities
                    WHERE ST_Intersects(geom, ST_GeomFromText(:extent, 4326))
                    LIMIT 200
                """)
                try:
                    edu_results = self.db.execute(
                        edu_query,
                        {'extent': extent_wkt}
                    ).fetchall()
                    poi_data['education'] = [
                        {
                            'name': r[0] or 'School',
                            'lon': float(r[1]),
                            'lat': float(r[2])
                        }
                        for r in edu_results
                    ]
                except Exception:
                    # An empty list is indistinguishable from a catchment with no
                    # schools, and that is what the report will say.
                    logger.exception(
                        "education POI query failed - the analysis will report no schools "
                        "in the area, which is not the same as finding none"
                    )
                    poi_data['education'] = []

            # Health facilities
            if layer_type in ['all', 'health']:
                health_query = text("""
                    SELECT
                        hf_type,
                        ST_X(geom) as lon,
                        ST_Y(geom) as lat
                    FROM infrastructure.health_facilities
                    WHERE ST_Intersects(geom, ST_GeomFromText(:extent, 4326))
                    LIMIT 200
                """)
                try:
                    health_results = self.db.execute(
                        health_query,
                        {'extent': extent_wkt}
                    ).fetchall()
                    poi_data['health'] = [
                        {
                            'name': r[0] or 'Health Facility',
                            'lon': float(r[1]),
                            'lat': float(r[2])
                        }
                        for r in health_results
                    ]
                except Exception:
                    logger.exception(
                        "health POI query failed - the analysis will report no health "
                        "facilities in the area, which is not the same as finding none"
                    )
                    poi_data['health'] = []

            # Rivers
            if layer_type in ['all', 'rivers']:
                river_query = text("""
                    SELECT
                        river_name,
                        ST_AsGeoJSON(geom) as geometry
                    FROM river.river84
                    WHERE ST_Intersects(geom, ST_GeomFromText(:extent, 4326))
                    LIMIT 100
                """)
                try:
                    river_results = self.db.execute(
                        river_query,
                        {'extent': extent_wkt}
                    ).fetchall()
                    poi_data['rivers'] = [
                        {
                            'name': r[0] or 'River',
                            'geometry': json.loads(r[1])
                        }
                        for r in river_results
                    ]
                except Exception:
                    logger.exception(
                        "river query failed - the analysis will report no rivers in the "
                        "area, which is not the same as finding none"
                    )
                    poi_data['rivers'] = []

            return poi_data

        except Exception as e:
            logger.error(f"Error getting POI layers: {e}")
            return {}

    # Export functions (placeholders for now)
    async def generate_pdf_report(self, extent_id: int) -> str:
        """Generate PDF report - placeholder"""
        raise NotImplementedError("PDF export not yet implemented")

    async def export_to_gpkg(self, extent_id: int) -> str:
        """Export to GeoPackage - placeholder"""
        raise NotImplementedError("GeoPackage export not yet implemented")

    async def export_to_geojson(self, extent_id: int) -> str:
        """Export extent, settlements, and buildings to GeoJSON"""
        import tempfile

        try:
            # Get extent
            extent = self.db.query(UserGroupExtent).filter(
                UserGroupExtent.id == extent_id
            ).first()

            if not extent:
                raise ValueError("Extent not found")

            # Get settlement statistics
            buildings = self.db.query(UserGroupBuilding).filter(
                UserGroupBuilding.extent_id == extent_id
            ).all()

            # Get extent geometry as GeoJSON
            extent_geom_query = text("""
                SELECT ST_AsGeoJSON(extent_geometry)
                FROM public.user_group_extents
                WHERE id = :extent_id
            """)
            extent_geojson = self.db.execute(
                extent_geom_query,
                {'extent_id': extent_id}
            ).first()[0]

            # Build GeoJSON FeatureCollection
            features = []

            # Add extent boundary as a feature
            features.append({
                'type': 'Feature',
                'properties': {
                    'type': 'extent_boundary',
                    'source_type': extent.source_type,
                    'buffer_distance_m': extent.buffer_distance_m
                },
                'geometry': json.loads(extent_geojson)
            })

            # Add settlements as point features
            for b in buildings:
                if b.settlement_location:
                    # Calculate building size categories from buildings_geojson
                    building_areas = [building.get('area', 0) for building in b.buildings_geojson] if b.buildings_geojson else []
                    small_count = sum(1 for area in building_areas if area < 50)
                    medium_count = sum(1 for area in building_areas if 50 <= area <= 150)
                    large_count = sum(1 for area in building_areas if area > 150)
                    total_area = float(b.total_building_area_m2) if b.total_building_area_m2 else 0
                    avg_size = total_area / b.building_count if b.building_count and b.building_count > 0 else 0

                    features.append({
                        'type': 'Feature',
                        'properties': {
                            'type': 'settlement',
                            'settlement_name': b.settlement_name,
                            'building_count': b.building_count,
                            'total_area_m2': total_area,
                            'small_buildings': small_count,
                            'medium_buildings': medium_count,
                            'large_buildings': large_count,
                            'avg_building_size_m2': round(avg_size, 2),
                            'direction_from_forest': b.direction_from_forest
                        },
                        'geometry': {
                            'type': 'Point',
                            'coordinates': [
                                self._get_point_lon(b.settlement_location),
                                self._get_point_lat(b.settlement_location)
                            ]
                        }
                    })

                # Add individual buildings if available
                if b.buildings_geojson:
                    for building in b.buildings_geojson:
                        features.append({
                            'type': 'Feature',
                            'properties': {
                                'type': 'building',
                                'settlement_name': b.settlement_name,
                                'area_m2': building.get('area', 0)
                            },
                            'geometry': {
                                'type': 'Point',
                                'coordinates': [building['lon'], building['lat']]
                            }
                        })

            geojson_data = {
                'type': 'FeatureCollection',
                'features': features
            }

            # Create temporary GeoJSON file
            temp_file = tempfile.NamedTemporaryFile(
                mode='w',
                delete=False,
                suffix='.geojson',
                encoding='utf-8'
            )
            json.dump(geojson_data, temp_file, indent=2)
            temp_file.close()

            return temp_file.name

        except Exception as e:
            logger.error(f"Error exporting to GeoJSON: {e}")
            raise

    async def export_to_csv(self, extent_id: int) -> str:
        """Export settlement statistics to CSV"""
        import csv
        import tempfile

        try:
            # Get settlement statistics
            buildings = self.db.query(UserGroupBuilding).filter(
                UserGroupBuilding.extent_id == extent_id
            ).order_by(UserGroupBuilding.settlement_name).all()

            if not buildings:
                raise ValueError("No analysis data found for this extent")

            # Create temporary CSV file
            temp_file = tempfile.NamedTemporaryFile(
                mode='w',
                delete=False,
                suffix='.csv',
                newline='',
                encoding='utf-8'
            )

            writer = csv.writer(temp_file)

            # Write header
            writer.writerow([
                'बस्तीको नाम (Settlement Name)',
                'भवन सङ्ख्या (Number of Buildings)',
                'जम्मा भवन क्षेत्रफल / Total Building Area (m²)',
                'साना भवन / Small Buildings (<50m²)',
                'मध्यम भवन / Medium Buildings (50-150m²)',
                'ठूला भवन / Large Buildings (>150m²)',
                'औसत भवन आकार / Average Building Size (m²)',
                'वनबाट दिशा (Direction from Forest)',
                'अक्षांश (Latitude)',
                'देशान्तर (Longitude)'
            ])

            # Write data rows
            for b in buildings:
                # Calculate building size categories from buildings_geojson
                building_areas = [building.get('area', 0) for building in b.buildings_geojson] if b.buildings_geojson else []
                small_count = sum(1 for area in building_areas if area < 50)
                medium_count = sum(1 for area in building_areas if 50 <= area <= 150)
                large_count = sum(1 for area in building_areas if area > 150)
                total_area = float(b.total_building_area_m2) if b.total_building_area_m2 else 0
                avg_size = total_area / b.building_count if b.building_count and b.building_count > 0 else 0

                writer.writerow([
                    b.settlement_name or 'Unknown',
                    b.building_count or 0,
                    round(total_area, 2),
                    small_count,
                    medium_count,
                    large_count,
                    round(avg_size, 2),
                    b.direction_from_forest or 'Unknown',
                    self._get_point_lat(b.settlement_location) if b.settlement_location else '',
                    self._get_point_lon(b.settlement_location) if b.settlement_location else ''
                ])

            temp_file.close()
            return temp_file.name

        except Exception as e:
            logger.error(f"Error exporting to CSV: {e}")
            raise

    # ============================================================================
    # Land Cover Analysis
    # ============================================================================

    async def analyze_land_cover(self, calculation_id: str, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Perform comprehensive land cover and biomass analysis for user group map

        This analysis:
        1. Gets user group extent geometry
        2. Gets community forest boundary geometry
        3. Calculates overlap and net analysis area
        4. Performs land cover classification (ESA World Cover)
        5. Calculates biomass and timber volume (AGB 2022 Nepal)

        Results are cached in database for performance optimization.

        Args:
            calculation_id: The calculation (community forest) ID
            force_refresh: If True, bypass cache and re-run analysis

        Returns:
            Dictionary with land cover classes, biomass, and area statistics

        Raises:
            ValueError: If community forest boundary or user group extent not found
        """
        from datetime import datetime, timezone

        try:
            logger.info(f"Starting land cover analysis for calculation {calculation_id} (force_refresh={force_refresh})")

            # Step 1: Get community forest boundary
            calc = self.db.query(Calculation).filter(
                Calculation.id == UUID(calculation_id)
            ).first()

            if not calc:
                raise ValueError(
                    "Community Forest boundary not found. "
                    "Please upload a forest boundary in the Analysis tab first."
                )

            # When user explicitly requests a re-analysis (force_refresh=True),
            # also invalidate OP data cache & map cache so preview shows fresh data
            if force_refresh:
                logger.info(f"FORCE_REFRESH: clearing caches for calc={calculation_id}")
                cid = UUID(calculation_id) if isinstance(calculation_id, str) else calculation_id
                try:
                    from app.models.op_data_cache import OpDataCache
                    deleted = self.db.query(OpDataCache).filter(
                        OpDataCache.calculation_id == cid
                    ).delete(synchronize_session=False)
                    self.db.commit()
                    logger.info(f"FORCE_REFRESH: OpDataCache deleted count={deleted}")
                except Exception as e:
                    logger.warning(f"FORCE_REFRESH: OpDataCache delete error: {e}")
                    self.db.rollback()
                try:
                    from app.services.management_plan_docx.plan_map_service import clear_map_cache
                    clear_map_cache(calculation_id=cid, layer_name="usergroup")
                    logger.info(f"FORCE_REFRESH: map cache cleared for usergroup")
                except Exception as e:
                    logger.warning(f"FORCE_REFRESH: map cache clear error: {e}")

            # Step 1.5: Check for cached results (unless force_refresh)
            if not force_refresh and calc.result_data and 'user_group_land_cover' in calc.result_data:
                logger.info(f"Returning cached land cover results for calculation {calculation_id}")
                cached_results = calc.result_data['user_group_land_cover']
                cached_results['from_cache'] = True
                return cached_results

            # Step 2: Confirm there IS a user group. The analysis itself runs
            # on the UNION of every polygon (Step 3), so this is a presence
            # check only - it must not pick one row (P7b).
            extents = self.get_extents(calculation_id)

            if not extents:
                raise ValueError(
                    "User Group extent not found. "
                    "Please upload or create a user group boundary in the Forest User Map tab first."
                )

            logger.info(
                f"User group: {len(extents)} polygon(s), calculation ID: {calc.id}"
            )

            # Step 3: Call PostgreSQL function to perform per-class biomass analysis
            # This ensures biomass is only counted for tree cover (and partially for shrubland/grassland)
            query = text("""
                SELECT
                    user_group_area_ha,
                    forest_overlap_area_ha,
                    net_analysis_area_ha,
                    land_cover_class,
                    land_cover_name,
                    land_cover_area_ha,
                    land_cover_percentage,
                    avg_biomass_mg_per_ha,
                    min_biomass_mg_per_ha,
                    max_biomass_mg_per_ha,
                    total_biomass_mg,
                    avg_volume_m3_per_ha,
                    total_volume_m3,
                    pixel_count
                FROM rasters.analyze_land_cover_and_biomass_per_class(
                    (SELECT ST_Union(extent_geometry) FROM public.user_group_extents
                     WHERE calculation_id = :calc_id AND extent_geometry IS NOT NULL),
                    (SELECT boundary_geom FROM public.calculations WHERE id = :calc_id)
                )
            """)

            results = self.db.execute(
                query,
                {'calc_id': str(calc.id)}
            ).fetchall()

            if not results:
                raise ValueError("No land cover data found. Please ensure raster datasets are available.")

            # Step 4: Process results
            land_cover_classes = []
            total_biomass = 0
            total_volume = 0
            user_group_area = 0
            forest_overlap_area = 0
            net_area = 0

            for row in results:
                # Extract area summary (same for all rows)
                if not land_cover_classes:
                    user_group_area = float(row[0])
                    forest_overlap_area = float(row[1])
                    net_area = float(row[2])
                    logger.info(f"PG_RESULT: user_group_area_ha={user_group_area}, forest_overlap_ha={forest_overlap_area}, net_area_ha={net_area}")

                # Extract land cover class data
                land_cover_classes.append({
                    'class_code': int(row[3]),
                    'class_name': row[4],
                    'area_ha': float(row[5]),
                    'percentage': float(row[6]),
                    'avg_biomass_mg_per_ha': float(row[7]),
                    'min_biomass_mg_per_ha': float(row[8]),
                    'max_biomass_mg_per_ha': float(row[9]),
                    'total_biomass_mg': float(row[10]),
                    'avg_volume_m3_per_ha': float(row[11]),
                    'total_volume_m3': float(row[12]),
                    'pixel_count': int(row[13])
                })

                total_biomass += float(row[10])
                total_volume += float(row[12])

            # Calculate overall averages
            avg_biomass = total_biomass / net_area if net_area > 0 else 0
            avg_volume = total_volume / net_area if net_area > 0 else 0

            logger.info(f"Land cover analysis completed: {len(land_cover_classes)} classes found")
            logger.info(f"Total biomass: {total_biomass:.2f} Mg, Total volume: {total_volume:.2f} m³")

            # Prepare results
            results = {
                'user_group_area_ha': round(user_group_area, 4),
                'forest_overlap_area_ha': round(forest_overlap_area, 4),
                'net_analysis_area_ha': round(net_area, 4),
                'land_cover_classes': land_cover_classes,
                'total_biomass_mg': round(total_biomass, 2),
                'total_volume_m3': round(total_volume, 2),
                'avg_biomass_mg_per_ha': round(avg_biomass, 2),
                'avg_volume_m3_per_ha': round(avg_volume, 2),
                'analysis_date': datetime.now(timezone.utc).isoformat(),
                'has_forest_overlap': forest_overlap_area > 0,
                'from_cache': False
            }

            # Cache results in database for future retrieval
            # NOTE: Must assign NEW dict to trigger SQLAlchemy JSONB change tracking
            new_result_data = dict(calc.result_data or {})
            new_result_data['user_group_land_cover'] = results
            calc.result_data = new_result_data
            self.db.commit()
            logger.info(f"Cached land cover results in database for calculation {calculation_id}")

            return results

        except ValueError:
            # Re-raise ValueError with original message
            raise
        except Exception as e:
            logger.error(f"Error performing land cover analysis: {e}")
            raise ValueError(f"Land cover analysis failed: {str(e)}")
