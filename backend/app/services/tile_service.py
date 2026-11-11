"""
Tile service for rendering raster data as map tiles
Uses PostGIS rasters and Pillow for PNG generation
"""
import io
import logging
import math
from typing import Tuple, Dict, Any, Optional
from functools import lru_cache
import time as _time
from PIL import Image, ImageDraw
import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.core.forest_types import get_forest_type_color

logger = logging.getLogger(__name__)

# Module-level tile cache — shared across ALL TileService instances
_tile_cache: dict = {}
_TILE_CACHE_MAX = 5000
_TILE_CACHE_TTL = 3600  # 1 hour


def _tile_cache_get(key: tuple):
    entry = _tile_cache.get(key)
    if entry is None:
        return None
    value, ts = entry
    if _time.time() - ts > _TILE_CACHE_TTL:
        del _tile_cache[key]
        return None
    return value


def _tile_cache_set(key: tuple, value: bytes):
    if len(_tile_cache) >= _TILE_CACHE_MAX:
        evict = sorted(_tile_cache.keys(), key=lambda k: _tile_cache[k][1])[:len(_tile_cache) // 5]
        for k in evict:
            del _tile_cache[k]
    _tile_cache[key] = (value, _time.time())


class TileService:
    """
    Generate map tiles from PostGIS raster data

    Supports XYZ tile format (Web Mercator / EPSG:3857)
    Returns 256×256px PNG tiles with configurable transparency
    """

    # NOTE: LRU tile cache; broken implementation — planned fix in Cache Plan
    # constraint: RASTER_TABLES is the single source of truth — validates raster_table name in _query_raster_tile to prevent SQL injection
    # Raster table mapping
    RASTER_TABLES = {
        'dem': 'rasters.dem',
        'slope': 'rasters.slope_regulation',
        'aspect': 'rasters.aspect',
        'canopy': 'rasters.canopy_height',
        'biomass': 'rasters.agb_2022_nepal',
        'nasa_forest_2020': 'rasters.nasa_forest_2020',  # NEW: NASA forest quality classification
        'forest_type': 'rasters.forest_type',
        'landcover': 'rasters.esa_world_cover',
        'forest_loss': 'rasters.nepal_lossyear',
        'forest_gain': 'rasters.nepal_gain',
        'temperature': 'rasters.annual_mean_temperature',  # Fixed: was 'rasters.temperature'
        'precipitation': 'rasters.annual_precipitation',  # Fixed: was 'rasters.precipitation'
        'soil_ph': 'rasters.soilgrids_isric',  # Soil pH (0-30cm depth)
        'soil_texture': 'rasters.soilgrids_isric',  # Soil texture (clay/sand/silt)
        'soil_carbon': 'rasters.soilgrids_isric',  # Soil organic carbon
        'soil_fertility': 'rasters.soilgrids_isric',  # Soil fertility index (derived)
        'soil_density': 'rasters.soilgrids_isric',  # Bulk density (compaction)
        'fire': 'rasters.forest_loss_fire',
        'forest_health': 'rasters.nepal_forest_health',
        'min_temp_coldest': 'rasters.min_temp_coldest_month',  # NEW: Minimum temperature of coldest month
    }

    # Band numbers for multi-band rasters (soilgrids_isric has 8 bands)
    # Band 1 = clay_g_kg, Band 2 = sand_g_kg, Band 3 = silt_g_kg, Band 4 = ph_h2o
    # Band 5 = soc_dg_kg, Band 6 = nitrogen_cg_kg, Band 7 = bdod_cg_cm3, Band 8 = cec_mmol_kg
    RASTER_BANDS = {
        'soil_ph': 4,         # pH value (band 4)
        'soil_carbon': 5,     # Soil Organic Carbon (band 5)
        'soil_density': 7,    # Bulk Density (band 7)
        'soil_texture': 1,    # Clay content for texture (band 1) - simplified
        'soil_fertility': 4,  # Use pH as proxy for fertility visualization (band 4)
        # For other layers, None means use default (band 1 or single-band)
    }

    # Read-only raster layer catalog (SSOT). Keys must match RASTER_TABLES.
    # Served to the workspace so users can search + add read-only overlays
    # without any client-side catalog duplication.
    RASTER_METADATA = {
        'slope': {'name': 'Slope', 'description': 'Terrain slope in degrees', 'source': 'Derived from SRTM DEM', 'resolution': '30m', 'year': None},
        'aspect': {'name': 'Aspect', 'description': 'Slope direction (compass bearing)', 'source': 'Derived from SRTM DEM', 'resolution': '30m', 'year': None},
        'dem': {'name': 'Elevation (DEM)', 'description': 'Height above sea level', 'source': 'SRTM 1 Arc-Second Global', 'resolution': '30m', 'year': '2000'},
        'canopy': {'name': 'Canopy Height', 'description': 'Tree canopy height in meters', 'source': 'ETH Zurich / GEDI', 'resolution': '30m', 'year': '2020'},
        'biomass': {'name': 'Biomass (AGB)', 'description': 'Above-ground biomass in Mg/ha', 'source': 'ESA CCI AGB V6', 'resolution': '100m', 'year': '2022'},
        'temperature': {'name': 'Temperature', 'description': 'Mean annual temperature', 'source': 'WorldClim 2.1', 'resolution': '1km', 'year': '1970-2000'},
        'precipitation': {'name': 'Precipitation', 'description': 'Annual precipitation in mm', 'source': 'WorldClim 2.1', 'resolution': '1km', 'year': '1970-2000'},
        'forest_health': {'name': 'Forest Health (NDVI)', 'description': 'Forest health based on NDVI values', 'source': 'Sentinel-2/Landsat NDVI', 'resolution': '10-30m', 'year': '2023'},
        'min_temp_coldest': {'name': 'Min Temperature (Coldest Month)', 'description': 'Minimum temperature of coldest month', 'source': 'WorldClim 2.1', 'resolution': '1km', 'year': '1970-2000'},
        'nasa_forest_2020': {'name': 'Forest Quality (NASA 2020)', 'description': 'Forest quality class: 1 Primary, 2 Young secondary, 3 Old secondary (0 = Non-forest, a mapped class, not NoData)', 'source': 'NASA/ORNL DAAC', 'resolution': '30m', 'year': '2020'},
        'forest_type': {'name': 'Forest Type (FRTC)', 'description': 'Forest type classification, FRTC 2015: 26 classes (1-25 forest types, 26 = Unclassified)', 'source': 'Nepal FRTC', 'resolution': '30m', 'year': '2015'},
        'landcover': {'name': 'Land Cover (ESA WorldCover)', 'description': 'ESA WorldCover 2021 land cover classification', 'source': 'ESA WorldCover', 'resolution': '10m', 'year': '2021'},
        'forest_loss': {'name': 'Forest Loss (Hansen)', 'description': 'Year of forest loss 2001-2024', 'source': 'Hansen Global Forest Change', 'resolution': '30m', 'year': '2001-2024'},
        'forest_gain': {'name': 'Forest Gain (Hansen)', 'description': 'Forest regrowth 2000-2012', 'source': 'Hansen Global Forest Change', 'resolution': '30m', 'year': '2000-2012'},
        'fire': {'name': 'Fire Loss', 'description': 'Forest loss from fire 2001-2024', 'source': 'Hansen Global Forest Change', 'resolution': '30m', 'year': '2001-2024'},
        'soil_ph': {'name': 'Soil pH', 'description': 'Soil acidity/alkalinity (0-30cm depth)', 'source': 'SoilGrids 2.0 (ISRIC)', 'resolution': '250m', 'year': '2020'},
        'soil_texture': {'name': 'Soil Texture', 'description': 'USDA soil texture classification', 'source': 'SoilGrids 2.0 (ISRIC)', 'resolution': '250m', 'year': '2020'},
        'soil_carbon': {'name': 'Soil Organic Carbon', 'description': 'SOC percentage (0-30cm depth)', 'source': 'SoilGrids 2.0 (ISRIC)', 'resolution': '250m', 'year': '2020'},
        'soil_fertility': {'name': 'Soil Fertility Index', 'description': 'Fertility score based on pH, SOC, N, CEC', 'source': 'SoilGrids 2.0 (ISRIC)', 'resolution': '250m', 'year': '2020'},
        'soil_density': {'name': 'Bulk Density (Compaction)', 'description': 'Soil compaction risk', 'source': 'SoilGrids 2.0 (ISRIC)', 'resolution': '250m', 'year': '2020'},
    }

    # Color definitions (from map_generator.py)
    SLOPE_COLORS = {
        'ranges': [
            (0, 5, (46, 204, 113)),      # Green - Flat
            (5, 15, (241, 196, 15)),     # Yellow - Gentle
            (15, 30, (230, 126, 34)),    # Orange - Moderate
            (30, 45, (231, 76, 60)),     # Red-Orange - Steep
            (45, 90, (192, 57, 43))      # Dark Red - Very Steep
        ]
    }

    ASPECT_COLORS = {
        0: (204, 204, 204),  # Gray - Flat
        1: (26, 84, 144),    # Dark Blue - N
        2: (52, 152, 219),   # Blue - NE
        3: (26, 188, 156),   # Cyan - E
        4: (241, 196, 15),   # Yellow - SE
        5: (231, 76, 60),    # Red - S
        6: (230, 126, 34),   # Orange - SW
        7: (243, 156, 18),   # Light Orange - W
        8: (155, 89, 182)    # Purple - NW
    }

    def __init__(self, db: Session):
        self.db = db

    def get_tile(
        self,
        calculation_id: str,
        layer_name: str,
        z: int,
        x: int,
        y: int,
        tile_size: int = 256,
        alpha: int = 128
    ) -> bytes:
        """
        Generate a tile for the given layer and coordinates.
        Cached by (calculation_id, layer_name, z, x, y, tile_size, alpha).

        Returns:
            PNG image bytes
        """
        cache_key = (str(calculation_id), layer_name, z, x, y, tile_size, alpha)
        cached = _tile_cache_get(cache_key)
        if cached is not None:
            return cached

        # 1. Get tile bounds in lat/lon
        bounds = self.xyz_to_bounds(x, y, z)
        logger.debug("[TILE] Bounds: %s", bounds)

        # 2. Get boundary geometry for this calculation
        try:
            boundary_wkt = self._get_boundary_wkt(calculation_id)
            logger.debug("[TILE] Got boundary WKT (length: %d)", len(boundary_wkt))
        except Exception as e:
            logger.error("[TILE ERROR] Failed to get boundary: %s", e)
            raise

        # 2b. Get dynamic ranges for classification
        elevation_range = None
        canopy_range = None
        if layer_name == 'dem':
            elevation_range = self._get_elevation_range(calculation_id)
            if elevation_range and elevation_range[0] is not None:
                logger.debug("[TILE] Dynamic elevation range: %.1fm - %.1fm", elevation_range[0], elevation_range[1])
        elif layer_name == 'canopy':
            canopy_range = self._get_canopy_range(calculation_id)
            if canopy_range and canopy_range[0] is not None:
                logger.debug("[TILE] Dynamic canopy range: %.1fm - %.1fm", canopy_range[0], canopy_range[1])

        # 3. Get raster table
        if layer_name not in self.RASTER_TABLES:
            raise ValueError(f"Unknown layer: {layer_name}")

        raster_table = self.RASTER_TABLES[layer_name]
        logger.debug("[TILE] Using raster table: %s", raster_table)

        # Get band number for multi-band rasters (e.g., soil layers)
        band_number = self.RASTER_BANDS.get(layer_name)
        if band_number:
            logger.debug("[TILE] Using band %s for layer %s", band_number, layer_name)

        # 4. Query raster data for this tile
        raster_data = self._query_raster_tile(
            raster_table,
            bounds,
            boundary_wkt,
            tile_size,
            band_number=band_number
        )

        if not raster_data:
            logger.debug("[TILE] No raster data found - returning empty tile")

        # 5. Apply colormap
        colored_tile = self._apply_colormap(raster_data, layer_name, alpha, elevation_range=elevation_range, canopy_range=canopy_range)

        # 6. Render as PNG
        png_bytes = self._render_png(colored_tile)
        logger.debug("[TILE] Generated PNG: %d bytes", len(png_bytes))

        _tile_cache_set(cache_key, png_bytes)
        return png_bytes

    # why: tiles rendered in EPSG:3857 (Web Mercator) for Leaflet compatibility
    def xyz_to_bounds(self, x: int, y: int, z: int) -> Tuple[float, float, float, float]:
        """
        Convert XYZ tile coordinates to lat/lon bounds

        Returns:
            (min_lon, min_lat, max_lon, max_lat)
        """
        n = 2.0 ** z

        # Longitude
        lon_min = x / n * 360.0 - 180.0
        lon_max = (x + 1) / n * 360.0 - 180.0

        # Latitude (Web Mercator)
        lat_max_rad = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
        lat_max = math.degrees(lat_max_rad)

        lat_min_rad = math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n)))
        lat_min = math.degrees(lat_min_rad)

        return (lon_min, lat_min, lon_max, lat_max)

    # business: CFMG — forest boundary tiles must be publicly accessible via WMS-style queries
    def _get_boundary_wkt(self, calculation_id: str) -> str:
        """Get boundary geometry as WKT"""
        query = text("""
            SELECT ST_AsText(boundary_geom) as wkt
            FROM calculations
            WHERE id = :calc_id
        """)

        result = self.db.execute(query, {"calc_id": calculation_id}).first()

        if not result:
            raise ValueError(f"Calculation {calculation_id} not found")

        return result.wkt

    def _get_elevation_range(self, calculation_id: str) -> Tuple[Optional[float], Optional[float]]:
        """Get min and max elevation for this calculation from result_data"""
        query = text("""
            SELECT result_data->>'elevation_min_m' as min_elev,
                   result_data->>'elevation_max_m' as max_elev
            FROM calculations
            WHERE id = :calc_id
        """)

        result = self.db.execute(query, {"calc_id": calculation_id}).first()

        if not result:
            return None, None

        try:
            min_elev = float(result.min_elev) if result.min_elev else None
            max_elev = float(result.max_elev) if result.max_elev else None

            # Validate elevation values
            if min_elev and max_elev and min_elev > -32000 and max_elev > -32000:
                return min_elev, max_elev
            else:
                return None, None
        except (ValueError, TypeError):
            return None, None

    def _get_canopy_range(self, calculation_id: str) -> Tuple[Optional[float], Optional[float]]:
        """Get min and max canopy height for this calculation from result_data"""
        query = text("""
            SELECT result_data->>'canopy_min_m' as min_canopy,
                   result_data->>'canopy_max_m' as max_canopy
            FROM calculations
            WHERE id = :calc_id
        """)

        result = self.db.execute(query, {"calc_id": calculation_id}).first()

        if not result:
            return None, None

        try:
            min_canopy = float(result.min_canopy) if result.min_canopy else None
            max_canopy = float(result.max_canopy) if result.max_canopy else None

            # Validate canopy values
            if min_canopy is not None and max_canopy is not None and min_canopy >= 0 and max_canopy >= 0:
                return min_canopy, max_canopy
            else:
                return None, None
        except (ValueError, TypeError):
            return None, None

    def _query_raster_tile(
        self,
        raster_table: str,
        bounds: Tuple[float, float, float, float],
        boundary_wkt: str,
        tile_size: int,
        band_number: Optional[int] = None
    ) -> Optional[list]:
        """
        Query raster data for a specific tile using grid sampling

        Args:
            raster_table: Name of raster table
            bounds: Tile bounds (min_lon, min_lat, max_lon, max_lat)
            boundary_wkt: Forest boundary as WKT string
            tile_size: Output image size
            band_number: Raster band to read (None = default band 1, required for multi-band rasters)

        Returns:
            List of dicts with i, j, val for each grid cell
        """
        min_lon, min_lat, max_lon, max_lat = bounds

        try:
                # NOTE: grid sampling at 32×32 (1024 cells) for performance; nearest-neighbor upscale to 256×256 output
            # Sample raster at grid points within tile AND forest boundary
            # Use 32x32 grid for performance
            sample_size = 32

            lon_step = (max_lon - min_lon) / sample_size
            lat_step = (max_lat - min_lat) / sample_size

            # Optimized query:
            # 1. Filter rasters by forest boundary (not tile bounds)
            # 2. Sample grid points
            # 3. Check if point is inside forest boundary before sampling
            # Result: Only show data within actual forest area

            if band_number is not None:
                st_value_call = "ST_Value(r.rast, :band_number, ST_SetSRID(ST_MakePoint(g.lon, g.lat), 4326))"
            else:
                st_value_call = "ST_Value(r.rast, ST_SetSRID(ST_MakePoint(g.lon, g.lat), 4326))"

            if raster_table not in self.RASTER_TABLES.values():
                raise ValueError(f"Invalid raster table: {raster_table}")

            _sql = """
                WITH forest_boundary AS (
                    SELECT ST_GeomFromText(:boundary_wkt, 4326) as geom
                ),
                relevant_rasters AS (
                    SELECT r.rast
                    FROM {raster_table} r, forest_boundary f
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
                    {st_value_call} as val
                FROM grid g
                CROSS JOIN relevant_rasters r
                CROSS JOIN forest_boundary f
                WHERE
                    ST_Contains(f.geom, ST_SetSRID(ST_MakePoint(g.lon, g.lat), 4326))
                    AND {st_value_call} IS NOT NULL
                LIMIT 2000
            """.format(raster_table=raster_table, st_value_call=st_value_call)
            query = text(_sql)

            _tile_params = {
                "boundary_wkt": boundary_wkt,
                "min_lon": min_lon,
                "min_lat": min_lat,
                "max_lon": max_lon,
                "max_lat": max_lat,
                "sample_size": sample_size,
                "lon_step": lon_step,
                "lat_step": lat_step
            }
            if band_number is not None:
                _tile_params["band_number"] = band_number
            result = self.db.execute(query, _tile_params)

            # Collect sample points
            samples = []
            for row in result:
                if row.val is not None:
                    samples.append({
                        'i': row.i,
                        'j': row.j,
                        'val': float(row.val)
                    })

            if samples:
                # Log statistics about the values
                values = [s['val'] for s in samples]
                logger.info(f"Tile query returned {len(samples)} samples for {raster_table}")
                logger.info(f"  Value range: min={min(values):.2f}, max={max(values):.2f}, avg={sum(values)/len(values):.2f}")
            else:
                logger.info(f"Tile query returned 0 samples for {raster_table}")

            if not samples:
                return None

            return samples

        except Exception as e:
            logger.error(f"querying raster tile: {e}")
            logger.exception("Failed to query raster tile")
            try:
                self.db.rollback()
            except Exception:
                logger.warning(
                    "rollback failed after a raster tile error - later tile queries "
                    "in this session will probably fail too", exc_info=True,
                )
            return None

    def _apply_colormap(
        self,
        raster_data: Optional[list],
        layer_name: str,
        alpha: int,
        elevation_range: Optional[Tuple[Optional[float], Optional[float]]] = None,
        canopy_range: Optional[Tuple[Optional[float], Optional[float]]] = None
    ) -> Image.Image:
        """
        Apply color mapping to raster data

        Returns:
            PIL Image (RGBA)
        """
        # Create blank transparent image
        img = Image.new('RGBA', (256, 256), (0, 0, 0, 0))

        if not raster_data:
            return img

        draw = ImageDraw.Draw(img)

        # Grid size used in sampling (32x32 samples for 256x256 image = 8px per cell)
        sample_size = 32
        cell_size = 256 // sample_size  # 8 pixels per cell

        # Apply layer-specific coloring
        logger.debug(f"[COLORMAP] Processing {len(raster_data)} samples for layer={layer_name}")

        if layer_name == 'slope':
            colored_count = 0
            # Track slope ranges for debugging
            range_counts = {'0-5': 0, '5-15': 0, '15-30': 0, '30-45': 0, '45+': 0}

            for sample in raster_data:
                val = sample['val']
                if val is None:
                    continue

                # Get color for this slope value
                color = self._get_slope_color(val, alpha)

                # Count by range
                if val < 5:
                    range_counts['0-5'] += 1
                elif val < 15:
                    range_counts['5-15'] += 1
                elif val < 30:
                    range_counts['15-30'] += 1
                elif val < 45:
                    range_counts['30-45'] += 1
                else:
                    range_counts['45+'] += 1

                # Draw rectangle for this grid cell
                i, j = sample['i'], sample['j']
                x1 = i * cell_size
                y1 = (sample_size - 1 - j) * cell_size  # Flip Y axis
                x2 = x1 + cell_size
                y2 = y1 + cell_size

                draw.rectangle([x1, y1, x2, y2], fill=color)
                colored_count += 1

            logger.debug(f"[COLORMAP] Applied colors to {colored_count}/{len(raster_data)} cells for slope")
            logger.debug(f"[COLORMAP] Slope distribution: {range_counts}")

        elif layer_name == 'aspect':
            for sample in raster_data:
                val = sample['val']
                if val is None or val < 0 or val > 8:
                    continue

                # Get color for this aspect class
                rgb = self.ASPECT_COLORS.get(int(val), (0, 0, 0))
                color = rgb + (alpha,)

                # Draw rectangle for this grid cell
                i, j = sample['i'], sample['j']
                x1 = i * cell_size
                y1 = (sample_size - 1 - j) * cell_size  # Flip Y axis
                x2 = x1 + cell_size
                y2 = y1 + cell_size

                draw.rectangle([x1, y1, x2, y2], fill=color)

        elif layer_name == 'dem':
            # For DEM, use continuous gradient with dynamic classification
            for sample in raster_data:
                val = sample['val']
                if val is None:
                    continue

                # Get color for elevation (dynamic or static fallback)
                color = self._get_elevation_color(val, alpha, elevation_range=elevation_range)

                # Draw rectangle for this grid cell
                i, j = sample['i'], sample['j']
                x1 = i * cell_size
                y1 = (sample_size - 1 - j) * cell_size  # Flip Y axis
                x2 = x1 + cell_size
                y2 = y1 + cell_size

                draw.rectangle([x1, y1, x2, y2], fill=color)

        elif layer_name == 'canopy':
            # For Canopy Height, use absolute ecological thresholds
            for sample in raster_data:
                val = sample['val']
                if val is None:
                    continue

                # Get color for canopy height (absolute ecological classification)
                color = self._get_canopy_color(val, alpha)

                # Draw rectangle for this grid cell
                i, j = sample['i'], sample['j']
                x1 = i * cell_size
                y1 = (sample_size - 1 - j) * cell_size  # Flip Y axis
                x2 = x1 + cell_size
                y2 = y1 + cell_size

                draw.rectangle([x1, y1, x2, y2], fill=color)

        elif layer_name == 'biomass':
            # For Biomass (AGB), use classified color scheme
            for sample in raster_data:
                val = sample['val']
                if val is None:
                    continue

                # Get color for biomass value
                color = self._get_biomass_color(val, alpha)

                # Draw rectangle for this grid cell
                i, j = sample['i'], sample['j']
                x1 = i * cell_size
                y1 = (sample_size - 1 - j) * cell_size  # Flip Y axis
                x2 = x1 + cell_size
                y2 = y1 + cell_size

                draw.rectangle([x1, y1, x2, y2], fill=color)

        elif layer_name == 'temperature':
            # For Temperature, use classified color scheme
            for sample in raster_data:
                val = sample['val']
                if val is None:
                    continue

                # Get color for temperature value
                color = self._get_temperature_color(val, alpha)

                # Draw rectangle for this grid cell
                i, j = sample['i'], sample['j']
                x1 = i * cell_size
                y1 = (sample_size - 1 - j) * cell_size  # Flip Y axis
                x2 = x1 + cell_size
                y2 = y1 + cell_size

                draw.rectangle([x1, y1, x2, y2], fill=color)

        elif layer_name == 'precipitation':
            # For Precipitation, use classified color scheme
            for sample in raster_data:
                val = sample['val']
                if val is None:
                    continue

                # Get color for precipitation value
                color = self._get_precipitation_color(val, alpha)

                # Draw rectangle for this grid cell
                i, j = sample['i'], sample['j']
                x1 = i * cell_size
                y1 = (sample_size - 1 - j) * cell_size  # Flip Y axis
                x2 = x1 + cell_size
                y2 = y1 + cell_size

                draw.rectangle([x1, y1, x2, y2], fill=color)

        elif layer_name == 'forest_health':
            # For Forest Health, use categorical color scheme
            for sample in raster_data:
                val = sample['val']
                if val is None:
                    continue

                # Get color for forest health code
                color = self._get_forest_health_color(val, alpha)

                # Draw rectangle for this grid cell
                i, j = sample['i'], sample['j']
                x1 = i * cell_size
                y1 = (sample_size - 1 - j) * cell_size  # Flip Y axis
                x2 = x1 + cell_size
                y2 = y1 + cell_size

                draw.rectangle([x1, y1, x2, y2], fill=color)

        elif layer_name == 'min_temp_coldest':
            # For Minimum Temperature (coldest month), use classified color scheme
            for sample in raster_data:
                val = sample['val']
                if val is None:
                    continue

                # Get color for minimum temperature value
                color = self._get_min_temp_color(val, alpha)

                # Draw rectangle for this grid cell
                i, j = sample['i'], sample['j']
                x1 = i * cell_size
                y1 = (sample_size - 1 - j) * cell_size  # Flip Y axis
                x2 = x1 + cell_size
                y2 = y1 + cell_size

                draw.rectangle([x1, y1, x2, y2], fill=color)

        elif layer_name == 'nasa_forest_2020':
            # For NASA Forest 2020, use official IPCC Tier 1 classification colors
            for sample in raster_data:
                val = sample['val']
                if val is None:
                    continue

                # Get color for NASA forest quality class
                color = self._get_nasa_forest_color(val, alpha)

                # Draw rectangle for this grid cell
                i, j = sample['i'], sample['j']
                x1 = i * cell_size
                y1 = (sample_size - 1 - j) * cell_size  # Flip Y axis
                x2 = x1 + cell_size
                y2 = y1 + cell_size

                draw.rectangle([x1, y1, x2, y2], fill=color)

        elif layer_name == 'forest_type':
            # For Forest Type (FRTC), use elevation-zone based color scheme (25 classes)
            for sample in raster_data:
                val = sample['val']
                if val is None:
                    continue

                # Get color for forest type class
                color = self._get_forest_type_color(val, alpha)

                # Draw rectangle for this grid cell
                i, j = sample['i'], sample['j']
                x1 = i * cell_size
                y1 = (sample_size - 1 - j) * cell_size  # Flip Y axis
                x2 = x1 + cell_size
                y2 = y1 + cell_size

                draw.rectangle([x1, y1, x2, y2], fill=color)

        elif layer_name == 'landcover':
            # For ESA WorldCover, use official ESA color scheme (11 classes)
            for sample in raster_data:
                val = sample['val']
                if val is None:
                    continue

                # Get color for land cover class
                color = self._get_landcover_color(val, alpha)

                # Draw rectangle for this grid cell
                i, j = sample['i'], sample['j']
                x1 = i * cell_size
                y1 = (sample_size - 1 - j) * cell_size  # Flip Y axis
                x2 = x1 + cell_size
                y2 = y1 + cell_size

                draw.rectangle([x1, y1, x2, y2], fill=color)

        elif layer_name == 'forest_loss':
            # For Forest Loss (Hansen), use temporal gradient (2001-2024)
            for sample in raster_data:
                val = sample['val']
                if val is None or val == 0:
                    continue  # Skip no loss

                # Get color for loss year
                color = self._get_forest_loss_color(val, alpha)

                # Draw rectangle for this grid cell
                i, j = sample['i'], sample['j']
                x1 = i * cell_size
                y1 = (sample_size - 1 - j) * cell_size  # Flip Y axis
                x2 = x1 + cell_size
                y2 = y1 + cell_size

                draw.rectangle([x1, y1, x2, y2], fill=color)

        elif layer_name == 'forest_gain':
            # For Forest Gain (Hansen), binary: 0 = no gain, 1 = forest regrowth
            for sample in raster_data:
                val = sample['val']
                if val is None or val == 0:
                    continue  # Skip no gain

                # Forest gain = Lime Green (bright, positive growth)
                color = (50, 205, 50, alpha)  # #32CD32 Lime Green

                # Draw rectangle for this grid cell
                i, j = sample['i'], sample['j']
                x1 = i * cell_size
                y1 = (sample_size - 1 - j) * cell_size  # Flip Y axis
                x2 = x1 + cell_size
                y2 = y1 + cell_size

                draw.rectangle([x1, y1, x2, y2], fill=color)

        elif layer_name == 'fire':
            # For Fire Loss, use fire-specific temporal gradient (2001-2024)
            for sample in raster_data:
                val = sample['val']
                if val is None or val == 0:
                    continue  # Skip no fire loss

                # Get color for fire loss year (fire-specific colors)
                color = self._get_fire_loss_color(val, alpha)

                # Draw rectangle for this grid cell
                i, j = sample['i'], sample['j']
                x1 = i * cell_size
                y1 = (sample_size - 1 - j) * cell_size  # Flip Y axis
                x2 = x1 + cell_size
                y2 = y1 + cell_size

                draw.rectangle([x1, y1, x2, y2], fill=color)

        elif layer_name == 'soil_ph':
            # For Soil pH, use acidity/alkalinity color scheme
            for sample in raster_data:
                val = sample['val']
                if val is None:
                    continue

                # Get color for pH value
                color = self._get_soil_ph_color(val, alpha)

                # Draw rectangle for this grid cell
                i, j = sample['i'], sample['j']
                x1 = i * cell_size
                y1 = (sample_size - 1 - j) * cell_size  # Flip Y axis
                x2 = x1 + cell_size
                y2 = y1 + cell_size

                draw.rectangle([x1, y1, x2, y2], fill=color)

        elif layer_name == 'soil_texture':
            # For Soil Texture, use USDA texture class colors
            for sample in raster_data:
                val = sample['val']
                if val is None:
                    continue

                # Get color for texture class
                color = self._get_soil_texture_color(val, alpha)

                # Draw rectangle for this grid cell
                i, j = sample['i'], sample['j']
                x1 = i * cell_size
                y1 = (sample_size - 1 - j) * cell_size  # Flip Y axis
                x2 = x1 + cell_size
                y2 = y1 + cell_size

                draw.rectangle([x1, y1, x2, y2], fill=color)

        elif layer_name == 'soil_carbon':
            # For Soil Organic Carbon, use low→high gradient
            for sample in raster_data:
                val = sample['val']
                if val is None:
                    continue

                # Get color for SOC value
                color = self._get_soil_carbon_color(val, alpha)

                # Draw rectangle for this grid cell
                i, j = sample['i'], sample['j']
                x1 = i * cell_size
                y1 = (sample_size - 1 - j) * cell_size  # Flip Y axis
                x2 = x1 + cell_size
                y2 = y1 + cell_size

                draw.rectangle([x1, y1, x2, y2], fill=color)

        elif layer_name == 'soil_fertility':
            # For Soil Fertility Index, use poor→excellent gradient
            for sample in raster_data:
                val = sample['val']
                if val is None:
                    continue

                # Get color for fertility index
                color = self._get_soil_fertility_color(val, alpha)

                # Draw rectangle for this grid cell
                i, j = sample['i'], sample['j']
                x1 = i * cell_size
                y1 = (sample_size - 1 - j) * cell_size  # Flip Y axis
                x2 = x1 + cell_size
                y2 = y1 + cell_size

                draw.rectangle([x1, y1, x2, y2], fill=color)

        elif layer_name == 'soil_density':
            # For Bulk Density, use compaction risk gradient
            for sample in raster_data:
                val = sample['val']
                if val is None:
                    continue

                # Get color for bulk density
                color = self._get_soil_density_color(val, alpha)

                # Draw rectangle for this grid cell
                i, j = sample['i'], sample['j']
                x1 = i * cell_size
                y1 = (sample_size - 1 - j) * cell_size  # Flip Y axis
                x2 = x1 + cell_size
                y2 = y1 + cell_size

                draw.rectangle([x1, y1, x2, y2], fill=color)

        # For other layers, default to grayscale
        else:
            for sample in raster_data:
                val = sample['val']
                if val is None:
                    continue

                # Simple grayscale for now
                gray_val = int(min(255, max(0, val)))
                color = (gray_val, gray_val, gray_val, alpha)

                i, j = sample['i'], sample['j']
                x1 = i * cell_size
                y1 = (sample_size - 1 - j) * cell_size
                x2 = x1 + cell_size
                y2 = y1 + cell_size

                draw.rectangle([x1, y1, x2, y2], fill=color)

        return img

    def _get_elevation_color(
        self,
        elevation_m: float,
        alpha: int,
        elevation_range: Optional[Tuple[Optional[float], Optional[float]]] = None
    ) -> Tuple[int, int, int, int]:
        """
        Get RGBA color for elevation value using dynamic classification

        Colors follow temperature gradient (warmer low → cooler high):
        - Low: Brown (warm, low elevation)
        - Medium-Low: Orange
        - Medium-High: Chartreuse green
        - High: Sky blue (cool, high elevation)
        """
        # Try to use dynamic classification if elevation range is available
        if elevation_range and elevation_range[0] is not None and elevation_range[1] is not None:
            min_elev, max_elev = elevation_range

            # Round to nearest 10 for cleaner values
            min_elev = (min_elev // 10) * 10
            max_elev = ((max_elev + 9) // 10) * 10
            elev_range = max_elev - min_elev

            # Avoid division by zero
            if elev_range < 1:
                elev_range = 1

            # Calculate 4-class breaks (quartiles)
            quarter = elev_range / 4.0
            break1 = min_elev + quarter
            break2 = min_elev + 2 * quarter
            break3 = min_elev + 3 * quarter

            # Apply color based on which quartile the value falls into
            # Using same colors as frontend: #8B4513 (brown), #FFA500 (orange), #7FFF00 (chartreuse), #87CEEB (sky blue)
            if elevation_m < break1:
                # Low: Brown (warm)
                return (139, 69, 19, alpha)  # #8B4513
            elif elevation_m < break2:
                # Medium-Low: Orange
                return (255, 165, 0, alpha)  # #FFA500
            elif elevation_m < break3:
                # Medium-High: Chartreuse (bright green)
                return (127, 255, 0, alpha)  # #7FFF00
            else:
                # High: Sky Blue (cool)
                return (135, 206, 235, alpha)  # #87CEEB

        # Fallback to static classification if no dynamic range available
        if elevation_m < 500:
            return (139, 69, 19, alpha)  # Brown
        elif elevation_m < 1500:
            return (255, 165, 0, alpha)  # Orange
        elif elevation_m < 3000:
            return (127, 255, 0, alpha)  # Chartreuse
        else:
            return (135, 206, 235, alpha)  # Sky Blue

    def _get_canopy_color(self, canopy_height_m: float, alpha: int) -> Tuple[int, int, int, int]:
        """
        Get RGBA color for canopy height using ABSOLUTE ecological thresholds

        Colors follow ecological meaning (red = sparse/degraded, green = healthy/mature):
        - 0-5m: Crimson Red (Sparse/Regeneration)
        - 5-15m: Dark Orange (Young Forest)
        - 15-30m: Light Green (Mature Forest)
        - >30m: Forest Green (Old Growth)
        """
        # Absolute ecological classification (based on forestry science)
        if canopy_height_m < 5:
            # Sparse/Regeneration: Crimson Red
            return (220, 20, 60, alpha)  # #DC143C
        elif canopy_height_m < 15:
            # Young Forest: Dark Orange
            return (255, 140, 0, alpha)  # #FF8C00
        elif canopy_height_m < 30:
            # Mature Forest: Light Green
            return (144, 238, 144, alpha)  # #90EE90
        else:
            # Old Growth: Forest Green
            return (34, 139, 34, alpha)  # #228B22

    def _get_biomass_color(self, biomass_mg_ha: float, alpha: int) -> Tuple[int, int, int, int]:
        """
        Get RGBA color for biomass (AGB) value

        Biomass raster contains actual values in Mg/ha:
        Color gradient: Red (low) → Yellow → Light Green → Green → Blue (very high)
        - 0-50: Very Low → Red
        - 50-100: Low → Yellow
        - 100-200: Medium → Light Green
        - 200-300: High → Green
        - >300: Very High → Blue
        """
        if biomass_mg_ha < 50:
            # Very Low: Crimson Red
            return (220, 20, 60, alpha)  # #DC143C
        elif biomass_mg_ha < 100:
            # Low: Gold/Yellow
            return (255, 215, 0, alpha)  # #FFD700
        elif biomass_mg_ha < 200:
            # Medium: Light Green
            return (144, 238, 144, alpha)  # #90EE90
        elif biomass_mg_ha < 300:
            # High: Forest Green
            return (34, 139, 34, alpha)  # #228B22
        else:
            # Very High: Dodger Blue
            return (30, 144, 255, alpha)  # #1E90FF

    def _get_temperature_color(self, temp_celsius: float, alpha: int) -> Tuple[int, int, int, int]:
        """
        Get RGBA color for temperature value

        Temperature raster contains mean annual temperature in °C:
        - <0: Very Cold → Blue
        - 0-10: Cold → Light Blue
        - 10-20: Moderate → Light Green
        - 20-25: Warm → Gold
        - >25: Hot → Orange Red
        """
        if temp_celsius < 0:
            # Very Cold: Blue
            return (0, 0, 255, alpha)  # #0000FF
        elif temp_celsius < 10:
            # Cold: Deep Sky Blue
            return (0, 191, 255, alpha)  # #00BFFF
        elif temp_celsius < 20:
            # Moderate: Light Green
            return (144, 238, 144, alpha)  # #90EE90
        elif temp_celsius < 25:
            # Warm: Gold
            return (255, 215, 0, alpha)  # #FFD700
        else:
            # Hot: Orange Red
            return (255, 69, 0, alpha)  # #FF4500

    def _get_precipitation_color(self, precip_mm: float, alpha: int) -> Tuple[int, int, int, int]:
        """
        Get RGBA color for precipitation value

        Precipitation raster contains annual precipitation in mm:
        - <500: Very Dry → Brown
        - 500-1000: Dry → Tan
        - 1000-2000: Moderate → Light Green
        - 2000-3000: Wet → Royal Blue
        - >3000: Very Wet → Dark Blue
        """
        if precip_mm < 500:
            # Very Dry: Saddle Brown
            return (139, 69, 19, alpha)  # #8B4513
        elif precip_mm < 1000:
            # Dry: Tan
            return (210, 180, 140, alpha)  # #D2B48C
        elif precip_mm < 2000:
            # Moderate: Light Green
            return (144, 238, 144, alpha)  # #90EE90
        elif precip_mm < 3000:
            # Wet: Royal Blue
            return (65, 105, 225, alpha)  # #4169E1
        else:
            # Very Wet: Medium Blue
            return (0, 0, 205, alpha)  # #0000CD

    def _get_slope_color(self, slope_value: float, alpha: int) -> Tuple[int, int, int, int]:
        """
        Get RGBA color for slope value

        Slope raster contains CATEGORICAL CODES (not degrees):
        0 = No data / Water (excluded)
        1 = <19° (Gentle) → GREEN
        2 = 19-31° (Moderate) → YELLOW
        3 = 31-45° (Steep) → ORANGE
        4 = >45° (Very Steep) → RED
        """
        # Map categorical codes to colors
        slope_code = int(slope_value)

        if slope_code == 1:
            # Gentle <19°: Green
            return (46, 204, 113, alpha)  # #2ECC71
        elif slope_code == 2:
            # Moderate 19-31°: Yellow
            return (241, 196, 15, alpha)  # #F1C40F
        elif slope_code == 3:
            # Steep 31-45°: Orange
            return (230, 126, 34, alpha)  # #E67E22
        elif slope_code == 4:
            # Very Steep >45°: Red
            return (231, 76, 60, alpha)  # #E74C3C
        else:
            # Fallback: Green (for code 0 or invalid)
            return (46, 204, 113, alpha)

    def _get_forest_health_color(self, health_value: float, alpha: int) -> Tuple[int, int, int, int]:
        """
        Get RGBA color for forest health value (based on NDVI)

        Forest health categorical codes (from rasters.nepal_forest_health):
        1 = Stressed (NDVI < 0.2) → RED (worst)
        2 = Poor (NDVI 0.2-0.4) → ORANGE
        3 = Moderate (NDVI 0.4-0.6) → GOLD/YELLOW
        4 = Healthy (NDVI 0.6-0.8) → LIGHT GREEN
        5 = Excellent (NDVI > 0.8) → DARK GREEN (best)
        """
        health_code = int(health_value)

        if health_code == 1:
            # Stressed: Crimson Red (lowest NDVI, worst health)
            return (220, 20, 60, alpha)  # #DC143C
        elif health_code == 2:
            # Poor: Dark Orange
            return (255, 140, 0, alpha)  # #FF8C00
        elif health_code == 3:
            # Moderate: Gold
            return (255, 215, 0, alpha)  # #FFD700
        elif health_code == 4:
            # Healthy: Light Green
            return (144, 238, 144, alpha)  # #90EE90
        elif health_code == 5:
            # Excellent: Forest Green (highest NDVI, best health)
            return (34, 139, 34, alpha)  # #228B22
        else:
            # Fallback: Light Green
            return (144, 238, 144, alpha)

    def _get_min_temp_color(self, temp_celsius: float, alpha: int) -> Tuple[int, int, int, int]:
        """
        Get RGBA color for minimum temperature (coldest month)

        Temperature ranges in °C:
        < -10: Extreme Cold → Dark Blue
        -10 to 0: Very Cold → Royal Blue
        0 to 5: Cold → Sky Blue
        5 to 10: Cool → Light Green
        10 to 15: Mild → Gold
        > 15: Warm → Orange
        """
        if temp_celsius < -10:
            # Extreme Cold: Medium Blue
            return (0, 0, 205, alpha)  # #0000CD
        elif temp_celsius < 0:
            # Very Cold: Royal Blue
            return (65, 105, 225, alpha)  # #4169E1
        elif temp_celsius < 5:
            # Cold: Sky Blue
            return (135, 206, 235, alpha)  # #87CEEB
        elif temp_celsius < 10:
            # Cool: Light Green
            return (144, 238, 144, alpha)  # #90EE90
        elif temp_celsius < 15:
            # Mild: Gold
            return (255, 215, 0, alpha)  # #FFD700
        else:
            # Warm: Dark Orange
            return (255, 140, 0, alpha)  # #FF8C00

    def _get_nasa_forest_color(self, forest_class: float, alpha: int) -> Tuple[int, int, int, int]:
        """
        Get RGBA color for NASA Forest 2020 classification

        Official NASA/ORNL DAAC color scheme for IPCC Tier 1 forest quality:
        0 = Non-forest (transparent/skip)
        1 = Primary Forest → Bright Green #00FF00 (old-growth, highest biomass)
        2 = Young Secondary Forest → Red #FF0000 (recently regenerated, low biomass)
        3 = Old Secondary Forest → Blue-Purple #6666FF (mature regrowth, medium-high biomass)

        Primary forests have 2-3x higher carbon stocks than secondary forests.
        Critical for IPCC reporting and conservation prioritization.
        """
        forest_code = int(forest_class)

        if forest_code == 1:
            # Primary Forest: Bright Green (pristine, highest carbon)
            return (0, 255, 0, alpha)  # #00FF00
        elif forest_code == 2:
            # Young Secondary: Red (regenerating, low carbon)
            return (255, 0, 0, alpha)  # #FF0000
        elif forest_code == 3:
            # Old Secondary: Blue-Purple (mature regrowth, medium carbon)
            return (102, 102, 255, alpha)  # #6666FF
        else:
            # Non-forest (0) or invalid: Skip/transparent
            # Return transparent color so it doesn't render
            return (0, 0, 0, 0)  # Fully transparent

    def _get_forest_type_color(self, forest_type_class: float, alpha: int) -> Tuple[int, int, int, int]:
        """
        Get RGBA color for Forest Type (FRTC) classification.

        Uses centralized SSOT (app/core/forest_types.py) for color values.
        """
        forest_code = int(forest_type_class)
        hex_color = get_forest_type_color(forest_code)
        r = int(hex_color[1:3], 16)
        g = int(hex_color[3:5], 16)
        b = int(hex_color[5:7], 16)
        return (r, g, b, alpha)

    def _get_fire_loss_color(self, fire_year_code: float, alpha: int) -> Tuple[int, int, int, int]:
        """
        Get RGBA color for Fire Loss year (Hansen GFC)

        Fire-specific temporal gradient from 2001-2024:
        - 2001-2008: Dark Orange (old burns, forest recovering)
        - 2009-2016: Orange-Red (mid burns)
        - 2017-2024: Dark Red (recent burns, need restoration)

        Emphasizes recent fires with darker red for restoration prioritization
        """
        year_code = int(fire_year_code)

        if 1 <= year_code <= 8:
            # 2001-2008: Dark Orange (old burns)
            return (255, 140, 0, alpha)  # #FF8C00
        elif 9 <= year_code <= 16:
            # 2009-2016: Orange-Red (mid burns)
            return (255, 69, 0, alpha)  # #FF4500
        elif 17 <= year_code <= 24:
            # 2017-2024: Dark Red (recent burns - restoration priority)
            return (139, 0, 0, alpha)  # #8B0000
        else:
            # No fire loss or invalid: Transparent
            return (0, 0, 0, 0)

    def _get_forest_loss_color(self, loss_year_code: float, alpha: int) -> Tuple[int, int, int, int]:
        """
        Get RGBA color for Forest Loss year (Hansen GFC)

        Temporal gradient from 2001-2024 (codes 1-24):
        - 2001-2004 (codes 1-4): Light Yellow → Yellow (old loss)
        - 2005-2008 (codes 5-8): Yellow → Orange
        - 2009-2012 (codes 9-12): Orange → Orange-Red
        - 2013-2016 (codes 13-16): Orange-Red → Red
        - 2017-2020 (codes 17-20): Red → Dark Red
        - 2021-2024 (codes 21-24): Dark Red → Very Dark Red (recent loss)

        Gradient: Older loss = lighter/yellower, Recent loss = darker/redder
        """
        year_code = int(loss_year_code)

        # Map year code (1-24) to actual year (2001-2024)
        # Then create gradient based on age of loss

        if 1 <= year_code <= 4:
            # 2001-2004: Light Yellow → Yellow
            position = (year_code - 1) / 3.0
            r = 255
            g = int(250 - (35 * position))  # 250 → 215
            b = int(205 - (205 * position))  # 205 → 0
            return (r, g, b, alpha)  # #FFFACD → #FFD700

        elif 5 <= year_code <= 8:
            # 2005-2008: Yellow → Orange
            position = (year_code - 5) / 3.0
            r = 255
            g = int(215 - (75 * position))  # 215 → 140
            b = 0
            return (r, g, b, alpha)  # #FFD700 → #FF8C00

        elif 9 <= year_code <= 12:
            # 2009-2012: Orange → Orange-Red
            position = (year_code - 9) / 3.0
            r = 255
            g = int(140 - (41 * position))  # 140 → 99
            b = int(0 + (71 * position))  # 0 → 71
            return (r, g, b, alpha)  # #FF8C00 → #FF6347

        elif 13 <= year_code <= 16:
            # 2013-2016: Orange-Red → Red
            position = (year_code - 13) / 3.0
            r = int(255 - (35 * position))  # 255 → 220
            g = int(99 - (79 * position))  # 99 → 20
            b = int(71 - (11 * position))  # 71 → 60
            return (r, g, b, alpha)  # #FF6347 → #DC143C

        elif 17 <= year_code <= 20:
            # 2017-2020: Red → Dark Red
            position = (year_code - 17) / 3.0
            r = int(220 - (42 * position))  # 220 → 178
            g = int(20 - (10 * position))  # 20 → 10 (actually goes to 34 in #B22222)
            b = int(60 - (26 * position))  # 60 → 34
            return (r, g, b, alpha)  # #DC143C → #B22222

        elif 21 <= year_code <= 24:
            # 2021-2024: Dark Red → Very Dark Red (most recent)
            position = (year_code - 21) / 3.0
            r = int(178 - (39 * position))  # 178 → 139
            g = int(34 - (34 * position))  # 34 → 0
            b = int(34 - (34 * position))  # 34 → 0
            return (r, g, b, alpha)  # #B22222 → #8B0000

        else:
            # No loss or invalid: Transparent
            return (0, 0, 0, 0)

    def _get_landcover_color(self, landcover_class: float, alpha: int) -> Tuple[int, int, int, int]:
        """
        Get RGBA color for ESA WorldCover 2021 classification

        Official ESA WorldCover color scheme (11 classes):
        10 = Tree Cover → #006400 (Dark Green)
        20 = Shrubland → #FFBB22 (Yellow-Orange)
        30 = Grassland → #FFFF4C (Yellow)
        40 = Cropland → #F096FF (Pink-Purple)
        50 = Built-up → #FA0000 (Red)
        60 = Bare/Sparse Vegetation → #B4B4B4 (Gray)
        70 = Snow and Ice → #F0F0F0 (Light Gray)
        80 = Water Bodies → #0064C8 (Blue)
        90 = Herbaceous Wetland → #0096A0 (Cyan)
        95 = Mangroves → #00CF75 (Teal-Green)
        100 = Moss and Lichen → #FAE6A0 (Tan)

        Colors are official ESA standard for global consistency
        """
        landcover_code = int(landcover_class)

        if landcover_code == 10:
            # Tree Cover: Dark Green
            return (0, 100, 0, alpha)  # #006400
        elif landcover_code == 20:
            # Shrubland: Yellow-Orange
            return (255, 187, 34, alpha)  # #FFBB22
        elif landcover_code == 30:
            # Grassland: Yellow
            return (255, 255, 76, alpha)  # #FFFF4C
        elif landcover_code == 40:
            # Cropland: Pink-Purple
            return (240, 150, 255, alpha)  # #F096FF
        elif landcover_code == 50:
            # Built-up: Red
            return (250, 0, 0, alpha)  # #FA0000
        elif landcover_code == 60:
            # Bare/Sparse Vegetation: Gray
            return (180, 180, 180, alpha)  # #B4B4B4
        elif landcover_code == 70:
            # Snow and Ice: Light Gray
            return (240, 240, 240, alpha)  # #F0F0F0
        elif landcover_code == 80:
            # Water Bodies: Blue
            return (0, 100, 200, alpha)  # #0064C8
        elif landcover_code == 90:
            # Herbaceous Wetland: Cyan
            return (0, 150, 160, alpha)  # #0096A0
        elif landcover_code == 95:
            # Mangroves: Teal-Green
            return (0, 207, 117, alpha)  # #00CF75
        elif landcover_code == 100:
            # Moss and Lichen: Tan
            return (250, 230, 160, alpha)  # #FAE6A0
        else:
            # Unknown/No data: Transparent
            return (0, 0, 0, 0)

    def _get_soil_ph_color(self, ph_value: float, alpha: int) -> Tuple[int, int, int, int]:
        """
        Get RGBA color for Soil pH (0-30cm depth)

        pH scale classification:
        <4.5: Extremely Acidic → Dark Red
        4.5-5.5: Strongly Acidic → Orange
        5.5-6.5: Slightly Acidic → Yellow-Gold
        6.5-7.5: Neutral (Optimal) → Green
        7.5-8.5: Slightly Alkaline → Light Blue
        >8.5: Strongly Alkaline → Purple
        """
        # SoilGrids pH is in pH units (0-14, but typically 3-9 for soils)
        ph = ph_value / 10.0 if ph_value > 14 else ph_value  # Handle scaled values

        if ph < 4.5:
            # Extremely Acidic: Crimson Red (poor for most crops)
            return (220, 20, 60, alpha)  # #DC143C
        elif ph < 5.5:
            # Strongly Acidic: Dark Orange
            return (255, 140, 0, alpha)  # #FF8C00
        elif ph < 6.5:
            # Slightly Acidic: Gold
            return (255, 215, 0, alpha)  # #FFD700
        elif ph < 7.5:
            # Neutral (Optimal): Green
            return (34, 139, 34, alpha)  # #228B22
        elif ph < 8.5:
            # Slightly Alkaline: Light Blue
            return (70, 130, 180, alpha)  # #4682B4
        else:
            # Strongly Alkaline: Medium Purple
            return (147, 112, 219, alpha)  # #9370DB

    def _get_soil_texture_color(self, texture_code: float, alpha: int) -> Tuple[int, int, int, int]:
        """
        Get RGBA color for Soil Texture (USDA 12-class)

        Based on clay/sand/silt content:
        - Clay dominant: Dark brown
        - Loam (balanced): Medium brown (optimal)
        - Sand dominant: Light tan
        """
        # Simplified texture visualization (actual texture requires 3 bands: clay, sand, silt)
        # For now, use a brown-tan gradient
        code = int(texture_code)

        # Map texture codes to colors (approximate)
        if code <= 3:
            # Clay, Silty Clay, Sandy Clay: Dark Brown
            return (101, 67, 33, alpha)  # #654321
        elif code <= 6:
            # Clay Loam, Silty Clay Loam, Sandy Clay Loam: Brown
            return (139, 69, 19, alpha)  # #8B4513
        elif code <= 9:
            # Loam, Silt Loam, Sandy Loam: Medium Brown (optimal)
            return (160, 82, 45, alpha)  # #A0522D
        else:
            # Sand, Loamy Sand, Silt: Tan
            return (210, 180, 140, alpha)  # #D2B48C

    def _get_soil_carbon_color(self, soc_value: float, alpha: int) -> Tuple[int, int, int, int]:
        """
        Get RGBA color for Soil Organic Carbon (0-30cm)

        SOC classification (as percentage):
        <0.5%: Very Low → Red
        0.5-1.0%: Low → Orange
        1.0-2.0%: Medium → Yellow
        2.0-3.0%: High → Light Green
        >3.0%: Very High (Forest soils) → Dark Green
        """
        # SoilGrids SOC is in dg/kg, convert to percentage (1 dg/kg = 0.1%)
        soc_percent = soc_value / 10.0 if soc_value > 10 else soc_value

        if soc_percent < 0.5:
            # Very Low: Crimson Red (poor soil health)
            return (220, 20, 60, alpha)  # #DC143C
        elif soc_percent < 1.0:
            # Low: Dark Orange
            return (255, 140, 0, alpha)  # #FF8C00
        elif soc_percent < 2.0:
            # Medium: Gold
            return (255, 215, 0, alpha)  # #FFD700
        elif soc_percent < 3.0:
            # High: Light Green
            return (144, 238, 144, alpha)  # #90EE90
        else:
            # Very High: Forest Green (excellent soil health)
            return (34, 139, 34, alpha)  # #228B22

    def _get_soil_fertility_color(self, fertility_score: float, alpha: int) -> Tuple[int, int, int, int]:
        """
        Get RGBA color for Soil Fertility Index (derived from pH + SOC + N + CEC)

        Fertility score (0-100):
        0-20: Very Low → Red
        20-40: Low → Orange
        40-60: Medium → Yellow
        60-80: High → Light Green
        80-100: Very High → Dark Green
        """
        # Normalize score to 0-100 if needed
        score = min(max(fertility_score, 0), 100)

        if score < 20:
            # Very Low: Crimson Red
            return (220, 20, 60, alpha)  # #DC143C
        elif score < 40:
            # Low: Dark Orange
            return (255, 140, 0, alpha)  # #FF8C00
        elif score < 60:
            # Medium: Gold
            return (255, 215, 0, alpha)  # #FFD700
        elif score < 80:
            # High: Light Green
            return (144, 238, 144, alpha)  # #90EE90
        else:
            # Very High: Forest Green
            return (34, 139, 34, alpha)  # #228B22

    def _get_soil_density_color(self, bulk_density: float, alpha: int) -> Tuple[int, int, int, int]:
        """
        Get RGBA color for Bulk Density (compaction risk)

        Bulk density in g/cm³ (SoilGrids in cg/cm³, divide by 100):
        <1.2: Low (Good) → Green
        1.2-1.4: Moderate → Yellow
        1.4-1.6: Elevated → Orange
        >1.6: High Risk → Red (restrictive for roots)
        """
        # SoilGrids bulk density is in cg/cm³, convert to g/cm³
        density_g_cm3 = bulk_density / 100.0 if bulk_density > 10 else bulk_density

        if density_g_cm3 < 1.2:
            # Low (Good): Green - good soil structure
            return (34, 139, 34, alpha)  # #228B22
        elif density_g_cm3 < 1.4:
            # Moderate: Gold - acceptable
            return (255, 215, 0, alpha)  # #FFD700
        elif density_g_cm3 < 1.6:
            # Elevated: Dark Orange - concern
            return (255, 140, 0, alpha)  # #FF8C00
        else:
            # High Risk: Crimson Red - restrictive for roots
            return (220, 20, 60, alpha)  # #DC143C

    def _render_png(self, image: Image.Image) -> bytes:
        """
        Render PIL Image as PNG bytes
        """
        buffer = io.BytesIO()
        image.save(buffer, format='PNG', optimize=True)
        buffer.seek(0)
        return buffer.read()

    # ============================================================================
    # User Group Extent Tile Methods
    # ============================================================================

    # business: user group extent tiles with optional forest-overlap exclusion for land-use planning
    def get_user_group_tile(
        self,
        calculation_id: str,
        layer_name: str,
        z: int,
        x: int,
        y: int,
        exclude_forest_overlap: bool = True,
        tile_size: int = 256,
        alpha: int = 180  # Slightly more opaque for better visibility
    ) -> bytes:
        """
        Generate a tile for user group extent with optional forest overlap exclusion

        Args:
            calculation_id: UUID of calculation (linked to user group extent)
            layer_name: Layer identifier (landcover or biomass)
            z: Zoom level
            x: Tile X coordinate
            y: Tile Y coordinate
            exclude_forest_overlap: If True, exclude community forest area (default: True)
            tile_size: Output image size (default 256×256)
            alpha: Transparency (0=transparent, 255=opaque, default 180=70%)

        Returns:
            PNG image bytes
        """
        logger.info(f"[USER_GROUP_TILE] Generating tile: layer={layer_name}, z={z}, x={x}, y={y}")
        logger.info(f"[USER_GROUP_TILE] Exclude forest overlap: {exclude_forest_overlap}")

        # 1. Get tile bounds in lat/lon
        bounds = self.xyz_to_bounds(x, y, z)

        # 2. Get user group extent geometry (with optional forest exclusion)
        try:
            if exclude_forest_overlap:
                extent_wkt = self._get_user_group_net_geometry(calculation_id)
                logger.info(f"[USER_GROUP_TILE] Using net geometry (forest overlap excluded)")
            else:
                extent_wkt = self._get_user_group_extent_geometry(calculation_id)
                logger.info(f"[USER_GROUP_TILE] Using full user group extent")
        except Exception as e:
            logger.error(f"[USER_GROUP_TILE ERROR] Failed to get extent geometry: {e}")
            raise

        # 3. Get raster table
        if layer_name not in self.RASTER_TABLES:
            raise ValueError(f"Unknown layer: {layer_name}")

        raster_table = self.RASTER_TABLES[layer_name]
        logger.info(f"[USER_GROUP_TILE] Using raster table: {raster_table}")

        # Get band number for multi-band rasters
        band_number = self.RASTER_BANDS.get(layer_name)

        # 4. Query raster data for this tile
        raster_data = self._query_raster_tile(
            raster_table,
            bounds,
            extent_wkt,
            tile_size,
            band_number=band_number
        )

        if not raster_data:
            logger.info(f"[USER_GROUP_TILE] No raster data found - returning empty tile")

        # 5. Apply colormap
        colored_tile = self._apply_colormap(raster_data, layer_name, alpha)

        # 6. Render as PNG
        png_bytes = self._render_png(colored_tile)
        logger.info(f"[USER_GROUP_TILE] Generated PNG: {len(png_bytes)} bytes")

        return png_bytes

    def _get_user_group_extent_geometry(self, calculation_id: str) -> str:
        """Get user group extent geometry as WKT"""
        # The UNION of every polygon: a user group can be several polygons (drawn separately or cut apart),
        # and this used to take only the newest one, so the rasters appeared in just that polygon.
        query = text("""
            SELECT ST_AsText(ST_Union(extent_geometry)) as wkt
            FROM public.user_group_extents
            WHERE calculation_id = :calc_id AND extent_geometry IS NOT NULL
            HAVING count(*) > 0
        """)

        result = self.db.execute(query, {"calc_id": calculation_id}).first()

        if not result:
            raise ValueError(f"No user group extent found for calculation {calculation_id}")

        return result.wkt

    def _get_user_group_net_geometry(self, calculation_id: str) -> str:
        """
        Get user group extent with forest overlap excluded (net geometry)
        Returns: WKT of (user_group_extent - forest_boundary)
        """
        query = text("""
            WITH user_extent AS (
                SELECT ST_Union(extent_geometry) AS extent_geometry
                FROM public.user_group_extents
                WHERE calculation_id = :calc_id AND extent_geometry IS NOT NULL
            ),
            forest_boundary AS (
                SELECT boundary_geom
                FROM public.calculations
                WHERE id = :calc_id
            )
            SELECT ST_AsText(
                CASE
                    WHEN ST_Intersects(ue.extent_geometry, fb.boundary_geom) THEN
                        ST_Difference(ue.extent_geometry, fb.boundary_geom)
                    ELSE
                        ue.extent_geometry
                END
            ) as wkt
            FROM user_extent ue, forest_boundary fb
        """)

        result = self.db.execute(query, {"calc_id": calculation_id}).first()

        if not result or not result.wkt:
            # Fallback to full extent if no overlap
            return self._get_user_group_extent_geometry(calculation_id)

        return result.wkt


# NOTE: simple dict-based instance cache — one TileService per db session, not LRU (planned Cache Plan fix)
# Cache for tile service instances
_tile_service_cache = {}

def get_tile_service(db: Session) -> TileService:
    """Get or create TileService instance"""
    # Simple instance cache (one per database session)
    session_id = id(db)
    if session_id not in _tile_service_cache:
        _tile_service_cache[session_id] = TileService(db)
    return _tile_service_cache[session_id]
