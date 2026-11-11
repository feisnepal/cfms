"""
Export functionality for fieldbook and sampling data.
Supports CSV, Excel, GPX, GeoJSON, and KML formats.
"""
# constraint: export formats — CSV, XLSX, GPX, GeoJSON, KML
# why: each format uses different serialization strategy
# constraint: GPX requires lat/lon in WGS84
from sqlalchemy.orm import Session
from uuid import UUID
import csv
import io
from typing import List, Dict, Any
from xml.etree import ElementTree as ET
import logging

from app.models.fieldbook import Fieldbook
from app.models.sampling import SamplingDesign
from app.core.constants import METERS_PER_DEGREE_LAT


logger = logging.getLogger(__name__)


def _rollback_quietly(db: Session) -> None:
    """Clear a transaction left failed by an earlier query, before the next one.

    Ten sites in this module opened with `try: db.rollback() except: pass`.
    The swallow is defensible on its face - this runs while an error is already
    being handled, and a rollback that raises must not replace the failure the
    caller is dealing with - but it also means a broken connection looks exactly
    like a clean one, and a session left dirty by something upstream never gets
    diagnosed. So: still no re-raise, but no longer silent. `exc_info` carries
    the call site, which is why this needs no `where` argument.
    """
    try:
        db.rollback()
    except Exception:
        logger.warning(
            "rollback failed while clearing a stale transaction for an export - "
            "the session may be unusable and later queries in this export will "
            "likely fail too", exc_info=True,
        )


# ===========================
# Fieldbook Export Functions -- moved to services/fieldbook_export.py (one row definition for all four
# formats); re-exported at the bottom of this module so existing imports keep working.
# ===========================

def _safe_string(val) -> str:
    s = str(val or '').strip()
    try:
        from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
        s = ILLEGAL_CHARACTERS_RE.sub('', s)
    except ImportError:
        import re
        s = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F]', '', s)
    if s.startswith(('=', '+', '-')):
        s = f"'{s}"
    return s

# ===========================
# Sampling Export Functions
# ===========================

