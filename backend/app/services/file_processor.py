"""
File processor for uploaded geospatial files
Handles Shapefile, KML, and GeoJSON formats (no GDAL required)
"""
# constraint: max upload 50MB
# constraint: supported formats: CSV, XLSX, SHP, GeoJSON, KML, GPX
# why: files processed in-memory to avoid temp file leaks
# NOTE: CSV encoding auto-detection (utf-8 / cp1252)
import os
import re
import csv
import tempfile
import zipfile
from typing import Tuple, Dict, Any, Optional, List, Sequence
from pathlib import Path
from ..utils.safe_archive import safe_extract, check_archive_limits
import shapefile  # pyshp - no GDAL required
import geojson
from shapely.geometry import (shape, mapping, Point, LineString, Polygon, MultiPoint,
                              MultiLineString, MultiPolygon, box as shapely_box)
from shapely import wkt
from shapely.ops import unary_union, transform, polygonize
from pyproj import CRS, Transformer
from fastapi import UploadFile, HTTPException
import xml.etree.ElementTree as ET
import sys

_PY314_PLUS = sys.version_info >= (3, 14)

import logging

from app.core.dropped import report_dropped

from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------#
# Unified polygonisation config — single typed source for feature_to_polygon
# ---------------------------------------------------------------------------#
@dataclass
class PolygonizeConfig:
    """Typed, explicit configuration for the shared Feature-to-Polygon engine.

    Replaces a vague `mode` grab-bag. Callers (sub-areas, blocks, boundary,
    user_group_boundary) supply only the fields they care about.
    """
    snap_tolerance_m: float = 20.0             # near-close ring threshold (case B)
    allow_point_hull: bool = False             # points -> hull fallback (case D; off by default)
    preserve_multipolygon: bool = True         # keep MultiPolygon / islands (invariant F)
    island_cluster_m: float = 100.0            # island cluster threshold (invariant F)
    alpha: Optional[float] = None              # alpha shape param (case D); None => convex
    name_prefix: str = "Sub-Area"              # fallback prefix when no name/attr found
    source_crs: Optional[Any] = None           # if given, inputs are reprojected to 4326


from ..core.config import settings
from ..core.constants import (
    SQM_PER_HA,
    WORKSPACE_IMPORT_MAX_FEATURES,
    WORKSPACE_IMPORT_MAX_VERTICES,
    WORKSPACE_IMPORT_MAX_AREA_HA,
    WORKSPACE_IMPORT_10KM_BUFFER_M,
    IMPORT_PURPOSE_INVENTORY,
    IMPORT_PURPOSE_SAMPLE_PLOT,
    IMPORT_PURPOSE_USER_GROUP_BOUNDARY,
    IMPORT_PURPOSE_BOUNDARY,
    IMPORT_PURPOSE_BLOCKS,
    IMPORT_PURPOSE_ROADS,
    IMPORT_PURPOSE_WATER,
    IMPORT_PURPOSE_OTHER,
    IMPORT_PURPOSE_STRICT_POINT,
    IMPORT_PURPOSE_POINT_PRESERVE,
    IMPORT_PURPOSE_LINE_PRESERVE,
    IMPORT_PURPOSE_POLYGON_AUTO_BUFFER,
    IMPORT_PURPOSE_ADMIN,
)


def _assume_wgs84_or_refuse(geometries: list, source: str) -> CRS:
    """Fall back to EPSG:4326 only when the coordinates could actually be degrees.

    Both callers reached this by failing to parse a declared CRS, and both used
    to assume WGS84 unconditionally. That assumption is free when the data
    really is in degrees and catastrophic when it is not: a UTM shapefile read
    as 4326 puts a Nepali forest in the Gulf of Guinea, and its hectares - a
    figure that ends up in a statutory document - are nonsense.

    The coordinates settle it. Longitude cannot exceed 180 and latitude cannot
    exceed 90, so a UTM easting of 500,000 is proof the guess is wrong. This
    cannot reject an import that works today: data that really is 4326 is in
    range and behaves exactly as before; data that is not was already producing
    a garbage extent, silently.
    """
    for geom in geometries:
        if geom is None or getattr(geom, "is_empty", False):
            continue
        try:
            minx, miny, maxx, maxy = geom.bounds
        except Exception:
            logger.warning(
                "could not read bounds while checking the assumed CRS - that "
                "geometry is skipped by the check", exc_info=True,
            )
            continue
        if max(abs(minx), abs(maxx)) > 180 or max(abs(miny), abs(maxy)) > 90:
            # POSTPONED 2026-08-25 (H3.4). This refused the import; it is back to
            # importing at the user's request until H3.4 is retested. The
            # detection stays, and it is now the loudest line this module emits.
            # Re-enable with:
            #   raise ValueError(
            #       f"CRS_UNREADABLE:The coordinate system of {source} could not "
            #       f"be read, and the coordinates are not longitude/latitude "
            #       f"({minx:.1f}, {miny:.1f}), so they cannot be assumed to be "
            #       f"WGS84. Re-export with a valid .prj, or convert to "
            #       f"EPSG:4326 before importing."
            #   )
            # The `imports.crs_unreadable` message and its CRS_UNREADABLE prefix
            # mapping are already in place for when it is turned back on.
            logger.error(
                "%s has an unreadable coordinate system AND coordinates that "
                "are not longitude/latitude (%.1f, %.1f). It is being imported "
                "as EPSG:4326 anyway, which is almost certainly WRONG - expect "
                "the forest to appear in the wrong place and its hectares to be "
                "nonsense.", source, minx, miny,
            )
            break
    logger.error(
        "could not read the declared CRS of %s - assuming EPSG:4326. The "
        "coordinates are within the degree range, so this is plausible, but "
        "check the imported extent and area.", source,
    )
    return CRS.from_epsg(4326)


async def read_upload_geometries(
    content: bytes,
    filename: str,
    crs_epsg: Optional[int] = None,
    gpx_selection: Optional[list] = None,
    lat_col: Optional[str] = None,
    lon_col: Optional[str] = None,
) -> Tuple[list, list, CRS]:
    """Read an uploaded file's bytes into raw (source-CRS) geometries.

    Shared by `process_uploaded_file` and the boundary-file parser so every
    supported vector format — including GeoPackage — trips exactly one
    read/dispatch/validation path.

    Returns ``(geometries, attributes, crs)`` with geometry index-aligned to
    attributes and the layer CRS resolved (defaulting to EPSG:4326). Raises
    ``ValueError`` for unsupported content, empty files, or geometry that fails
    the type / Nepal-extent checks.
    """
    file_ext = Path(filename).suffix.lower()

    # Create temporary directory for file processing
    with tempfile.TemporaryDirectory() as temp_dir:
        # Sanitize filename to prevent path traversal
        safe_filename = re.sub(r'[^\w\-_\. ]', '_', filename)
        safe_filename = os.path.basename(safe_filename)
        temp_path = Path(temp_dir) / safe_filename

        # Write uploaded content to temp file
        with open(temp_path, "wb") as buffer:
            buffer.write(content)

        # Handle ZIP files (shapefile archive or KMZ)
        if file_ext == ".zip":
            # H2.9 / S3-10: one hardened extractor for every archive site.
            # The hand-rolled checks here covered bombs and traversal but used a
            # string prefix comparison ("/tmp/out" prefixes "/tmp/output-else"),
            # and nothing anywhere refused symlinks or capped total size.
            safe_extract(temp_path, temp_dir)
            shp_files = list(Path(temp_dir).glob("*.shp"))
            if not shp_files:
                raise ValueError("No .shp file found in ZIP archive")
            file_to_process = str(shp_files[0])
        else:
            file_to_process = str(temp_path)

        # Read file based on extension
        try:
            if file_ext == ".gpkg":
                geometries, attributes, crs = read_geopackage(file_to_process)
            elif file_ext == ".zip" or file_ext == ".shp" or file_to_process.endswith(".shp"):
                geometries, attributes, crs = read_shapefile(file_to_process)
            elif file_ext == ".geojson" or file_ext == ".json":
                geometries, attributes, crs = read_geojson(file_to_process)
            elif file_ext == ".kml":
                geometries, attributes, crs = read_kml(file_to_process)
            elif file_ext == ".kmz":
                geometries, attributes, crs = read_kmz(file_to_process)
            elif file_ext == ".gpx":
                geometries, attributes, crs = read_gpx(file_to_process)
                if gpx_selection:
                    geometries, attributes = filter_gpx_by_type(geometries, attributes, gpx_selection)
            elif file_ext == ".csv":
                crs_code = crs_epsg or 4326
                geometries, attributes, crs = read_csv(
                    file_to_process, crs_epsg=crs_code, lat_col=lat_col, lon_col=lon_col
                )
            elif file_ext == ".xlsx":
                crs_code = crs_epsg or 4326
                geometries, attributes, crs = read_xlsx(
                    file_to_process, crs_epsg=crs_code, lat_col=lat_col, lon_col=lon_col
                )
            else:
                raise ValueError(f"Unsupported file type: {file_ext}")
        except Exception as e:
            raise ValueError(f"Error reading file: {str(e)}")

        if not geometries:
            raise ValueError("File contains no features")

        # Validate geometry types
        validate_geometry_types(geometries)

        # H-GEO-1: and that the file is actually in Nepal. Before the polygon
        # engine runs, because that is where a file with nonsense coordinates
        # does its damage.
        validate_geometry_within_nepal(geometries, crs)

        return geometries, attributes, crs


async def process_uploaded_file(
    file: UploadFile,
    crs_epsg: Optional[int] = None,
    gpx_selection: Optional[list] = None,
    purpose: Optional[str] = None,
    lat_col: Optional[str] = None,
    lon_col: Optional[str] = None,
) -> Tuple[list, list, Dict[str, Any]]:
    """
    Process uploaded geospatial file and extract geometry+attributes.

    Args:
        file: Uploaded file (SHP, GeoJSON, KML, KMZ, GPX, CSV, XLSX)
        crs_epsg: EPSG code for CSV/XLSX files (default: auto-detect)
        gpx_selection: List of GPX sub-types to include: ['wpt','trk','rte']
        purpose: Import purpose — drives geometry conversion behaviour
        lat_col: User-picked latitude column for CSV/XLSX (overrides detection)
        lon_col: User-picked longitude column for CSV/XLSX (overrides detection)

    Returns:
        Tuple of (geometries_list, attributes_list, metadata_dict)

    Raises:
        ValueError: If file format is not supported or contains invalid geometry
    """
    # Check file extension
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in settings.ALLOWED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file format: {file_ext}. "
            f"Supported formats: {', '.join(settings.ALLOWED_EXTENSIONS)}"
        )

    # Enforce per-file size limit for workspace imports
    max_bytes = settings.WORKSPACE_IMPORT_MAX_FILE_SIZE_MB * 1024 * 1024
    await file.seek(0)
    content = await file.read()
    if len(content) > max_bytes:
        raise ValueError(
            f"File too large: {len(content) / 1024 / 1024:.1f}MB "
            f"(workspace max: {settings.WORKSPACE_IMPORT_MAX_FILE_SIZE_MB}MB)"
        )
    await file.seek(0)

    # Verify content magic bytes match extension
    _verify_content_magic(content, file_ext)

    geometries, attributes, crs = await read_upload_geometries(
        content, file.filename, crs_epsg=crs_epsg, gpx_selection=gpx_selection,
        lat_col=lat_col, lon_col=lon_col,
    )

    # Process geometry list into unified shape
    geometry, metadata = process_geometry_list(geometries, attributes, purpose=purpose)

    # Ensure geometry is in SRID 4326
    geometry_4326 = transform_to_4326(geometry, crs)

    # Build metadata
    metadata.update({
        'source_format': file_ext,
        'feature_count': len(geometries),
        'geometry_types': list(set(g.geom_type for g in geometries)),
        'file_size_bytes': len(content),
    })

    return geometries, attributes, metadata


