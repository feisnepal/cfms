"""
Field Inventory Validator
Validates CSV uploads with 4 stand types (Regeneration, Sapling, Pole, Tree)
"""
# constraint: DBH must be 0-300 cm
# constraint: height must be >= DBH
# why: validation done in-memory before DB write to avoid partial inserts
import pandas as pd
import numpy as np
from typing import Dict, List, Any, Optional, Tuple
from sqlalchemy import text
from sqlalchemy.orm import Session
from uuid import UUID
import logging

from ..services.validators.species_code_validator import SpeciesCodeValidator
from ..core.dbh_classifier import DbhClassRegistry
from ..services.upload.rules import RULES, evaluate, species_limits_sql
from ..services.upload.corrections import propose_corrections
from ..services.upload.units import dbh_unit_problem, height_unit_problem
from ..utils.forest_dimension import get_forest_dimension, dimension_label, ForestDimension

logger = logging.getLogger(__name__)


class FieldInventoryValidator:
    """
    Validator for field inventory CSV files with 4 stand types
    """

    # Required column groups by stand type
    # Allow flexible column name matching
    REQUIRED_COLUMNS = {
        'common': ['block_name', 'sample_plot_number', 'longitude', 'latitude'],
        'regeneration': ['regen_species_scientific', 'regen_dbh', 'regen_count'],
        'sapling': ['sapling_species_scientific', 'sapling_dbh', 'sapling_count'],  # Accept both sapling_dbh and sapling_dbh_cm
        'pole': ['pole_species_scientific', 'pole_dbh', 'pole_height'],  # Accept both pole_dbh_cm and pole_dbh, pole_height_m and pole_height
        'tree': ['tree_species_scientific', 'tree_dbh', 'tree_height']  # Accept both tree_dbh_cm and tree_dbh, tree_height_m and tree_height
    }

    # Column name alternatives (first match wins)
    COLUMN_ALTERNATIVES = {
        'block_name': ['compartment_name'],
        'sapling_dbh': ['sapling_dbh_cm', 'sapling_dbh'],
        'pole_dbh': ['pole_dbh_cm', 'pole_dbh'],
        'tree_dbh': ['tree_dbh_cm', 'tree_dbh'],
        'pole_height': ['pole_height_m', 'pole_height'],
        'tree_height': ['tree_height_m', 'tree_height']
    }

    # Optional columns
    OPTIONAL_COLUMNS = {
        'regeneration': ['regen_sn'],
        'sapling': ['sapling_sn'],
        'pole': ['pole_sn', 'pole_class', 
                 'pole_stem_volume_m3', 'pole_branch_volume_m3', 'pole_tree_volume_m3',
                 'pole_gross_volume_m3', 'pole_net_volume_m3', 'pole_firewood_m3'],
        'tree': ['tree_sn', 'tree_class',
                 'tree_stem_volume_m3', 'tree_branch_volume_m3', 'tree_tree_volume_m3',
                 'tree_gross_volume_m3', 'tree_net_volume_m3', 'tree_firewood_m3']
    }

    @staticmethod
    def _build_validation_thresholds():
        """Build DBH thresholds from SSOT validation system."""
        validation_system = DbhClassRegistry.get_system("validation")
        thresholds = {}
        for c in validation_system:
            thresholds[c.key] = {
                'min': int(c.lower),
                'max': int(c.upper) if c.upper is not None else 999,
                'strict': c.extra.get('strict', False)
            }
        return thresholds

    # DBH thresholds (in cm) — sourced from SSOT dbh_classifier
    DBH_THRESHOLDS = None  # lazy init

    def __init__(self, db: Session):
        """Initialize validator with database session"""
        self.db = db
        self.species_validator = SpeciesCodeValidator(db)
        if self.__class__.DBH_THRESHOLDS is None:
            self.__class__.DBH_THRESHOLDS = self._build_validation_thresholds()
        self.errors = []
        self.warnings = []
        self.info = []
        self.proposals = []

    async def validate_field_inventory_file(
        self,
        df: pd.DataFrame,
        calculation_id: Optional[UUID] = None
    ) -> Dict[str, Any]:
        """
        Validate field inventory CSV file

        Args:
            df: DataFrame with field inventory data
            calculation_id: Optional calculation ID for boundary validation

        Returns:
            Validation report dict
        """
        self.errors = []
        self.warnings = []
        self.info = []
        self.proposals = []

        self.dimension = ForestDimension.BLOCK
        if calculation_id:
            self.dimension = get_forest_dimension(self.db, calculation_id)

        logger.info(f"[FIELD_INVENTORY_VALIDATOR] Starting validation for {len(df)} rows, dimension={self.dimension}")

        # 1. Detect and validate columns
        column_detection = self._detect_columns(df)
        if not column_detection['valid']:
            return {
                'success': False,
                'summary': {
                    'total_rows': len(df),
                    'ready_for_processing': False,
                    'has_critical_errors': True
                },
                'data_detection': column_detection,
                'errors': self.errors,
                'warnings': self.warnings,
                'info': self.info
            }

        # 2. Validate coordinates
        coord_validation = self._validate_coordinates(df, column_detection['columns'])

        # 3. Validate duplicate sample plots
        duplicate_validation = self._validate_duplicate_plots(df, column_detection['columns'])

        # 4. Validate all 4 species columns
        species_validation = await self._validate_species_columns(df, column_detection['columns'])

        # 5. Validate DBH ranges for all 4 stand types
        dbh_validation = self._validate_dbh_ranges(df, column_detection['columns'])

        # 6. Validate counts for regeneration and sapling
        count_validation = self._validate_counts(df, column_detection['columns'])

        # 6b. Heights, and the per-species maximums (soft)
        height_validation = self._validate_heights(df, column_detection['columns'])
        species_limit_validation = self._validate_species_limits(df, column_detection['columns'])

        # 7. Boundary validation (if calculation_id provided)
        boundary_check = None
        if calculation_id:
            boundary_check = await self._validate_boundary(df, column_detection['columns'], calculation_id)

        # Compile summary
        has_critical_errors = len([e for e in self.errors if e['severity'] == 'error']) > 0
        ready_for_processing = not has_critical_errors

        # If boundary check failed, mark as not ready
        if boundary_check and not boundary_check.get('within_tolerance', True):
            ready_for_processing = False
            has_critical_errors = True

        report = {
            'proposals': list(self.proposals),
            'success': ready_for_processing,
            'summary': {
                'total_rows': len(df),
                'ready_for_processing': ready_for_processing,
                'has_critical_errors': has_critical_errors,
                'error_count': len([e for e in self.errors if e['severity'] == 'error']),
                'warning_count': len([w for w in self.warnings if w['severity'] == 'warning']),
                'info_count': len(self.info)
            },
            'data_detection': column_detection,
            'errors': self.errors,
            'warnings': self.warnings,
            'info': self.info
        }

        if boundary_check:
            report['boundary_check'] = boundary_check

        logger.info(f"[FIELD_INVENTORY_VALIDATOR] Validation complete: ready={ready_for_processing}, errors={len(self.errors)}, warnings={len(self.warnings)}")

        return report

    def _detect_columns(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Detect and validate column structure"""
        logger.info(f"[COLUMN_DETECTION] Detecting columns from: {list(df.columns)}")

        detected_columns = {}
        missing_required = []

        # Normalize column names (lowercase)
        df_columns_lower = [col.lower().strip() for col in df.columns]
        column_map = {col.lower().strip(): col for col in df.columns}

        # Detect common columns
        for req_col in self.REQUIRED_COLUMNS['common']:
            found = None
            req_lower = req_col.lower()

            # Exact match
            if req_lower in df_columns_lower:
                found = column_map[req_lower]

            # If not found, try alternatives
            if not found and req_col in self.COLUMN_ALTERNATIVES:
                for alt in self.COLUMN_ALTERNATIVES[req_col]:
                    alt_lower = alt.lower()
                    if alt_lower in df_columns_lower:
                        found = column_map[alt_lower]
                        logger.info(f"[COLUMN_DETECTION] Using alternative '{alt}' for '{req_col}'")
                        break

            if found:
                detected_columns[req_col] = found
            else:
                missing_required.append(req_col)
                self.errors.append({
                    'severity': 'error',
                    'type': 'missing_column',
                    'message': f"REQUIRED_COLUMN_MISSING: आवश्यक स्तम्भ '{req_col}' फेला परेन"
                })

        # Detect stand type columns (regeneration, sapling, pole, tree)
        for stand_type, req_cols in self.REQUIRED_COLUMNS.items():
            if stand_type == 'common':
                continue

            for req_col in req_cols:
                found = None
                req_lower = req_col.lower()

                # Try exact match first
                if req_lower in df_columns_lower:
                    found = column_map[req_lower]

                # If not found, try alternatives
                if not found and req_col in self.COLUMN_ALTERNATIVES:
                    for alt in self.COLUMN_ALTERNATIVES[req_col]:
                        alt_lower = alt.lower()
                        if alt_lower in df_columns_lower:
                            found = column_map[alt_lower]
                            logger.info(f"[COLUMN_DETECTION] Using alternative '{alt}' for '{req_col}'")
                            break

                if found:
                    detected_columns[req_col] = found
                else:
                    # For stand-specific columns, it's OK if missing (not all plots have all stand types)
                    self.warnings.append({
                        'severity': 'warning',
                        'type': 'missing_optional_column',
                        'message': f"Optional column '{req_col}' not found (stand type: {stand_type})"
                    })

        # Check if we have at least one stand type
        has_regen = 'regen_species_scientific' in detected_columns
        has_sapling = 'sapling_species_scientific' in detected_columns
        has_pole = 'pole_species_scientific' in detected_columns
        has_tree = 'tree_species_scientific' in detected_columns

        if not (has_regen or has_sapling or has_pole or has_tree):
            self.errors.append({
                'severity': 'error',
                'type': 'no_stand_types',
                'message': f'NO_STAND_TYPES: {dimension_label(self.dimension, nepali=True)}मा कुनै पनि स्टैन्ड प्रकार (regeneration, sapling, pole, tree) फेला परेन'
            })
            return {
                'valid': False,
                'columns': detected_columns,
                'missing_required': missing_required,
                'stand_types_present': []
            }

        stand_types_present = []
        if has_regen:
            stand_types_present.append('regeneration')
        if has_sapling:
            stand_types_present.append('sapling')
        if has_pole:
            stand_types_present.append('pole')
        if has_tree:
            stand_types_present.append('tree')

        logger.info(f"[COLUMN_DETECTION] Stand types present: {stand_types_present}")

        return {
            'valid': len(missing_required) == 0,
            'columns': detected_columns,
            'missing_required': missing_required,
            'stand_types_present': stand_types_present
        }

    def _validate_coordinates(self, df: pd.DataFrame, columns: Dict[str, str]) -> Dict[str, Any]:
        """Validate longitude and latitude"""
        logger.info("[COORDINATE_VALIDATION] Validating coordinates...")

        lon_col = columns.get('longitude')
        lat_col = columns.get('latitude')

        if not lon_col or not lat_col:
            return {'valid': False}

        # Check for missing values
        missing_lon = df[lon_col].isna().sum()
        missing_lat = df[lat_col].isna().sum()

        if missing_lon > 0 or missing_lat > 0:
            self.errors.append({
                'severity': 'error',
                'type': 'missing_coordinates',
                'message': f"MISSING_COORDINATES: {missing_lon} देशान्तर, {missing_lat} अक्षान्तर नभएको"
            })

        # Check valid ranges (Nepal bounds: ~80-88°E, ~26-31°N)
        valid_lon = df[lon_col].between(80, 88)
        valid_lat = df[lat_col].between(26, 31)

        invalid_lon = (~valid_lon).sum()
        invalid_lat = (~valid_lat).sum()

        if invalid_lon > 0:
            self.warnings.append({
                'severity': 'warning',
                'type': 'invalid_longitude',
                'message': f"{invalid_lon} पंक्तिहरूको देशान्तर नेपालको सीमा बाहिर (८०-८८° पूर्व)"
            })

        if invalid_lat > 0:
            self.warnings.append({
                'severity': 'warning',
                'type': 'invalid_latitude',
                'message': f"{invalid_lat} पंक्तिहरूको अक्षान्तर नेपालको सीमा बाहिर (२६-३१° उत्तर)"
            })

        return {'valid': True}

    def _validate_duplicate_plots(self, df: pd.DataFrame, columns: Dict[str, str]) -> Dict[str, Any]:
        """
        Validate sample plot coordinates consistency

        NOTE: Multiple rows with same (block_name, sample_plot_number) is EXPECTED
        because one sample plot can have multiple trees/measurements.

        We only check if the same plot has INCONSISTENT coordinates (error).
        """
        logger.info("[DUPLICATE_VALIDATION] Checking for coordinate consistency per plot...")

        block_col = columns.get('block_name')
        plot_col = columns.get('sample_plot_number')
        lat_col = columns.get('latitude')
        lon_col = columns.get('longitude')

        if not block_col or not plot_col or not lat_col or not lon_col:
            return {'valid': True}  # Skip validation if columns missing

        # Group by (block_name, sample_plot_number) and check coordinate consistency
        inconsistent_plots = []

        for (block, plot), group in df.groupby([block_col, plot_col]):
            # Get unique coordinates for this plot (ignoring NaN)
            unique_coords = group[[lat_col, lon_col]].dropna().drop_duplicates()

            # If a plot has more than one unique coordinate pair, that's an error
            if len(unique_coords) > 1:
                inconsistent_plots.append({
                    'block_name': block,
                    'sample_plot_number': plot,
                    'coordinate_count': len(unique_coords),
                    'coordinates': unique_coords.to_dict('records')
                })

        if inconsistent_plots:
            # This is common when GPS is recorded per tree instead of per plot
            # Change to WARNING instead of ERROR - we'll use first coordinate or centroid
            self.warnings.append({
                'severity': 'warning',
                'type': 'inconsistent_coordinates',
                'message': f"INCONSISTENT_COORDINATES: {len(inconsistent_plots)} {dimension_label(self.dimension, nepali=True)}मा फरक GPS निर्देशांक (पहिलो निर्देशांक वा केन्द्र प्रयोग गर्नेछौं)",
                'details': inconsistent_plots[:5] if len(inconsistent_plots) > 5 else inconsistent_plots
            })
            logger.warning(f"[DUPLICATE_VALIDATION] {len(inconsistent_plots)} plots have varying coordinates (common when GPS recorded per tree)")

        # Count unique sample plots
        unique_plots = df[[block_col, plot_col]].drop_duplicates()
        total_measurements = len(df)
        unique_plot_count = len(unique_plots)

        logger.info(f"[DUPLICATE_VALIDATION] Found {unique_plot_count} unique sample plots with {total_measurements} total measurements")

        # Add info message about multiple measurements per plot (this is normal and expected)
        if total_measurements > unique_plot_count:
            self.info.append({
                'type': 'multiple_measurements',
                'message': f"Dataset has {total_measurements} measurements from {unique_plot_count} sample plots (multiple measurements per plot is normal)"
            })

        return {'valid': True, 'unique_plot_count': unique_plot_count, 'total_measurements': total_measurements}

    async def _validate_species_columns(self, df: pd.DataFrame, columns: Dict[str, str]) -> Dict[str, Any]:
        """Validate all 4 species columns"""
        logger.info("[SPECIES_VALIDATION] Validating species columns...")

        species_columns = {
            'regeneration': columns.get('regen_species_scientific'),
            'sapling': columns.get('sapling_species_scientific'),
            'pole': columns.get('pole_species_scientific'),
            'tree': columns.get('tree_species_scientific')
        }

        validation_results = {}

        for stand_type, col_name in species_columns.items():
            if not col_name or col_name not in df.columns:
                continue

            logger.info(f"[SPECIES_VALIDATION] Validating {stand_type} species column: {col_name}")

            # Get unique species values (excluding NaN)
            unique_species = df[col_name].dropna().unique()

            invalid_species = []
            for species_value in unique_species:
                if pd.isna(species_value) or str(species_value).strip() == '':
                    continue

                # Validate species
                scientific_name, species_code, method, confidence, warning = \
                    self.species_validator.validate_species_value(species_value, None)

                # a near-miss that was matched by similarity (not exact, not an alias) is reported too: the user should know we read
                # "Shorea robustta" as "Shorea robusta" (UP-3.4); only a real fallback / no match carries a warning text
                if warning or method == 'fuzzy':
                    invalid_species.append({
                        'original': species_value,
                        'resolved': scientific_name,
                        'method': method,
                        'confidence': confidence,
                        'warning': warning
                    })

            if invalid_species:
                self.warnings.append({
                    'severity': 'warning',
                    'type': f'{stand_type}_species_validation',
                    'message': f"{len(invalid_species)} species in {stand_type} may need review",
                    'details': invalid_species
                })

            validation_results[stand_type] = {
                'total_unique': len(unique_species),
                'invalid_count': len(invalid_species)
            }

        logger.info(f"[SPECIES_VALIDATION] Complete: {validation_results}")
        return validation_results

    # ── numeric limits: ONE rule table (upload/rules.py) for DBH, height and count ─────────────────────────────────────────
    _MEASURE_NP = {"dbh": "DBH", "height": "उचाइ", "count": "गणना"}
    _UNIT_NP = {"cm": "से.मी.", "m": "मि.", "count": ""}

    @staticmethod
    def _rows_text(rows: List[int]) -> str:
        return ", ".join(map(str, rows[:20])) + (" …" if len(rows) > 20 else "")

    def _apply_rules(self, df: pd.DataFrame, columns: Dict[str, str], measure: str) -> Dict[str, Any]:
        """Check every column of one measure against its rule: outside the hard limits is an error, outside the soft ones a warning to confirm.

        The detector files the columns under 'sapling_dbh' / 'pole_dbh' / 'tree_dbh' / 'pole_height' / 'regen_count' ...; those are the rule keys. An older
        version of this check asked for '*_dbh_cm', which is never a key, so only the regeneration range was ever checked.
        """
        results: Dict[str, Any] = {}
        for key, rule in RULES.items():
            if rule.measure != measure:
                continue
            col = columns.get(key) or columns.get(f"{key}_cm") or columns.get(f"{key}_m")
            if not col or col not in df.columns:
                continue
            # A WHOLE column in the wrong unit (millimetres, feet) is one finding from the unit check, not a refusal of every row.
            if (measure == "dbh" and dbh_unit_problem(df[col])) or (measure == "height" and height_unit_problem(df[col])):
                continue
            ev = evaluate(rule, df[col])
            if ev.total == 0:
                continue
            stand = rule.stand.capitalize()
            label, unit = self._MEASURE_NP[measure], self._UNIT_NP[rule.unit]
            lo, hi = ev.hard_min, ev.hard_max
            # the upper edge of a size class belongs to the next class: say "30 भन्दा कम", not "10-30"
            range_ne = f"{lo:g} देखि {hi:g} {unit} भन्दा कम".replace("  ", " ") if ev.hard_max_exclusive else f"{lo:g}-{hi:g} {unit}".strip()
            hard_rows = ev.hard_rows
            if hard_rows and measure in ("dbh", "height"):
                # which row, which class the value really belongs to, and a repeatable random replacement inside the column's own class
                self.proposals.extend(propose_corrections(rule, col, df[col]))
            issue = {"dbh": "dbh_out_of_range", "height": "height_out_of_range", "count": "invalid_count"}[measure]
            if hard_rows:
                self.errors.append({
                    'severity': 'error', 'type': issue, 'stand_type': rule.stand,
                    'message': f"{stand}: {len(hard_rows)} {label} मान अपेक्षित परिसर बाहिर ({range_ne}), पङ्क्ति: {self._rows_text(hard_rows)}",
                    'expected_range': f"{lo:g}-{hi:g} {unit}".strip(), 'rows': hard_rows[:20],
                })
            if ev.not_whole_rows:
                self.errors.append({
                    'severity': 'error', 'type': 'invalid_count', 'stand_type': rule.stand,
                    'message': f"{stand}: {len(ev.not_whole_rows)} {label} पूर्ण संख्या हुनुपर्छ, पङ्क्ति: {self._rows_text(ev.not_whole_rows)}",
                    'rows': ev.not_whole_rows[:20],
                })
            if ev.soft_rows:
                if rule.soft_min is not None and rule.soft_max is not None:
                    usual = f"{rule.soft_min:g}-{rule.soft_max:g}"
                elif rule.soft_max is not None:
                    usual = f"≤ {rule.soft_max:g}"
                else:
                    usual = f"≥ {rule.soft_min:g}"
                self.warnings.append({
                    'severity': 'warning', 'type': {"dbh": "dbh_unusual", "height": "height_unusual", "count": "count_unusual"}[measure],
                    'stand_type': rule.stand,
                    'message': f"{stand}: {len(ev.soft_rows)} {label} मान सामान्य परिसर ({usual} {unit}) बाहिर छ, नेपालमा असामान्य — पुष्टि गर्नुहोस्, पङ्क्ति: {self._rows_text(ev.soft_rows)}",
                    'rows': ev.soft_rows[:20],
                })
            results[rule.stand] = {
                'total': ev.total, 'out_of_range': len(hard_rows), 'unusual': len(ev.soft_rows),
                'expected_range': f"{lo:g}-{hi:g} {rule.unit}", 'strict': True,
            }
        return results

    def _validate_dbh_ranges(self, df: pd.DataFrame, columns: Dict[str, str]) -> Dict[str, Any]:
        """DBH of the four stand types against the rule table."""
        logger.info("[DBH_VALIDATION] Validating DBH ranges...")
        return self._apply_rules(df, columns, "dbh")

    def _validate_heights(self, df: pd.DataFrame, columns: Dict[str, str]) -> Dict[str, Any]:
        """Pole and tree heights against the rule table (this check did not exist before)."""
        logger.info("[HEIGHT_VALIDATION] Validating heights...")
        return self._apply_rules(df, columns, "height")

    def _validate_counts(self, df: pd.DataFrame, columns: Dict[str, str]) -> Dict[str, Any]:
        """Regeneration and sapling counts: whole numbers, at least 1, and flagged when the plot holds an unusual number."""
        logger.info("[COUNT_VALIDATION] Validating count columns...")
        return self._apply_rules(df, columns, "count")

    def _species_limits(self, names: List[str]) -> Dict[str, Tuple[Optional[float], Optional[float]]]:
        """{lower-case scientific name: (max DBH cm, max height m)} for the species we know."""
        if not names:
            return {}
        rows = self.db.execute(text(species_limits_sql()), {"names": names}).fetchall()
        return {r[0]: (r[1], r[2]) for r in rows}

    def _validate_species_limits(self, df: pd.DataFrame, columns: Dict[str, str]) -> Dict[str, Any]:
        """A species cannot exceed what is known of it: DBH or height above the species' own maximum is a soft flag (confirm), never a refusal.

        Rows already refused by a hard limit are not repeated here.
        """
        results: Dict[str, Any] = {}
        for stand in ("pole", "tree"):
            sp_col = columns.get(f"{stand}_species_scientific")
            if not sp_col or sp_col not in df.columns:
                continue
            names = sorted({str(v).strip().lower() for v in df[sp_col].dropna() if str(v).strip()})
            limits = self._species_limits(names)
            if not limits:
                continue
            for measure, idx in (("dbh", 0), ("height", 1)):
                col = columns.get(f"{stand}_{measure}")
                rule = RULES.get(f"{stand}_{measure}")
                if not col or col not in df.columns or rule is None:
                    continue
                values = pd.to_numeric(df[col], errors="coerce")
                _, hard_hi = rule.hard_bounds()
                bad_rows, example = [], None
                for i, (name, value) in enumerate(zip(df[sp_col], values)):
                    cap = limits.get(str(name).strip().lower(), (None, None))[idx] if pd.notna(name) else None
                    if cap is None or pd.isna(value) or value <= cap or (hard_hi is not None and value > hard_hi):
                        continue
                    bad_rows.append(int(df.index[i]) + 2)
                    example = example or (str(name).strip(), float(value), float(cap))
                if bad_rows:
                    label, unit = self._MEASURE_NP[measure], self._UNIT_NP["cm" if measure == "dbh" else "m"]
                    self.warnings.append({
                        'severity': 'warning', 'type': f"{measure}_above_species_max", 'stand_type': stand,
                        'message': f"{stand.capitalize()}: {len(bad_rows)} {label} मान प्रजातिको अधिकतम भन्दा बढी (जस्तै {example[0]}: {example[1]:g} > {example[2]:g} {unit}) — पुष्टि गर्नुहोस्, पङ्क्ति: {self._rows_text(bad_rows)}",
                        'rows': bad_rows[:20],
                    })
                    results[f"{stand}_{measure}"] = len(bad_rows)
        return results

    async def _validate_boundary(
        self,
        df: pd.DataFrame,
        columns: Dict[str, str],
        calculation_id: UUID
    ) -> Optional[Dict[str, Any]]:
        """Validate sample plots against boundary"""
        logger.info(f"[BOUNDARY_VALIDATION] Checking boundary for calculation {calculation_id}")

        try:
            from ..services.boundary_validator import validate_inventory_boundary
            from shapely.geometry import Point

            lon_col = columns.get('longitude')
            lat_col = columns.get('latitude')

            if not lon_col or not lat_col:
                return None

            # Extract unique sample plot points
            plot_points = []
            for idx, row in df.iterrows():
                if pd.notna(row[lon_col]) and pd.notna(row[lat_col]):
                    plot_points.append((
                        float(row[lon_col]),
                        float(row[lat_col]),
                        idx + 1
                    ))

            # Validate boundary (20% tolerance)
            boundary_result = validate_inventory_boundary(
                self.db,
                calculation_id,
                plot_points,
                tolerance_percent=20.0
            )

            logger.info(f"[BOUNDARY_VALIDATION] Result: {boundary_result['out_of_boundary_percentage']}% outside")

            # If >20% outside, add error
            if not boundary_result['within_tolerance']:
                self.errors.append({
                    'severity': 'error',
                    'type': 'boundary_error',
                    'message': boundary_result.get('error_message', 'BOUNDARY_ERROR: धेरै सेम्पल प्लट सीमा बाहिर छन्')
                })
            elif boundary_result['needs_correction']:
                self.warnings.append({
                    'severity': 'warning',
                    'type': 'boundary_warning',
                    'message': f"BOUNDARY_WARNING: {boundary_result['out_of_boundary_count']} सेम्पल प्लट सीमा बाहिर छन् (२०% सहनशीलता भित्र)"
                })

            return boundary_result

        except Exception as e:
            logger.error(f"[BOUNDARY_VALIDATION] Error: {str(e)}")
            self.warnings.append({
                'severity': 'warning',
                'type': 'boundary_check_error',
                'message': f"Could not validate boundary: {str(e)}"
            })
            return None