def export_sampling_csv(db: Session, design_id: UUID) -> bytes:
    """
    Export sampling points to CSV format with complete field data.
    Includes: Plot No, Block, Longitude, Latitude, Elevation, UTM Easting, UTM Northing, UTM Zone, Distance from Boundary
    """
    # CRITICAL: Rollback any previous failed transactions at the START
    # This prevents "InFailedSqlTransaction" errors from cascading
    _rollback_quietly(db)

    design = db.query(SamplingDesign).filter(SamplingDesign.id == design_id).first()

    if not design or not design.points_geometry:
        raise ValueError("Sampling design not found or has no points")

    # Get geometry as WKT using PostGIS
    from sqlalchemy import text
    wkt_query = text("""
        SELECT ST_AsText(points_geometry) as wkt
        FROM public.sampling_designs
        WHERE id = :design_id
    """)
    result = db.execute(wkt_query, {"design_id": str(design_id)}).first()

    if not result or not result.wkt:
        raise ValueError("Failed to retrieve geometry as WKT")

    # Parse MultiPoint geometry
    from shapely import wkt as shapely_wkt
    multipoint = shapely_wkt.loads(result.wkt)

    # Get block assignment
    block_assignment = design.points_block_assignment or []

    # Get calculation boundary for distance calculation
    from app.models.calculation import Calculation
    calc = db.query(Calculation).filter(Calculation.id == design.calculation_id).first()
    boundary_wkt = None
    if calc:
        boundary_query = text("""
            SELECT ST_AsText(boundary_geom) as wkt
            FROM public.calculations
            WHERE id = :calc_id
        """)
        boundary_result = db.execute(boundary_query, {"calc_id": str(design.calculation_id)}).first()
        if boundary_result:
            boundary_wkt = boundary_result.wkt

    # Create CSV
    output = io.StringIO()
    writer = csv.writer(output)

    # Write header with all displayed fields including topographic features
    writer.writerow([
        'प्लट नं. (Plot No)',
        'ब्लक (Block)',
        'क्षेत्रको प्रकार (Zone Type)',
        'देशान्तर (Longitude)',
        'अक्षांश (Latitude)',
        'उचाइ / Elevation (m)',
        'UTM इस्टिङ (UTM Easting)',
        'UTM नर्दिङ (UTM Northing)',
        'UTM जोन (UTM Zone)',
        'सिमानाबाट दूरी / Distance from Boundary (m)',
        'नजिकको फिचर (Nearest Feature)',
        'फिचरको प्रकार (Feature Type)',
        'फिचरसम्मको दूरी / Distance to Feature (m)',
        'फिचरतर्फको दिशा (Direction to Feature)'
    ])

    # Import required modules for calculations
    from app.utils.geospatial import extract_elevation_at_point
    from app.utils.geospatial_vector_optimized import (
        preclip_topographic_features,
        find_nearest_topographic_feature_optimized
    )
    from pyproj import Transformer
    import logging
    logger = logging.getLogger(__name__)

    # Pre-clip ridge/river data ONCE for performance (20-100x faster!)
    # IMPORTANT: Wrap in transaction handling to prevent "InFailedSqlTransaction" errors
    clipped_features = None
    if boundary_wkt:
        try:
            # Rollback any previous failed transactions
            _rollback_quietly(db)

            clipped_features = preclip_topographic_features(
                db=db,
                boundary_wkt=boundary_wkt,
                buffer_meters=200.0
            )
            # DEBUG: Log what we got
            if clipped_features:
                ridge_count = len(clipped_features.get('ridges', []))
                river_count = len(clipped_features.get('rivers', []))
                logger.info(f"Pre-clipped {ridge_count} ridges and {river_count} rivers for CSV export")
                if ridge_count == 0 and river_count == 0:
                    logger.warning("Pre-clipping returned 0 features - ridge/river columns will be empty!")
            else:
                logger.warning("Pre-clipping returned None - ridge/river columns will be empty!")
        except Exception as e:
            logger.error(f"Failed to pre-clip topographic features: {e}", exc_info=True)
            # Rollback the failed transaction
            _rollback_quietly(db)
            clipped_features = None

    # Write points with complete data
    for i, point in enumerate(multipoint.geoms):
        lon, lat = point.x, point.y

        # Find block assignment for this point
        block_info = next((b for b in block_assignment if b.get('point_index') == i), None)
        block_name = block_info.get('block_name', f'Plot {i+1}') if block_info else f'Plot {i+1}'
        zone_type = block_info.get('zone_type', 'Productive') if block_info else 'Productive'
        zone_type_display = zone_type.capitalize() if zone_type else 'Productive'

        # Calculate UTM coordinates
        utm_zone = 44 if lon < 84 else 45
        transformer = Transformer.from_crs(f"EPSG:4326", f"EPSG:326{utm_zone}", always_xy=True)
        utm_easting, utm_northing = transformer.transform(lon, lat)

        # Extract elevation
        elevation_m = extract_elevation_at_point(db, lon, lat)

        # Calculate distance from boundary
        distance_from_boundary = None
        if boundary_wkt:
            try:
                boundary_geom = shapely_wkt.loads(boundary_wkt)
                distance_from_boundary = point.distance(boundary_geom.boundary) * METERS_PER_DEGREE_LAT
            except Exception:
                # The column is left empty rather than wrong, which is the right
                # fallback - but the boundary is the same for every row, so a
                # failure here empties the column for the whole export.
                logger.warning(
                    "distance-from-boundary unavailable - the column will be "
                    "empty for this export", exc_info=True,
                )

        # Extract topographic features (ridge/river)
        topo_feature = None
        feature_name = ''
        feature_type = ''
        feature_distance = ''
        feature_direction = ''

        if clipped_features:
            try:
                topo_feature = find_nearest_topographic_feature_optimized(
                    db=db,
                    longitude=lon,
                    latitude=lat,
                    clipped_features=clipped_features,
                    search_radius_meters=100.0,
                    prefer_rivers=True,
                    min_distance_threshold=20.0
                )

                if topo_feature:
                    feature_name = topo_feature.get("feature_name", "")
                    feature_type = topo_feature.get("feature_type", "")
                    feature_distance = f'{int(topo_feature.get("distance_meters", 0))}'
                    feature_direction = topo_feature.get("direction", "")
                else:
                    if i == 0:
                        logger.warning(f"Point 1: No topographic feature found within 1000m")
            except Exception as e:
                logger.warning(f"Failed to find topographic feature for point {i+1}: {e}", exc_info=True)

        # Write CSV row
        writer.writerow([
            i + 1,  # Plot number starts at 1
            block_name,
            zone_type_display,
            f'{lon:.7f}',
            f'{lat:.7f}',
            f'{int(elevation_m)}' if elevation_m and elevation_m > 0 else 'N/A',
            f'{utm_easting:.2f}',
            f'{utm_northing:.2f}',
            f'{utm_zone}N',
            f'{distance_from_boundary:.2f}' if distance_from_boundary else '',
            feature_name,
            feature_type,
            feature_distance,
            feature_direction
        ])

    return output.getvalue().encode('utf-8')


