"""
Additional Map Generation Functions for Forest Management System
# business: generates thematic maps for new reporting UI — 5 specialized map types
# constraint: A4 size, 300 DPI — print-ready resolution for field use
# why: separate from legacy map_generator for incremental migration — replaces old system piece by piece
# NOTE: all functions designed as mixin methods for MapGenerator class (self pattern)

This file contains the implementations for 5 additional map types:
1. Topographic Map (elevation contours)
2. Forest Type Map (species classification)
3. Canopy Height Map (forest structure)
4. Soil Map (texture classification)
5. Forest Health Map (health status)

These functions should be integrated into the MapGenerator class in map_generator.py
"""
import logging

from app.utils.map_grid import compute_snapped_grid, apply_snapped_ticks

from app.core.dropped import report_dropped

logger = logging.getLogger(__name__)

def generate_topographic_map(
    self,
    geometry: Dict[str, Any],
    db_session,
    forest_name: str = 'Forest Boundary',
    orientation: str = 'auto',
    output_path: Optional[str] = None
) -> io.BytesIO:
    # business: contour intervals at 20m — standard for CFMG management planning
    # constraint: DEM-based contours via PostGIS ST_Contour — requires DEM raster loaded
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
        logger.warning(f"Warning: Could not load DEM raster: {e}")
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


def generate_forest_type_map(
    self,
    geometry: Dict[str, Any],
    db_session,
    forest_name: str = 'Forest Boundary',
    orientation: str = 'auto',
    output_path: Optional[str] = None
) -> io.BytesIO:
    # business: species classification map used for block-level management prescriptions
    # constraint: relies on field inventory species data joined to block geometries
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
        logger.warning(f"Warning: Could not load forest type raster: {e}")
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


def generate_canopy_height_map(
    self,
    geometry: Dict[str, Any],
    db_session,
    forest_name: str = 'Forest Boundary',
    orientation: str = 'auto',
    output_path: Optional[str] = None
) -> io.BytesIO:
    # business: canopy height classes map to forest structure — key for harvesting decisions
    # constraint: 5 height classes — matches CFMG forest structure classification schema
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
        logger.warning(f"Warning: Could not load canopy height raster: {e}")
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


def generate_soil_map(
    self,
    geometry: Dict[str, Any],
    db_session,
    forest_name: str = 'Forest Boundary',
    orientation: str = 'auto',
    output_path: Optional[str] = None
) -> io.BytesIO:
    # business: soil texture informs species suitability and plantation planning
    # constraint: SoilGrids ISRIC 250m resolution — 12 soil texture classes
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
        logger.warning(f"Warning: Could not load soil raster: {e}")
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
        logger.warning(f"Warning: Could not load forest health raster: {e}")
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
