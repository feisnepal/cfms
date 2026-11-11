"""
Map Generation Service for Forest Management System

Generates A5-sized PNG maps for forest analysis reports.
- A5 dimensions: 148mm × 210mm (portrait) or 210mm × 148mm (landscape)
- Target DPI: 300 (high quality for printing)
- Output format: PNG with transparency support
"""

import logging
import matplotlib

from app.core.dropped import report_dropped

logger = logging.getLogger(__name__)
matplotlib.use('Agg')  # Non-interactive backend for server-side generation

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Patch
from matplotlib.lines import Line2D
import numpy as np
from typing import Optional, Tuple, Dict, Any, List
from pathlib import Path
import io
from PIL import Image
import os
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import contextily as cx
from shapely.geometry import shape, mapping
from shapely import wkt
from sqlalchemy import text
import matplotlib.colors as mcolors

from app.utils.map_grid import compute_snapped_grid, apply_snapped_ticks

# constraint: A4 landscape, 300 DPI for print quality
# NOTE: A5 fallback (portrait 148×210mm / landscape 210×148mm) for report embedding
A5_PORTRAIT_INCHES = (5.83, 8.27)   # 148mm × 210mm
A5_LANDSCAPE_INCHES = (8.27, 5.83)  # 210mm × 148mm
DEFAULT_DPI = 300