async def boundary_feature_from_upload(file: UploadFile) -> Dict[str, Any]:
    """Read any supported boundary file into a single boundary Feature.

    Mirrors the workspace Layer Import's ``purpose='boundary'`` conversion
    (ArcGIS-style Feature-to-Polygon for closed line rings and convex hulls for
    point clouds) so a GeoPackage — which a browser cannot parse because it is
    SQLite — behaves exactly like an equivalent KML or SHP.

    Returns a GeoJSON Feature whose geometry is a Polygon / MultiPolygon in
    EPSG:4326.
    """
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in settings.ALLOWED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file format: {file_ext}. "
            f"Supported formats: {', '.join(settings.ALLOWED_EXTENSIONS)}"
        )

    # Enforce per-file size limit (same cap as the workspace import)
    max_bytes = settings.WORKSPACE_IMPORT_MAX_FILE_SIZE_MB * 1024 * 1024
    await file.seek(0)
    content = await file.read()
    if len(content) > max_bytes:
        raise ValueError(
            f"File too large: {len(content) / 1024 / 1024:.1f}MB "
            f"(workspace max: {settings.WORKSPACE_IMPORT_MAX_FILE_SIZE_MB}MB)"
        )
    await file.seek(0)

    # Verify content magic bytes match extension
    _verify_content_magic(content, file_ext)

    geometries, attributes, crs = await read_upload_geometries(content, file.filename)

    geometry, _ = process_geometry_list(
        geometries, attributes, purpose=IMPORT_PURPOSE_BOUNDARY
    )
    geometry_4326 = transform_to_4326(geometry, crs)

    return {"type": "Feature", "geometry": mapping(geometry_4326), "properties": {}}


async def process_uploaded_file_legacy(file: UploadFile) -> Tuple[str, Dict[str, Any]]:
    """Backward-compatible wrapper — returns WKT string + metadata.

    Preserves the original signature for existing upload endpoints.
    """
    _, _, metadata = await process_uploaded_file(file)
    # Re-merge original WKT from the merged geometry
    file_ext = Path(file.filename).suffix.lower()

    # Re-run with old-style merge to get WKT
    with tempfile.TemporaryDirectory() as temp_dir:
        safe_filename = re.sub(r'[^\w\-_\. ]', '_', file.filename)
        temp_path = Path(temp_dir) / os.path.basename(safe_filename)
        await file.seek(0)
        content = await file.read()
        with open(temp_path, "wb") as buffer:
            buffer.write(content)

        await file.seek(0)

        if file_ext == ".zip":
            # H2.9 / S3-10: this site checked traversal but not bombs at all.
            safe_extract(temp_path, temp_dir)
            shp_files = list(Path(temp_dir).glob("*.shp"))
            file_to_process = str(shp_files[0]) if shp_files else str(temp_path)
        else:
            file_to_process = str(temp_path)

        if file_ext == ".zip" or file_to_process.endswith(".shp"):
            geometries, attributes, crs = read_shapefile(file_to_process)
        elif file_ext == ".geojson" or file_ext == ".json":
            geometries, attributes, crs = read_geojson(file_to_process)
        elif file_ext == ".kml":
            geometries, attributes, crs = read_kml(file_to_process)
        elif file_ext == ".kmz":
            geometries, attributes, crs = read_kmz(file_to_process)
        elif file_ext == ".gpx":
            geometries, attributes, crs = read_gpx(file_to_process)
        elif file_ext == ".csv":
            geometries, attributes, crs = read_csv(file_to_process)
        elif file_ext == ".xlsx":
            geometries, attributes, crs = read_xlsx(file_to_process)
        else:
            raise ValueError(f"Unsupported: {file_ext}")

        geometry, _ = process_geometry_list(geometries, attributes)
        geometry_4326 = transform_to_4326(geometry, crs)
        wkt = geometry_4326.wkt

    return wkt, metadata


def read_shapefile(filepath: str) -> Tuple[list, list, CRS]:
    """Read shapefile and return geometries, attributes, and CRS"""
    import logging
    logger = logging.getLogger(__name__)
    
    sf = shapefile.Reader(filepath)
    try:
        geometries = []
        attributes = []
        skipped_count = 0

        for idx, shapeRec in enumerate(sf.shapeRecords()):
            try:
                # Convert shapefile shape to shapely geometry
                geom = shape(shapeRec.shape.__geo_interface__)
                
                # Skip empty/invalid geometries
                if geom is None or geom.is_empty:
                    logger.warning(f"read_shapefile: skipping empty geometry at record {idx}")
                    skipped_count += 1
                    continue
                
                geometries.append(geom)

                # Get attributes
                attrs = {}
                for i, field in enumerate(sf.fields[1:]):  # Skip DeletionFlag
                    attrs[field[0]] = shapeRec.record[i]
                attributes.append(attrs)
                
            except Exception as e:
                logger.warning(f"read_shapefile: failed to process record {idx}: {e}")
                skipped_count += 1
                continue

        logger.info(f"read_shapefile: read {len(geometries)} geometries, skipped {skipped_count} records from {filepath}")

        # Get CRS from .prj file if exists
        prj_file = filepath.replace('.shp', '.prj')
        crs = None
        if os.path.exists(prj_file):
            prj_text = _read_text_file(prj_file)
            try:
                crs = CRS.from_wkt(prj_text)
            except Exception:
                logger.warning(
                    "the .prj of %s could not be parsed", prj_file,
                    exc_info=True,
                )
                crs = _assume_wgs84_or_refuse(geometries, "this shapefile")
        else:
            crs = CRS.from_epsg(4326)

        return geometries, attributes, crs
    finally:
        sf.close()


def _is_geopackage(filepath: str) -> bool:
    """Lightweight GeoPackage magic-byte check.

    A GeoPackage is an SQLite database whose 4-byte Application ID at offset 68
    equals 'GPKG' (0x474B5020 in the mask set => 0x47504B47). We validate the
    header so a non-GPKG file is rejected clearly rather than mis-parsed.
    """
    try:
        with open(filepath, "rb") as f:
            header = f.read(100)
    except OSError:
        return False
    if not header.startswith(b"SQLite format 3\0"):
        return False
    if len(header) >= 72 and header[68:72] == b"GPKG":
        return True
    return False


def read_geopackage(filepath: str) -> Tuple[list, list, CRS]:
    """Read GeoPackage (.gpkg) and return geometries, attributes, and CRS.

    Uses pyogrio (thin GDAL-backed reader, preferred over full geopandas/fiona).
    Returns a single combined layer (first non-empty one if the file holds
    several), geometry/attributes index-aligned like the other readers, and the
    layer CRS (falls back to WGS84 if absent).
    """
    import logging
    logger = logging.getLogger(__name__)

    if not _is_geopackage(filepath):
        raise ValueError("File is not a valid GeoPackage (bad magic bytes).")

    import pyogrio

    geometries = []
    attributes = []
    crs = None
    read_any = False

    # Enumerate layers via list_layers; identify their names.
    try:
        layers_meta = pyogrio.list_layers(filepath)
    except Exception as e:
        logger.warning(f"read_geopackage: list_layers failed ({e}); defaulting to main layer")
        layers_meta = None

    if hasattr(layers_meta, "shape") and len(layers_meta) > 0:
        # [[name, geom_type], ...]
        layer_names = [str(r[0]) for r in layers_meta if r is not None and len(r) and r[0] is not None]
    else:
        layer_names = ["main"]

    # A namespaced layer (e.g. 'prefix:layer') needs masking off.
    def _strip_prefix(layer_name: str) -> str:
        return str(layer_name).split(":", 1)[-1] if ":" in str(layer_name) else str(layer_name)

    for layer in layer_names:
        try:
            data = pyogrio.read_dataframe(filepath, layer=layer)
        except Exception as e:
            logger.warning(f"read_geopackage: failed to read layer {layer}: {e}")
            continue
        if data is None or len(data) == 0:
            continue

        layer_geom = data.geometry.tolist()
        layer_attrs = data.drop(columns="geometry").to_dict("records")
        # Ensure index alignment even with missing/null geometry values.
        for idx, g in enumerate(layer_geom):
            if g is None or g.is_empty:
                logger.warning(f"read_geopackage: skipping empty geometry in layer {layer} at {idx}")
                continue
            geometries.append(g)
            attributes.append(layer_attrs[idx] if idx < len(layer_attrs) else {})
            read_any = True

        if crs is None and data.crs is not None:
            try:
                crs = CRS.from_wkt(str(data.crs))
            except Exception:
                logger.warning(
                    "the CRS %r of layer %s could not be parsed",
                    str(getattr(data, 'crs', None)), layer, exc_info=True,
                )
                crs = _assume_wgs84_or_refuse(geometries, f"layer '{layer}'")

    if not read_any:
        raise ValueError("GeoPackage contains no readable features.")

    if crs is None:
        crs = CRS.from_epsg(4326)

    logger.info(f"read_geopackage: read {len(geometries)} geometries from {filepath}")
    return geometries, attributes, crs


def _read_text_file(filepath: str) -> str:
    """Read a text file as UTF-8, whatever the platform's default encoding is.

    ``open(path, 'r')`` uses the *locale* encoding -- cp1252 on Windows -- so a
    UTF-8 file with Devanagari in it (attribute names, place names: routine here)
    died with "'charmap' codec can't decode byte 0x8d". GeoJSON is UTF-8 by spec
    (RFC 7946), and the browser sends UTF-8, so UTF-8 is tried first (``utf-8-sig``
    also swallows a BOM). Only a file that is not valid UTF-8 -- a legacy export --
    falls back to cp1252, with undefined bytes replaced rather than refusing the file.
    """
    with open(filepath, 'rb') as f:
        raw = f.read()
    try:
        return raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        return raw.decode('cp1252', errors='replace')


def read_geojson(filepath: str) -> Tuple[list, list, CRS]:
    """Read GeoJSON and return geometries, attributes, and CRS"""
    data = geojson.loads(_read_text_file(filepath))
    _check_geojson_depth(data)

    geometries = []
    attributes = []

    if data['type'] == 'FeatureCollection':
        features = data['features']
    elif data['type'] == 'Feature':
        features = [data]
    else:
        features = [{'geometry': data, 'properties': {}}]

    for feature in features:
        geom = shape(feature['geometry'])
        geometries.append(geom)
        attributes.append(feature.get('properties', {}))

    # GeoJSON uses WGS84 by default
    crs = CRS.from_epsg(4326)

    return geometries, attributes, crs