def export_sampling_gpx(db: Session, design_id: UUID) -> bytes:
    """
    Export sampling points to GPX format with complete field data.
    Includes elevation, UTM coordinates, block information, and zone type.
    """
    # CRITICAL: Rollback any previous failed transactions at the START
    _rollback_quietly(db)

    design = db.query(SamplingDesign).filter(SamplingDesign.id == design_id).first()

    if not design or not design.points_geometry:
        raise ValueError("Sampling design not found or has no points")

    # Get geometry as WKT using PostGIS
    from sqlalchemy import text
    wkt_query = text("""
        SELECT ST_AsText(points_geometry) as wkt
        FROM public.sampling_designs
        WHERE id = :design_id
    """)
    result = db.execute(wkt_query, {"design_id": str(design_id)}).first()

    if not result or not result.wkt:
        raise ValueError("Failed to retrieve geometry as WKT")

    # Parse MultiPoint geometry
    from shapely import wkt as shapely_wkt
    multipoint = shapely_wkt.loads(result.wkt)

    # Get block assignment
    block_assignment = design.points_block_assignment or []

    # Get calculation boundary for distance calculation
    from app.models.calculation import Calculation
    calc = db.query(Calculation).filter(Calculation.id == design.calculation_id).first()
    boundary_wkt = None
    if calc:
        boundary_query = text("""
            SELECT ST_AsText(boundary_geom) as wkt
            FROM public.calculations
            WHERE id = :calc_id
        """)
        boundary_result = db.execute(boundary_query, {"calc_id": str(design.calculation_id)}).first()
        if boundary_result:
            boundary_wkt = boundary_result.wkt

    # Import required modules for calculations
    from app.utils.geospatial import extract_elevation_at_point
    from pyproj import Transformer

    # Create GPX XML
    gpx = ET.Element('gpx', {
        'version': '1.1',
        'creator': 'Community Forest Management System',
        'xmlns': 'http://www.topografix.com/GPX/1/1'
    })

    metadata = ET.SubElement(gpx, 'metadata')
    ET.SubElement(metadata, 'name').text = f'Sampling Points - {design.sampling_type}'
    ET.SubElement(metadata, 'desc').text = f'{design.total_points} sampling plots'

    for i, point in enumerate(multipoint.geoms):
        lon, lat = point.x, point.y

        # Find block assignment for this point
        block_info = next((b for b in block_assignment if b.get('point_index') == i), None)
        block_name = block_info.get('block_name', f'Plot {i+1}') if block_info else f'Plot {i+1}'
        zone_type = block_info.get('zone_type', 'Productive') if block_info else 'Productive'

        # Calculate UTM coordinates
        utm_zone = 44 if lon < 84 else 45
        transformer = Transformer.from_crs(f"EPSG:4326", f"EPSG:326{utm_zone}", always_xy=True)
        utm_easting, utm_northing = transformer.transform(lon, lat)

        # Extract elevation
        elevation_m = extract_elevation_at_point(db, lon, lat)

        # Calculate distance from boundary
        distance_from_boundary = None
        if boundary_wkt:
            try:
                boundary_geom = shapely_wkt.loads(boundary_wkt)
                distance_from_boundary = point.distance(boundary_geom.boundary) * METERS_PER_DEGREE_LAT
            except Exception:
                # The column is left empty rather than wrong, which is the right
                # fallback - but the boundary is the same for every row, so a
                # failure here empties the column for the whole export.
                logger.warning(
                    "distance-from-boundary unavailable - the column will be "
                    "empty for this export", exc_info=True,
                )

        wpt = ET.SubElement(gpx, 'wpt', {
            'lat': f'{lat:.7f}',
            'lon': f'{lon:.7f}'
        })
        ET.SubElement(wpt, 'name').text = f'Plot {i+1}'
        ET.SubElement(wpt, 'type').text = 'sampling_plot'

        # Add elevation
        if elevation_m:
            ET.SubElement(wpt, 'ele').text = f'{int(elevation_m)}'

        # Build description with all fields
        desc_parts = []
        desc_parts.append(f'Block: {block_name}')
        desc_parts.append(f'Zone: {zone_type.capitalize()}')
        desc_parts.append(f'UTM: {utm_easting:.2f}E, {utm_northing:.2f}N ({utm_zone}N)')
        if elevation_m:
            desc_parts.append(f'Elevation: {int(elevation_m)}m')
        if distance_from_boundary:
            desc_parts.append(f'Distance from Boundary: {distance_from_boundary:.2f}m')
        if design.plot_shape:
            desc_parts.append(f'Plot: {design.plot_shape}')
            if design.plot_radius_meters:
                desc_parts.append(f'Radius: {design.plot_radius_meters}m')

        ET.SubElement(wpt, 'desc').text = ' | '.join(desc_parts)

    # Convert to bytes
    tree = ET.ElementTree(gpx)
    output = io.BytesIO()
    tree.write(output, encoding='utf-8', xml_declaration=True)
    output.seek(0)
    return output.read()


