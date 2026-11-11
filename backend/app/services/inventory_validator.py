"""
Main validation orchestrator for inventory data
Coordinates all validation checks and generates comprehensive reports
"""
# constraint: DBH 0-300 cm, height 0-100 m, species code required
# why: validation before DB write prevents constraint violations
# NOTE: field inventory and legacy inventory share validation rules
import logging
from typing import Dict, Any, List, Optional
import pandas as pd
import numpy as np
from sqlalchemy.orm import Session

from .validators.species_matcher import SpeciesMatcher
from .validators.species_code_validator import SpeciesCodeValidator
from .validators.coordinate_detector import CoordinateDetector
from .validators.diameter_detector import DiameterDetector
from .validators.class_normalizer import ClassNormalizer
from .validators.regeneration_validator import RegenerationValidator
from app.services.upload.rules import STEM_DBH, STEM_HEIGHT


logger = logging.getLogger(__name__)


class InventoryValidator:
    """
    Main validator that orchestrates all validation checks
    """

    def __init__(self, db: Session):
        """
        Initialize validator with database session

        Args:
            db: SQLAlchemy database session
        """
        self.db = db
        self.species_matcher = SpeciesMatcher(db)
        self.species_code_validator = SpeciesCodeValidator(db)
        self.coord_detector = CoordinateDetector()
        self.diameter_detector = DiameterDetector()
        self.class_normalizer = ClassNormalizer()
        self.regeneration_validator = RegenerationValidator()

    async def validate_inventory_file(
        self,
        df: pd.DataFrame,
        user_specified_crs: Optional[int] = None,
        calculation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Comprehensive validation of inventory CSV data

        Args:
            df: DataFrame with inventory data
            user_specified_crs: Optional EPSG code from user
            calculation_id: Optional calculation UUID for physiographic zone detection

        Returns:
            Comprehensive validation report dict
        """
        report = {
            'summary': {},
            'data_detection': {},
            'errors': [],
            'warnings': [],
            'info': [],
            'corrections': []
        }

        # Physiographic zone detection (currently disabled for performance)
        # TODO: Re-enable as background task or cache result
        physiographic_zone = None
        # NOTE: When physiographic_zone is None, unknown species default to Hill spp (safe fallback)

        # 1. Detect coordinate columns
        x_col, y_col = self.coord_detector.detect_coordinate_columns(df)

        if not x_col or not y_col:
            report['errors'].append({
                'type': 'missing_coordinates',
                'message': 'Could not detect coordinate columns',
                'available_columns': list(df.columns),
                'expected': 'LONGITUDE/LATITUDE, long/lat, or x/y'
            })
            report['summary'] = self._calculate_summary(df, report)
            return report

        report['data_detection']['coordinate_columns'] = {
            'x': x_col,
            'y': y_col
        }

        # 1b. Rows with no usable coordinates (blank or not a number). They cannot be placed on
        # the map, so they are skipped when the trees are stored -- say so now, with the rows,
        # instead of letting the user find out from a smaller total afterwards.
        x_num = pd.to_numeric(df[x_col], errors='coerce')
        y_num = pd.to_numeric(df[y_col], errors='coerce')
        no_coords = ~(np.isfinite(x_num) & np.isfinite(y_num))
        if no_coords.any():
            bad_rows = (df.index[no_coords] + 2).tolist()  # +2: header row + 1-based
            report['warnings'].append({
                'type': 'missing_coordinate_rows',
                'severity': 'warning',
                'count': int(no_coords.sum()),
                'rows': bad_rows[:50],
                'message': (
                    f"{int(no_coords.sum())} tree(s) have no usable longitude/latitude and will be "
                    f"skipped (rows {', '.join(str(r) for r in bad_rows[:10])}"
                    f"{', ...' if len(bad_rows) > 10 else ''})"
                ),
                'suggestion': 'Fill in the coordinates for these rows and upload again to include them',
            })

        # 2. Detect CRS
        x_values = df[x_col].values
        y_values = df[y_col].values

        crs_detection = self._refine_utm_zone(self.coord_detector.detect_crs(x_values, y_values), x_values, y_values, user_specified_crs)
        report['data_detection']['crs'] = crs_detection

        # Handle CRS errors
        if crs_detection.get('error') == 'coordinates_swapped':
            report['errors'].append({
                'type': 'coordinates_swapped',
                'message': crs_detection['message'],
                'suggestion': crs_detection['suggestion']
            })
            report['summary'] = self._calculate_summary(df, report)
            return report

        if crs_detection.get('epsg') == 'UNKNOWN':
            if not user_specified_crs:
                report['errors'].append({
                    'type': 'unknown_crs',
                    'message': 'Could not detect CRS automatically',
                    'detected_range': crs_detection.get('detected_range'),
                    'action_required': 'Please specify EPSG code',
                    'common_nepal_crs': [
                        {'epsg': 4326, 'name': 'WGS84 Geographic'},
                        {'epsg': 32644, 'name': 'UTM Zone 44N (Western Nepal)'},
                        {'epsg': 32645, 'name': 'UTM Zone 45N (Eastern Nepal)'}
                    ]
                })
                report['summary'] = self._calculate_summary(df, report)
                return report
            else:
                # Use user-specified CRS
                report['info'].append({
                    'type': 'crs_user_specified',
                    'message': f'Using user-specified CRS: EPSG:{user_specified_crs}',
                    'epsg': user_specified_crs
                })
                detected_epsg = user_specified_crs
        else:
            detected_epsg = crs_detection['epsg']

        # Validate against user-specified CRS
        if user_specified_crs and user_specified_crs != detected_epsg:
            crs_validation = self.coord_detector.validate_crs(
                x_values, y_values, user_specified_crs
            )
            if crs_validation['status'] == 'conflict':
                report['warnings'].append(crs_validation)

        # 3. Validate individual coordinates
        coord_issues = self.coord_detector.validate_coordinates(
            x_values, y_values, detected_epsg
        )
        for issue in coord_issues:
            if issue['severity'] == 'error':
                report['errors'].append(issue)
            else:
                report['warnings'].append(issue)

        # 4. Detect diameter column and type
        diameter_col = self._detect_diameter_column(df)
        if not diameter_col:
            report['errors'].append({
                'type': 'missing_diameter',
                'message': 'Could not find diameter/girth column',
                'available_columns': list(df.columns),
                'expected': 'dia_cm, diameter, dbh, girth, or gbh'
            })
            report['summary'] = self._calculate_summary(df, report)
            return report

        diameter_detection = self.diameter_detector.detect_measurement_type(
            df[diameter_col].values,
            diameter_col
        )
        report['data_detection']['diameter'] = diameter_detection

        # Convert girth to diameter if needed
        if diameter_detection['type'] == 'girth':
            original_values = df[diameter_col].copy()
            df[diameter_col] = self.diameter_detector.convert_girth_to_diameter(
                df[diameter_col].values
            )

            samples = self.diameter_detector.get_conversion_samples(
                original_values.values, num_samples=3
            )

            report['corrections'].append({
                'type': 'girth_to_diameter',
                'column': diameter_col,
                'affected_rows': len(df),
                'method': 'DBH = GBH / π',
                'samples': samples,
                'confidence': diameter_detection.get('confidence', 'high')
            })

        # 5. Validate species names (supports both codes 1-23 and scientific names)
        species_col = self._detect_species_column(df)
        if species_col:
            species_validation = self._validate_species(df, species_col, physiographic_zone)
            report['warnings'].extend(species_validation['warnings'])
            report['errors'].extend(species_validation['errors'])
            if species_validation['corrections']:
                report['corrections'].append({
                    'type': 'species_validation',
                    'column': species_col,
                    'affected_rows': len(species_validation['corrections']),
                    'samples': list(species_validation['corrections'].values())[:5]
                })
        else:
            report['errors'].append({
                'type': 'missing_species',
                'message': 'Could not find species column',
                'expected': 'species, scientific_name, or tree_species'
            })

        # 6. Validate heights for seedlings
        height_col = self._detect_height_column(df)
        if height_col and diameter_col:
            seedling_validation = self._validate_seedling_heights(
                df, diameter_col, height_col
            )
            report['warnings'].extend(seedling_validation)

        # 7. Validate DBH and height ranges
        if diameter_col:
            dbh_validation = self._validate_dbh_range(df, diameter_col)
            report['errors'].extend(dbh_validation['errors'])
            report['warnings'].extend(dbh_validation['warnings'])

        if height_col:
            height_validation = self._validate_height_range(df, height_col)
            report['errors'].extend(height_validation['errors'])
            report['warnings'].extend(height_validation['warnings'])

        # 8. Check for duplicate coordinates
        duplicate_check = self._check_duplicate_coordinates(df, x_col, y_col)
        if duplicate_check:
            report['warnings'].append(duplicate_check)

        # 9. Normalize class column (A/B/C/D, I/II/III/IV, क/ख/ग/घ → 1/2/3/4)
        class_col = self._detect_class_column(df)
        if class_col:
            df, class_report = self.class_normalizer.normalize_dataframe(df, class_col)
            if class_report['status'] == 'completed':
                report['data_detection']['class_normalization'] = class_report
                if class_report['total_conversions'] > 0:
                    report['corrections'].append({
                        'type': 'class_normalization',
                        'column': class_col,
                        'affected_rows': class_report['total_conversions'],
                        'statistics': class_report['statistics'],
                        'samples': class_report['conversions'][:5]
                    })
                if class_report['invalid_values']:
                    for invalid in class_report['invalid_values']:
                        report['warnings'].append({
                            'row': invalid['row'] + 1,
                            'column': class_col,
                            'value': invalid['original_value'],
                            'message': invalid['message'],
                            'severity': 'warning'
                        })

        # 10. Validate regeneration trees (DBH 1-10 cm should not have height/class)
        if diameter_col:
            regen_report = self.regeneration_validator.validate_dataframe(
                df,
                diameter_col,
                height_col,
                class_col
            )
            if regen_report['status'] == 'completed':
                report['data_detection']['regeneration'] = regen_report
                if regen_report['needs_user_confirmation']:
                    report['warnings'].append({
                        'type': 'regeneration_confirmation_needed',
                        'severity': 'warning',
                        'message': f"{regen_report['trees_with_issues']} regeneration trees have height/class values",
                        'details': regen_report['trees_with_issues_list'][:5],
                        'action_required': 'User confirmation needed to remove height/class from regeneration trees',
                        'total_affected': regen_report['trees_with_issues']
                    })

        # 11. Summary statistics
        report['summary'] = self._calculate_summary(df, report)

        return report

    def _detect_diameter_column(self, df: pd.DataFrame) -> Optional[str]:
        """Detect diameter/girth column"""
        possible_names = ['dia_cm', 'dbh_cm', 'diameter', 'diameter_cm', 'dbh', 'girth', 'gbh', 'diam', 'dia']
        for col in df.columns:
            if col.lower() in possible_names:
                return col
        return None

    def _detect_species_column(self, df: pd.DataFrame) -> Optional[str]:
        """Detect species column"""
        possible_names = ['species', 'scientific_name', 'species_scientific', 'species_name', 'tree_species', 'spp']
        for col in df.columns:
            if col.lower() in possible_names:
                return col
        return None

    def _detect_height_column(self, df: pd.DataFrame) -> Optional[str]:
        """Detect height column"""
        possible_names = ['height_m', 'height', 'tree_height', 'ht', 'h']
        for col in df.columns:
            if col.lower() in possible_names:
                return col
        return None

    def _detect_class_column(self, df: pd.DataFrame) -> Optional[str]:
        """Detect class column"""
        possible_names = ['class', 'tree_class', 'quality_class', 'quality', 'grade']
        for col in df.columns:
            if col.lower() in possible_names:
                return col
        return None

    def _validate_species(
        self,
        df: pd.DataFrame,
        species_col: str,
        physiographic_zone: Optional[str] = None
    ) -> Dict:
        """
        Validate all species values - supports both numeric codes (1-23) and scientific names
        Uses physiographic zone for fallback species selection
        """
        result = {
            'warnings': [],
            'errors': [],
            'corrections': {}
        }

        for idx, row in df.iterrows():
            species_value = row[species_col]

            # Validate species using new code validator
            (
                scientific_name,
                species_code,
                method,
                confidence,
                warning_message
            ) = self.species_code_validator.validate_species_value(
                species_value,
                physiographic_zone
            )

            # Handle different validation results
            if method == 'code':
                # Numeric code entered (1-23) - convert to scientific name
                df.at[idx, species_col] = scientific_name
                result['corrections'][idx] = {
                    'original': species_value,
                    'corrected': scientific_name,
                    'method': 'code_conversion',
                    'species_code': species_code,
                    'confidence': confidence
                }

            elif method == 'fuzzy':
                # Fuzzy match on scientific name
                result['warnings'].append({
                    'row': idx + 2,  # +2 for header and 0-indexing
                    'column': species_col,
                    'original': species_value,
                    'corrected': scientific_name,
                    'species_code': species_code,
                    'confidence': round(confidence, 2),
                    'message': f'Species name auto-corrected ({int(confidence*100)}% match)'
                })
                df.at[idx, species_col] = scientific_name
                result['corrections'][idx] = {
                    'original': species_value,
                    'corrected': scientific_name,
                    'method': 'fuzzy_match',
                    'species_code': species_code,
                    'confidence': confidence
                }

            elif method == 'fallback':
                # Unknown species - using Terai/Hill spp fallback
                result['warnings'].append({
                    'row': idx + 2,
                    'column': species_col,
                    'original': species_value,
                    'corrected': scientific_name,
                    'species_code': species_code,
                    'confidence': round(confidence, 2),
                    'message': warning_message,
                    'severity': 'warning'
                })
                df.at[idx, species_col] = scientific_name
                result['corrections'][idx] = {
                    'original': species_value,
                    'corrected': scientific_name,
                    'method': 'fallback',
                    'species_code': species_code,
                    'confidence': confidence,
                    'reason': warning_message
                }

            elif method == 'exact' or method == 'alias':
                # Perfect match - no correction needed
                if scientific_name != str(species_value).strip():
                    df.at[idx, species_col] = scientific_name

            elif method == 'no_match':
                # Complete failure - couldn't match or fallback
                result['errors'].append({
                    'row': idx + 2,
                    'column': species_col,
                    'value': species_value,
                    'message': warning_message or 'Species not recognized and fallback failed',
                    'suggestions': self.species_matcher.get_suggestions(str(species_value))[:3]
                })

        return result

    def _validate_seedling_heights(
        self,
        df: pd.DataFrame,
        diameter_col: str,
        height_col: str
    ) -> List[Dict]:
        """Validate heights for seedlings (DBH < 10 cm)"""
        warnings = []

        seedlings = df[df[diameter_col] < 10]

        for idx in seedlings.index:
            if pd.notna(df.at[idx, height_col]):
                warnings.append({
                    'row': idx + 2,
                    'column': height_col,
                    'dbh_cm': round(df.at[idx, diameter_col], 2),
                    'provided_height': round(df.at[idx, height_col], 2),
                    'severity': 'info',
                    'message': 'Height will be ignored for seedling (DBH < 10 cm)',
                    'action': 'Will use default H/D ratio for volume calculation'
                })

        return warnings

    def _refine_utm_zone(self, detection: Dict, x_values, y_values, user_crs: Optional[int]) -> Dict:
        """UTM zone 44 or 45? The old detector tests only the smallest easting and northing against two overlapping windows, so almost any UTM file
        in the overlap read as zone 44 ("UTM 44N bounds (Western Nepal)", confidence "high") whatever its true zone.

        The zone the user chose wins. Otherwise the zone whose converted points land inside Nepal's real outline (and only one does, almost always:
        99.9% of points across Nepal in the measurement behind ``detect_systems``). A tie, or no fit, keeps the old answer.
        """
        from app.services.upload.coordinates import SYSTEM_LABELS, UTM_ZONES, detect_systems

        old = detection.get('epsg')
        if old not in UTM_ZONES:
            return detection
        if user_crs in UTM_ZONES:
            chosen, method = user_crs, 'zone chosen by the user'
        else:
            try:
                suggested = detect_systems(self.db, x_values, y_values).get('suggested_epsg')
            except Exception:  # noqa: BLE001 -- the refinement is an improvement on the old answer; if it cannot run the old answer stands
                logger.warning("UTM zone refinement failed; keeping the detector's answer", exc_info=True)
                return detection
            if suggested not in UTM_ZONES:
                return detection
            chosen, method = suggested, 'UTM zone whose points land inside Nepal'
        if chosen == old:
            return detection
        return {**detection, 'epsg': chosen, 'name': f"WGS84 / {SYSTEM_LABELS[chosen]}", 'confidence': 'high', 'method': method}

    def _validate_dbh_range(self, df: pd.DataFrame, diameter_col: str) -> Dict:
        """Validate stem diameters against the rule table (``STEM_DBH``): one continuous range for every stem, not the stand classes.

        Refused: missing, zero or negative, under 1 cm (cannot be measured at breast height), over 200 cm. Confirm (warning): over 100 cm.
        """
        issues = {'errors': [], 'warnings': []}
        lo, hi = STEM_DBH.hard_bounds()

        for idx, value in df[diameter_col].items():
            row = idx + 2
            if pd.isna(value):
                issues['errors'].append({'row': row, 'column': diameter_col, 'value': value, 'message': 'Missing DBH value'})
            elif value <= 0:
                issues['errors'].append({'row': row, 'column': diameter_col, 'value': value, 'message': 'DBH must be positive'})
            elif value > hi:
                issues['errors'].append({
                    'row': row, 'column': diameter_col, 'value': value,
                    'message': f'DBH {value} cm is unrealistically large (the most a stem can measure here is {hi:g} cm)',
                    'suggestion': 'Check for data entry error or wrong units'
                })
            elif value < lo:
                issues['errors'].append({
                    'row': row, 'column': diameter_col, 'value': value,
                    'message': f'DBH {value} cm is too small to measure at breast height',
                    'suggestion': f'Minimum DBH {lo:g} cm'
                })
            elif value > STEM_DBH.soft_max:
                issues['warnings'].append({
                    'row': row, 'column': diameter_col, 'value': value,
                    'message': f'DBH {value} cm is above {STEM_DBH.soft_max:g} cm, which is unusual in Nepal - is it correct?',
                    'suggestion': 'Please confirm the measurement'
                })

        return issues

    def _validate_height_range(self, df: pd.DataFrame, height_col: str) -> Dict:
        """Validate stem heights against the rule table (``STEM_HEIGHT``): refused at or below 0, under breast height (1.3 m) or over 50 m; asked above 45 m."""
        issues = {'errors': [], 'warnings': []}
        lo, hi = STEM_HEIGHT.hard_bounds()

        for idx, value in df[height_col].items():
            if pd.isna(value):
                continue  # Height is optional for some trees

            if value <= 0:
                issues['errors'].append({'row': idx + 2, 'column': height_col, 'value': value, 'message': 'Height must be positive'})
            elif value > hi:
                issues['errors'].append({
                    'row': idx + 2, 'column': height_col, 'value': value,
                    'message': f'Height {value} m exceeds Nepal maximum (~{hi:g} m)',
                    'suggestion': 'Check for wrong units (feet instead of meters?)'
                })
            elif value > STEM_HEIGHT.soft_max:
                issues['warnings'].append({
                    'row': idx + 2, 'column': height_col, 'value': value,
                    'message': f'Height {value} m is very tall for Nepal',
                    'suggestion': 'Verify measurement'
                })
            elif value < lo:
                issues['errors'].append({
                    'row': idx + 2, 'column': height_col, 'value': value,
                    'message': f'Height {value} m is below breast height ({lo:g} m)',
                    'suggestion': 'Trees shorter than breast height cannot have DBH measured'
                })

        return issues

    def _check_duplicate_coordinates(
        self,
        df: pd.DataFrame,
        x_col: str,
        y_col: str,
        tolerance: float = 0.00001
    ) -> Optional[Dict]:
        """Check for duplicate coordinates (within ~1 meter)"""
        duplicates = []

        # Create a temporary coordinate string for grouping
        df['_coord_str'] = df.apply(
            lambda row: f"{round(row[x_col], 5)}_{round(row[y_col], 5)}",
            axis=1
        )

        # Find duplicates
        dup_groups = df[df.duplicated(subset='_coord_str', keep=False)].groupby('_coord_str')

        for coord_str, group in dup_groups:
            if len(group) > 1:
                duplicates.append({
                    'coordinates': coord_str.replace('_', ', '),
                    'row_count': len(group),
                    'rows': (group.index + 2).tolist()
                })

        # Clean up temporary column
        df.drop('_coord_str', axis=1, inplace=True)

        if duplicates:
            return {
                'type': 'duplicate_coordinates',
                'severity': 'warning',
                'message': f'{len(duplicates)} sets of duplicate coordinates found',
                'duplicates': duplicates[:5],  # Show first 5
                'total_duplicate_sets': len(duplicates),
                'suggestion': 'Check for copy-paste errors or GPS measurement issues'
            }

        return None

    def _calculate_summary(self, df: pd.DataFrame, report: Dict) -> Dict:
        """Calculate validation summary statistics"""
        error_rows = set()
        warning_rows = set()

        for error in report['errors']:
            if 'row' in error:
                error_rows.add(error['row'])

        for warning in report['warnings']:
            if 'row' in warning:
                warning_rows.add(warning['row'])

        return {
            'total_rows': int(len(df)),
            'valid_rows': int(len(df) - len(error_rows)),
            'rows_with_errors': int(len(error_rows)),
            'rows_with_warnings': int(len(warning_rows)),
            'error_count': int(len(report['errors'])),
            'warning_count': int(len(report['warnings'])),
            'auto_corrections': int(len(report['corrections'])),
            'has_critical_errors': len(report['errors']) > 0,
            'ready_for_processing': len(error_rows) == 0
        }