def read_kml(filepath: str) -> Tuple[list, list, CRS]:
    """Read KML and return geometries, attributes, and CRS

    Uses secure XML parser with external entities disabled.
    """
    # `resolve_entities` is an LXML keyword. This module uses the STDLIB
    # ElementTree, which has never accepted it on any Python version — so the
    # else-branch raised TypeError every time, and KML import was broken on
    # everything below 3.14. It went unnoticed because this project's only
    # interpreter is 3.14, where the guard skips the broken line; the deployed
    # and pinned version is 3.11, where it does not. Found by CI, 2026-08-25.
    #
    # Removing the branch loses nothing: stdlib ElementTree does not expand
    # external entities at all, so the flag was expressing an intent it never
    # implemented. Real hardening against entity-expansion DoS is defusedxml,
    # which is now in the lock (it arrived as a cairosvg dependency) — worth
    # doing deliberately rather than as a fix to a version guard.
    tree = ET.parse(filepath)
    root = tree.getroot()

    # Handle KML namespace
    ns = {'kml': 'http://www.opengis.net/kml/2.2'}

    geometries = []
    attributes = []

    # Find all Placemark elements
    for placemark in root.findall('.//kml:Placemark', ns):
        name = placemark.find('kml:name', ns)
        name_text = name.text if name is not None else "Unnamed"

        # Get coordinates from Point, LineString, or Polygon
        coords_elem = None
        geom_type = None

        for geom_tag in ['Point', 'LineString', 'Polygon']:
            elem = placemark.find(f'.//kml:{geom_tag}//kml:coordinates', ns)
            if elem is not None:
                coords_elem = elem
                geom_type = geom_tag
                break

        if coords_elem is not None:
            coords_text = coords_elem.text.strip()
            coords = []
            for coord_str in coords_text.split():
                parts = coord_str.split(',')
                if len(parts) >= 2:
                    coords.append((float(parts[0]), float(parts[1])))

            # Create shapely geometry
            if geom_type == 'Point' and coords:
                geom = Point(coords[0])
            elif geom_type == 'LineString' and len(coords) >= 2:
                geom = LineString(coords)
            elif geom_type == 'Polygon' and len(coords) >= 3:
                geom = Polygon(coords)
            else:
                continue

            geometries.append(geom)
            attributes.append({'name': name_text})

    # KML uses WGS84
    crs = CRS.from_epsg(4326)

    return geometries, attributes, crs


_MAGIC_BYTES = {
    '.kml': (b'<?xml', b'<kml'),
    '.kmz': (b'PK\x03\x04',),
    '.gpx': (b'<?xml', b'<gpx'),
    '.geojson': (b'{', b'['),
    '.json': (b'{', b'['),
    '.csv': (b'\xef\xbb\xbf', b'\xff\xfe', b'\xfe\xff', None),
    '.xlsx': (b'PK\x03\x04',),
    '.shp': (b'\x00\x00', b'\x00\x00\x27'),
}

_GEOJSON_MAX_DEPTH = 20


def _verify_content_magic(content: bytes, file_ext: str) -> None:
    """Verify file content starts with expected magic bytes for the given extension."""
    expected = _MAGIC_BYTES.get(file_ext)
    if expected is None:
        return
    # Allow any match from the tuple; None means any content is OK
    if any(m is None for m in expected):
        return
    if not any(content[:len(m)] == m for m in expected if m is not None):
        raise ValueError(
            f"File content does not match expected format for {file_ext}"
        )