def export_sampling_kml(db: Session, design_id: UUID) -> bytes:
    """
    Export sampling points to KML format (Google Earth) with complete field data.
    Includes elevation, UTM coordinates, and block information.
    """
    design = db.query(SamplingDesign).filter(SamplingDesign.id == design_id).first()

    if not design or not design.points_geometry:
        raise ValueError("Sampling design not found or has no points")

    # Get geometry as WKT using PostGIS
    from sqlalchemy import text
    wkt_query = text("""
        SELECT ST_AsText(points_geometry) as wkt
        FROM public.sampling_designs
        WHERE id = :design_id
    """)
    result = db.execute(wkt_query, {"design_id": str(design_id)}).first()

    if not result or not result.wkt:
        raise ValueError("Failed to retrieve geometry as WKT")

    # Parse MultiPoint geometry
    from shapely import wkt as shapely_wkt
    multipoint = shapely_wkt.loads(result.wkt)

    # Get block assignment
    block_assignment = design.points_block_assignment or []

    # Get calculation boundary for distance calculation
    from app.models.calculation import Calculation
    calc = db.query(Calculation).filter(Calculation.id == design.calculation_id).first()
    boundary_wkt = None
    if calc:
        boundary_query = text("""
            SELECT ST_AsText(boundary_geom) as wkt
            FROM public.calculations
            WHERE id = :calc_id
        """)
        boundary_result = db.execute(boundary_query, {"calc_id": str(design.calculation_id)}).first()
        if boundary_result:
            boundary_wkt = boundary_result.wkt

    # Import required modules for calculations
    from app.utils.geospatial import extract_elevation_at_point
    from app.utils.geospatial_vector_optimized import (
        preclip_topographic_features,
        find_nearest_topographic_feature_optimized
    )
    from pyproj import Transformer
    import logging
    logger = logging.getLogger(__name__)
    import math

    # Create KML XML
    kml = ET.Element('kml', {'xmlns': 'http://www.opengis.net/kml/2.2'})
    document = ET.SubElement(kml, 'Document')

    ET.SubElement(document, 'name').text = f'Sampling Points - {design.sampling_type}'
    ET.SubElement(document, 'description').text = (
        f'Sampling design with {design.total_points} plots. '
        f'Type: {design.sampling_type}. '
        f'Intensity: {design.intensity_per_hectare}/ha.'
    )

    # Add style for sampling points
    style = ET.SubElement(document, 'Style', {'id': 'samplingPlot'})
    icon_style = ET.SubElement(style, 'IconStyle')
    ET.SubElement(icon_style, 'scale').text = '1.2'
    icon = ET.SubElement(icon_style, 'Icon')
    ET.SubElement(icon, 'href').text = 'http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png'

    # Add folder for points
    folder = ET.SubElement(document, 'Folder')
    ET.SubElement(folder, 'name').text = 'Sampling Plots'

    for i, point in enumerate(multipoint.geoms):
        lon, lat = point.x, point.y

        # Find block assignment for this point
        block_info = next((b for b in block_assignment if b.get('point_index') == i), None)
        block_name = block_info.get('block_name', f'Plot {i+1}') if block_info else f'Plot {i+1}'
        zone_type = block_info.get('zone_type', 'Productive') if block_info else 'Productive'

        # Calculate UTM coordinates
        utm_zone = 44 if lon < 84 else 45
        transformer = Transformer.from_crs(f"EPSG:4326", f"EPSG:326{utm_zone}", always_xy=True)
        utm_easting, utm_northing = transformer.transform(lon, lat)

        # Extract elevation
        elevation_m = extract_elevation_at_point(db, lon, lat)

        # Calculate distance from boundary
        distance_from_boundary = None
        if boundary_wkt:
            try:
                boundary_geom = shapely_wkt.loads(boundary_wkt)
                distance_from_boundary = point.distance(boundary_geom.boundary) * METERS_PER_DEGREE_LAT
            except Exception:
                # The column is left empty rather than wrong, which is the right
                # fallback - but the boundary is the same for every row, so a
                # failure here empties the column for the whole export.
                logger.warning(
                    "distance-from-boundary unavailable - the column will be "
                    "empty for this export", exc_info=True,
                )

        placemark = ET.SubElement(folder, 'Placemark')
        ET.SubElement(placemark, 'name').text = f'Plot {i+1}'
        ET.SubElement(placemark, 'styleUrl').text = '#samplingPlot'

        # Build HTML description with all fields
        desc = f'<b>Plot {i+1}</b><br/>'
        desc += f'Block: {block_name}<br/>'
        desc += f'Zone Type: {zone_type.capitalize()}<br/>'
        desc += f'Longitude: {lon:.7f}<br/>'
        desc += f'Latitude: {lat:.7f}<br/>'
        if elevation_m:
            desc += f'Elevation: {int(elevation_m)}m ASLM<br/>'
        desc += f'UTM Easting: {utm_easting:.2f}<br/>'
        desc += f'UTM Northing: {utm_northing:.2f}<br/>'
        desc += f'UTM Zone: {utm_zone}N<br/>'
        if distance_from_boundary:
            desc += f'Distance from Boundary: {distance_from_boundary:.2f}m<br/>'

        if design.plot_shape:
            desc += f'<br/><b>Plot Details:</b><br/>'
            desc += f'Shape: {design.plot_shape}<br/>'
            if design.plot_radius_meters:
                plot_area = math.pi * float(design.plot_radius_meters) ** 2
                desc += f'Radius: {design.plot_radius_meters}m<br/>'
                desc += f'Area: {plot_area:.2f} m²'
            elif design.plot_length_meters and design.plot_width_meters:
                plot_area = float(design.plot_length_meters) * float(design.plot_width_meters)
                desc += f'Length: {design.plot_length_meters}m x Width: {design.plot_width_meters}m<br/>'
                desc += f'Area: {plot_area:.2f} m²'

        ET.SubElement(placemark, 'description').text = desc

        point_elem = ET.SubElement(placemark, 'Point')
        # KML format: lon,lat,elevation
        elev_val = int(elevation_m) if elevation_m else 0
        ET.SubElement(point_elem, 'coordinates').text = f'{lon:.7f},{lat:.7f},{elev_val}'

    # Convert to bytes
    tree = ET.ElementTree(kml)
    output = io.BytesIO()
    tree.write(output, encoding='utf-8', xml_declaration=True)
    output.seek(0)
    return output.read()


# Field book exports live in fieldbook_export.py. Imported LAST: that module reaches back into this one for
# `_safe_string` / `_rollback_quietly`, which are defined above by now.
from app.services.fieldbook_export import (  # noqa: E402,F401
    export_fieldbook_csv,
    export_fieldbook_excel,
    export_fieldbook_geojson,
    export_fieldbook_gpx,
)
