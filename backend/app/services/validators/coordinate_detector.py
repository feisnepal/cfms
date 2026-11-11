"""
Coordinate column detection and CRS identification
Handles various column naming conventions and coordinate reference systems
"""
from typing import Tuple, Dict, Optional, List
import numpy as np
import pandas as pd


class CoordinateDetector:
    """Detects coordinate columns and CRS from data"""

    # Column name aliases
    LONGITUDE_ALIASES = [
        'longitude', 'long', 'lon', 'lng',
        'x', 'easting', 'east',
        'coord_x', 'x_coord', 'long_dd', 'lon_dd',
        'देशान्तर', 'देशान्तर रेखा', 'देशांतर', 'देशान्तर रेखांश',
        'लङ्गीट्यूड', 'लांगिच्यूड',
    ]

    LATITUDE_ALIASES = [
        'latitude', 'lat',
        'y', 'northing', 'north',
        'coord_y', 'y_coord', 'lat_dd',
        'अक्षाँस', 'अक्षांश', 'अक्षांश रेखा', 'अक्षाश',
        'अक्षांश रेखांश', 'ल्याटिच्यूड', 'लाटिट्यूड',
    ]

    # Nepal bounds for validation
    NEPAL_BOUNDS = {
        'geographic': {
            'lon_min': 80.0, 'lon_max': 88.3,
            'lat_min': 26.3, 'lat_max': 30.5
        },
        'utm_44n': {
            'x_min': 200000, 'x_max': 700000,
            'y_min': 2800000, 'y_max': 3500000
        },
        'utm_45n': {
            'x_min': 200000, 'x_max': 900000,
            'y_min': 2800000, 'y_max': 3500000
        }
    }

    def detect_coordinate_columns(
        self,
        df: pd.DataFrame
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Detect X and Y coordinate columns

        Args:
            df: DataFrame to search

        Returns:
            Tuple of (x_column, y_column) or (None, None)
        """
        columns_lower = {col.lower(): col for col in df.columns}

        # Try to find longitude/X
        x_col = None
        for alias in self.LONGITUDE_ALIASES:
            if alias in columns_lower:
                x_col = columns_lower[alias]
                break

        # Try to find latitude/Y
        y_col = None
        for alias in self.LATITUDE_ALIASES:
            if alias in columns_lower:
                y_col = columns_lower[alias]
                break

        return x_col, y_col

    def detect_crs(
        self,
        x_values: np.ndarray,
        y_values: np.ndarray
    ) -> Dict:
        """
        Detect CRS from coordinate values

        Args:
            x_values: X/Longitude coordinates
            y_values: Y/Latitude coordinates

        Returns:
            Dict with 'epsg', 'name', 'confidence', 'method'
        """
        # A blank cell reads as NaN, and min()/max() of an array holding even one NaN is NaN
        # -- every range test below then fails and a perfectly good file reports "could not
        # detect CRS". Detect from the usable coordinates only; rows without them are
        # reported separately by the validator and skipped when the trees are stored.
        x_all = pd.to_numeric(pd.Series(np.ravel(x_values)), errors='coerce').to_numpy(dtype=float)
        y_all = pd.to_numeric(pd.Series(np.ravel(y_values)), errors='coerce').to_numpy(dtype=float)
        usable = np.isfinite(x_all) & np.isfinite(y_all)
        if not usable.any():
            return {
                'epsg': 'UNKNOWN',
                'confidence': 'none',
                'message': 'No usable coordinates (all blank or not numbers)',
            }
        x_values, y_values = x_all[usable], y_all[usable]

        x_min, x_max = np.min(x_values), np.max(x_values)
        y_min, y_max = np.min(y_values), np.max(y_values)
        x_mean = np.mean(x_values)

        # Test 1: Geographic coordinates (WGS84)
        geo = self.NEPAL_BOUNDS['geographic']
        if (geo['lon_min'] <= x_min <= geo['lon_max'] and
            geo['lon_min'] <= x_max <= geo['lon_max'] and
            geo['lat_min'] <= y_min <= geo['lat_max'] and
            geo['lat_min'] <= y_max <= geo['lat_max']):

            return {
                'epsg': 4326,
                'name': 'WGS84 (Geographic)',
                'confidence': 'high',
                'method': 'Nepal geographic bounds',
                'detected_range': {
                    'x': [float(x_min), float(x_max)],
                    'y': [float(y_min), float(y_max)]
                }
            }

        # Test 2: Check if coordinates are swapped
        if (geo['lon_min'] <= y_min <= geo['lon_max'] and
            geo['lat_min'] <= x_min <= geo['lat_max']):

            return {
                'epsg': 'UNKNOWN',
                'error': 'coordinates_swapped',
                'message': 'X and Y coordinates appear to be swapped',
                'confidence': 'error',
                'suggestion': 'Please swap longitude and latitude columns'
            }

        # Test 3: UTM Zone 44N (Western Nepal)
        utm44 = self.NEPAL_BOUNDS['utm_44n']
        if (utm44['x_min'] <= x_min <= utm44['x_max'] and
            utm44['y_min'] <= y_min <= utm44['y_max']):

            return {
                'epsg': 32644,
                'name': 'WGS84 / UTM Zone 44N',
                'confidence': 'high',
                'method': 'UTM 44N bounds (Western Nepal)',
                'detected_range': {
                    'x': [float(x_min), float(x_max)],
                    'y': [float(y_min), float(y_max)]
                }
            }

        # Test 4: UTM Zone 45N (Eastern Nepal)
        utm45 = self.NEPAL_BOUNDS['utm_45n']
        if (utm45['x_min'] <= x_min <= utm45['x_max'] and
            utm45['y_min'] <= y_min <= utm45['y_max']):

            return {
                'epsg': 32645,
                'name': 'WGS84 / UTM Zone 45N',
                'confidence': 'high',
                'method': 'UTM 45N bounds (Eastern Nepal)',
                'detected_range': {
                    'x': [float(x_min), float(x_max)],
                    'y': [float(y_min), float(y_max)]
                }
            }

        # Unknown CRS
        return {
            'epsg': 'UNKNOWN',
            'confidence': 'none',
            'message': 'Could not detect CRS from coordinate values',
            'detected_range': {
                'x': [float(x_min), float(x_max)],
                'y': [float(y_min), float(y_max)]
            }
        }

    def validate_crs(
        self,
        x_values: np.ndarray,
        y_values: np.ndarray,
        user_specified_crs: int
    ) -> Dict:
        """
        Validate user-specified CRS against detected CRS

        Args:
            x_values: X coordinates
            y_values: Y coordinates
            user_specified_crs: EPSG code specified by user

        Returns:
            Dict with validation results
        """
        detected = self.detect_crs(x_values, y_values)

        if detected.get('epsg') == 'UNKNOWN':
            return {
                'status': 'warning',
                'message': 'Could not auto-detect CRS. Using user-specified.',
                'user_specified': user_specified_crs,
                'detected': None
            }

        if detected['epsg'] != user_specified_crs:
            return {
                'status': 'conflict',
                'message': f"User specified EPSG:{user_specified_crs} but coordinates appear to be in {detected['name']}",
                'user_specified': user_specified_crs,
                'detected': detected['epsg'],
                'action_required': True
            }

        return {
            'status': 'ok',
            'message': 'CRS validation successful',
            'crs': user_specified_crs
        }

    def validate_coordinates(
        self,
        x_values: np.ndarray,
        y_values: np.ndarray,
        epsg: int
    ) -> List[Dict]:
        """
        Validate individual coordinates

        Args:
            x_values: X coordinates
            y_values: Y coordinates
            epsg: Expected EPSG code

        Returns:
            List of validation issues
        """
        issues = []

        def _coerce(v):
            while isinstance(v, (pd.Series, pd.DataFrame)):
                v = v.iloc[0]
            if isinstance(v, np.ndarray):
                v = v.ravel()[0]
            try:
                return float(v)
            except (TypeError, ValueError):
                return 0.0

        for idx, (x, y) in enumerate(zip(x_values, y_values)):
            x = _coerce(x)
            y = _coerce(y)
            # Blank / non-numeric coordinates are reported once, with their rows, by the
            # validator (missing_coordinate_rows); don't also flag each as "nan outside Nepal".
            if not (np.isfinite(x) and np.isfinite(y)):
                continue
            # Check for null island (0, 0)
            if x == 0.0 and y == 0.0:
                issues.append({
                    'row': idx + 2,  # +2 for header and 0-indexing
                    'severity': 'error',
                    'message': 'Coordinates are (0, 0) - Null Island',
                    'suggestion': 'GPS coordinates not recorded',
                    'x': x,
                    'y': y
                })
                continue

            # Validate based on CRS
            if epsg == 4326:
                # Geographic bounds
                geo = self.NEPAL_BOUNDS['geographic']
                if not (geo['lon_min'] <= x <= geo['lon_max']):
                    issues.append({
                        'row': idx + 2,
                        'severity': 'warning',
                        'field': 'longitude',
                        'value': x,
                        'message': f'Longitude {x} outside Nepal bounds ({geo["lon_min"]}-{geo["lon_max"]}°E)',
                        'suggestion': 'Tree location appears outside Nepal'
                    })

                if not (geo['lat_min'] <= y <= geo['lat_max']):
                    issues.append({
                        'row': idx + 2,
                        'severity': 'warning',
                        'field': 'latitude',
                        'value': y,
                        'message': f'Latitude {y} outside Nepal bounds ({geo["lat_min"]}-{geo["lat_max"]}°N)',
                        'suggestion': 'Tree location appears outside Nepal'
                    })

            elif epsg == 32644:
                # UTM 44N bounds
                utm44 = self.NEPAL_BOUNDS['utm_44n']
                if not (utm44['x_min'] <= x <= utm44['x_max']):
                    issues.append({
                        'row': idx + 2,
                        'severity': 'warning',
                        'field': 'x/easting',
                        'value': x,
                        'message': f'Easting {x} outside UTM 44N Nepal bounds'
                    })

                if not (utm44['y_min'] <= y <= utm44['y_max']):
                    issues.append({
                        'row': idx + 2,
                        'severity': 'warning',
                        'field': 'y/northing',
                        'value': y,
                        'message': f'Northing {y} outside UTM 44N Nepal bounds'
                    })

            elif epsg == 32645:
                # UTM 45N bounds
                utm45 = self.NEPAL_BOUNDS['utm_45n']
                if not (utm45['x_min'] <= x <= utm45['x_max']):
                    issues.append({
                        'row': idx + 2,
                        'severity': 'warning',
                        'field': 'x/easting',
                        'value': x,
                        'message': f'Easting {x} outside UTM 45N Nepal bounds'
                    })

                if not (utm45['y_min'] <= y <= utm45['y_max']):
                    issues.append({
                        'row': idx + 2,
                        'severity': 'warning',
                        'field': 'y/northing',
                        'value': y,
                        'message': f'Northing {y} outside UTM 45N Nepal bounds'
                    })

        return issues