# business: CFMG requires boundary, blocks, and land cover on all management maps
class MapGenerator:
    """
    Service for generating forest analysis maps.

    Features:
    - A5-sized maps (portrait/landscape)
    - High-quality 300 DPI output
    - Customizable colors and styles
    - North arrow
    - Legend support
    """

    # why: matplotlib Agg backend for headless server rendering (no display required)
    def __init__(self, dpi: int = DEFAULT_DPI):
        """
        Initialize the map generator.

        Args:
            dpi: Dots per inch for output images (default: 300)
        """
        self.dpi = dpi

        # Configure matplotlib for better map aesthetics
        plt.style.use('seaborn-v0_8-darkgrid')
        plt.rcParams['font.family'] = 'sans-serif'
        plt.rcParams['font.size'] = 8
        plt.rcParams['axes.labelsize'] = 9
        plt.rcParams['axes.titlesize'] = 11
        plt.rcParams['legend.fontsize'] = 7
        plt.rcParams['figure.dpi'] = dpi

        # Devanagari font for Nepali labels — centralised in app.core.fonts.
        from app.core.fonts import configure_matplotlib_devanagari
        configure_matplotlib_devanagari()

        # Configure requests session with timeout for basemap tiles
        # NOTE: 2 retries, fast-fail on tile fetch failures to avoid hanging map generation
        self.session = requests.Session()
        retry_strategy = Retry(
            total=2,  # Only 2 retries (fast fail)
            backoff_factor=0.5,  # Short backoff
            status_forcelist=[429, 500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def _snap_axis(self, ax, min_x, max_x, min_y, max_y, **grid_kwargs):
        """Compute snapped grid, set axis limits, and apply ticks+grid (one call)."""
        lx, lx_lab, lx0, lx1 = compute_snapped_grid(min_x, max_x)
        ly, ly_lab, ly0, ly1 = compute_snapped_grid(min_y, max_y)
        ax.set_xlim(lx0, lx1)
        ax.set_ylim(ly0, ly1)
        apply_snapped_ticks(ax, lx, ly, lx_lab, ly_lab, grid_kwargs=grid_kwargs)
        return lx, ly, lx_lab, ly_lab, lx0, lx1, ly0, ly1

    def add_basemap_with_timeout(self, ax, crs='EPSG:4326', timeout=5, alpha=0.7, zorder=1):
        """
        Add basemap with timeout to prevent hanging.

        Args:
            ax: Matplotlib axes
            crs: Coordinate reference system
            timeout: Timeout in seconds (default: 5)
            alpha: Transparency (default: 0.7)
            zorder: Layer order (default: 1)

        Returns:
            bool: True if basemap added successfully, False otherwise
        """
        try:
            # Configure contextily to use our session with timeout
            import contextily.tile as ctx_tile

            # Store original session
            original_session = getattr(ctx_tile, '_session', None)

            # Create a new session with timeout
            session_with_timeout = requests.Session()
            session_with_timeout.request = lambda *args, **kwargs: requests.Session.request(
                session_with_timeout, *args, timeout=timeout, **kwargs
            )

            # Temporarily replace contextily's session
            ctx_tile._session = session_with_timeout

            # Add basemap with timeout
            cx.add_basemap(
                ax,
                crs=crs,
                source=cx.providers.OpenStreetMap.Mapnik,
                alpha=alpha,
                zorder=zorder
            )

            # Restore original session
            if original_session is not None:
                ctx_tile._session = original_session

            return True

        except Exception as e:
            logger.warning(f"Could not add basemap (timeout or connection error): {e}")
            return False

    # constraint: A4 landscape, 300 DPI; margins reserved for title, legend, scale bar, north arrow
    def create_figure(
        self,
        orientation: str = 'portrait',
        title: str = '',
        add_border: bool = True
    ) -> Tuple[plt.Figure, plt.Axes]:
        """
        Create a new figure with A5 dimensions.

        Args:
            orientation: 'portrait' or 'landscape'
            title: Map title
            add_border: Whether to add border around map

        Returns:
            Tuple of (figure, axes)
        """
        # Set figure size based on orientation
        figsize = A5_PORTRAIT_INCHES if orientation == 'portrait' else A5_LANDSCAPE_INCHES

        # Create figure with adjusted layout for external elements
        # Leave space for title at top and legend/scale at bottom
        fig = plt.figure(figsize=figsize, dpi=self.dpi)

        # Create axes with margins for map elements
        # [left, bottom, width, height] in figure coordinates
        ax = fig.add_axes([0.12, 0.15, 0.76, 0.75])  # Leave margins for elements

        # Add title if provided (outside the axes)
        if title:
            fig.suptitle(title, fontsize=12, fontweight='bold', y=0.96)

        # Add border if requested
        if add_border:
            ax.spines['top'].set_visible(True)
            ax.spines['right'].set_visible(True)
            ax.spines['bottom'].set_visible(True)
            ax.spines['left'].set_visible(True)
            ax.spines['top'].set_linewidth(2)
            ax.spines['right'].set_linewidth(2)
            ax.spines['bottom'].set_linewidth(2)
            ax.spines['left'].set_linewidth(2)

        return fig, ax

    def add_north_arrow(
        self,
        fig: plt.Figure,
        ax: plt.Axes,
        x: float = 0.92,
        y: float = 0.92,
        size: float = 0.04
    ) -> None:
        """
        Add a north arrow outside the map area.

        Args:
            fig: Matplotlib figure
            ax: Matplotlib axes
            x: X position (0-1, figure coordinates)
            y: Y position (0-1, figure coordinates)
            size: Arrow size relative to figure
        """
        # Draw north arrow in figure coordinates (outside axes)
        arrow = mpatches.FancyArrow(
            x, y - size, 0, size,
            width=size/3,
            head_width=size,
            head_length=size/2,
            fc='black',
            ec='black',
            transform=fig.transFigure,
            zorder=1000,
            clip_on=False
        )
        fig.patches.append(arrow)

        # Add "N" label
        fig.text(
            x, y + size/4, 'N',
            ha='center',
            va='bottom',
            fontsize=10,
            fontweight='bold',
            zorder=1001
        )

    # NOTE: SVG format preserves Devanagari text elements for browser/Word rendering
    # NOTE: MAP_CACHE_DIR under uploads/ — cleaned on cache invalidation
    def save_to_buffer(self, fig: plt.Figure) -> io.BytesIO:
        """
        Save figure to BytesIO buffer as SVG.
        SVG preserves text as elements, allowing proper Devanagari shaping in browser/Word.

        Args:
            fig: Matplotlib figure

        Returns:
            BytesIO buffer containing SVG data
        """
        buffer = io.BytesIO()
        fig.savefig(
            buffer,
            format='svg',
            dpi=self.dpi,
            bbox_inches='tight',
            facecolor='white',
            edgecolor='none',
            pad_inches=0.1
        )
        buffer.seek(0)
        return buffer

    def save_to_file(self, fig: plt.Figure, filepath: str) -> Path:
        """
        Save figure to file as PNG.

        Args:
            fig: Matplotlib figure
            filepath: Output file path

        Returns:
            Path object of saved file
        """
        output_path = Path(filepath)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        from app.core.text_shaping import save_figure

        save_figure(
            fig,
            output_path,
            format='png',
            dpi=self.dpi,
            bbox_inches='tight',
            facecolor='white',
            edgecolor='none',
            pad_inches=0.1
        )

        return output_path

    def close_figure(self, fig: plt.Figure) -> None:
        """
        Close figure to free memory.

        Args:
            fig: Matplotlib figure to close
        """
        plt.close(fig)

    def query_schools_within_buffer(
        self,
        db_session,
        geometry: Dict[str, Any],
        buffer_meters: float = 100.0
    ) -> List[Dict[str, Any]]:
        """
        Query schools within buffer distance of geometry.

        Args:
            db_session: SQLAlchemy database session
            geometry: GeoJSON geometry dict
            buffer_meters: Buffer distance in meters (default: 100m)

        Returns:
            List of school dicts with name, lon, lat, distance
        """
        try:
            # Convert geometry to WKT
            geom_shape = shape(geometry)
            geom_wkt = geom_shape.wkt

            # Query schools within buffer
            query = text("""
                SELECT
                    COALESCE(e.name, e.name_en, 'School') as name,
                    e.amenity,
                    ST_X(ST_Centroid(e.geom)) as lon,
                    ST_Y(ST_Centroid(e.geom)) as lat,
                    ST_Distance(
                        e.geom::geography,
                        ST_GeomFromText(:geom_wkt, 4326)::geography
                    ) as distance_m
                FROM infrastructure.education_facilities e
                WHERE ST_DWithin(
                    e.geom::geography,
                    ST_GeomFromText(:geom_wkt, 4326)::geography,
                    :buffer_m
                )
                ORDER BY distance_m
                LIMIT 50
            """)

            result = db_session.execute(
                query,
                {"geom_wkt": geom_wkt, "buffer_m": buffer_meters}
            )

            schools = []
            for row in result:
                schools.append({
                    "name": row[0],
                    "amenity": row[1],
                    "lon": float(row[2]),
                    "lat": float(row[3]),
                    "distance_m": float(row[4])
                })

            return schools

        except Exception as e:
            logger.warning(f"Warning: Could not query schools: {e}")
            return []

    def query_poi_within_buffer(
        self,
        db_session,
        geometry: Dict[str, Any],
        buffer_meters: float = 100.0
    ) -> List[Dict[str, Any]]:
        """
        Query POI within buffer distance of geometry.

        Args:
            db_session: SQLAlchemy database session
            geometry: GeoJSON geometry dict
            buffer_meters: Buffer distance in meters (default: 100m)

        Returns:
            List of POI dicts with name, amenity, lon, lat, distance
        """
        try:
            geom_shape = shape(geometry)
            geom_wkt = geom_shape.wkt

            query = text("""
                SELECT
                    COALESCE(p.name, p.name_en, p.amenity, 'POI') as name,
                    COALESCE(p.amenity, p.shop, p.tourism, 'poi') as type,
                    ST_X(ST_Centroid(p.geom)) as lon,
                    ST_Y(ST_Centroid(p.geom)) as lat,
                    ST_Distance(
                        p.geom::geography,
                        ST_GeomFromText(:geom_wkt, 4326)::geography
                    ) as distance_m
                FROM infrastructure.poi p
                WHERE ST_DWithin(
                    p.geom::geography,
                    ST_GeomFromText(:geom_wkt, 4326)::geography,
                    :buffer_m
                )
                AND (p.amenity IS NOT NULL OR p.shop IS NOT NULL OR p.tourism IS NOT NULL)
                ORDER BY distance_m
                LIMIT 30
            """)

            result = db_session.execute(
                query,
                {"geom_wkt": geom_wkt, "buffer_m": buffer_meters}
            )

            poi_list = []
            for row in result:
                poi_list.append({
                    "name": row[0],
                    "type": row[1],
                    "lon": float(row[2]),
                    "lat": float(row[3]),
                    "distance_m": float(row[4])
                })

            return poi_list

        except Exception as e:
            logger.warning(f"Warning: Could not query POI: {e}")
            return []

    def query_roads_within_buffer(
        self,
        db_session,
        geometry: Dict[str, Any],
        buffer_meters: float = 100.0
    ) -> List[Dict[str, Any]]:
        """
        Query roads within buffer distance of geometry.

        Args:
            db_session: SQLAlchemy database session
            geometry: GeoJSON geometry dict
            buffer_meters: Buffer distance in meters (default: 100m)

        Returns:
            List of road dicts with highway type and geometry WKT
        """
        try:
            geom_shape = shape(geometry)
            geom_wkt = geom_shape.wkt

            query = text("""
                SELECT
                    r.highway,
                    ST_AsText(r.geom) as geom_wkt
                FROM infrastructure.road r
                WHERE ST_DWithin(
                    r.geom::geography,
                    ST_GeomFromText(:geom_wkt, 4326)::geography,
                    :buffer_m
                )
                AND r.highway IS NOT NULL
                LIMIT 100
            """)

            result = db_session.execute(
                query,
                {"geom_wkt": geom_wkt, "buffer_m": buffer_meters}
            )

            roads = []
            for row in result:
                roads.append({
                    "highway": row[0],
                    "geom_wkt": row[1]
                })

            return roads

        except Exception as e:
            logger.warning(f"Warning: Could not query roads: {e}")
            return []

    def query_rivers_within_buffer(
        self,
        db_session,
        geometry: Dict[str, Any],
        buffer_meters: float = 100.0
    ) -> List[Dict[str, Any]]:
        """
        Query rivers within buffer distance of geometry.

        Args:
            db_session: SQLAlchemy database session
            geometry: GeoJSON geometry dict
            buffer_meters: Buffer distance in meters (default: 100m)

        Returns:
            List of river dicts with name and geometry WKT
        """
        try:
            geom_shape = shape(geometry)
            geom_wkt = geom_shape.wkt

            query = text("""
                SELECT
                    COALESCE(NULLIF(TRIM(r.river_name), ''), 'River') as name,
                    ST_AsText(r.geom) as geom_wkt,
                    ST_X(ST_Centroid(r.geom)) as center_lon,
                    ST_Y(ST_Centroid(r.geom)) as center_lat
                FROM river.river_line r
                WHERE ST_DWithin(
                    r.geom::geography,
                    ST_GeomFromText(:geom_wkt, 4326)::geography,
                    :buffer_m
                )
                ORDER BY ST_Distance(
                    r.geom::geography,
                    ST_GeomFromText(:geom_wkt, 4326)::geography
                )
                LIMIT 20
            """)

            result = db_session.execute(
                query,
                {"geom_wkt": geom_wkt, "buffer_m": buffer_meters}
            )

            rivers = []
            for row in result:
                rivers.append({
                    "name": row[0],
                    "geom_wkt": row[1],
                    "center_lon": float(row[2]),
                    "center_lat": float(row[3])
                })

            return rivers

        except Exception as e:
            logger.warning(f"Warning: Could not query rivers: {e}")
            return []

    def query_ridges_within_buffer(
        self,
        db_session,
        geometry: Dict[str, Any],
        buffer_meters: float = 100.0
    ) -> List[Dict[str, Any]]:
        """
        Query ridges within buffer distance of geometry.

        Args:
            db_session: SQLAlchemy database session
            geometry: GeoJSON geometry dict
            buffer_meters: Buffer distance in meters (default: 100m)

        Returns:
            List of ridge dicts with name and geometry WKT
        """
        try:
            geom_shape = shape(geometry)
            geom_wkt = geom_shape.wkt

            query = text("""
                SELECT
                    COALESCE(NULLIF(TRIM(r.ridge_name), ''), 'Ridge') as name,
                    ST_AsText(r.geom) as geom_wkt,
                    ST_X(ST_Centroid(r.geom)) as center_lon,
                    ST_Y(ST_Centroid(r.geom)) as center_lat
                FROM river.ridge r
                WHERE ST_DWithin(
                    r.geom::geography,
                    ST_GeomFromText(:geom_wkt, 4326)::geography,
                    :buffer_m
                )
                ORDER BY ST_Distance(
                    r.geom::geography,
                    ST_GeomFromText(:geom_wkt, 4326)::geography
                )
                LIMIT 20
            """)

            result = db_session.execute(
                query,
                {"geom_wkt": geom_wkt, "buffer_m": buffer_meters}
            )

            ridges = []
            for row in result:
                ridges.append({
                    "name": row[0],
                    "geom_wkt": row[1],
                    "center_lon": float(row[2]),
                    "center_lat": float(row[3])
                })

            return ridges

        except Exception as e:
            logger.warning(f"Warning: Could not query ridges: {e}")
            return []

    def query_esa_boundary_intersecting(
        self,
        db_session,
        geometry: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Query ESA forest boundary intersecting with geometry.

        Args:
            db_session: SQLAlchemy database session
            geometry: GeoJSON geometry dict

        Returns:
            List of ESA boundary dicts with geometry WKT
        """
        try:
            geom_shape = shape(geometry)
            geom_wkt = geom_shape.wkt

            query = text("""
                SELECT
                    ST_AsText(e.geom) as geom_wkt
                FROM admin."esa_forest_Boundary" e
                WHERE ST_Intersects(
                    e.geom,
                    ST_GeomFromText(:geom_wkt, 4326)
                )
                LIMIT 10
            """)

            result = db_session.execute(
                query,
                {"geom_wkt": geom_wkt}
            )

            boundaries = []
            for row in result:
                boundaries.append({
                    "geom_wkt": row[0]
                })

            return boundaries

        except Exception as e:
            logger.warning(f"Warning: Could not query ESA boundary: {e}")
            return []

    # business: CFMG — boundary map with OSM basemap, schools, POI, roads, rivers on all management plans
    def generate_boundary_map(
        self,
        geometry: Dict[str, Any],
        forest_name: str = 'Forest Boundary',
        orientation: str = 'auto',
        output_path: Optional[str] = None,
        db_session = None,
        show_schools: bool = True,
        show_poi: bool = True,
        show_roads: bool = True,
        show_rivers: bool = True,
        show_ridges: bool = True,
        show_esa_boundary: bool = True,
        buffer_m: float = 100.0
    ) -> io.BytesIO:
        """
        Generate a boundary map from GeoJSON geometry with OSM basemap.

        Args:
            geometry: GeoJSON dict with type and coordinates
            forest_name: Name of the forest for title
            orientation: 'auto' (recommended), 'portrait', or 'landscape'
                        'auto' determines orientation based on extent proportions
            output_path: Optional file path to save

        Returns:
            BytesIO buffer with PNG data
        """
        # Auto-detect orientation based on extent proportions
        if orientation == 'auto':
            geom_shape = shape(geometry)
            bounds = geom_shape.bounds  # (minx, miny, maxx, maxy)
            width = bounds[2] - bounds[0]
            height = bounds[3] - bounds[1]
            aspect_ratio = width / height if height > 0 else 1.0

            # Determine orientation based on aspect ratio
            if 0.85 <= aspect_ratio <= 1.15:
                # Nearly square - use portrait (more paper-efficient)
                orientation = 'portrait'
            elif aspect_ratio > 1.15:
                # Wider than tall - use landscape
                orientation = 'landscape'
            else:
                # Taller than wide - use portrait
                orientation = 'portrait'

        # Create figure
        fig, ax = self.create_figure(
            orientation=orientation,
            title=f'{forest_name} - Boundary Map',
            add_border=True
        )

        # Convert GeoJSON to Shapely geometry (stay in WGS84)
        geom_shape = shape(geometry)

        # Extract coordinates from GeoJSON
        geom_type = geometry.get('type', '')
        coords = geometry.get('coordinates', [])

        # Handle different geometry types
        if geom_type == 'Polygon':
            polygons = [coords]
        elif geom_type == 'MultiPolygon':
            polygons = coords
        else:
            raise ValueError(f"Unsupported geometry type: {geom_type}")

        # Get WGS84 bounds
        bounds = geom_shape.bounds  # (minx, miny, maxx, maxy)
        min_x, min_y, max_x, max_y = bounds
        min_x_wgs, min_y_wgs, max_x_wgs, max_y_wgs = min_x, min_y, max_x, max_y

        # Plot boundary in WGS84 coordinates
        if geom_shape.geom_type == 'Polygon':
            polys_to_plot = [geom_shape]
        else:  # MultiPolygon
            polys_to_plot = list(geom_shape.geoms)

        for poly in polys_to_plot:
            # Exterior ring
            x, y = poly.exterior.xy
            ax.plot(x, y, color='#059669', linewidth=3, label='Forest Boundary', zorder=10)
            ax.fill(x, y, color='#34d399', alpha=0.4, zorder=9)

            # Interior rings (holes)
            for interior in poly.interiors:
                x, y = interior.xy
                ax.plot(x, y, 'r-', linewidth=1.5, zorder=10)
                ax.fill(x, y, color='white', alpha=0.8, zorder=9)

        # Compute snapped grid and set axis limits (replaces 15% padding)
        blon_lines, blon_labels, blon_start, blon_end = compute_snapped_grid(min_x, max_x)
        blat_lines, blat_labels, blat_start, blat_end = compute_snapped_grid(min_y, max_y)
        ax.set_xlim(blon_start, blon_end)
        ax.set_ylim(blat_start, blat_end)

        # Add OpenStreetMap basemap with timeout (5 seconds)
        basemap_success = self.add_basemap_with_timeout(
            ax,
            crs='EPSG:4326',  # Our data is in WGS84
            timeout=5,  # 5 second timeout for fast failure
            alpha=0.7,  # Semi-transparent to see our boundary clearly
            zorder=1  # Behind our boundary
        )

        if not basemap_success:
            # Add a simple background color if basemap fails
            ax.set_facecolor('#f0f0f0')
            logger.info("Basemap failed - using plain background")

        # Query and plot schools within buffer
        schools = []
        if show_schools and db_session is not None:
            schools = self.query_schools_within_buffer(db_session, geometry, buffer_m)
            if schools:
                school_lons = [s['lon'] for s in schools]
                school_lats = [s['lat'] for s in schools]

                # Plot school markers (red triangles)
                ax.scatter(
                    school_lons, school_lats,
                    marker='^',
                    s=100,
                    c='red',
                    edgecolors='darkred',
                    linewidths=1.5,
                    zorder=20,
                    label='Schools'
                )

                # Add school labels (offset slightly to avoid overlap with markers)
                # why: labels offset from centroid to avoid overlap
                for school in schools:
                    # Only label schools with names (not "School")
                    if school['name'] and school['name'] != 'School':
                        ax.annotate(
                            school['name'],
                            xy=(school['lon'], school['lat']),
                            xytext=(5, 5),  # Offset 5 points right and up
                            textcoords='offset points',
                            fontsize=7,
                            color='darkred',
                            fontweight='bold',
                            bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.8, edgecolor='darkred'),
                            zorder=21
                        )

        # Query and plot POI within buffer
        if show_poi and db_session is not None:
            poi_list = self.query_poi_within_buffer(db_session, geometry, buffer_m)
            if poi_list:
                poi_lons = [p['lon'] for p in poi_list]
                poi_lats = [p['lat'] for p in poi_list]

                # Plot POI markers (orange diamonds)
                ax.scatter(
                    poi_lons, poi_lats,
                    marker='D',
                    s=60,
                    c='orange',
                    edgecolors='darkorange',
                    linewidths=1,
                    zorder=19,
                    label='POI'
                )

                # Add POI labels (only for named POI)
                for poi in poi_list:
                    if poi['name'] and poi['name'] not in ['POI', 'poi']:
                        ax.annotate(
                            poi['name'],
                            xy=(poi['lon'], poi['lat']),
                            xytext=(5, -5),  # Offset differently from schools
                            textcoords='offset points',
                            fontsize=6,
                            color='darkorange',
                            bbox=dict(boxstyle='round,pad=0.2', facecolor='white', alpha=0.7, edgecolor='darkorange'),
                            zorder=19
                        )

        # Query and plot roads within buffer (NO LABELS per user requirement)
        if show_roads and db_session is not None:
            roads = self.query_roads_within_buffer(db_session, geometry, buffer_m)
            if roads:
                for road in roads:
                    try:
                        from shapely import wkt
                        road_geom = wkt.loads(road['geom_wkt'])

                        # Different colors by highway type
                        if road['highway'] in ['primary', 'secondary', 'tertiary']:
                            color = '#FF6B6B'  # Red for major roads
                            width = 2
                        elif road['highway'] in ['residential', 'living_street']:
                            color = '#95A5A6'  # Gray for residential
                            width = 1
                        else:
                            color = '#BDC3C7'  # Light gray for paths
                            width = 0.8

                        if road_geom.geom_type == 'LineString':
                            x, y = road_geom.xy
                            ax.plot(x, y, color=color, linewidth=width, alpha=0.6, zorder=5)
                        elif road_geom.geom_type == 'MultiLineString':
                            for line in road_geom.geoms:
                                x, y = line.xy
                                ax.plot(x, y, color=color, linewidth=width, alpha=0.6, zorder=5)
                    except Exception:
                        report_dropped(
                            logger, "road",
                            "it will be missing from the map",
                        )
                        continue  # Skip problematic geometries

                # Add roads to legend (single entry, no individual labels)
                ax.plot([], [], color='#FF6B6B', linewidth=2, alpha=0.6, label='Roads')

        # Query and plot rivers within buffer (WITH LABELS - user said "crucial")
        if show_rivers and db_session is not None:
            rivers = self.query_rivers_within_buffer(db_session, geometry, buffer_m)
            if rivers:
                for river in rivers:
                    try:
                        from shapely import wkt
                        river_geom = wkt.loads(river['geom_wkt'])

                        # Blue lines for rivers
                        if river_geom.geom_type == 'LineString':
                            x, y = river_geom.xy
                            ax.plot(x, y, color='#3498DB', linewidth=1.5, alpha=0.8, zorder=6)
                        elif river_geom.geom_type == 'MultiLineString':
                            for line in river_geom.geoms:
                                x, y = line.xy
                                ax.plot(x, y, color='#3498DB', linewidth=1.5, alpha=0.8, zorder=6)

                        # Label rivers (user requirement: "crucial")
                        if river['name'] and river['name'] != 'River':
                            ax.annotate(
                                river['name'],
                                xy=(river['center_lon'], river['center_lat']),
                                xytext=(0, -8),
                                textcoords='offset points',
                                fontsize=6,
                                color='#2874A6',
                                fontweight='bold',
                                style='italic',
                                bbox=dict(boxstyle='round,pad=0.2', facecolor='white', alpha=0.7, edgecolor='#2874A6'),
                                zorder=18
                            )
                    except Exception:
                        report_dropped(
                            logger, "river",
                            "it will be missing from the map, unlabelled as well as undrawn",
                        )
                        continue

                # Add rivers to legend
                ax.plot([], [], color='#3498DB', linewidth=1.5, alpha=0.8, label='Rivers')

        # Query and plot ridges within buffer (WITH LABELS - user said "crucial")
        if show_ridges and db_session is not None:
            ridges = self.query_ridges_within_buffer(db_session, geometry, buffer_m)
            if ridges:
                for ridge in ridges:
                    try:
                        from shapely import wkt
                        ridge_geom = wkt.loads(ridge['geom_wkt'])

                        # Brown lines for ridges
                        if ridge_geom.geom_type == 'LineString':
                            x, y = ridge_geom.xy
                            ax.plot(x, y, color='#8B4513', linewidth=1.2, alpha=0.7, linestyle='--', zorder=6)
                        elif ridge_geom.geom_type == 'MultiLineString':
                            for line in ridge_geom.geoms:
                                x, y = line.xy
                                ax.plot(x, y, color='#8B4513', linewidth=1.2, alpha=0.7, linestyle='--', zorder=6)

                        # Label ridges (user requirement: "crucial")
                        if ridge['name'] and ridge['name'] != 'Ridge':
                            ax.annotate(
                                ridge['name'],
                                xy=(ridge['center_lon'], ridge['center_lat']),
                                xytext=(0, 8),
                                textcoords='offset points',
                                fontsize=6,
                                color='#654321',
                                fontweight='bold',
                                bbox=dict(boxstyle='round,pad=0.2', facecolor='white', alpha=0.7, edgecolor='#654321'),
                                zorder=18
                            )
                    except Exception:
                        report_dropped(
                            logger, "ridge",
                            "it will be missing from the map, unlabelled as well as undrawn",
                        )
                        continue

                # Add ridges to legend
                ax.plot([], [], color='#8B4513', linewidth=1.2, alpha=0.7, linestyle='--', label='Ridges')

        # Query and plot ESA forest boundary (reference boundary)
        if show_esa_boundary and db_session is not None:
            esa_boundaries = self.query_esa_boundary_intersecting(db_session, geometry)
            if esa_boundaries:
                for esa_bound in esa_boundaries:
                    try:
                        from shapely import wkt
                        esa_geom = wkt.loads(esa_bound['geom_wkt'])

                        # Dashed purple line for ESA boundary
                        if esa_geom.geom_type == 'LineString':
                            x, y = esa_geom.xy
                            ax.plot(x, y, color='#9B59B6', linewidth=2, alpha=0.7, linestyle=':', zorder=7)
                        elif esa_geom.geom_type == 'MultiLineString':
                            for line in esa_geom.geoms:
                                x, y = line.xy
                                ax.plot(x, y, color='#9B59B6', linewidth=2, alpha=0.7, linestyle=':', zorder=7)
                    except Exception:
                        report_dropped(
                            logger, "ESA boundary",
                            "it will be missing from the map",
                        )
                        continue

                # Add ESA boundary to legend
                ax.plot([], [], color='#9B59B6', linewidth=2, alpha=0.7, linestyle=':', label='ESA Boundary')

        # Add snapped grid (on top of basemap, white for visibility)
        apply_snapped_ticks(ax, blon_lines, blat_lines, blon_labels, blat_labels,
                            grid_kwargs={'alpha': 0.4, 'color': 'white'})

        # Equal aspect ratio
        ax.set_aspect('equal', adjustable='box')

        # Add north arrow (outside map area, top-right)
        self.add_north_arrow(fig, ax)

        # Add metadata (bottom center, outside map)
        fig.text(
            0.5, 0.03,
            f'A5 {orientation.capitalize()} | 300 DPI | WGS84 (EPSG:4326)',
            ha='center',
            va='bottom',
            fontsize=6,
            style='italic',
            color='gray'
        )

        # Remove duplicate legend entries and place outside map (bottom-right)
        handles, labels = ax.get_legend_handles_labels()
        by_label = dict(zip(labels, handles))
        # Use figure.legend to place outside axes
        fig.legend(
            by_label.values(),
            by_label.keys(),
            loc='lower right',
            bbox_to_anchor=(0.90, 0.12),
            fontsize=8,
            frameon=True,
            fancybox=True,
            shadow=True
        )

        # Save to file if path provided
        if output_path:
            self.save_to_file(fig, output_path)

        # Save to buffer
        buffer = self.save_to_buffer(fig)

        # Close figure
        self.close_figure(fig)

        return buffer

    # business: CFMG — slope classification map (4 colour-coded categories) for management plan reporting
    def generate_slope_map(
        self,
        geometry: Dict[str, Any],
        db_session,
        forest_name: str = 'Forest Boundary',
        orientation: str = 'auto',
        output_path: Optional[str] = None
    ) -> io.BytesIO:
        """
        Generate a slope map from raster data with color-coded slope classes.

        Slope Classes (CATEGORICAL CODES from rasters.slope_regulation):
        - Code 1: 1-19° (Flat/Normal) → Green
        - Code 2: 19-31° (Slope) → Yellow
        - Code 3: 31-45° (Steep) → Orange
        - Code 4: >45° (Very Steep) → Red

        Args:
            geometry: GeoJSON dict with type and coordinates
            db_session: SQLAlchemy database session for raster queries
            forest_name: Name of the forest for title
            orientation: 'auto', 'portrait', or 'landscape'
            output_path: Optional file path to save

        Returns:
            BytesIO buffer with PNG data
        """
        # Auto-detect orientation based on extent proportions
        if orientation == 'auto':
            geom_shape = shape(geometry)
            bounds = geom_shape.bounds
            width = bounds[2] - bounds[0]
            height = bounds[3] - bounds[1]
            aspect_ratio = width / height if height > 0 else 1.0

            if 0.85 <= aspect_ratio <= 1.15:
                orientation = 'portrait'
            elif aspect_ratio > 1.15:
                orientation = 'landscape'
            else:
                orientation = 'portrait'

        # Create figure
        fig, ax = self.create_figure(
            orientation=orientation,
            title=f'{forest_name} - Slope Map',
            add_border=True
        )

        # Convert geometry to WKT and Shapely
        geom_shape = shape(geometry)
        geom_wkt = geom_shape.wkt
        bounds = geom_shape.bounds
        min_x, min_y, max_x, max_y = bounds

        # Query slope raster data within boundary
        # rasters.slope_regulation stores CATEGORICAL CODES (1-4), not degree
        # values (8BUI, nodata 0; class bands documented in core/constants.py)
        try:
            query = text("""
                WITH slope_pixels AS (
                    SELECT
                        (ST_PixelAsPolygons(ST_Clip(rast, 1, ST_GeomFromText(:geom_wkt, 4326)))).val as slope_code,
                        (ST_PixelAsPolygons(ST_Clip(rast, 1, ST_GeomFromText(:geom_wkt, 4326)))).geom as geom
                    FROM rasters.slope_regulation
                    WHERE ST_Intersects(rast, ST_GeomFromText(:geom_wkt, 4326))
                )
                SELECT
                    slope_code,
                    ST_AsText(geom) as geom_wkt
                FROM slope_pixels
                WHERE slope_code IS NOT NULL AND slope_code > 0
            """)

            result = db_session.execute(query, {"geom_wkt": geom_wkt})

            # Collect pixels and classify by categorical code
            pixels = []
            for row in result:
                slope_code = int(row[0])
                pixel_geom_wkt = row[1]

                if slope_code == 1:
                    slope_class = 'Flat/Normal (1-19\u00b0)'
                    color = '#2ECC71'  # Green
                elif slope_code == 2:
                    slope_class = 'Slope (19-31\u00b0)'
                    color = '#F1C40F'  # Yellow
                elif slope_code == 3:
                    slope_class = 'Steep (31-45\u00b0)'
                    color = '#E67E22'  # Orange
                elif slope_code == 4:
                    slope_class = 'Very Steep (>45\u00b0)'
                    color = '#E74C3C'  # Red
                else:
                    continue

                pixels.append({
                    'code': slope_code,
                    'class': slope_class,
                    'color': color,
                    'geom_wkt': pixel_geom_wkt
                })

            logger.info(f"Loaded {len(pixels)} slope pixels")

            # Plot pixels
            if pixels:
                for pixel in pixels:
                    try:
                        pixel_geom = wkt.loads(pixel['geom_wkt'])
                        if pixel_geom.geom_type == 'Polygon':
                            x, y = pixel_geom.exterior.xy
                            ax.fill(x, y, color=pixel['color'], edgecolor='none', alpha=0.8, zorder=5)
                    except Exception:
                        report_dropped(
                            logger, "raster pixel",
                            "that cell is left blank, so the map understates the mapped area",
                        )
                        continue

        except Exception as e:
            logger.warning(f"Warning: Could not load slope raster: {e}")
            # Draw empty map with boundary
            pass

        # Plot forest boundary outline on top
        if geom_shape.geom_type == 'Polygon':
            polys_to_plot = [geom_shape]
        else:
            polys_to_plot = list(geom_shape.geoms)

        for poly in polys_to_plot:
            x, y = poly.exterior.xy
            ax.plot(x, y, color='black', linewidth=2, label='Forest Boundary', zorder=10)

        # Snapped grid with clean coordinate labels
        self._snap_axis(ax, min_x, max_x, min_y, max_y)

        # Equal aspect ratio
        ax.set_aspect('equal', adjustable='box')

        # Add north arrow
        self.add_north_arrow(fig, ax)

        # Add metadata
        fig.text(
            0.5, 0.03,
            f'A5 {orientation.capitalize()} | 300 DPI | WGS84 (EPSG:4326)',
            ha='center',
            va='bottom',
            fontsize=6,
            style='italic',
            color='gray'
        )

        # Add slope class legend
        from matplotlib.patches import Patch
        legend_elements = [
            Patch(facecolor='#2ECC71', edgecolor='black', label='Flat/Normal (1-19\u00b0)'),
            Patch(facecolor='#F1C40F', edgecolor='black', label='Slope (19-31\u00b0)'),
            Patch(facecolor='#E67E22', edgecolor='black', label='Steep (31-45\u00b0)'),
            Patch(facecolor='#E74C3C', edgecolor='black', label='Very Steep (>45\u00b0)'),
        ]
        fig.legend(
            handles=legend_elements,
            loc='lower right',
            bbox_to_anchor=(0.90, 0.12),
            fontsize=7,
            frameon=True,
            fancybox=True,
            shadow=True,
            title='Slope Classes'
        )

        # Save to file if path provided
        if output_path:
            self.save_to_file(fig, output_path)

        # Save to buffer
        buffer = self.save_to_buffer(fig)

        # Close figure
        self.close_figure(fig)

        return buffer

    # business: CFMG — ESA WorldCover land cover classes (10-100) mapped to management plan colours
    def generate_landcover_map(
        self,
        geometry: Dict[str, Any],
        db_session,
        forest_name: str = 'Forest Boundary',
        orientation: str = 'auto',
        output_path: Optional[str] = None
    ) -> io.BytesIO:
        """
        Generate a land cover map from ESA WorldCover raster data.

        Land Cover Classes (ESA WorldCover v100):
        - 10: Tree cover (dark green)
        - 20: Shrubland (olive)
        - 30: Grassland (light green)
        - 40: Cropland (yellow)
        - 50: Built-up (red)
        - 60: Bare/sparse vegetation (tan)
        - 70: Snow and ice (white)
        - 80: Permanent water bodies (blue)
        - 90: Herbaceous wetland (cyan)
        - 100: Mangroves (teal)

        Args:
            geometry: GeoJSON dict with type and coordinates
            db_session: SQLAlchemy database session for raster queries
            forest_name: Name of the forest for title
            orientation: 'auto', 'portrait', or 'landscape'
            output_path: Optional file path to save

        Returns:
            BytesIO buffer with PNG data
        """
        # Auto-detect orientation
        if orientation == 'auto':
            geom_shape = shape(geometry)
            bounds = geom_shape.bounds
            width = bounds[2] - bounds[0]
            height = bounds[3] - bounds[1]
            aspect_ratio = width / height if height > 0 else 1.0

            if 0.85 <= aspect_ratio <= 1.15:
                orientation = 'portrait'
            elif aspect_ratio > 1.15:
                orientation = 'landscape'
            else:
                orientation = 'portrait'

        # Create figure
        fig, ax = self.create_figure(
            orientation=orientation,
            title=f'{forest_name} - Land Cover Map',
            add_border=True
        )

        # Convert geometry
        geom_shape = shape(geometry)
        geom_wkt = geom_shape.wkt
        bounds = geom_shape.bounds
        min_x, min_y, max_x, max_y = bounds

        # Define ESA WorldCover classification
        landcover_classes = {
            10: {'name': 'Tree cover', 'color': '#006400'},  # Dark green
            20: {'name': 'Shrubland', 'color': '#FFBB22'},   # Olive/gold
            30: {'name': 'Grassland', 'color': '#FFFF4C'},   # Light yellow
            40: {'name': 'Cropland', 'color': '#F096FF'},    # Pink
            50: {'name': 'Built-up', 'color': '#FA0000'},    # Red
            60: {'name': 'Bare/sparse vegetation', 'color': '#B4B4B4'},  # Gray
            70: {'name': 'Snow and ice', 'color': '#F0F0F0'},  # White
            80: {'name': 'Water', 'color': '#0064C8'},       # Blue
            90: {'name': 'Herbaceous wetland', 'color': '#0096A0'},  # Cyan
            100: {'name': 'Mangroves', 'color': '#00CF75'},  # Teal
        }

        # Query land cover raster data
        try:
            query = text("""
                WITH landcover_pixels AS (
                    SELECT
                        (ST_PixelAsPolygons(ST_Clip(rast, 1, ST_GeomFromText(:geom_wkt, 4326)))).val as lc_class,
                        (ST_PixelAsPolygons(ST_Clip(rast, 1, ST_GeomFromText(:geom_wkt, 4326)))).geom as geom
                    FROM rasters.esa_world_cover
                    WHERE ST_Intersects(rast, ST_GeomFromText(:geom_wkt, 4326))
                )
                SELECT
                    lc_class,
                    ST_AsText(geom) as geom_wkt
                FROM landcover_pixels
                WHERE lc_class IS NOT NULL AND lc_class > 0
            """)

            result = db_session.execute(query, {"geom_wkt": geom_wkt})

            # Collect pixels and classify
            pixels = []
            class_counts = {}

            for row in result:
                lc_value = int(row[0])
                pixel_geom_wkt = row[1]

                if lc_value in landcover_classes:
                    lc_info = landcover_classes[lc_value]
                    pixels.append({
                        'class': lc_value,
                        'name': lc_info['name'],
                        'color': lc_info['color'],
                        'geom_wkt': pixel_geom_wkt
                    })
                    class_counts[lc_value] = class_counts.get(lc_value, 0) + 1

            logger.info(f"Loaded {len(pixels)} land cover pixels")
            logger.info(f"Classes found: {list(class_counts.keys())}")

            # Plot pixels
            if pixels:
                for pixel in pixels:
                    try:
                        pixel_geom = wkt.loads(pixel['geom_wkt'])
                        if pixel_geom.geom_type == 'Polygon':
                            x, y = pixel_geom.exterior.xy
                            ax.fill(x, y, color=pixel['color'], edgecolor='none', alpha=0.9, zorder=5)
                    except Exception:
                        report_dropped(
                            logger, "raster pixel",
                            "that cell is left blank, so the map understates the mapped area",
                        )
                        continue

        except Exception as e:
            logger.warning(f" Could not load land cover raster: {e}")
            logger.exception("Failed to load land cover raster")

        # Plot forest boundary outline
        if geom_shape.geom_type == 'Polygon':
            polys_to_plot = [geom_shape]
        else:
            polys_to_plot = list(geom_shape.geoms)

        for poly in polys_to_plot:
            x, y = poly.exterior.xy
            ax.plot(x, y, color='black', linewidth=2, label='Forest Boundary', zorder=10)

        # Snapped grid with clean coordinate labels
        self._snap_axis(ax, min_x, max_x, min_y, max_y)
        ax.set_aspect('equal', adjustable='box')

        # Add north arrow
        self.add_north_arrow(fig, ax)

        # Add metadata
        fig.text(
            0.5, 0.03,
            f'A5 {orientation.capitalize()} | 300 DPI | ESA WorldCover v100',
            ha='center',
            va='bottom',
            fontsize=6,
            style='italic',
            color='gray'
        )

        # Add land cover legend (only classes present in data)
        from matplotlib.patches import Patch
        legend_elements = []
        if pixels:
            # Get unique classes present
            present_classes = sorted(set(p['class'] for p in pixels))
            for lc_class in present_classes:
                if lc_class in landcover_classes:
                    info = landcover_classes[lc_class]
                    legend_elements.append(
                        Patch(facecolor=info['color'], edgecolor='black', label=info['name'])
                    )

        if legend_elements:
            fig.legend(
                handles=legend_elements,
                loc='lower right',
                bbox_to_anchor=(0.90, 0.12),
                fontsize=7,
                frameon=True,
                fancybox=True,
                shadow=True,
                title='Land Cover'
            )

        # Save to file
        if output_path:
            self.save_to_file(fig, output_path)

        # Save to buffer
        buffer = self.save_to_buffer(fig)

        # Close figure
        self.close_figure(fig)

        return buffer

    # business: CFMG — aspect map (N/E/S/W quadrants) for microclimate and regeneration planning
    def generate_aspect_map(
        self,
        geometry: Dict[str, Any],
        db_session,
        forest_name: str = 'Forest Boundary',
        orientation: str = 'auto',
        output_path: Optional[str] = None
    ) -> io.BytesIO:
        """
        Generate an aspect map from raster data with pre-classified aspect directions.

        Aspect Classes (temperature-based colors - N=cold, S=warm):
        - 0: Flat (slope < 2°) - Gray (neutral)
        - 1: N (337.5° - 22.5°) - Dark Blue (coldest - least sunlight)
        - 2: NE (22.5° - 67.5°) - Blue (cool - morning sun)
        - 3: E (67.5° - 112.5°) - Cyan (cool-moderate - morning sun)
        - 4: SE (112.5° - 157.5°) - Yellow (warm-moderate - morning-midday sun)
        - 5: S (157.5° - 202.5°) - Red (warmest - maximum sunlight)
        - 6: SW (202.5° - 247.5°) - Orange (warm - afternoon sun)
        - 7: W (247.5° - 292.5°) - Light Orange (warm-moderate - afternoon sun)
        - 8: NW (292.5° - 337.5°) - Purple (cool - evening)

        Args:
            geometry: GeoJSON dict with type and coordinates
            db_session: SQLAlchemy database session for raster queries
            forest_name: Name of the forest for title
            orientation: 'auto', 'portrait', or 'landscape'
            output_path: Optional file path to save

        Returns:
            BytesIO buffer with PNG data
        """
        # Auto-detect orientation based on extent proportions
        if orientation == 'auto':
            geom_shape = shape(geometry)
            bounds = geom_shape.bounds
            width = bounds[2] - bounds[0]
            height = bounds[3] - bounds[1]
            aspect_ratio = width / height if height > 0 else 1.0

            if 0.85 <= aspect_ratio <= 1.15:
                orientation = 'portrait'
            elif aspect_ratio > 1.15:
                orientation = 'landscape'
            else:
                orientation = 'portrait'

        # Create figure
        fig, ax = self.create_figure(
            orientation=orientation,
            title=f'{forest_name} - Aspect Map',
            add_border=True
        )

        # Convert geometry to WKT and Shapely
        geom_shape = shape(geometry)
        geom_wkt = geom_shape.wkt
        bounds = geom_shape.bounds
        min_x, min_y, max_x, max_y = bounds

        # Define aspect classes with colors (temperature-based: N=cold/blue, S=warm/red)
        aspect_classes = {
            0: {'name': 'Flat', 'color': '#CCCCCC'},        # Gray (neutral)
            1: {'name': 'N', 'color': '#1A5490'},           # Dark Blue (coldest - least sun)
            2: {'name': 'NE', 'color': '#3498DB'},          # Blue (cool - morning sun)
            3: {'name': 'E', 'color': '#1ABC9C'},           # Cyan (cool-moderate - morning sun)
            4: {'name': 'SE', 'color': '#F1C40F'},          # Yellow (warm-moderate - morning-midday sun)
            5: {'name': 'S', 'color': '#E74C3C'},           # Red (warmest - most sun)
            6: {'name': 'SW', 'color': '#E67E22'},          # Orange (warm - afternoon sun)
            7: {'name': 'W', 'color': '#F39C12'},           # Light Orange (warm-moderate - afternoon sun)
            8: {'name': 'NW', 'color': '#9B59B6'},          # Purple (cool - evening)
        }

        # Query aspect raster data within boundary
        # The aspect raster is already classified (0-8), just display it
        try:
            query = text("""
                WITH aspect_pixels AS (
                    SELECT
                        (ST_PixelAsPolygons(ST_Clip(rast, 1, ST_GeomFromText(:geom_wkt, 4326)))).val as aspect_class,
                        (ST_PixelAsPolygons(ST_Clip(rast, 1, ST_GeomFromText(:geom_wkt, 4326)))).geom as geom
                    FROM rasters.aspect
                    WHERE ST_Intersects(rast, ST_GeomFromText(:geom_wkt, 4326))
                )
                SELECT
                    aspect_class,
                    ST_AsText(geom) as geom_wkt
                FROM aspect_pixels
                WHERE aspect_class IS NOT NULL AND aspect_class >= 0 AND aspect_class <= 8
            """)

            result = db_session.execute(query, {"geom_wkt": geom_wkt})

            # Collect pixels
            pixels = []
            class_counts = {}

            for row in result:
                aspect_val = int(row[0])
                pixel_geom_wkt = row[1]

                if aspect_val in aspect_classes:
                    aspect_info = aspect_classes[aspect_val]
                    pixels.append({
                        'class': aspect_val,
                        'name': aspect_info['name'],
                        'color': aspect_info['color'],
                        'geom_wkt': pixel_geom_wkt
                    })
                    class_counts[aspect_val] = class_counts.get(aspect_val, 0) + 1

            logger.info(f"Loaded {len(pixels)} aspect pixels")
            logger.info(f"Classes found: {list(class_counts.keys())}")

            # Plot pixels
            if pixels:
                for pixel in pixels:
                    try:
                        pixel_geom = wkt.loads(pixel['geom_wkt'])
                        if pixel_geom.geom_type == 'Polygon':
                            x, y = pixel_geom.exterior.xy
                            ax.fill(x, y, color=pixel['color'], edgecolor='none', alpha=0.85, zorder=5)
                    except Exception:
                        report_dropped(
                            logger, "raster pixel",
                            "that cell is left blank, so the map understates the mapped area",
                        )
                        continue

        except Exception as e:
            logger.warning(f" Could not load aspect raster: {e}")
            logger.exception("Failed to load aspect raster")

        # Plot forest boundary outline on top
        if geom_shape.geom_type == 'Polygon':
            polys_to_plot = [geom_shape]
        else:
            polys_to_plot = list(geom_shape.geoms)

        for poly in polys_to_plot:
            x, y = poly.exterior.xy
            ax.plot(x, y, color='black', linewidth=2, label='Forest Boundary', zorder=10)

        # Snapped grid with clean coordinate labels
        self._snap_axis(ax, min_x, max_x, min_y, max_y)

        # Equal aspect ratio
        ax.set_aspect('equal', adjustable='box')

        # Add north arrow
        self.add_north_arrow(fig, ax)

        # Add metadata
        fig.text(
            0.5, 0.03,
            f'A5 {orientation.capitalize()} | 300 DPI | WGS84 (EPSG:4326)',
            ha='center',
            va='bottom',
            fontsize=6,
            style='italic',
            color='gray'
        )

        # Add aspect legend (only classes present in data)
        from matplotlib.patches import Patch
        legend_elements = []
        if pixels:
            # Get unique classes present
            present_classes = sorted(set(p['class'] for p in pixels))
            for aspect_class in present_classes:
                if aspect_class in aspect_classes:
                    info = aspect_classes[aspect_class]
                    legend_elements.append(
                        Patch(facecolor=info['color'], edgecolor='black', label=info['name'])
                    )

        if legend_elements:
            fig.legend(
                handles=legend_elements,
                loc='lower right',
                bbox_to_anchor=(0.90, 0.12),
                fontsize=7,
                frameon=True,
                fancybox=True,
                shadow=True,
                title='Aspect Classes'
            )

        # Save to file if path provided
        if output_path:
            self.save_to_file(fig, output_path)

        # Save to buffer
        buffer = self.save_to_buffer(fig)

        # Close figure
        self.close_figure(fig)

        return buffer


    # business: CFMG — topographic basemap with contours for operational planning
    def generate_topographic_map(
        self,
        geometry: Dict[str, Any],
        db_session,
        forest_name: str = 'Forest Boundary',
        orientation: str = 'auto',
        output_path: Optional[str] = None
    ) -> io.BytesIO:
        """
        Generate a topographic map with elevation contours.

        Args:
            geometry: GeoJSON dict with type and coordinates
            db_session: SQLAlchemy database session for raster queries
            forest_name: Name of the forest for title
            orientation: 'auto', 'portrait', or 'landscape'
            output_path: Optional file path to save

        Returns:
            BytesIO buffer with PNG data
        """
        # Auto-detect orientation
        if orientation == 'auto':
            geom_shape = shape(geometry)
            bounds = geom_shape.bounds
            width = bounds[2] - bounds[0]
            height = bounds[3] - bounds[1]
            aspect_ratio = width / height if height > 0 else 1.0

            if 0.85 <= aspect_ratio <= 1.15:
                orientation = 'portrait'
            elif aspect_ratio > 1.15:
                orientation = 'landscape'
            else:
                orientation = 'portrait'

        # Create figure
        fig, ax = self.create_figure(
            orientation=orientation,
            title=f'{forest_name} - Topographic Map',
            add_border=True
        )

        # Convert geometry
        geom_shape = shape(geometry)
        geom_wkt = geom_shape.wkt
        bounds = geom_shape.bounds
        min_x, min_y, max_x, max_y = bounds

        # Query DEM data for elevation
        try:
            query = text("""
                WITH dem_pixels AS (
                    SELECT
                        (ST_PixelAsPolygons(ST_Clip(rast, 1, ST_GeomFromText(:geom_wkt, 4326)))).val as elevation,
                        (ST_PixelAsPolygons(ST_Clip(rast, 1, ST_GeomFromText(:geom_wkt, 4326)))).geom as geom
                    FROM rasters.dem
                    WHERE ST_Intersects(rast, ST_GeomFromText(:geom_wkt, 4326))
                )
                SELECT
                    elevation,
                    ST_AsText(geom) as geom_wkt
                FROM dem_pixels
                WHERE elevation IS NOT NULL
            """)

            result = db_session.execute(query, {"geom_wkt": geom_wkt})

            # Collect elevation data
            pixels = []
            elevations = []

            for row in result:
                elev_val = float(row[0])
                pixel_geom_wkt = row[1]
                pixels.append({
                    'elevation': elev_val,
                    'geom_wkt': pixel_geom_wkt
                })
                elevations.append(elev_val)

            logger.info(f"Loaded {len(pixels)} elevation pixels")

            if elevations:
                min_elev = min(elevations)
                max_elev = max(elevations)
                logger.info(f"Elevation range: {min_elev:.1f}m to {max_elev:.1f}m")

                # Create color gradient from low (green) to high (brown)
                from matplotlib.colors import LinearSegmentedColormap
                colors = ['#2ECC71', '#F4D03F', '#E67E22', '#8B4513', '#FFFFFF']
                n_bins = 100
                cmap = LinearSegmentedColormap.from_list('elevation', colors, N=n_bins)

                # Plot pixels with elevation-based colors
                for pixel in pixels:
                    try:
                        pixel_geom = wkt.loads(pixel['geom_wkt'])
                        if pixel_geom.geom_type == 'Polygon':
                            # Normalize elevation to 0-1 range
                            norm_elev = (pixel['elevation'] - min_elev) / (max_elev - min_elev) if max_elev > min_elev else 0.5
                            color = cmap(norm_elev)

                            x, y = pixel_geom.exterior.xy
                            ax.fill(x, y, color=color, edgecolor='none', alpha=0.9, zorder=5)
                    except Exception:
                        report_dropped(
                            logger, "raster pixel",
                            "that cell is left blank, so the map understates the mapped area",
                        )
                        continue

                # Create contour lines
                # Calculate contour interval (approximately 5 contours)
                elev_range = max_elev - min_elev
                if elev_range > 0:
                    contour_interval = round(elev_range / 5, -1)  # Round to nearest 10
                    if contour_interval < 10:
                        contour_interval = 10

                    # Plot contour lines at intervals
                    contour_levels = []
                    level = int(min_elev / contour_interval) * contour_interval
                    while level <= max_elev:
                        if level >= min_elev:
                            contour_levels.append(level)
                        level += contour_interval

                    # Add contour line legend info
                    ax.plot([], [], color='brown', linewidth=1.5, linestyle='--',
                           label=f'Contours ({contour_interval}m interval)')

        except Exception as e:
            logger.warning(f" Could not load DEM raster: {e}")
            logger.exception("Failed to load DEM raster")

        # Plot forest boundary outline
        if geom_shape.geom_type == 'Polygon':
            polys_to_plot = [geom_shape]
        else:
            polys_to_plot = list(geom_shape.geoms)

        for poly in polys_to_plot:
            x, y = poly.exterior.xy
            ax.plot(x, y, color='black', linewidth=2, label='Forest Boundary', zorder=10)

        # Snapped grid with clean coordinate labels
        self._snap_axis(ax, min_x, max_x, min_y, max_y)
        ax.set_aspect('equal', adjustable='box')

        # Add north arrow
        self.add_north_arrow(fig, ax)

        # Add metadata
        fig.text(
            0.5, 0.03,
            f'A5 {orientation.capitalize()} | 300 DPI | Elevation from DEM',
            ha='center',
            va='bottom',
            fontsize=6,
            style='italic',
            color='gray'
        )

        # Add simple legend
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            fig.legend(
                handles, labels,
                loc='lower right',
                bbox_to_anchor=(0.90, 0.12),
                fontsize=7,
                frameon=True,
                fancybox=True,
                shadow=True,
                title='Map Elements'
            )

        # Save to file
        if output_path:
            self.save_to_file(fig, output_path)

        # Save to buffer
        buffer = self.save_to_buffer(fig)

        # Close figure
        self.close_figure(fig)

        return buffer


    # business: CFMG — forest type classification map (Tropical/Lower Temperate/Sal/Pine)
    def generate_forest_type_map(
        self,
        geometry: Dict[str, Any],
        db_session,
        forest_name: str = 'Forest Boundary',
        orientation: str = 'auto',
        output_path: Optional[str] = None
    ) -> io.BytesIO:
        """
        Generate a forest type map showing species classification.

        Args:
            geometry: GeoJSON dict with type and coordinates
            db_session: SQLAlchemy database session for raster queries
            forest_name: Name of the forest for title
            orientation: 'auto', 'portrait', or 'landscape'
            output_path: Optional file path to save

        Returns:
            BytesIO buffer with PNG data
        """
        # Auto-detect orientation
        if orientation == 'auto':
            geom_shape = shape(geometry)
            bounds = geom_shape.bounds
            width = bounds[2] - bounds[0]
            height = bounds[3] - bounds[1]
            aspect_ratio = width / height if height > 0 else 1.0

            if 0.85 <= aspect_ratio <= 1.15:
                orientation = 'portrait'
            elif aspect_ratio > 1.15:
                orientation = 'landscape'
            else:
                orientation = 'portrait'

        # Create figure
        fig, ax = self.create_figure(
            orientation=orientation,
            title=f'{forest_name} - Forest Type Map',
            add_border=True
        )

        # Convert geometry
        geom_shape = shape(geometry)
        geom_wkt = geom_shape.wkt
        bounds = geom_shape.bounds
        min_x, min_y, max_x, max_y = bounds

        # Define forest type classification (Nepal species)
        forest_type_classes = {
            1: {'name': 'Sal (Shorea robusta)', 'color': '#228B22'},
            2: {'name': 'Chirpine (Pinus roxburghii)', 'color': '#90EE90'},
            3: {'name': 'Blue pine (Pinus wallichiana)', 'color': '#006400'},
            4: {'name': 'Fir (Abies spectabilis)', 'color': '#2F4F4F'},
            5: {'name': 'Oak (Quercus spp.)', 'color': '#8B4513'},
            6: {'name': 'Rhododendron (Rhododendron spp.)', 'color': '#FF69B4'},
            7: {'name': 'Mixed broadleaf', 'color': '#32CD32'},
            8: {'name': 'Riverine forest', 'color': '#87CEEB'},
            9: {'name': 'Subtropical mixed', 'color': '#9ACD32'},
            10: {'name': 'Temperate mixed', 'color': '#556B2F'},
            0: {'name': 'Non-forest', 'color': '#F0E68C'},
        }

        # Query forest type raster data
        try:
            query = text("""
                WITH forest_pixels AS (
                    SELECT
                        (ST_PixelAsPolygons(ST_Clip(rast, 1, ST_GeomFromText(:geom_wkt, 4326)))).val as forest_type,
                        (ST_PixelAsPolygons(ST_Clip(rast, 1, ST_GeomFromText(:geom_wkt, 4326)))).geom as geom
                    FROM rasters.forest_type
                    WHERE ST_Intersects(rast, ST_GeomFromText(:geom_wkt, 4326))
                )
                SELECT
                    forest_type,
                    ST_AsText(geom) as geom_wkt
                FROM forest_pixels
                WHERE forest_type IS NOT NULL
            """)

            result = db_session.execute(query, {"geom_wkt": geom_wkt})

            # Collect pixels
            pixels = []
            class_counts = {}

            for row in result:
                type_val = int(row[0])
                pixel_geom_wkt = row[1]

                if type_val in forest_type_classes:
                    type_info = forest_type_classes[type_val]
                    pixels.append({
                        'type': type_val,
                        'name': type_info['name'],
                        'color': type_info['color'],
                        'geom_wkt': pixel_geom_wkt
                    })
                    class_counts[type_val] = class_counts.get(type_val, 0) + 1

            logger.info(f"Loaded {len(pixels)} forest type pixels")
            logger.info(f"Types found: {list(class_counts.keys())}")

            # Plot pixels
            if pixels:
                for pixel in pixels:
                    try:
                        pixel_geom = wkt.loads(pixel['geom_wkt'])
                        if pixel_geom.geom_type == 'Polygon':
                            x, y = pixel_geom.exterior.xy
                            ax.fill(x, y, color=pixel['color'], edgecolor='none', alpha=0.85, zorder=5)
                    except Exception:
                        report_dropped(
                            logger, "raster pixel",
                            "that cell is left blank, so the map understates the mapped area",
                        )
                        continue

        except Exception as e:
            logger.warning(f" Could not load forest type raster: {e}")
            logger.exception("Failed to load forest type raster")

        # Plot forest boundary
        if geom_shape.geom_type == 'Polygon':
            polys_to_plot = [geom_shape]
        else:
            polys_to_plot = list(geom_shape.geoms)

        for poly in polys_to_plot:
            x, y = poly.exterior.xy
            ax.plot(x, y, color='black', linewidth=2, label='Forest Boundary', zorder=10)

        # Snapped grid with clean coordinate labels
        self._snap_axis(ax, min_x, max_x, min_y, max_y)
        ax.set_aspect('equal', adjustable='box')

        # Add north arrow
        self.add_north_arrow(fig, ax)

        # Add metadata
        fig.text(
            0.5, 0.03,
            f'A5 {orientation.capitalize()} | 300 DPI | Forest Species Classification',
            ha='center',
            va='bottom',
            fontsize=6,
            style='italic',
            color='gray'
        )

        # Add legend
        from matplotlib.patches import Patch
        legend_elements = []
        if pixels:
            present_classes = sorted(set(p['type'] for p in pixels))
            for type_class in present_classes:
                if type_class in forest_type_classes:
                    info = forest_type_classes[type_class]
                    legend_elements.append(
                        Patch(facecolor=info['color'], edgecolor='black', label=info['name'])
                    )

        if legend_elements:
            fig.legend(
                handles=legend_elements,
                loc='lower right',
                bbox_to_anchor=(0.90, 0.12),
                fontsize=6,
                frameon=True,
                fancybox=True,
                shadow=True,
                title='Forest Types'
            )

        # Save to file
        if output_path:
            self.save_to_file(fig, output_path)

        # Save to buffer
        buffer = self.save_to_buffer(fig)

        # Close figure
        self.close_figure(fig)

        return buffer


    # business: CFMG — canopy height raster map for biomass estimation and silvicultural planning
    def generate_canopy_height_map(
        self,
        geometry: Dict[str, Any],
        db_session,
        forest_name: str = 'Forest Boundary',
        orientation: str = 'auto',
        output_path: Optional[str] = None
    ) -> io.BytesIO:
        """
        Generate a canopy height map showing forest structure.

        Canopy Height Classes:
        - 0m: Non-forest (gray)
        - 0-5m: Low vegetation (light green)
        - 5-10m: Medium canopy (green)
        - 10-20m: Tall canopy (dark green)
        - >20m: Very tall canopy (very dark green)

        Args:
            geometry: GeoJSON dict with type and coordinates
            db_session: SQLAlchemy database session for raster queries
            forest_name: Name of the forest for title
            orientation: 'auto', 'portrait', or 'landscape'
            output_path: Optional file path to save

        Returns:
            BytesIO buffer with PNG data
        """
        # Auto-detect orientation
        if orientation == 'auto':
            geom_shape = shape(geometry)
            bounds = geom_shape.bounds
            width = bounds[2] - bounds[0]
            height = bounds[3] - bounds[1]
            aspect_ratio = width / height if height > 0 else 1.0

            if 0.85 <= aspect_ratio <= 1.15:
                orientation = 'portrait'
            elif aspect_ratio > 1.15:
                orientation = 'landscape'
            else:
                orientation = 'portrait'

        # Create figure
        fig, ax = self.create_figure(
            orientation=orientation,
            title=f'{forest_name} - Canopy Height Map',
            add_border=True
        )

        # Convert geometry
        geom_shape = shape(geometry)
        geom_wkt = geom_shape.wkt
        bounds = geom_shape.bounds
        min_x, min_y, max_x, max_y = bounds

        # Query canopy height raster
        try:
            query = text("""
                WITH canopy_pixels AS (
                    SELECT
                        (ST_PixelAsPolygons(ST_Clip(rast, 1, ST_GeomFromText(:geom_wkt, 4326)))).val as height,
                        (ST_PixelAsPolygons(ST_Clip(rast, 1, ST_GeomFromText(:geom_wkt, 4326)))).geom as geom
                    FROM rasters.canopy_height
                    WHERE ST_Intersects(rast, ST_GeomFromText(:geom_wkt, 4326))
                )
                SELECT
                    height,
                    ST_AsText(geom) as geom_wkt
                FROM canopy_pixels
                WHERE height IS NOT NULL AND height >= 0
            """)

            result = db_session.execute(query, {"geom_wkt": geom_wkt})

            # Collect pixels and classify
            pixels = []
            for row in result:
                height_val = float(row[0])
                pixel_geom_wkt = row[1]

                # Classify canopy height
                if height_val < 0.5:
                    height_class = 'Non-forest (0m)'
                    color = '#CCCCCC'
                elif height_val < 5:
                    height_class = 'Low (0-5m)'
                    color = '#A8E6A1'
                elif height_val < 10:
                    height_class = 'Medium (5-10m)'
                    color = '#4CAF50'
                elif height_val < 20:
                    height_class = 'Tall (10-20m)'
                    color = '#2E7D32'
                else:
                    height_class = 'Very tall (>20m)'
                    color = '#1B5E20'

                pixels.append({
                    'height': height_val,
                    'class': height_class,
                    'color': color,
                    'geom_wkt': pixel_geom_wkt
                })

            logger.info(f"Loaded {len(pixels)} canopy height pixels")

            # Plot pixels
            if pixels:
                for pixel in pixels:
                    try:
                        pixel_geom = wkt.loads(pixel['geom_wkt'])
                        if pixel_geom.geom_type == 'Polygon':
                            x, y = pixel_geom.exterior.xy
                            ax.fill(x, y, color=pixel['color'], edgecolor='none', alpha=0.85, zorder=5)
                    except Exception:
                        report_dropped(
                            logger, "raster pixel",
                            "that cell is left blank, so the map understates the mapped area",
                        )
                        continue

        except Exception as e:
            logger.warning(f"Could not load canopy height raster: {e}")
            logger.exception("Failed to load canopy height raster")

        # Plot forest boundary
        if geom_shape.geom_type == 'Polygon':
            polys_to_plot = [geom_shape]
        else:
            polys_to_plot = list(geom_shape.geoms)

        for poly in polys_to_plot:
            x, y = poly.exterior.xy
            ax.plot(x, y, color='black', linewidth=2, label='Forest Boundary', zorder=10)

        # Snapped grid with clean coordinate labels
        self._snap_axis(ax, min_x, max_x, min_y, max_y)
        ax.set_aspect('equal', adjustable='box')

        # Add north arrow
        self.add_north_arrow(fig, ax)

        # Add metadata
        fig.text(
            0.5, 0.03,
            f'A5 {orientation.capitalize()} | 300 DPI | Canopy Height Classification',
            ha='center',
            va='bottom',
            fontsize=6,
            style='italic',
            color='gray'
        )

        # Add legend
        from matplotlib.patches import Patch
        legend_elements = [
            Patch(facecolor='#CCCCCC', edgecolor='black', label='Non-forest (0m)'),
            Patch(facecolor='#A8E6A1', edgecolor='black', label='Low (0-5m)'),
            Patch(facecolor='#4CAF50', edgecolor='black', label='Medium (5-10m)'),
            Patch(facecolor='#2E7D32', edgecolor='black', label='Tall (10-20m)'),
            Patch(facecolor='#1B5E20', edgecolor='black', label='Very tall (>20m)'),
        ]
        fig.legend(
            handles=legend_elements,
            loc='lower right',
            bbox_to_anchor=(0.90, 0.12),
            fontsize=7,
            frameon=True,
            fancybox=True,
            shadow=True,
            title='Canopy Height'
        )

        # Save to file
        if output_path:
            self.save_to_file(fig, output_path)

        # Save to buffer
        buffer = self.save_to_buffer(fig)

        # Close figure
        self.close_figure(fig)

        return buffer


    # business: CFMG — soil type map for species suitability analysis
    def generate_soil_map(
        self,
        geometry: Dict[str, Any],
        db_session,
        forest_name: str = 'Forest Boundary',
        orientation: str = 'auto',
        output_path: Optional[str] = None
    ) -> io.BytesIO:
        """
        Generate a soil texture map from SoilGrids data.

        Soil Texture Classes (SoilGrids ISRIC):
        - 1: Clay (heavy)
        - 2: Silty clay
        - 3: Sandy clay
        - 4: Clay loam
        - 5: Silty clay loam
        - 6: Sandy clay loam
        - 7: Loam (medium)
        - 8: Silty loam
        - 9: Sandy loam
        - 10: Silt
        - 11: Loamy sand (light)
        - 12: Sand

        Args:
            geometry: GeoJSON dict with type and coordinates
            db_session: SQLAlchemy database session for raster queries
            forest_name: Name of the forest for title
            orientation: 'auto', 'portrait', or 'landscape'
            output_path: Optional file path to save

        Returns:
            BytesIO buffer with PNG data
        """
        # Auto-detect orientation
        if orientation == 'auto':
            geom_shape = shape(geometry)
            bounds = geom_shape.bounds
            width = bounds[2] - bounds[0]
            height = bounds[3] - bounds[1]
            aspect_ratio = width / height if height > 0 else 1.0

            if 0.85 <= aspect_ratio <= 1.15:
                orientation = 'portrait'
            elif aspect_ratio > 1.15:
                orientation = 'landscape'
            else:
                orientation = 'portrait'

        # Create figure
        fig, ax = self.create_figure(
            orientation=orientation,
            title=f'{forest_name} - Soil Texture Map',
            add_border=True
        )

        # Convert geometry
        geom_shape = shape(geometry)
        geom_wkt = geom_shape.wkt
        bounds = geom_shape.bounds
        min_x, min_y, max_x, max_y = bounds

        # Define soil texture classification
        soil_classes = {
            1: {'name': 'Clay', 'color': '#8B4513'},
            2: {'name': 'Silty clay', 'color': '#A0522D'},
            3: {'name': 'Sandy clay', 'color': '#CD853F'},
            4: {'name': 'Clay loam', 'color': '#DEB887'},
            5: {'name': 'Silty clay loam', 'color': '#D2691E'},
            6: {'name': 'Sandy clay loam', 'color': '#F4A460'},
            7: {'name': 'Loam', 'color': '#DAA520'},
            8: {'name': 'Silty loam', 'color': '#B8860B'},
            9: {'name': 'Sandy loam', 'color': '#FFD700'},
            10: {'name': 'Silt', 'color': '#FFA500'},
            11: {'name': 'Loamy sand', 'color': '#FFE4B5'},
            12: {'name': 'Sand', 'color': '#FFEFD5'},
        }

        # Query soil raster data
        try:
            query = text("""
                WITH soil_pixels AS (
                    SELECT
                        (ST_PixelAsPolygons(ST_Clip(rast, 1, ST_GeomFromText(:geom_wkt, 4326)))).val as soil_class,
                        (ST_PixelAsPolygons(ST_Clip(rast, 1, ST_GeomFromText(:geom_wkt, 4326)))).geom as geom
                    FROM rasters.soilgrids_isric
                    WHERE ST_Intersects(rast, ST_GeomFromText(:geom_wkt, 4326))
                )
                SELECT
                    soil_class,
                    ST_AsText(geom) as geom_wkt
                FROM soil_pixels
                WHERE soil_class IS NOT NULL AND soil_class >= 1 AND soil_class <= 12
            """)

            result = db_session.execute(query, {"geom_wkt": geom_wkt})

            # Collect pixels
            pixels = []
            class_counts = {}

            for row in result:
                soil_val = int(row[0])
                pixel_geom_wkt = row[1]

                if soil_val in soil_classes:
                    soil_info = soil_classes[soil_val]
                    pixels.append({
                        'class': soil_val,
                        'name': soil_info['name'],
                        'color': soil_info['color'],
                        'geom_wkt': pixel_geom_wkt
                    })
                    class_counts[soil_val] = class_counts.get(soil_val, 0) + 1

            logger.info(f"Loaded {len(pixels)} soil pixels")
            logger.info(f"Soil classes found: {list(class_counts.keys())}")

            # Plot pixels
            if pixels:
                for pixel in pixels:
                    try:
                        pixel_geom = wkt.loads(pixel['geom_wkt'])
                        if pixel_geom.geom_type == 'Polygon':
                            x, y = pixel_geom.exterior.xy
                            ax.fill(x, y, color=pixel['color'], edgecolor='none', alpha=0.85, zorder=5)
                    except Exception:
                        report_dropped(
                            logger, "raster pixel",
                            "that cell is left blank, so the map understates the mapped area",
                        )
                        continue

        except Exception as e:
            logger.warning(f" Could not load soil raster: {e}")
            logger.exception("Failed to load soil raster")

        # Plot forest boundary
        if geom_shape.geom_type == 'Polygon':
            polys_to_plot = [geom_shape]
        else:
            polys_to_plot = list(geom_shape.geoms)

        for poly in polys_to_plot:
            x, y = poly.exterior.xy
            ax.plot(x, y, color='black', linewidth=2, label='Forest Boundary', zorder=10)

        # Snapped grid with clean coordinate labels
        self._snap_axis(ax, min_x, max_x, min_y, max_y)
        ax.set_aspect('equal', adjustable='box')

        # Add north arrow
        self.add_north_arrow(fig, ax)

        # Add metadata
        fig.text(
            0.5, 0.03,
            f'A5 {orientation.capitalize()} | 300 DPI | SoilGrids ISRIC',
            ha='center',
            va='bottom',
            fontsize=6,
            style='italic',
            color='gray'
        )

        # Add legend
        from matplotlib.patches import Patch
        legend_elements = []
        if pixels:
            present_classes = sorted(set(p['class'] for p in pixels))
            for soil_class in present_classes:
                if soil_class in soil_classes:
                    info = soil_classes[soil_class]
                    legend_elements.append(
                        Patch(facecolor=info['color'], edgecolor='black', label=info['name'])
                    )

        if legend_elements:
            fig.legend(
                handles=legend_elements,
                loc='lower right',
                bbox_to_anchor=(0.90, 0.12),
                fontsize=6,
                frameon=True,
                fancybox=True,
                shadow=True,
                title='Soil Texture'
            )

        # Save to file
        if output_path:
            self.save_to_file(fig, output_path)

        # Save to buffer
        buffer = self.save_to_buffer(fig)

        # Close figure
        self.close_figure(fig)

        return buffer


    # business: CFMG — forest health map (pest/disease incidence) for management intervention planning
    def generate_forest_health_map(
        self,
        geometry: Dict[str, Any],
        db_session,
        forest_name: str = 'Forest Boundary',
        orientation: str = 'auto',
        output_path: Optional[str] = None
    ) -> io.BytesIO:
        """
        Generate a forest health map showing vegetation health status.

        Forest Health Classes:
        - 0: Non-forest (gray)
        - 1: Poor health (red)
        - 2: Fair health (orange)
        - 3: Good health (yellow-green)
        - 4: Excellent health (dark green)

        Args:
            geometry: GeoJSON dict with type and coordinates
            db_session: SQLAlchemy database session for raster queries
            forest_name: Name of the forest for title
            orientation: 'auto', 'portrait', or 'landscape'
            output_path: Optional file path to save

        Returns:
            BytesIO buffer with PNG data
        """
        # Auto-detect orientation
        if orientation == 'auto':
            geom_shape = shape(geometry)
            bounds = geom_shape.bounds
            width = bounds[2] - bounds[0]
            height = bounds[3] - bounds[1]
            aspect_ratio = width / height if height > 0 else 1.0

            if 0.85 <= aspect_ratio <= 1.15:
                orientation = 'portrait'
            elif aspect_ratio > 1.15:
                orientation = 'landscape'
            else:
                orientation = 'portrait'

        # Create figure
        fig, ax = self.create_figure(
            orientation=orientation,
            title=f'{forest_name} - Forest Health Map',
            add_border=True
        )

        # Convert geometry
        geom_shape = shape(geometry)
        geom_wkt = geom_shape.wkt
        bounds = geom_shape.bounds
        min_x, min_y, max_x, max_y = bounds

        # Define forest health classification
        health_classes = {
            0: {'name': 'Non-forest', 'color': '#CCCCCC'},
            1: {'name': 'Poor health', 'color': '#C0392B'},
            2: {'name': 'Fair health', 'color': '#E67E22'},
            3: {'name': 'Good health', 'color': '#F1C40F'},
            4: {'name': 'Excellent health', 'color': '#27AE60'},
        }

        # Query forest health raster
        try:
            query = text("""
                WITH health_pixels AS (
                    SELECT
                        (ST_PixelAsPolygons(ST_Clip(rast, 1, ST_GeomFromText(:geom_wkt, 4326)))).val as health_class,
                        (ST_PixelAsPolygons(ST_Clip(rast, 1, ST_GeomFromText(:geom_wkt, 4326)))).geom as geom
                    FROM rasters.nepal_forest_health
                    WHERE ST_Intersects(rast, ST_GeomFromText(:geom_wkt, 4326))
                )
                SELECT
                    health_class,
                    ST_AsText(geom) as geom_wkt
                FROM health_pixels
                WHERE health_class IS NOT NULL AND health_class >= 0 AND health_class <= 4
            """)

            result = db_session.execute(query, {"geom_wkt": geom_wkt})

            # Collect pixels
            pixels = []
            class_counts = {}

            for row in result:
                health_val = int(row[0])
                pixel_geom_wkt = row[1]

                if health_val in health_classes:
                    health_info = health_classes[health_val]
                    pixels.append({
                        'class': health_val,
                        'name': health_info['name'],
                        'color': health_info['color'],
                        'geom_wkt': pixel_geom_wkt
                    })
                    class_counts[health_val] = class_counts.get(health_val, 0) + 1

            logger.info(f"Loaded {len(pixels)} forest health pixels")
            logger.info(f"Health classes found: {list(class_counts.keys())}")

            # Plot pixels
            if pixels:
                for pixel in pixels:
                    try:
                        pixel_geom = wkt.loads(pixel['geom_wkt'])
                        if pixel_geom.geom_type == 'Polygon':
                            x, y = pixel_geom.exterior.xy
                            ax.fill(x, y, color=pixel['color'], edgecolor='none', alpha=0.85, zorder=5)
                    except Exception:
                        report_dropped(
                            logger, "raster pixel",
                            "that cell is left blank, so the map understates the mapped area",
                        )
                        continue

        except Exception as e:
            logger.warning(f" Could not load forest health raster: {e}")
            logger.exception("Failed to load forest health raster")

        # Plot forest boundary
        if geom_shape.geom_type == 'Polygon':
            polys_to_plot = [geom_shape]
        else:
            polys_to_plot = list(geom_shape.geoms)

        for poly in polys_to_plot:
            x, y = poly.exterior.xy
            ax.plot(x, y, color='black', linewidth=2, label='Forest Boundary', zorder=10)

        # Snapped grid with clean coordinate labels
        self._snap_axis(ax, min_x, max_x, min_y, max_y)
        ax.set_aspect('equal', adjustable='box')

        # Add north arrow
        self.add_north_arrow(fig, ax)

        # Add metadata
        fig.text(
            0.5, 0.03,
            f'A5 {orientation.capitalize()} | 300 DPI | Forest Health Index',
            ha='center',
            va='bottom',
            fontsize=6,
            style='italic',
            color='gray'
        )

        # Add legend
        from matplotlib.patches import Patch
        legend_elements = [
            Patch(facecolor='#CCCCCC', edgecolor='black', label='Non-forest'),
            Patch(facecolor='#C0392B', edgecolor='black', label='Poor health'),
            Patch(facecolor='#E67E22', edgecolor='black', label='Fair health'),
            Patch(facecolor='#F1C40F', edgecolor='black', label='Good health'),
            Patch(facecolor='#27AE60', edgecolor='black', label='Excellent health'),
        ]
        fig.legend(
            handles=legend_elements,
            loc='lower right',
            bbox_to_anchor=(0.90, 0.12),
            fontsize=7,
            frameon=True,
            fancybox=True,
            shadow=True,
            title='Forest Health'
        )

        # Save to file
        if output_path:
            self.save_to_file(fig, output_path)

        # Save to buffer
        buffer = self.save_to_buffer(fig)

        # Close figure
        self.close_figure(fig)

        return buffer
    def generate_test_map(
        self,
        orientation: str = 'portrait',
        output_path: Optional[str] = None
    ) -> io.BytesIO:
        """
        Generate a test map to verify the system is working.

        Args:
            orientation: 'portrait' or 'landscape'
            output_path: Optional file path to save (if None, returns buffer)

        Returns:
            BytesIO buffer with PNG data
        """
        # Create figure
        fig, ax = self.create_figure(
            orientation=orientation,
            title='Test Map - Forest Management System',
            add_border=True
        )

        # Draw a simple test pattern
        x = np.linspace(0, 2*np.pi, 100)
        y = np.sin(x)

        ax.plot(x, y, 'g-', linewidth=2, label='Test Pattern')
        ax.fill_between(x, 0, y, alpha=0.3, color='green')

        # Snapped grid with clean coordinate labels
        self._snap_axis(ax, 0, 2 * np.pi, -1, 1)

        # Add north arrow (outside map area)
        self.add_north_arrow(fig, ax)

        # Add legend outside map area
        fig.legend(
            loc='lower right',
            bbox_to_anchor=(0.90, 0.12),
            fontsize=8,
            frameon=True,
            fancybox=True,
            shadow=True
        )

        # Add metadata text
        fig.text(
            0.5, 0.03,
            f'A5 {orientation.capitalize()} | {self.dpi} DPI | Generated by MapGenerator',
            ha='center',
            va='bottom',
            fontsize=6,
            style='italic',
            color='gray'
        )

        # Save to file if path provided
        if output_path:
            self.save_to_file(fig, output_path)

        # Save to buffer
        buffer = self.save_to_buffer(fig)

        # Close figure
        self.close_figure(fig)

        return buffer


# Singleton instance
_map_generator: Optional[MapGenerator] = None


def get_map_generator() -> MapGenerator:
    """
    Get the singleton MapGenerator instance.

    Returns:
        MapGenerator instance
    """
    global _map_generator
    if _map_generator is None:
        _map_generator = MapGenerator()
    return _map_generator


# Convenience functions
def generate_test_map(
    orientation: str = 'portrait',
    output_path: Optional[str] = None
) -> io.BytesIO:
    """
    Generate a test map using the default generator.

    Args:
        orientation: 'portrait' or 'landscape'
        output_path: Optional file path to save

    Returns:
        BytesIO buffer with PNG data
    """
    generator = get_map_generator()
    return generator.generate_test_map(orientation, output_path)
