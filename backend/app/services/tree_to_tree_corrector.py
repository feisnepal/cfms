"""
Tree-to-Tree Boundary Corrector

Auto-corrects out-of-boundary trees by snapping to nearest valid tree
within 50m radius. This preserves natural forest structure and corrects
likely GPS errors.

Author: Forest Management System
Date: February 14, 2026
"""
# why: reconciles tree assignments when block geometry changes
# constraint: nearest-neighbor assignment within 50m threshold
# NOTE: preserves original tree data, only changes block_id

from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Dict, Tuple, Optional
import pandas as pd
import logging
from shapely import wkt
from shapely.geometry import Point, Polygon, MultiPolygon

logger = logging.getLogger(__name__)


class TreeToTreeCorrector:
    """
    Auto-correct out-of-boundary trees by snapping to nearest valid tree
    within 50m radius.

    This approach is more ecologically realistic than snapping to boundary edges,
    as it preserves natural forest structure and spatial relationships between trees.
    """

    def __init__(self, db: Session):
        self.db = db
        self.max_correction_distance = 50.0  # meters
        self.duplicate_avoidance_offset_min = 1.0  # meters
        self.duplicate_avoidance_offset_max = 2.0  # meters

    def generate_corrections(
        self,
        trees_df: pd.DataFrame,
        boundary_wkt: str,
        calculation_id: str
    ) -> Dict:
        """
        Generate correction plan for out-of-boundary trees.

        Args:
            trees_df: DataFrame with columns [longitude, latitude, row_number]
            boundary_wkt: WKT string of boundary polygon
            calculation_id: UUID of calculation for temp table naming

        Returns:
            {
                'total_trees': int,
                'valid_trees': int,
                'total_out_of_boundary': int,
                'out_of_boundary_percentage': float,
                'correctable': int,
                'uncorrectable': int,
                'corrections': List[Dict],
                'correction_summary': str,
                'recommendation': str
            }
        """

        logger.info(f"Generating tree-to-tree corrections for {len(trees_df)} trees")

        try:
            # Step 1: Create temporary table with all trees
            table_name = self._create_temp_tree_table(trees_df, calculation_id)

            # Step 2: Identify valid and invalid trees
            valid_count, invalid_count = self._classify_trees(table_name, boundary_wkt)

            logger.info(f"Valid trees: {valid_count}, Invalid trees: {invalid_count}")

            if invalid_count == 0:
                # All trees inside boundary
                self._cleanup_temp_table(table_name)
                return {
                    'total_trees': valid_count,
                    'valid_trees': valid_count,
                    'total_out_of_boundary': 0,
                    'out_of_boundary_percentage': 0.0,
                    'correctable': 0,
                    'uncorrectable': 0,
                    'corrections': [],
                    'correction_summary': 'All trees are within the boundary.',
                    'recommendation': 'proceed'
                }

            # Step 3: Find nearest valid tree for each invalid tree
            corrections = self._find_nearest_valid_trees(table_name, boundary_wkt)

            # Step 4: Generate correction report
            report = self._generate_report(corrections, valid_count, invalid_count)

            # Step 5: Cleanup temp table
            self._cleanup_temp_table(table_name)

            logger.info(f"Generated {len(corrections)} corrections: "
                       f"{report['correctable']} correctable, "
                       f"{report['uncorrectable']} uncorrectable")

            return report

        except Exception as e:
            logger.error(f"Error generating tree-to-tree corrections: {str(e)}")
            raise

    def _create_temp_tree_table(self, trees_df: pd.DataFrame, calc_id: str) -> str:
        """Create temporary table with tree locations"""

        # Sanitize calculation ID for table name
        table_name = f"temp_trees_{calc_id.replace('-', '_')}"

        ALLOWED_TABLE_PREFIXES = {"temp_trees_"}
        if not any(table_name.startswith(p) for p in ALLOWED_TABLE_PREFIXES):
            raise ValueError(f"Invalid table name: {table_name}")

        try:
            # Drop table if exists
            drop_sql = text(f"DROP TABLE IF EXISTS {table_name}")
            self.db.execute(drop_sql)

            # Create table
            create_sql = text(f"""
                CREATE TEMP TABLE {table_name} (
                    id SERIAL PRIMARY KEY,
                    row_number INTEGER,
                    longitude DOUBLE PRECISION,
                    latitude DOUBLE PRECISION,
                    location GEOGRAPHY(POINT, 4326)
                )
            """)
            self.db.execute(create_sql)

            # Create spatial index for fast queries
            index_sql = text(f"""
                CREATE INDEX idx_{table_name}_location
                ON {table_name} USING GIST(location)
            """)
            self.db.execute(index_sql)

            # Insert trees
            insert_sql = text(f"""
                INSERT INTO {table_name} (row_number, longitude, latitude, location)
                VALUES (:row_num, :lon, :lat, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography)
            """)

            for idx, row in trees_df.iterrows():
                self.db.execute(insert_sql, {
                    'row_num': int(row['row_number']),
                    'lon': float(row['longitude']),
                    'lat': float(row['latitude'])
                })

            self.db.commit()
            logger.info(f"Created temp table {table_name} with {len(trees_df)} trees")

            return table_name

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error creating temp tree table: {str(e)}")
            raise

    def _classify_trees(self, table_name: str, boundary_wkt: str) -> Tuple[int, int]:
        """
        Classify trees as valid (inside boundary) or invalid (outside boundary).

        Returns:
            (valid_count, invalid_count)
        """

        sql = text(f"""
            WITH boundary AS (
                SELECT ST_GeomFromText(:boundary_wkt, 4326) AS geom
            ),

            valid_trees AS (
                SELECT COUNT(*) as cnt
                FROM {table_name} t, boundary b
                WHERE ST_Contains(b.geom, t.location::geometry)
            ),

            invalid_trees AS (
                SELECT COUNT(*) as cnt
                FROM {table_name} t, boundary b
                WHERE NOT ST_Contains(b.geom, t.location::geometry)
            )

            SELECT
                (SELECT cnt FROM valid_trees) as valid_count,
                (SELECT cnt FROM invalid_trees) as invalid_count
        """)

        result = self.db.execute(sql, {'boundary_wkt': boundary_wkt}).fetchone()

        return (result.valid_count, result.invalid_count)

    def _find_nearest_valid_trees(self, table_name: str, boundary_wkt: str) -> List[Dict]:
        """
        Find nearest valid tree within 50m for each invalid tree.

        Returns list of corrections with:
        - row_number: Original CSV row
        - original_lon, original_lat: Original coordinates
        - target_tree_row: Row number of nearest valid tree
        - corrected_lon, corrected_lat: New coordinates (with offset)
        - distance_moved_m: Distance from original to corrected
        - status: 'corrected' or 'no_neighbor_within_50m'
        """

        sql = text(f"""
            WITH boundary AS (
                SELECT ST_GeomFromText(:boundary_wkt, 4326) AS geom
            ),

            valid_trees AS (
                SELECT t.id, t.row_number, t.location, t.longitude, t.latitude
                FROM {table_name} t, boundary b
                WHERE ST_Contains(b.geom, t.location::geometry)
            ),

            invalid_trees AS (
                SELECT t.id, t.row_number, t.location, t.longitude, t.latitude
                FROM {table_name} t, boundary b
                WHERE NOT ST_Contains(b.geom, t.location::geometry)
            ),

            nearest_matches AS (
                SELECT
                    inv.row_number AS invalid_row,
                    inv.longitude AS original_lon,
                    inv.latitude AS original_lat,
                    inv.location AS original_location,

                    -- Find nearest valid tree within 50m
                    (
                        SELECT v.row_number
                        FROM valid_trees v
                        WHERE ST_DWithin(inv.location, v.location, :max_distance)
                        ORDER BY ST_Distance(inv.location, v.location)
                        LIMIT 1
                    ) AS target_tree_row,

                    (
                        SELECT v.location
                        FROM valid_trees v
                        WHERE ST_DWithin(inv.location, v.location, :max_distance)
                        ORDER BY ST_Distance(inv.location, v.location)
                        LIMIT 1
                    ) AS target_location,

                    (
                        SELECT ST_Distance(inv.location, v.location)
                        FROM valid_trees v
                        WHERE ST_DWithin(inv.location, v.location, :max_distance)
                        ORDER BY ST_Distance(inv.location, v.location)
                        LIMIT 1
                    ) AS distance_to_target

                FROM invalid_trees inv
            )

            SELECT
                invalid_row AS row_number,
                original_lon,
                original_lat,
                target_tree_row,

                -- Generate corrected position with random 1-2m offset to avoid duplicates
                CASE
                    WHEN target_location IS NOT NULL THEN
                        ST_X(
                            ST_Project(
                                target_location,
                                random() * (:offset_max - :offset_min) + :offset_min,  -- Random 1-2 meters
                                radians(random() * 360)  -- Random direction 0-360 degrees
                            )::geometry
                        )
                    ELSE NULL
                END AS corrected_lon,

                CASE
                    WHEN target_location IS NOT NULL THEN
                        ST_Y(
                            ST_Project(
                                target_location,
                                random() * (:offset_max - :offset_min) + :offset_min,
                                radians(random() * 360)
                            )::geometry
                        )
                    ELSE NULL
                END AS corrected_lat,

                distance_to_target AS distance_moved_m,

                CASE
                    WHEN target_tree_row IS NULL THEN 'no_neighbor_within_50m'
                    ELSE 'corrected'
                END AS status

            FROM nearest_matches
            ORDER BY invalid_row
        """)

        result = self.db.execute(sql, {
            'boundary_wkt': boundary_wkt,
            'max_distance': self.max_correction_distance,
            'offset_min': self.duplicate_avoidance_offset_min,
            'offset_max': self.duplicate_avoidance_offset_max
        })

        corrections = []
        for row in result:
            corrections.append({
                'row_number': row.row_number,
                'original_coords': [row.original_lon, row.original_lat],
                'corrected_coords': (
                    [row.corrected_lon, row.corrected_lat]
                    if row.corrected_lon else None
                ),
                'snapped_to_tree_row': row.target_tree_row,
                'distance_moved_m': round(row.distance_moved_m, 2) if row.distance_moved_m else None,
                'status': row.status
            })

        return corrections

    def _generate_report(
        self,
        corrections: List[Dict],
        valid_count: int,
        invalid_count: int
    ) -> Dict:
        """Generate summary report"""

        correctable = sum(1 for c in corrections if c['status'] == 'corrected')
        uncorrectable = sum(1 for c in corrections if c['status'] == 'no_neighbor_within_50m')

        total_trees = valid_count + invalid_count
        invalid_percentage = (invalid_count / total_trees * 100) if total_trees > 0 else 0

        # Generate summary message
        summary_parts = []
        summary_parts.append(
            f"{invalid_count} trees ({invalid_percentage:.1f}%) are outside the boundary."
        )

        if correctable > 0:
            summary_parts.append(
                f"{correctable} can be auto-corrected by snapping to nearest tree within 50 meters."
            )

        if uncorrectable > 0:
            summary_parts.append(
                f"{uncorrectable} trees have no valid neighbor within 50m and cannot be auto-corrected."
            )

        summary = " ".join(summary_parts)

        # Determine recommendation
        recommendation = self._get_recommendation(
            invalid_percentage, correctable, uncorrectable
        )

        return {
            'total_trees': total_trees,
            'valid_trees': valid_count,
            'total_out_of_boundary': invalid_count,
            'out_of_boundary_percentage': round(invalid_percentage, 2),
            'correctable': correctable,
            'uncorrectable': uncorrectable,
            'corrections': corrections,
            'correction_summary': summary,
            'recommendation': recommendation,
            'correction_method': 'nearest_tree'
        }

    def _get_recommendation(
        self,
        invalid_pct: float,
        correctable: int,
        uncorrectable: int
    ) -> str:
        """
        Determine recommendation based on analysis.

        Returns:
            - 'proceed': All good, can proceed without corrections
            - 'auto_correct_all': Can auto-correct all invalid trees
            - 'auto_correct_partial': Can correct some, but some uncorrectable
            - 'review_needed': Too many uncorrectable trees, needs review
            - 'reject': More than 20% outside boundary
        """

        if invalid_pct == 0:
            return "proceed"
        elif invalid_pct > 20.0:
            return "reject"
        elif uncorrectable == 0:
            return "auto_correct_all"
        elif uncorrectable <= correctable * 0.1:  # Less than 10% uncorrectable
            return "auto_correct_partial"
        else:
            return "review_needed"

    def _cleanup_temp_table(self, table_name: str):
        """Drop temporary table"""
        ALLOWED_TABLE_PREFIXES = {"temp_trees_"}
        if not any(table_name.startswith(p) for p in ALLOWED_TABLE_PREFIXES):
            raise ValueError(f"Invalid table name: {table_name}")
        try:
            sql = text(f"DROP TABLE IF EXISTS {table_name}")
            self.db.execute(sql)
            self.db.commit()
            logger.info(f"Cleaned up temp table {table_name}")
        except Exception as e:
            logger.warning(f"Error cleaning up temp table: {str(e)}")

    def apply_corrections(
        self,
        trees_df: pd.DataFrame,
        corrections: List[Dict]
    ) -> pd.DataFrame:
        """
        Apply corrections to DataFrame.

        Updates longitude/latitude columns and adds metadata columns:
        - was_corrected: Boolean
        - original_longitude, original_latitude: Original values
        - correction_method: 'nearest_tree' or None
        - snapped_to_tree_row: Row number of target tree
        - distance_moved_m: Distance moved in meters
        """

        # Create correction lookup by row_number
        correction_map = {c['row_number']: c for c in corrections}

        # Add metadata columns if they don't exist
        if 'was_corrected' not in trees_df.columns:
            trees_df['was_corrected'] = False
        if 'original_longitude' not in trees_df.columns:
            trees_df['original_longitude'] = trees_df['longitude']
        if 'original_latitude' not in trees_df.columns:
            trees_df['original_latitude'] = trees_df['latitude']
        if 'correction_method' not in trees_df.columns:
            trees_df['correction_method'] = None
        if 'snapped_to_tree_row' not in trees_df.columns:
            trees_df['snapped_to_tree_row'] = None
        if 'distance_moved_m' not in trees_df.columns:
            trees_df['distance_moved_m'] = None

        # Apply corrections
        corrections_applied = 0
        for idx, row in trees_df.iterrows():
            row_num = int(row['row_number'])

            if row_num in correction_map:
                correction = correction_map[row_num]

                if correction['status'] == 'corrected' and correction['corrected_coords']:
                    trees_df.at[idx, 'longitude'] = correction['corrected_coords'][0]
                    trees_df.at[idx, 'latitude'] = correction['corrected_coords'][1]
                    trees_df.at[idx, 'was_corrected'] = True
                    trees_df.at[idx, 'correction_method'] = 'nearest_tree'
                    trees_df.at[idx, 'snapped_to_tree_row'] = correction['snapped_to_tree_row']
                    trees_df.at[idx, 'distance_moved_m'] = correction['distance_moved_m']
                    corrections_applied += 1

        logger.info(f"Applied {corrections_applied} tree-to-tree corrections to DataFrame")

        return trees_df