def _check_geojson_depth(obj, current_depth=0) -> None:
    """Guard against deeply nested GeoJSON (stack overflow attack)."""
    if current_depth > _GEOJSON_MAX_DEPTH:
        raise ValueError("GeoJSON nesting exceeds maximum depth")
    if isinstance(obj, dict):
        for v in obj.values():
            _check_geojson_depth(v, current_depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            _check_geojson_depth(item, current_depth + 1)


# H-GEO-1. The service is designed for Nepal and no other area is applicable,
# so a file whose coordinates fall outside the country is not "unusual data" --
# it is the wrong file, or a corrupt one, and processing it produces figures
# that mean nothing.
#
# The numbers are the ones `validators/coordinate_detector.py` has always used
# for CSV and Excel tree inventory. They were never wired to geometry import,
# so a shapefile from anywhere on earth was accepted silently. That is also how
# the coordinate cloud behind H-HULL-1 reached the polygon engine: points at
# 1e-311 are not in Nepal, and nothing on the geometry path was asking.
#
# The margin is deliberate and generous. A community forest on the border can
# legitimately carry vertices a little outside a rectangle drawn around the
# country, and survey error compounds that. Half a degree is roughly 55 km --
# wide enough that no real Nepali forest is refused, narrow enough that data
# from another country, another hemisphere, or a corrupt file still is.
NEPAL_GEOGRAPHIC_BOUNDS = {"lon_min": 80.0, "lon_max": 88.3,
                           "lat_min": 26.3, "lat_max": 30.5}
NEPAL_BOUNDS_MARGIN_DEG = 0.5


def _within_nepal(lon_min: float, lat_min: float,
                  lon_max: float, lat_max: float) -> bool:
    """Does this box overlap Nepal, allowing the border margin?"""
    m = NEPAL_BOUNDS_MARGIN_DEG
    b = NEPAL_GEOGRAPHIC_BOUNDS
    return not (
        lon_max < b["lon_min"] - m or lon_min > b["lon_max"] + m
        or lat_max < b["lat_min"] - m or lat_min > b["lat_max"] + m
    )


def validate_geometry_within_nepal(geometries: list, source_crs: Any = None) -> None:
    """Refuse a file whose footprint is not plausibly in Nepal.

    Checks the bounding box, not every vertex: one transform of one box is
    cheap, and it runs BEFORE the polygon engine, which is the point -- the
    engine is where a pathological file does its damage.

    Whatever the source CRS, the comparison happens in EPSG:4326. Keeping one
    rule in one unit avoids a per-projection table that would drift out of step
    with reality, which is how `NEPAL_BOUNDS` ended up defined in one module
    and enforced in one code path.
    """
    boxes = [g.bounds for g in geometries if g is not None and not g.is_empty]
    if not boxes:
        return
    minx = min(b[0] for b in boxes)
    miny = min(b[1] for b in boxes)
    maxx = max(b[2] for b in boxes)
    maxy = max(b[3] for b in boxes)

    def _refusal(lon_min, lat_min, lon_max, lat_max):
        b = NEPAL_GEOGRAPHIC_BOUNDS
        return ValueError(
            f"This file's coordinates are not in Nepal. Its extent is "
            f"longitude {lon_min:.4f}..{lon_max:.4f}, latitude "
            f"{lat_min:.4f}..{lat_max:.4f}; Nepal is longitude "
            f"{b['lon_min']}..{b['lon_max']}, latitude {b['lat_min']}..{b['lat_max']}. "
            f"Check that the file has the projection you expect -- coordinates in "
            f"the wrong CRS, or in metres where degrees were assumed, land far "
            f"outside the country."
        )

    # Numbers that cannot be degrees at all (|lon| > 180 or |lat| > 90) used to slip through this check -- the reprojection below failed and
    # the check was SKIPPED -- and then crashed the polygon engine with a projection error (a 500). They are simply not in Nepal.
    geographic = source_crs in (None, 4326, "EPSG:4326") or str(source_crs).upper().endswith("4326")
    if geographic and (abs(minx) > 180 or abs(maxx) > 180 or abs(miny) > 90 or abs(maxy) > 90):
        raise _refusal(minx, miny, maxx, maxy)

    footprint = shapely_box(minx, miny, maxx, maxy)
    try:
        footprint = transform_to_4326(footprint, source_crs)
    except Exception as exc:  # noqa: BLE001 -- an untransformable box cannot be judged
        logger.warning(
            "could not reproject the import footprint to EPSG:4326 (%s); "
            "skipping the Nepal bounds check for this file", exc,
        )
        return

    lon_min, lat_min, lon_max, lat_max = footprint.bounds
    if _within_nepal(lon_min, lat_min, lon_max, lat_max):
        return

    # Axis order confusion is not the wrong country. `workspace.py` already
    # detects and corrects swapped lat/lon at import -- it runs AFTER this
    # function, so refusing here would pre-empt a fix the system deliberately
    # performs, and a real Nepali file would be rejected for having its axes
    # the wrong way round. If the swapped reading lands in Nepal, this is that
    # case: let it through and let the existing fix do its work.
    if _within_nepal(lat_min, lon_min, lat_max, lon_max):
        logger.info(
            "import footprint is in Nepal only when lat/lon are swapped; "
            "leaving it to the import-time swap correction",
        )
        return

    raise _refusal(lon_min, lat_min, lon_max, lat_max)


def validate_geometry_types(geometries: list) -> None:
    """Validate that all geometries are supported types (Point/LineString/Polygon/Multi*).

    Raises ValueError if any geometry is an unsupported type.
    """
    supported = (Point, LineString, Polygon, MultiPoint, MultiLineString, MultiPolygon)
    for geom in geometries:
        if not isinstance(geom, supported):
            raise ValueError(
                f"Unsupported geometry type: {geom.geom_type}. "
                f"Supported: Point, LineString, Polygon, MultiPoint, MultiLineString, MultiPolygon"
            )


def validate_feature_count(geometries: list) -> int:
    """Validate feature count does not exceed max. Returns count."""
    count = len(geometries)
    if count > WORKSPACE_IMPORT_MAX_FEATURES:
        raise ValueError(
            f"MAX_FEATURES: Too many features: {count} (max: {WORKSPACE_IMPORT_MAX_FEATURES})"
        )
    return count


def validate_vertex_count(geometries: list) -> int:
    """Validate total vertex count does not exceed max. Returns total.

    Uses explicit geom_type checks instead of `hasattr(geom, 'coords')` — in
    Shapely 2.x accessing `.coords`/`.exterior` on a multi-part geometry raises
    NotImplementedError (multi-part geometries have no single coordinate
    sequence), so hasattr is unsafe here.
    """
    total = 0
    for geom in geometries:
        if geom is None or geom.is_empty:
            continue
        gt = geom.geom_type
        if gt == 'Polygon':
            total += len(geom.exterior.coords)
            total += sum(len(i.coords) for i in geom.interiors)
        elif gt == 'MultiPolygon':
            for poly in geom.geoms:
                total += len(poly.exterior.coords)
                total += sum(len(i.coords) for i in poly.interiors)
        elif gt == 'LineString':
            total += len(geom.coords)
        elif gt == 'MultiLineString':
            total += sum(len(line.coords) for line in geom.geoms)
        elif gt == 'Point':
            total += 1
        elif gt == 'MultiPoint':
            total += len(geom.geoms)
    if total > WORKSPACE_IMPORT_MAX_VERTICES:
        raise ValueError(
            f"MAX_VERTICES: Too many vertices: {total} (max: {WORKSPACE_IMPORT_MAX_VERTICES})"
        )
    return total


def validate_area_limit(geometries: list) -> float:
    """Validate polygon area does not exceed max. Returns max area in ha."""
    max_area = 0.0
    for geom in geometries:
        if hasattr(geom, 'geom_type') and 'Polygon' in geom.geom_type:
            area_sqm, area_ha = calculate_polygon_area_utm(geom)
            max_area = max(max_area, area_ha)
            if area_ha > WORKSPACE_IMPORT_MAX_AREA_HA:
                raise ValueError(
                    f"AREA_LIMIT: Polygon area {area_ha:.1f} ha exceeds max {WORKSPACE_IMPORT_MAX_AREA_HA} ha"
                )
    return max_area


def validate_layer_distance(db_session, calculation_id: int, geometries: list) -> None:
    """Validate all features are within 10km of the calculation's boundary.

    Uses ST_DWithin(geography, geography, buffer) for accurate geodesic distance.
    The bounding box index (&&) is implicitly used by PostGIS with GiST indexes.
    """
    from ..models.calculation import Calculation
    from sqlalchemy import func, text

    calc = db_session.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calc or not calc.boundary_geom:
        # Purpose-first drafts can add the boundary later (Block first → merge).
        # With no boundary yet there is nothing to measure against, so defer the
        # proximity gate until a boundary exists. Mirrors geometry_sanitizer's
        # no-boundary skip (Gap 5.b) and validate_first_layer's Block-first rule.
        return

    # Get boundary WKT for the PostGIS query
    boundary_wkt = db_session.scalar(func.ST_AsText(calc.boundary_geom))
    if not boundary_wkt:
        raise ValueError("Invalid boundary geometry")

    for geom in geometries:
        centroid = geom.centroid
        pt_wkt = f"POINT ({centroid.x} {centroid.y})"

        within = db_session.execute(
            text("""
                SELECT ST_DWithin(
                    ST_GeogFromText(:pt),
                    ST_GeogFromText(:boundary),
                    :buffer
                )
            """),
            {"pt": pt_wkt, "boundary": boundary_wkt, "buffer": WORKSPACE_IMPORT_10KM_BUFFER_M}
        ).scalar()

        if not within:
            raise ValueError(
                f"Feature at ({centroid.y:.4f}, {centroid.x:.4f}) is more than "
                f"{WORKSPACE_IMPORT_10KM_BUFFER_M / 1000:.0f} km from the forest boundary"
            )


def validate_first_layer(db_session, calculation_id: int, purpose: str) -> None:
    """Validate that an admin layer (Blocks/Compartments) exists before sub-layers.

    Checks both workspace_layers (imported files) AND forest_blocks (calculation
    blocks created via upload → block-naming, or create-from-map).

    U-6 (Task 6.2): the dependency rule is widened — any of {imported admin layer,
    a populated forest_blocks row, OR the calculation boundary} satisfies the
    "first layer" requirement, regardless of origin (imported or derived).
    """
    if purpose in IMPORT_PURPOSE_ADMIN:
        return  # Admin layers are always allowed first

    from ..models.workspace_layer import WorkspaceLayer
    from ..models.calculation import Calculation

    # Check workspace_layers (imported via workspace endpoint)
    ws_exists = db_session.query(WorkspaceLayer).filter(
        WorkspaceLayer.calculation_id == calculation_id,
        WorkspaceLayer.purpose.in_(IMPORT_PURPOSE_ADMIN),
        WorkspaceLayer.deleted_at.is_(None),
    ).first()
    if ws_exists is not None:
        return

    # Check forest_blocks (created via upload → block-naming or create-from-map)
    from ..models.forest_block import ForestBlock

    fb_exists = db_session.query(ForestBlock).filter(
        ForestBlock.calculation_id == calculation_id,
    ).first()
    if fb_exists is not None:
        return

    # Widened dependency (U-6/Task 6.2): a populated forest boundary also satisfies
    # the first-layer requirement (e.g. boundary-only forest → single-block forest).
    calculation = db_session.query(Calculation).filter(Calculation.id == calculation_id).first()
    if calculation is not None and calculation.boundary_geom is not None:
        return

    raise ValueError(
        "FIRST_LAYER: You must import a Block or Compartment layer (or set the forest boundary) first "
        "before importing sub-layers or reference data"
    )


def read_gpx(filepath: str) -> Tuple[list, list, CRS]:
    """Read GPX and return geometries, attributes, and CRS.

    Parses waypoints (<wpt>), tracks (<trk>), and routes (<rte>) using
    pure ElementTree. Disables external entity resolution for security.
    """
    # `resolve_entities` is an LXML keyword. This module uses the STDLIB
    # ElementTree, which has never accepted it on any Python version — so the
    # else-branch raised TypeError every time, and KML import was broken on
    # everything below 3.14. It went unnoticed because this project's only
    # interpreter is 3.14, where the guard skips the broken line; the deployed
    # and pinned version is 3.11, where it does not. Found by CI, 2026-08-25.
    #
    # Removing the branch loses nothing: stdlib ElementTree does not expand
    # external entities at all, so the flag was expressing an intent it never
    # implemented. Real hardening against entity-expansion DoS is defusedxml,
    # which is now in the lock (it arrived as a cairosvg dependency) — worth
    # doing deliberately rather than as a fix to a version guard.
    tree = ET.parse(filepath)
    root = tree.getroot()

    # GPX namespace
    ns = {'gpx': 'http://www.topografix.com/GPX/1/1'}

    geometries = []
    attributes = []
    gpx_sub_types = {'wpt': 0, 'trk': 0, 'rte': 0}

    # Parse waypoints
    for wpt in root.findall('.//gpx:wpt', ns):
        lat = float(wpt.get('lat'))
        lon = float(wpt.get('lon'))
        name_elem = wpt.find('gpx:name', ns)
        name = name_elem.text if name_elem is not None else None
        geom = Point(lon, lat)
        geometries.append(geom)
        attrs = {'name': name, 'gpx_type': 'wpt'}
        attributes.append(attrs)
        gpx_sub_types['wpt'] += 1

    # Parse tracks
    for trk in root.findall('.//gpx:trk', ns):
        name_elem = trk.find('gpx:name', ns)
        track_name = name_elem.text if name_elem is not None else None
        for seg in trk.findall('.//gpx:trkseg', ns):
            coords = []
            for pt in seg.findall('.//gpx:trkpt', ns):
                lat = float(pt.get('lat'))
                lon = float(pt.get('lon'))
                coords.append((lon, lat))
            if len(coords) >= 2:
                geom = LineString(coords)
                geometries.append(geom)
                attrs = {'name': track_name, 'gpx_type': 'trk'}
                attributes.append(attrs)
                gpx_sub_types['trk'] += 1

    # Parse routes
    for rte in root.findall('.//gpx:rte', ns):
        name_elem = rte.find('gpx:name', ns)
        route_name = name_elem.text if name_elem is not None else None
        coords = []
        for pt in rte.findall('.//gpx:rtept', ns):
            lat = float(pt.get('lat'))
            lon = float(pt.get('lon'))
            coords.append((lon, lat))
        if len(coords) >= 2:
            geom = LineString(coords)
            geometries.append(geom)
            attrs = {'name': route_name, 'gpx_type': 'rte'}
            attributes.append(attrs)
            gpx_sub_types['rte'] += 1

    return geometries, attributes, CRS.from_epsg(4326)


def extract_gpx_metadata(geometries: list, attributes: list) -> dict:
    """Extract GPX metadata summary from parsed results."""
    types = {'wpt': 0, 'trk': 0, 'rte': 0}
    for attrs in attributes:
        gpx_type = attrs.get('gpx_type')
        if gpx_type in types:
            types[gpx_type] += 1
    return {'gpx_sub_types': types}


# CSV injection pattern — cells starting with these chars are suspicious
_CSV_INJECTION_PATTERN = re.compile(r'^[\s]*[=+\-@]')


def _sanitize_csv_value(value: str) -> str:
    """Sanitize a CSV cell value against formula injection."""
    if isinstance(value, str) and _CSV_INJECTION_PATTERN.match(value):
        return "'" + value  # prefix with apostrophe to neutralize
    return value


def _detect_workspace_columns(headers: List[str]) -> Dict[str, Optional[str]]:
    """Fuzzy-detect column roles from CSV headers.

    Returns a dict with keys: 'lat', 'lon', 'wkt', 'name', 'id'
    Values are the matched column name or None.
    """
    result = {'lat': None, 'lon': None, 'wkt': None, 'name': None, 'id': None}
    lowered = {h: h.lower().strip() for h in headers}

    # Latitude candidates
    lat_keywords = ['latitude', 'lat', 'ycoord', 'y_coord', 'y', 'north',
                    'अक्षाँस', 'अक्षांश', 'अक्षांश रेखा', 'अक्षाश', 'अक्षांश रेखांश', 'ल्याटिच्यूड', 'लाटिट्यूड']
    for h, low in lowered.items():
        if any(kw == low or low.startswith(kw) or low.endswith(kw) for kw in lat_keywords):
            result['lat'] = h
            break

    # Longitude candidates
    lon_keywords = ['longitude', 'long', 'lon', 'xcoord', 'x_coord', 'x', 'east',
                    'देशान्तर', 'देशान्तर रेखा', 'देशांतर', 'देशान्तर रेखांश', 'लङ्गीट्यूड', 'लांगिच्यूड']
    for h, low in lowered.items():
        if any(kw == low or low.startswith(kw) or low.endswith(kw) for kw in lon_keywords):
            result['lon'] = h
            break

    # WKT candidates
    wkt_keywords = ['wkt', 'geometry', 'geom', 'the_geom', 'shape', 'geography']
    for h, low in lowered.items():
        if any(kw == low for kw in wkt_keywords):
            result['wkt'] = h
            break

    # Name candidates
    name_keywords = ['name', 'title', 'label', 'description', 'forest_name', 'block_name']
    for h, low in lowered.items():
        if any(kw == low or low.endswith('_' + kw) for kw in name_keywords):
            result['name'] = h
            break

    # ID / SN candidates (numeric)
    id_keywords = ['sn', 's.n', 'id', '编号', 'क्र', 'क्रम']
    for h, low in lowered.items():
        if any(kw == low for kw in id_keywords):
            result['id'] = h
            break

    return result


def _parse_coordinate(value: str) -> Optional[float]:
    """Parse a coordinate string, supporting DMS format.

    Accepts:
    - Decimal degrees: "27.12345"
    - DMS: "27°12'34.5\"N" or "27°12'34.5\""
    - DMS with spaces: "27 12 34.5"
    """
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None

    # Try decimal degrees first
    try:
        return float(value)
    except ValueError:
        pass

    # Try DMS: 27°12'34.5"N or 27 12 34.5 or 27:12:34.5
    dms_pattern = re.compile(
        r'([+-]?\d+)[°d:]\s*(\d+)[m\':]\s*(\d+(?:\.\d+)?)[s"\']?\s*([NSEWnsew])?'
    )
    match = dms_pattern.match(value)
    if match:
        degrees = float(match.group(1))
        minutes = float(match.group(2))
        seconds = float(match.group(3))
        direction = match.group(4)
        result = degrees + minutes / 60.0 + seconds / 3600.0
        if direction and direction.upper() in ('S', 'W'):
            result = -result
        return result

    return None


def _apply_coord_overrides(
    columns: Dict[str, Optional[str]], headers: List[str],
    lat_col: Optional[str], lon_col: Optional[str],
) -> Dict[str, Optional[str]]:
    """Apply user-picked coordinate columns over the auto-detected roles.

    The user-group CSV column picker (UP-3.2) sends both columns; when both are
    present and real, they win over detection. A missing column is a plain
    ValueError naming it, so the picker can be shown again.
    """
    if not (lat_col and lon_col):
        return columns
    if lat_col not in headers:
        raise ValueError(f"Latitude column not found: {lat_col}")
    if lon_col not in headers:
        raise ValueError(f"Longitude column not found: {lon_col}")
    columns = dict(columns)
    columns['lat'] = lat_col
    columns['lon'] = lon_col
    return columns


def read_csv(
    filepath: str,
    crs_epsg: int = 4326,
    lat_col: Optional[str] = None,
    lon_col: Optional[str] = None,
) -> Tuple[list, list, CRS]:
    """Read CSV file and return geometries, attributes, and CRS.

    Auto-detects lat/lon or WKT columns (``lat_col``/``lon_col`` override the
    auto-detected coordinate columns). Enforces 50-row limit.
    """
    with open(filepath, 'r', encoding='utf-8-sig') as f:
        # Detect encoding via utf-8-sig (handles BOM) first, fallback to cp1252
        try:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
        except UnicodeDecodeError:
            f.seek(0)
            reader = csv.DictReader(f, encoding='cp1252')
            headers = reader.fieldnames or []

        if not headers:
            raise ValueError("CSV file has no headers")

        # Detect column roles
        columns = _detect_workspace_columns(headers)
        columns = _apply_coord_overrides(columns, headers, lat_col, lon_col)
        has_latlon = columns['lat'] and columns['lon']
        has_wkt = bool(columns['wkt'])

        if not has_latlon and not has_wkt:
            raise ValueError(
                "CSV must have lat/lon columns (latitude, longitude) "
                "or a WKT geometry column. Found: " + ", ".join(headers)
            )

        geometries = []
        attributes = []
        row_count = 0

        for row in reader:
            row_count += 1
            if row_count > 50:
                break

            # Sanitize all values
            sanitized = {k: _sanitize_csv_value(v) if isinstance(v, str) else v
                         for k, v in row.items()}

            if has_wkt:
                try:
                    geom = wkt.loads(sanitized[columns['wkt']])
                except Exception as e:
                    raise ValueError(f"Row {row_count}: invalid WKT: {e}")
            else:
                lat = _parse_coordinate(sanitized.get(columns['lat']))
                lon = _parse_coordinate(sanitized.get(columns['lon']))
                if lat is None or lon is None:
                    raise ValueError(
                        f"Row {row_count}: could not parse lat/lon: "
                        f"{sanitized.get(columns['lat'])}, {sanitized.get(columns['lon'])}"
                    )
                geom = Point(lon, lat)

            geometries.append(geom)

            # Build attributes: name + first 3 text columns
            attrs = {}
            if columns['name'] and columns['name'] in sanitized:
                attrs['name'] = sanitized[columns['name']]
            # Include first 3 non-lat/lon/wkt columns as attributes
            text_cols = [h for h in headers
                         if h not in (columns['lat'], columns['lon'], columns['wkt'])][:3]
            for col in text_cols:
                if col in sanitized:
                    attrs[col] = sanitized[col]
            attributes.append(attrs)

    # Transform CRS if needed (UTM → WGS84)
    source_crs = CRS.from_epsg(crs_epsg) if crs_epsg != 4326 else None
    if source_crs:
        transformer = Transformer.from_crs(source_crs, CRS.from_epsg(4326), always_xy=True)
        geometries = [transform(transformer.transform, g) for g in geometries]

    return geometries, attributes, CRS.from_epsg(4326)


def read_xlsx(
    filepath: str,
    crs_epsg: int = 4326,
    lat_col: Optional[str] = None,
    lon_col: Optional[str] = None,
) -> Tuple[list, list, CRS]:
    """Read XLSX file and return geometries, attributes, and CRS.

    Uses pandas read_excel. Enforces 50-row limit. Same column detection as CSV
    (``lat_col``/``lon_col`` override the auto-detected coordinate columns).
    """
    try:
        import pandas as pd
    except ImportError:
        raise ValueError("pandas is required to read .xlsx files")

    df = pd.read_excel(filepath, nrows=50, dtype=str)
    if df.empty:
        raise ValueError("XLSX file is empty")

    headers = list(df.columns)
    columns = _detect_workspace_columns(headers)
    columns = _apply_coord_overrides(columns, headers, lat_col, lon_col)
    has_latlon = columns['lat'] and columns['lon']
    has_wkt = bool(columns['wkt'])

    if not has_latlon and not has_wkt:
        raise ValueError(
            "XLSX must have lat/lon columns (latitude, longitude) "
            "or a WKT geometry column. Found: " + ", ".join(headers)
        )

    geometries = []
    attributes = []

    for idx, row in df.iterrows():
        if idx >= 50:
            break
        sanitized = {k: _sanitize_csv_value(str(v)) if pd.notna(v) else v
                     for k, v in row.items()}

        if has_wkt:
            try:
                geom = wkt.loads(sanitized[columns['wkt']])
            except Exception as e:
                raise ValueError(f"Row {idx + 1}: invalid WKT: {e}")
        else:
            lat = _parse_coordinate(str(sanitized.get(columns['lat'], '')))
            lon = _parse_coordinate(str(sanitized.get(columns['lon'], '')))
            if lat is None or lon is None:
                raise ValueError(
                    f"Row {idx + 1}: could not parse lat/lon: "
                    f"{sanitized.get(columns['lat'])}, {sanitized.get(columns['lon'])}"
                )
            geom = Point(lon, lat)

        geometries.append(geom)
        attrs = {}
        if columns['name'] and columns['name'] in sanitized:
            attrs['name'] = sanitized[columns['name']]
        text_cols = [h for h in headers
                     if h not in (columns['lat'], columns['lon'], columns['wkt'])][:3]
        for col in text_cols:
            if col in sanitized and pd.notna(sanitized[col]):
                attrs[col] = sanitized[col]
        attributes.append(attrs)

    # Transform CRS if needed (UTM → WGS84)
    source_crs = CRS.from_epsg(crs_epsg) if crs_epsg != 4326 else None
    if source_crs:
        transformer = Transformer.from_crs(source_crs, CRS.from_epsg(4326), always_xy=True)
        geometries = [transform(transformer.transform, g) for g in geometries]

    return geometries, attributes, CRS.from_epsg(4326)


def filter_gpx_by_type(geometries: list, attributes: list, selected_types: list) -> Tuple[list, list]:
    """Filter GPX features by selected sub-types."""
    filtered_geoms = []
    filtered_attrs = []
    for geom, attrs in zip(geometries, attributes):
        if attrs.get('gpx_type') in selected_types:
            filtered_geoms.append(geom)
            filtered_attrs.append(attrs)
    return filtered_geoms, filtered_attrs


def read_kmz(filepath: str) -> Tuple[list, list, CRS]:
    """Read KMZ (zipped KML) and return geometries, attributes, and CRS.

    Unzips the KMZ, finds the first .kml file, and delegates to read_kml().
    """
    kml_data = None
    non_kml_warnings = []

    with zipfile.ZipFile(filepath, 'r') as zf:
        # H2.9 / S3-10: nothing is extracted here — the KML is read straight
        # into memory — so the traversal check this used to run was moot, while
        # the bomb check it ran had no absolute size cap. `zf.read()` on a bomb
        # entry fills RAM instead of a disk, which is no better.
        check_archive_limits(zf)

        # Find .kml file
        kml_files = [n for n in zf.namelist() if n.lower().endswith('.kml')]
        if not kml_files:
            raise ValueError("No .kml file found in KMZ archive")

        # Read the first KML file
        kml_data = zf.read(kml_files[0])

        # Warn about non-KML content (images, etc.)
        for name in zf.namelist():
            ext = Path(name).suffix.lower()
            if ext in ('.jpg', '.jpeg', '.png', '.gif', '.tif', '.tiff', '.bmp'):
                non_kml_warnings.append(f"KMZ contains non-KML content: {name} (will be ignored)")

    # Write KML data to temp file and parse
    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.kml', delete=False, mode='wb') as tmp:
        tmp.write(kml_data)
        tmp_path = tmp.name

    try:
        geometries, attributes, crs = read_kml(tmp_path)
        validate_geometry_types(geometries)
        return geometries, attributes, crs
    finally:
        os.unlink(tmp_path)


def process_geometry_list(geometries: list, attributes: list, purpose: Optional[str] = None) -> Tuple[Any, Dict[str, Any]]:
    """
    Process geometry list based on type (Point, LineString, or Polygon).

    Behaviour per purpose:

    | Purpose                | Points              | Lines               | Polygons        | Mixed                     |
    |------------------------|---------------------|---------------------|-----------------|---------------------------|
    | inventory / sample_plot| keep points         | ❌ reject           | ❌ reject       | ❌ reject                 |
    | water                  | keep points         | keep lines          | keep polygons   | ✅ accept all             |
    | roads                  | connect → line      | keep lines          | ❌ reject       | lines + connect points    |
    | blocks / boundary /    | convex hull → poly  | closed→poly,        | keep polygons   | normal polygonise         |
    |   user_group_boundary  |                     | open→division      |                 |                           |
    | other / None           | keep as-is          | keep as-is          | keep as-is      | ✅ accept all             |

    Args:
        geometries: List of shapely geometry objects
        attributes: List of attribute dictionaries
        purpose: Import purpose that controls geometry conversion behaviour (None = keep all as-is)

    Returns:
        Tuple of (processed geometry or multi-geometry, metadata dict)
    """
    metadata = {}

    if not geometries:
        raise ValueError("No geometries to process")

    # Treat None purpose as "other" (keep all geometries as-is)
    effective_purpose = purpose if purpose is not None else "other"

    # Separate geometries by type with their indices
    polygon_data: list = []  # (index, geom, attrs)
    line_data: list = []
    point_data: list = []

    for i, geom in enumerate(geometries):
        attrs = attributes[i] if i < len(attributes) else {}
        geom_type = geom.geom_type

        if "Polygon" in geom_type:
            polygon_data.append((i, geom, attrs))
        elif "LineString" in geom_type or "Line" in geom_type:
            line_data.append((i, geom, attrs))
        elif "Point" in geom_type:
            point_data.append((i, geom, attrs))

    has_polygons = bool(polygon_data)
    has_lines = bool(line_data)
    has_points = bool(point_data)

    # ------------------------------------------------------------------
    #  INVENTORY / SAMPLE PLOT — strictly points
    # ------------------------------------------------------------------
    if effective_purpose in IMPORT_PURPOSE_STRICT_POINT:
        label = "Tree Inventory" if effective_purpose == 'inventory' else "Sample Plot"
        if has_polygons:
            raise ValueError(f"{label} expects point features only. The file contains polygon geometry.")
        if has_lines:
            raise ValueError(f"{label} expects point features only. The file contains line geometry.")
        if not has_points:
            raise ValueError(f"{label} expects point features but no point geometries were found.")
        return _build_multigeometry([g for _, g, _ in point_data], metadata)

    # ------------------------------------------------------------------
    #  WATER — accepts any geometry, preserves original type
    # ------------------------------------------------------------------
    if effective_purpose == IMPORT_PURPOSE_WATER:
        all_geoms = []
        for _, g, _ in polygon_data: all_geoms.append(g)
        for _, g, _ in line_data: all_geoms.append(g)
        for _, g, _ in point_data: all_geoms.append(g)
        if not all_geoms:
            raise ValueError("No recognised geometries found.")
        return _build_multigeometry(all_geoms, metadata)

    # ------------------------------------------------------------------
    #  ROADS — lines kept, points connected into line, polygons rejected
    # ------------------------------------------------------------------
    if effective_purpose == IMPORT_PURPOSE_ROADS:
        if has_polygons:
            raise ValueError("Roads & Trails expects line or point features only. The file contains polygon geometry.")

        # Lines only
        if has_lines and not has_points:
            return _build_multigeometry([g for _, g, _ in line_data], metadata)

        # Points only → connect in file order into an open line
        if has_points and not has_lines:
            pts = [g for _, g, _ in point_data]
            if len(pts) < 2:
                raise ValueError(
                    "Roads & Trails with a single point cannot form a line. "
                    "Please provide at least 2 points (waypoints) along the road."
                )
            line = LineString([(p.x, p.y) for p in pts])
            metadata['auto_connected'] = True
            metadata['point_count'] = len(pts)
            return line, metadata

        # Lines + points: keep existing lines, connect points as additional line
        kept = [g for _, g, _ in line_data]
        pts = [g for _, g, _ in point_data]
        if len(pts) >= 2:
            kept.append(LineString([(p.x, p.y) for p in pts]))
            metadata['auto_connected'] = True
            metadata['point_count'] = len(pts)
        return _build_multigeometry(kept, metadata)

    # ------------------------------------------------------------------
    #  BLOCKS / BOUNDARY / USER GROUP BOUNDARY — polygon-purposes
    # ------------------------------------------------------------------
    if effective_purpose in IMPORT_PURPOSE_POLYGON_AUTO_BUFFER:

        # Point-only → auto-buffer to polygon
        if has_points and not has_polygons and not has_lines:
            pts = [g for _, g, _ in point_data]
            if len(pts) == 1:
                poly = pts[0].buffer(0.001)
            else:
                poly = MultiPoint(pts).convex_hull
                if poly.area == 0:
                    poly = pts[0].buffer(0.001)

            metadata['auto_buffered'] = True
            metadata['auto_buffer_note'] = (
                "Point data auto-converted to polygon via convex hull"
                if len(pts) > 1 else
                "Single point auto-converted to polygon via buffer"
            )

            block_names = perform_spatial_join_labeling([poly], point_data)
            name = block_names.get(0) or f"{effective_purpose.replace('_', ' ').title()} 1"
            area_sqm, area_ha = calculate_polygon_area_utm(poly)
            centroid = poly.centroid
            metadata['blocks'] = [{
                'index': 0,
                'name': name,
                'geometry': mapping(poly),
                'area_sqm': area_sqm,
                'area_hectares': area_ha,
                'centroid': {'lon': centroid.x, 'lat': centroid.y}
            }]
            metadata['block_count'] = 1
            return poly, metadata

        # --- Standard polygonisation (has polygons and/or lines) ---
        # --- Standard polygonisation (has polygons and/or lines) ---
        # If we have only polygons (no lines/points), preserve them as-is for ready-to-use blocks
        if not line_data and not point_data:
            # Simple polygons ready to use - preserve as-is
            blocks = []
            for idx, (_, geom, attrs) in enumerate(polygon_data):
                name = extract_name_from_attrs(attrs) or f"{effective_purpose.replace('_', ' ').title()} {idx + 1}"
                area_sqm, area_ha = calculate_polygon_area_utm(geom)
                centroid = geom.centroid
                blocks.append({
                    'index': idx,
                    'name': name,
                    'geometry': mapping(geom),
                    'area_sqm': area_sqm,
                    'area_hectares': area_ha,
                    'centroid': {'lon': centroid.x, 'lat': centroid.y}
                })
            metadata['blocks'] = blocks
            metadata['block_count'] = len(blocks)
            
            if len(polygon_data) == 1:
                geometry = polygon_data[0][1]
            else:
                geometry = MultiPolygon([g for _, g, _ in polygon_data])
                metadata['note'] = f"Multi-block file with {len(polygon_data)} blocks preserved as-is"
            return geometry, metadata
        
        return _polygonise(polygon_data, line_data, point_data, metadata)

    # ------------------------------------------------------------------
    #  OTHER (and fallback) — preserve all geometry as-is
    # ------------------------------------------------------------------
    all_geoms = []
    for _, g, _ in polygon_data: all_geoms.append(g)
    for _, g, _ in line_data: all_geoms.append(g)
    for _, g, _ in point_data: all_geoms.append(g)
    if not all_geoms:
        raise ValueError("No recognised geometries found.")
    return _build_multigeometry(all_geoms, metadata)


def _build_multigeometry(geoms: list, metadata: dict) -> tuple:
    """Return a single geometry from a list, auto-wrapping into Multi*."""
    if not geoms:
        raise ValueError("No geometries to process")
    if len(geoms) == 1:
        return geoms[0], metadata
    types = set(g.geom_type for g in geoms)
    if types == {'Point'}:
        return MultiPoint(geoms), metadata
    if types == {'LineString'}:
        return MultiLineString(geoms), metadata
    if types == {'Polygon'}:
        return MultiPolygon(geoms), metadata
    from shapely.geometry import GeometryCollection
    return GeometryCollection(geoms), metadata


def _polygonise(polygon_data, line_data, point_data, metadata) -> tuple:
    """Convert lines-to-polygons, apply division-line partitioning,
    and return a merged Polygon / MultiPolygon with block metadata.

    Delegates to the shared `feature_to_polygon` engine - the same
    node-and-polygonize Feature-to-Polygon implementation
    `workspace.import_layer` uses - so this legacy entry point
    (`process_uploaded_file` / CFOP upload) and the newer workspace import
    path share one correct implementation instead of two.
    """
    geometries = (
        [g for _, g, _ in polygon_data]
        + [g for _, g, _ in line_data]
        + [g for _, g, _ in point_data]
    )
    attributes = (
        [a for _, _, a in polygon_data]
        + [a for _, _, a in line_data]
        + [a for _, _, a in point_data]
    )

    # allow_point_hull=False: a points-only input never reaches _polygonise -
    # process_geometry_list's point-only auto-buffer branch (above) handles
    # that case before this function is called. Here, points are labels only.
    config = PolygonizeConfig(allow_point_hull=False, name_prefix="Block")
    features, poly_warnings = feature_to_polygon(geometries, attributes, config)

    if not features:
        raise ValueError("No polygon geometries found or created from lines")

    all_polygons = [g for g, _ in features]
    if line_data and len(all_polygons) >= 1:
        metadata['partitioned'] = True
        metadata['partition_info'] = {
            'division_lines_used': len(line_data) - poly_warnings.get('dropped_unclosed', 0),
            'blocks_created': len(all_polygons),
        }

    # 5. Build blocks metadata
    blocks = []
    for idx, (poly, attrs) in enumerate(features):
        block_name = attrs.get('name') or f"Block {idx + 1}"
        area_sqm, area_ha = calculate_polygon_area_utm(poly)
        centroid = poly.centroid
        blocks.append({
            'index': idx,
            'name': block_name,
            'geometry': mapping(poly),
            'area_sqm': area_sqm,
            'area_hectares': area_ha,
            'centroid': {'lon': centroid.x, 'lat': centroid.y}
        })

    metadata['blocks'] = blocks
    metadata['block_count'] = len(blocks)

    if len(all_polygons) == 1:
        geometry = all_polygons[0]
    else:
        geometry = MultiPolygon(all_polygons)
        metadata['note'] = f"Multi-block file with {len(all_polygons)} blocks"

    return geometry, metadata


def _metres_to_degrees(metres: float) -> float:
    """Approx conversion for small distances ~ metres to degrees longitude."""
    return metres / 111_320.0


def convert_lines_to_multi_line(
    geometries: list,
    tolerance_m: float = None,
) -> Tuple[List[Any], List[Any]]:
    """
    Snap near-closed LineStrings into closed rings.

    For each LineString whose endpoints are nearer than `tolerance_m`, snap the
    last coordinate onto the first to form a closed ring, then build a Polygon.
    Lines that are already exactly closed become Polygons.  Returns
    (remaining_lines, closed_polygons).
    """
    if tolerance_m is None:
        from ..core.constants import SUB_AREA_SNAP_TOLERANCE_M
        tolerance_m = SUB_AREA_SNAP_TOLERANCE_M
    degree_tol = _metres_to_degrees(tolerance_m)
    lines = []
    closed_polygons = []
    for geom in geometries:
        if not hasattr(geom, "geom_type") or geom.geom_type not in ("LineString", "LinearRing"):
            continue
        coords = list(geom.coords)
        if len(coords) < 4:
            lines.append(geom)
            continue
        closed = coords[0] == coords[-1]
        if not closed:
            gap = Point(coords[0]).distance(Point(coords[-1]))
            if gap <= degree_tol:
                coords = list(coords) + [coords[0]]
                closed = True
        if closed:
            try:
                poly = Polygon(coords)
                if poly.is_valid and poly.area > 0:
                    closed_polygons.append(poly)
                    continue
            except Exception:
                report_dropped(
                    logger, "closed line ring",
                    "it will not become a polygon, so that area is not imported",
                )
        lines.append(geom)
    return lines, closed_polygons


def _group_key(attrs: dict, config: "PolygonizeConfig") -> Optional[str]:
    """Extract a grouping key for case-D point clustering.

    Prefers an explicit grouping/name attribute so points that belong to one
    logical unit (e.g. one sub-area / island) hull together. Returns None when
    the point carries no grouping attribute (single blob for all points).
    """
    for k in ("group", "group_name", "unit", "name", "labeled"):
        v = attrs.get(k)
        if v not in (None, ""):
            return str(v)
    return None


def _cluster_points_by_distance(points: List[Any], cluster_metres: float) -> List[List[Any]]:
    """Cluster points into disjoint groups by a distance threshold (invariant F).

    Points whose pairwise distance is within `cluster_metres` belong to the same
    island; points separated by more form separate islands (so we DO NOT hull
    once across open water). Returns a list of point-lists, one per cluster.
    """
    degree_tol = _metres_to_degrees(cluster_metres)
    clusters: List[List[Any]] = []
    for pt in points:
        placed = False
        for c in clusters:
            if any(a.distance(pt) <= degree_tol for a in c):
                c.append(pt)
                placed = True
                break
        if not placed:
            clusters.append([pt])
    # Merge clusters that have become transitively-close (greedy transitivity).
    merged = True
    while merged:
        merged = False
        out: List[List[Any]] = []
        for c in clusters:
            hit = None
            for i, existing in enumerate(out):
                if any(a.distance(b) <= degree_tol for a in c for b in existing):
                    hit = i
                    break
            if hit is not None:
                out[hit].extend(c)
                merged = True
            else:
                out.append(c)
        clusters = out
    return clusters


def _concave_hull(points: Sequence[Any], alpha: Optional[float]) -> Optional[Any]:
    """Build a concave (alpha) hull over `points`, with robust fallbacks.

    Uses Shapely >= 2.1 concave_hull (task 2.1) when available, else convex hull.
    Always calls make_valid() after hull generation (task 2.2) and falls back to
    the convex hull if the alpha shape is missing / degenerate / invalid.
    """
    pts = MultiPoint(list(points))
    try:
        from shapely import concave_hull as _ch, make_valid as _mv
        hull = _ch(pts, ratio=alpha, allow_holes=False) if alpha is not None else pts.convex_hull
        hull = _mv(hull)
        if hull.is_empty or hull.area <= 0:
            hull = _mv(pts.convex_hull)
    except Exception:
        # The fallback is a CONVEX hull where a concave one was asked for, so
        # the boundary bulges outward over ground the points never covered.
        logger.warning(
            "concave hull failed - falling back to the convex hull, which "
            "encloses more ground than the points do", exc_info=True,
        )
        try:
            from shapely import make_valid as _mv
            hull = _mv(pts.convex_hull)
        except Exception:
            logger.warning(
                "could not repair the convex hull - using it unvalidated, which "
                "may be self-intersecting", exc_info=True,
            )
            hull = pts.convex_hull
    if hull.is_empty or hull.area <= 0:
        return None
    return hull


# Below this magnitude a coordinate is indistinguishable from zero at any
# surveying precision: 1e-9 degrees is about 0.1 mm on the ground, and 1e-9
# metres is a nanometre. Nothing that comes off a GPS, a total station or a
# cadastral map carries a value that small and means it.
COORD_PRECISION_FLOOR = 1e-9


def _sanitize_coordinate_magnitudes(geometries: list) -> Tuple[list, int]:
    """Snap sub-precision coordinates to zero. Returns (geometries, n_changed).

    **Why this exists (H-HULL-1).** A 39-point cloud mixing ordinary magnitudes
    (~1e1) with near-zero ones (down to 5e-324) made `feature_to_polygon` run
    forever -- not slowly, forever, pinning one core with no exception raised
    and no output. It was found by the Hypothesis property test in
    `tests/services/test_feature_to_polygon_case_d.py`, and reproduced at every
    alpha; with the sub-precision values snapped, the same input completes in
    9 ms.

    The individual primitives are all fast on that input -- `concave_hull` in
    1 ms, `_cluster_points_by_distance` in 10 ms -- so the pathology is in the
    per-cluster work that follows, which the extreme dynamic range turns
    quadratic or worse. The floor removes the range rather than the symptom.

    **Why it is not a domain check.** This function must stay
    coordinate-system-agnostic: it sees EPSG:4326 degrees, projected UTM
    metres, and synthetic test data. A Nepal envelope belongs at the import
    boundary, where a file from the wrong country can be refused with a message
    that says so -- see `validators/coordinate_detector.NEPAL_BOUNDS`. This is a
    statement about float precision, which holds in any unit.

    **Why a hang and not an exception.** `_concave_hull` already has careful
    fallbacks, but every one of them hangs off `except Exception`. A call that
    never returns raises nothing, so it walks straight past the guard, the
    convex-hull fallback and the honest warning about enclosing more ground
    than the points do. That is why the fix has to run BEFORE the work rather
    than around it.
    """
    changed = 0
    out = []
    for geom in geometries:
        if geom is None or geom.is_empty:
            out.append(geom)
            continue
        try:
            cleaned = transform(
                lambda xx, yy, zz=None: (
                    tuple(0.0 if abs(v) < COORD_PRECISION_FLOOR else v for v in xx),
                    tuple(0.0 if abs(v) < COORD_PRECISION_FLOOR else v for v in yy),
                ),
                geom,
            )
        except Exception:  # noqa: BLE001 -- a geometry we cannot rewrite is left as it came
            logger.warning(
                "could not normalise coordinate magnitudes for a %s; passing it "
                "through unchanged", getattr(geom, "geom_type", "geometry"),
                exc_info=True,
            )
            out.append(geom)
            continue
        if not cleaned.equals_exact(geom, 0.0):
            changed += 1
        out.append(cleaned)
    return out, changed


# A noded planar graph over hand-digitized lines can produce a negligible
# sliver face where two lines nearly-but-not-quite meet at the same point.
# 25 sqm is far below any real block/compartment/sub-area, so a face this
# small is a digitizing artefact, not a unit anyone intended to create.
SLIVER_FACE_FLOOR_SQM = 25.0


def _polygonize_edge_network(polygons: List[Any], lines: List[Any]) -> List[Any]:
    """Node every polygon boundary + line into one planar graph and extract faces.

    This is the "Feature to Polygon" construction ArcGIS uses: every input
    polygon ring and every input line is one edge of a single graph.
    `unary_union` nodes them at every true intersection - a crossing, or a
    T-junction where one line ends on another - and `polygonize` extracts
    every enclosed face in one pass. Unlike sequentially calling
    `shapely.ops.split` once per line (the previous approach here), this
    needs no per-line ordering and no assumption that a line crosses fully
    from one side of a polygon to the other: a line that starts on a
    polygon's edge and ends by touching another line closes a face exactly
    like one that crosses the outer boundary on both ends.

    A polygon untouched by any line simply reproduces itself as one face.
    A line that touches nothing closes no face and is silently absent from
    the result (the caller counts those as dropped/dangling).
    """
    edges: List[Any] = []
    for p in polygons:
        if p is None or p.is_empty:
            continue
        if p.geom_type == "Polygon":
            edges.append(p.exterior)
            edges.extend(p.interiors)
        elif p.geom_type == "MultiPolygon":
            for part in p.geoms:
                edges.append(part.exterior)
                edges.extend(part.interiors)
    for ln in lines:
        if ln is not None and not ln.is_empty:
            edges.append(ln)

    if not edges:
        return []

    try:
        noded = unary_union(edges)
    except Exception:
        logger.warning(
            "could not node the Feature-to-Polygon edge network - no faces "
            "produced from this polygon/line set", exc_info=True,
        )
        return []

    try:
        faces = [f for f in polygonize(noded) if f.is_valid and f.area > 0]
    except Exception:
        logger.warning(
            "polygonize failed on the noded Feature-to-Polygon edge network",
            exc_info=True,
        )
        return []

    kept = []
    for f in faces:
        try:
            area_sqm, _ = calculate_polygon_area_utm(f)
        except Exception:
            logger.warning(
                "sliver-floor area check failed for a polygonized face - "
                "keeping it (treated as not-a-sliver rather than dropped)",
                exc_info=True,
            )
            area_sqm = None
        if area_sqm is not None and area_sqm < SLIVER_FACE_FLOOR_SQM:
            report_dropped(
                logger, "sliver face",
                "it is smaller than the sliver floor, so it is not imported "
                "as a block",
            )
            continue
        kept.append(f)
    return kept


def feature_to_polygon(
    geometries: list,
    attributes: list,
    config: PolygonizeConfig = None,
) -> Tuple[List[Tuple[Any, Dict[str, Any]]], Dict[str, Any]]:
    """
    Unified Feature-to-Polygon engine for every polygon-purpose layer.

    Accepts mixed input (polygons / closed or near-closed lines / open division
    lines / label points) and returns one (Polygon-or-MultiPolygon, attrs) entry
    per resulting feature, plus a warnings dict.

    Behaviour (cases):
      - A: existing polygons preserved as-is (one feature each).
      - B: closed / near-closed lines are snapped-to-close (within
           config.snap_tolerance_m) and converted into Polygons.
      - C: remaining open lines and every case-A/B polygon boundary are noded
           into one planar graph and polygonized via _polygonize_edge_network
           (ArcGIS-style Feature-to-Polygon - handles a line ending on
           another line, not just on the outer boundary); label points name
           the resulting faces via point-in-polygon.
      - D (off by default, config.allow_point_hull): points-only input is hulled
           into a polygon; config.island_cluster_m clusters disjoint groups.

    Args:
        geometries: List of shapely geometries (already in EPSG:4326 unless
                    config.source_crs is provided).
        attributes: Parallel list of attribute dicts (index-aligned).
        config: PolygonizeConfig; None => defaults (snap 20 m).

    Returns:
        (features, warnings): features = [(geom, attrs), ...], each geom a
        Polygon / MultiPolygon; warnings = {"dropped_unclosed": int, ...}.
    """
    if config is None:
        config = PolygonizeConfig()

    # H-HULL-1: before any geometry work. A coordinate below the precision
    # floor cannot be real, and mixing such values with ordinary ones makes
    # this function run forever on one core -- see
    # `_sanitize_coordinate_magnitudes`.
    geometries, _rewritten = _sanitize_coordinate_magnitudes(geometries)
    if _rewritten:
        logger.warning(
            "normalised sub-precision coordinates in %d geometry/geometries "
            "(|value| < %g snapped to 0). Values that small are not real "
            "survey data and make hull construction non-terminating.",
            _rewritten, COORD_PRECISION_FLOOR,
        )

    # CRS normalization (invariant: storage in 4326; metric ops in local UTM)
    if config.source_crs is not None:
        _normalized = []
        for g in geometries:
            _normalized.append(transform_to_4326(g, config.source_crs))
        geometries = _normalized

    polygon_data = []
    line_data = []
    point_data = []
    for i, geom in enumerate(geometries):
        attrs = attributes[i] if i < len(attributes) else {}
        gt = getattr(geom, "geom_type", "")
        if "Polygon" in gt:
            polygon_data.append((i, geom, attrs))
        elif "LineString" in gt or "Line" in gt:
            line_data.append((i, geom, attrs))
        elif "Point" in gt:
            point_data.append((i, geom, attrs))

    result: List[Tuple[Any, Dict[str, Any]]] = []
    warnings: Dict[str, Any] = {"dropped_unclosed": 0}

    # Case A — existing polygons preserved.
    for _, geom, attrs in polygon_data:
        a = dict(attrs)
        a["source"] = "poly"
        result.append((geom, a))

    # Case B — snap-close near-closed lines into polygons.
    if line_data:
        lines = [g for _, g, _ in line_data]
        remaining_lines, closed_polys = convert_lines_to_multi_line(
            lines, config.snap_tolerance_m
        )
        for poly in closed_polys:
            result.append((poly, {"source": "line_snapped"}))

        # Case C — open lines partition the polygon(s) they touch, via a proper
        # planar-graph node + polygonize (see `_polygonize_edge_network`)
        # rather than a sequential `shapely.ops.split` per line. This is what
        # correctly handles a line that starts on a polygon edge and ends by
        # intersecting ANOTHER open line rather than crossing straight through
        # to the far boundary.
        all_polys = [g for g, _ in result]
        poly_union = unary_union(all_polys) if all_polys else None
        touching_lines = []
        for ln in remaining_lines:
            if poly_union is not None and poly_union.intersects(ln):
                touching_lines.append(ln)
            else:
                warnings["dropped_unclosed"] += 1
        if touching_lines and all_polys:
            faces = _polygonize_edge_network(all_polys, touching_lines)
            if faces:
                result = [(f, {"source": "line_partition"}) for f in faces]
            else:
                warnings["dropped_unclosed"] += len(touching_lines)

    # Case D — points-only (or no closed shapes): hull points into polygons.
    if not result and point_data:
        warnings["point_hull"] = True
        point_geoms = [(g, a3) for _, g, a3 in point_data]
        all_pts = [g for g, _ in point_geoms]

        if config.allow_point_hull and len(all_pts) >= 3:
            # Group points by an explicit grouping/name attribute (task 2.1):
            # points sharing a group hull together -> one polygon per group.
            group_keys = {(_group_key(a, config) or "__single__") for _, a in point_geoms}
            if any(k != "__single__" for k in group_keys):
                groups: Dict[str, List[Any]] = {}
                for g, a in point_geoms:
                    key = _group_key(a, config) or "__single__"
                    groups.setdefault(key, []).append(g)
                for key, gpts in groups.items():
                    if len(gpts) < 3:
                        warnings["dropped_unclosed"] += 1
                        continue
                    hull = _concave_hull(gpts, config.alpha)
                    if hull is None:
                        warnings["dropped_unclosed"] += 1
                        continue
                    result.append((hull, {"source": "point_hull", "name": key}))
                warnings["island_group_count"] = len(groups)
            else:
                # No grouping attr -> "no names => a single polygon from all the
                # points" (plan case D). Island split (invariant F) only applies
                # when the cloud *clearly* separates into several multi-point
                # clusters; a single continuous polygon is never split.
                clusters = _cluster_points_by_distance(all_pts, config.island_cluster_m)
                real_clusters = [c for c in clusters if len(c) >= 3]
                if set(len(c) for c in real_clusters) and len(real_clusters) > 1:
                    island_idx = 0
                    warnings["island_group_count"] = len(real_clusters)
                    for cluster in real_clusters:
                        hull = _concave_hull(cluster, config.alpha)
                        if hull is None:
                            warnings["dropped_unclosed"] += 1
                            continue
                        island_idx += 1
                        result.append((hull, {"source": "point_hull", "name": island_idx}))
                else:
                    # One continuous cloud (or every cluster has < 3 points) ->
                    # single polygon from all points.
                    hull = _concave_hull(all_pts, config.alpha)
                    if hull is None:
                        warnings["dropped_unclosed"] += 1
                    else:
                        result.append((hull, {"source": "point_hull"}))
        elif len(all_pts) >= 3:
            # Degenerate guard: still produce a polygon so the layer is usable.
            hull = _concave_hull(all_pts, config.alpha)
            if hull is None:
                warnings["dropped_unclosed"] += 1
            else:
                result.append((hull, {"source": "point_hull"}))
        else:
            warnings["dropped_unclosed"] += 1

    # Case C names — label polygons from label points via point-in-polygon.
    polys = [p for p, _ in result]
    labels = perform_spatial_join_labeling(polys, point_data) if (point_data and result) else {}
    for idx, (geom, attrs) in enumerate(result):
        point_name = labels.get(idx)
        if point_name:
            attrs["name"] = point_name
            if attrs.get("source") != "poly":
                attrs["source"] = "point_label"
        elif not attrs.get("name"):
            # Name lookup must skip internal housekeeping keys.
            _lookup = {k: v for k, v in attrs.items() if k not in ("source", "category")}
            attrs["name"] = extract_name_from_attrs(_lookup) or f"{config.name_prefix} {idx + 1}"

    if point_data:
        warnings["point_count"] = len(point_data)
    warnings["polygon_count"] = len(result)

    return result, warnings


def process_points_list(geometries: list, attributes: list, metadata: Dict[str, Any]) -> Polygon:
    """
    Process point geometries
    Creates a small buffer around the first point for demonstration
    """
    # Get first point
    point = geometries[0]

    # Create 100m buffer (approximate, will be refined by projection)
    buffer_geometry = point.buffer(0.001)  # ~100m in degrees

    # Store point attributes in metadata
    if attributes and len(attributes) > 0:
        for key, value in attributes[0].items():
            if value is not None:
                metadata[key] = value

    return buffer_geometry


## `partition_polygon_with_lines` and `convert_lines_to_polygons` (the
## sequential-`shapely.ops.split`-per-line implementation) were removed here.
## Both purposes - closing a ring from a closed line, and partitioning a
## polygon with open division lines - are now served by the node-and-
## polygonize `_polygonize_edge_network` / `convert_lines_to_multi_line`
## pair used by `feature_to_polygon`, which every caller (including the
## legacy `_polygonise`) now goes through.


def perform_spatial_join_labeling(polygons: list, point_data: list) -> dict:
    """
    Perform Point-in-Polygon spatial join to label polygons with point attributes

    Args:
        polygons: List of Polygon geometries
        point_data: List of tuples (index, Point geometry, attributes)

    Returns:
        Dict mapping polygon index to name from point within it
    """
    from shapely.geometry import Point

    block_names = {}

    for poly_idx, polygon in enumerate(polygons):
        # Find points within this polygon
        for pt_idx, point_geom, point_attrs in point_data:
            if polygon.contains(point_geom) or polygon.intersects(point_geom):
                # Extract name from point attributes
                name = None
                # Priority: 'name' field (case-insensitive)
                for key in point_attrs.keys():
                    if key.lower() == 'name':
                        name = str(point_attrs[key])
                        break

                # If no name field, use first string attribute
                if not name:
                    for key, value in point_attrs.items():
                        if value and isinstance(value, str):
                            name = str(value)
                            break

                if name:
                    block_names[poly_idx] = name
                    break  # Found label for this polygon

    return block_names


def process_lines_list(geometries: list, metadata: Dict[str, Any]) -> Polygon:
    """
    Process line geometries - convert to polygon using polygonize
    """
    from shapely.ops import polygonize

    # Merge all lines
    merged_lines = unary_union(geometries)

    # Try to create polygon from lines
    try:
        polygons = list(polygonize([merged_lines]))
        if polygons:
            # Use largest polygon if multiple
            geometry = max(polygons, key=lambda p: p.area)
        else:
            # If polygonize fails, create buffer around lines
            geometry = merged_lines.buffer(0.0001)
    except Exception:
        # A 0.0001-degree buffer around the lines is roughly an 11 m ribbon,
        # not the enclosed area - a very different polygon from the one
        # polygonize would have produced.
        logger.warning(
            "polygonize failed - falling back to a thin buffer around the "
            "lines, which is a ribbon rather than the enclosed area",
            exc_info=True,
        )
        # Fallback: buffer around lines
        geometry = merged_lines.buffer(0.0001)

    return geometry


def process_polygons_list(geometries: list, metadata: Dict[str, Any]) -> Polygon:
    """
    Process polygon geometries - merge if multiple features
    """
    if len(geometries) == 1:
        # Single feature - return as-is
        geometry = geometries[0]
    else:
        # Multiple features - merge into single polygon
        geometry = unary_union(geometries)

    # Handle MultiPolygon - convert to single Polygon
    if isinstance(geometry, MultiPolygon):
        if len(geometry.geoms) == 1:
            # Single polygon in MultiPolygon - extract it
            geometry = list(geometry.geoms)[0]
        else:
            # Multiple polygons - use the largest one
            geometry = max(geometry.geoms, key=lambda p: p.area)
            metadata["note"] = f"Multiple polygons found, using largest ({len(geometry.geoms)} total)"

    return geometry


def extract_name_from_attrs(attrs: dict) -> Optional[str]:
    """
    Extract name from a single attribute dictionary

    Args:
        attrs: Dictionary of attributes

    Returns:
        Extracted name or None
    """
    if not attrs:
        return None

    # Try to find "name" attribute (case-insensitive)
    for key in attrs.keys():
        if key.lower() == "name":
            if attrs[key] is not None:
                return str(attrs[key])

    # Try first string attribute
    for key, value in attrs.items():
        if value is not None and isinstance(value, str) and value.strip():
            return str(value)

    return None


def extract_block_name_from_attrs(attributes: list, metadata: Dict[str, Any]) -> None:
    """
    Extract block name using priority order:
    1. Attribute explicitly named "Name" or "name"
    2. First detected string attribute
    3. Default name
    """
    if not attributes or len(attributes) == 0:
        metadata["name"] = "Block_0"
        return

    first_attrs = attributes[0]

    # Try to find "name" attribute (case-insensitive)
    for key in first_attrs.keys():
        if key.lower() == "name":
            if first_attrs[key] is not None:
                metadata["name"] = str(first_attrs[key])
                return

    # Try first string attribute
    for key, value in first_attrs.items():
        if value is not None and isinstance(value, str):
            metadata["name"] = str(value)
            return

    # Fallback to default
    metadata["name"] = "Block_0"


def transform_to_4326(geometry: Any, source_crs: Optional[CRS]) -> Any:
    """
    Transform geometry to SRID 4326 (WGS84)

    Args:
        geometry: Shapely geometry object
        source_crs: Source CRS

    Returns:
        Transformed geometry in EPSG:4326
    """
    if source_crs is None or source_crs.to_epsg() == 4326:
        return geometry

    # Create transformer
    transformer = Transformer.from_crs(
        source_crs,
        CRS.from_epsg(4326),
        always_xy=True
    )

    # Transform geometry
    from shapely.ops import transform
    return transform(transformer.transform, geometry)


def calculate_polygon_area_utm(polygon: Polygon) -> Tuple[float, float]:
    """
    Calculate accurate area of a polygon using UTM projection.

    Automatically selects the correct UTM zone based on the polygon's location.
    Works globally for any coordinates.

    Args:
        polygon: Shapely Polygon in EPSG:4326 (WGS84)

    Returns:
        Tuple of (area_sqm, area_hectares)
    """
    # Get centroid to determine appropriate UTM zone
    centroid = polygon.centroid

    # Calculate UTM zone using standard formula
    # Zone number = floor((longitude + 180) / 6) + 1
    zone = int((centroid.x + 180) / 6) + 1

    # Determine hemisphere and EPSG code
    if centroid.y >= 0:
        # Northern hemisphere: 32601-32660
        utm_epsg = 32600 + zone
    else:
        # Southern hemisphere: 32701-32760
        utm_epsg = 32700 + zone

    # Create transformer from WGS84 to UTM
    transformer = Transformer.from_crs(
        CRS.from_epsg(4326),  # WGS84
        CRS.from_epsg(utm_epsg),  # Automatically calculated UTM zone
        always_xy=True
    )

    # Transform polygon to UTM
    polygon_utm = transform(transformer.transform, polygon)

    # Calculate area in square meters
    area_sqm = polygon_utm.area
    area_hectares = area_sqm / SQM_PER_HA

    return area_sqm, area_hectares


def calculate_area_utm(geometry: Any, crs: Optional[CRS]) -> Tuple[float, float]:
    """
    Calculate accurate area in square meters using UTM projection.

    Automatically selects the correct UTM zone based on the geometry's location.
    Works globally for any coordinates.

    Args:
        geometry: Shapely geometry in EPSG:4326
        crs: Source CRS

    Returns:
        Tuple of (area_sqm, area_hectares)
    """
    # Get centroid to determine appropriate UTM zone
    centroid = geometry.centroid

    # Calculate UTM zone using standard formula
    # Zone number = floor((longitude + 180) / 6) + 1
    zone = int((centroid.x + 180) / 6) + 1

    # Determine hemisphere and EPSG code
    if centroid.y >= 0:
        # Northern hemisphere: 32601-32660
        utm_epsg = 32600 + zone
    else:
        # Southern hemisphere: 32701-32760
        utm_epsg = 32700 + zone

    # Transform to UTM
    transformer = Transformer.from_crs(
        CRS.from_epsg(4326),
        CRS.from_epsg(utm_epsg),
        always_xy=True
    )

    from shapely.ops import transform
    geometry_utm = transform(transformer.transform, geometry)

    # Calculate area
    area_sqm = geometry_utm.area
    area_hectares = area_sqm / SQM_PER_HA

    return area_sqm, area_hectares


BOUNDARY_HEAL_BUFFER_M: float = 0.01


def derive_boundary_from_polygons(polygons: List[Any]) -> Any:
    """Dissolve a set of polygons into a single forest-boundary geometry (T6.1).

    Uses unary_union to dissolve interior edges, and applies a tiny
    buffer-then-unbuffer (BOUNDARY_HEAL_BUFFER_M) to heal micro-gaps between
    touching polygons before the area comparison. Returns a Shapely geometry
    (Polygon/MultiPolygon), or None if no valid polygons were supplied.
    """
    if not polygons:
        return None
    valid = [p for p in polygons if p is not None and not getattr(p, "is_empty", True)]
    if not valid:
        return None
    unioned = unary_union(valid)
    if unioned.is_empty:
        return None
    healed = unioned.buffer(BOUNDARY_HEAL_BUFFER_M / 1000.0).buffer(-BOUNDARY_HEAL_BUFFER_M / 1000.0)
    if healed.is_empty:
        return unioned
    return healed


def boundary_area_matches_block_sum(boundary_shape: Any, block_shapes: List[Any], tolerance: float = 0.001) -> Tuple[bool, float, float]:
    """Invariant A: |boundary_area - Σ block_areas| / boundary_area < tolerance.

    Returns (matches, boundary_area_ha, sum_block_area_ha). Real-world imports may
    have micro-gaps/overlaps, so this is a warning check (lists divergence), not a
    hard failure.
    """
    bank = 111000.0 * 111000.0  # deg^2 -> m^2 approx
    boundary_area_ha = (getattr(boundary_shape, "area", 0) or 0) * bank / 10000.0
    sum_block_ha = sum((getattr(b, "area", 0) or 0) for b in block_shapes) * bank / 10000.0
    if boundary_area_ha <= 0:
        return False, 0.0, sum_block_ha
    ratio = abs(boundary_area_ha - sum_block_ha) / boundary_area_ha
    return ratio < tolerance, round(boundary_area_ha, 4), round(sum_block_ha, 4)


