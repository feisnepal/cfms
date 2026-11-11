"""
Regeneration Tree Validator

Detects regeneration trees (DBH 1-10 cm) and validates that they should not
have height or class measurements according to Nepal forest inventory standards.

Author: Forest Management System
Date: February 13, 2026
"""

from typing import List, Dict, Any, Optional, Tuple
import pandas as pd

from ...core.dbh_classifier import DbhClassRegistry as _DCR


def _resolve_dbh_thresholds():
    """Lazy-resolve DBH thresholds from SSOT registry (B4 fix)."""
    regen = _DCR.get_system("harvesting_cfmg")
    regen_cls = next((c for c in regen if c.key == "regeneration"), None)
    if regen_cls:
        return regen_cls.lower, regen_cls.upper
    return 1.0, 10.0


class RegenerationValidator:
    """Validates regeneration trees (DBH 1-10 cm) and flags inappropriate height/class values"""

    # DBH thresholds — resolved from SSOT registry at first use
    REGENERATION_MIN_DBH: float = 1.0
    REGENERATION_MAX_DBH: float = 10.0
    SEEDLING_MAX_DBH: float = 4.0
    SAPLING_MAX_DBH: float = 10.0
    _thresholds_resolved: bool = False

    def __init__(self):
        """Initialize the regeneration validator"""
        if not RegenerationValidator._thresholds_resolved:
            RegenerationValidator._resolve_class_thresholds()
        self.regeneration_trees = []
        self.trees_with_issues = []

    @classmethod
    def _resolve_class_thresholds(cls):
        lo, hi = _resolve_dbh_thresholds()
        cls.REGENERATION_MIN_DBH = lo
        cls.REGENERATION_MAX_DBH = hi
        # Fine-grained: seedling = regen range start to 4, sapling = 4 to regen max
        seedling = _DCR.classify(0, "guideline_simple")
        if seedling:
            cls.SEEDLING_MAX_DBH = seedling.upper
        sapling = _DCR.classify(5, "guideline_simple")
        if sapling:
            cls.SAPLING_MAX_DBH = sapling.upper
        cls._thresholds_resolved = True

    def validate_dataframe(
        self,
        df: pd.DataFrame,
        dia_column: str,
        height_column: Optional[str] = None,
        class_column: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Validate regeneration trees in a DataFrame

        Args:
            df: DataFrame to validate
            dia_column: Name of the diameter column
            height_column: Name of the height column (optional)
            class_column: Name of the class column (optional)

        Returns:
            Dictionary with validation results and details
        """
        if dia_column not in df.columns:
            return {
                'status': 'skipped',
                'message': f'Column "{dia_column}" not found in data'
            }

        self.regeneration_trees = []
        self.trees_with_issues = []

        # Find regeneration trees
        for idx, row in df.iterrows():
            dbh = row[dia_column]

            # Skip if DBH is null or not numeric
            if pd.isna(dbh):
                continue

            try:
                dbh_value = float(dbh)
            except (ValueError, TypeError):
                continue

            # Check if it's a regeneration tree
            if self.REGENERATION_MIN_DBH <= dbh_value < self.REGENERATION_MAX_DBH:
                tree_info = {
                    'row': idx + 1,
                    'dbh': dbh_value,
                    'has_height': False,
                    'has_class': False,
                    'height_value': None,
                    'class_value': None
                }

                # Check if height is present
                if height_column and height_column in df.columns:
                    height_val = row[height_column]
                    if pd.notna(height_val) and height_val != '' and height_val != 0:
                        tree_info['has_height'] = True
                        tree_info['height_value'] = height_val

                # Check if class is present
                if class_column and class_column in df.columns:
                    class_val = row[class_column]
                    if pd.notna(class_val) and class_val != '' and class_val != 0:
                        tree_info['has_class'] = True
                        tree_info['class_value'] = class_val

                self.regeneration_trees.append(tree_info)

                # Track trees with inappropriate values
                if tree_info['has_height'] or tree_info['has_class']:
                    self.trees_with_issues.append(tree_info)

        # Generate report
        report = {
            'status': 'completed',
            'total_regeneration': len(self.regeneration_trees),
            'trees_with_issues': len(self.trees_with_issues),
            'regeneration_trees': self.regeneration_trees,
            'trees_with_issues_list': self.trees_with_issues,
            'needs_user_confirmation': len(self.trees_with_issues) > 0,
            'threshold': {
                'min_dbh': self.REGENERATION_MIN_DBH,
                'max_dbh': self.REGENERATION_MAX_DBH
            }
        }

        return report

    def remove_height_class_values(
        self,
        df: pd.DataFrame,
        dia_column: str,
        height_column: Optional[str] = None,
        class_column: Optional[str] = None
    ) -> Tuple[pd.DataFrame, int]:
        """
        Remove height and class values from regeneration trees

        Args:
            df: DataFrame to modify
            dia_column: Name of the diameter column
            height_column: Name of the height column (optional)
            class_column: Name of the class column (optional)

        Returns:
            Tuple of (modified_df, count_of_modifications)
        """
        modifications = 0

        for idx, row in df.iterrows():
            dbh = row[dia_column]

            # Skip if DBH is null or not numeric
            if pd.isna(dbh):
                continue

            try:
                dbh_value = float(dbh)
            except (ValueError, TypeError):
                continue

            # If it's a regeneration tree, remove height/class
            if self.REGENERATION_MIN_DBH <= dbh_value < self.REGENERATION_MAX_DBH:
                # Remove height
                if height_column and height_column in df.columns:
                    height_val = df.at[idx, height_column]
                    if pd.notna(height_val):
                        if height_val != '':
                            df.at[idx, height_column] = None
                            modifications += 1

                # Remove class
                if class_column and class_column in df.columns:
                    class_val = df.at[idx, class_column]
                    if pd.notna(class_val):
                        if class_val != '':
                            df.at[idx, class_column] = None
                            modifications += 1

        return df, modifications

    def get_summary(self, report: Dict[str, Any]) -> str:
        """
        Generate a human-readable summary of regeneration validation

        Args:
            report: Report dictionary from validate_dataframe()

        Returns:
            Formatted summary string
        """
        if report['status'] == 'skipped':
            return report['message']

        lines = [
            "REGENERATION VALIDATION SUMMARY:",
            f"DBH threshold: {report['threshold']['min_dbh']}-{report['threshold']['max_dbh']} cm",
            f"Total regeneration trees: {report['total_regeneration']}",
            f"Trees with height/class values: {report['trees_with_issues']}"
        ]

        if report['trees_with_issues'] > 0:
            lines.append("\nWARNING: Found regeneration trees with inappropriate height/class values:")
            lines.append("According to Nepal forest inventory standards, regeneration trees (DBH 1-10 cm)")
            lines.append("should not have height or class measurements.\n")

            for item in report['trees_with_issues_list'][:10]:  # Show first 10
                issues = []
                if item['has_height']:
                    issues.append(f"Height={item['height_value']} m")
                if item['has_class']:
                    issues.append(f"Class={item['class_value']}")

                lines.append(f"  Row {item['row']}: DBH={item['dbh']:.1f} cm, {', '.join(issues)}")

            if len(report['trees_with_issues_list']) > 10:
                lines.append(f"  ... and {len(report['trees_with_issues_list']) - 10} more")

            lines.append("\nUser confirmation required to remove these values.")

        return '\n'.join(lines)

    @staticmethod
    def is_regeneration(dbh: float) -> bool:
        """
        Check if a tree is regeneration based on DBH

        Args:
            dbh: Diameter at breast height in cm

        Returns:
            True if regeneration, False otherwise
        """
        if pd.isna(dbh):
            return False
        try:
            dbh_value = float(dbh)
            return RegenerationValidator.REGENERATION_MIN_DBH <= dbh_value < RegenerationValidator.REGENERATION_MAX_DBH
        except (ValueError, TypeError):
            return False
