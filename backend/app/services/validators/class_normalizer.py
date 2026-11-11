"""
Tree Class Normalizer

Converts various tree class formats to standard numeric format (1/2/3/4):
- Letters: A/a → 1, B/b → 2, C/c → 3, D/d → 4
- Roman numerals: I/i → 1, II/ii → 2, III/iii → 3, IV/iv → 4
- Nepali characters: क → 1, ख → 2, ग → 3, घ → 4
- Numbers: 1, 2, 3, 4 (kept as-is)

Author: Forest Management System
Date: February 13, 2026
"""

from typing import Optional, Tuple, Dict, Any
import pandas as pd


class ClassNormalizer:
    """Normalizes tree class values to standard numeric format (1/2/3/4)"""

    # Mapping dictionaries for different formats
    LETTER_MAP = {
        'A': 1, 'a': 1,
        'B': 2, 'b': 2,
        'C': 3, 'c': 3,
        'D': 4, 'd': 4
    }

    ROMAN_MAP = {
        'I': 1, 'i': 1,
        'II': 2, 'ii': 2,
        'III': 3, 'iii': 3,
        'IV': 4, 'iv': 4
    }

    NEPALI_MAP = {
        'क': 1,  # Ka
        'ख': 2,  # Kha
        'ग': 3,  # Ga
        'घ': 4   # Gha
    }

    def __init__(self):
        """Initialize the class normalizer"""
        self.conversions = []
        self.invalid_values = []

    def normalize_value(self, value: Any) -> Tuple[Optional[int], str, str]:
        """
        Normalize a single class value to numeric format

        Args:
            value: The class value to normalize (can be str, int, float, etc.)

        Returns:
            Tuple of (normalized_value, method, message)
            - normalized_value: 1/2/3/4 or None if invalid
            - method: 'numeric', 'letter', 'roman', 'nepali', 'invalid', or 'empty'
            - message: Description of conversion or error
        """
        # Handle empty/null values
        if pd.isna(value) or value == '' or value is None:
            return None, 'empty', 'Empty class value'

        # Convert to string and strip whitespace
        value_str = str(value).strip()

        # Already numeric 1-4
        try:
            numeric_val = int(float(value_str))
            if numeric_val in [1, 2, 3, 4]:
                return numeric_val, 'numeric', f'Already numeric: {numeric_val}'
        except (ValueError, TypeError):
            pass

        # Check letter format (A/B/C/D)
        if value_str in self.LETTER_MAP:
            normalized = self.LETTER_MAP[value_str]
            return normalized, 'letter', f'Converted letter "{value_str}" → {normalized}'

        # Check Roman numerals (I/II/III/IV)
        if value_str in self.ROMAN_MAP:
            normalized = self.ROMAN_MAP[value_str]
            return normalized, 'roman', f'Converted Roman "{value_str}" → {normalized}'

        # Check Nepali characters (क/ख/ग/घ)
        if value_str in self.NEPALI_MAP:
            normalized = self.NEPALI_MAP[value_str]
            return normalized, 'nepali', f'Converted Nepali "{value_str}" → {normalized}'

        # Invalid value
        return None, 'invalid', f'Invalid class value: "{value_str}" (expected: 1-4, A-D, I-IV, or क-घ)'

    def normalize_dataframe(self, df: pd.DataFrame, class_column: str) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """
        Normalize class column in a DataFrame

        Args:
            df: DataFrame to normalize
            class_column: Name of the class column

        Returns:
            Tuple of (normalized_df, report)
            - normalized_df: DataFrame with normalized class values
            - report: Dictionary with conversion statistics and details
        """
        if class_column not in df.columns:
            return df, {
                'status': 'skipped',
                'message': f'Column "{class_column}" not found in data'
            }

        self.conversions = []
        self.invalid_values = []

        # Convert column to string dtype for categorical data (1,2,3,4,A,B,C,D,etc.)
        # Replace NaN with empty string first to avoid "nan" string values
        df[class_column] = df[class_column].fillna('').astype(str)

        # Statistics
        stats = {
            'total_rows': len(df),
            'numeric': 0,
            'letter': 0,
            'roman': 0,
            'nepali': 0,
            'empty': 0,
            'invalid': 0
        }

        # Normalize each value
        for idx, value in enumerate(df[class_column]):
            normalized, method, message = self.normalize_value(value)

            # Update statistics
            stats[method] += 1

            # Track conversions and invalid values
            if method not in ['empty', 'numeric']:
                if method == 'invalid':
                    self.invalid_values.append({
                        'row': idx + 1,
                        'original_value': value,
                        'message': message
                    })
                else:
                    self.conversions.append({
                        'row': idx + 1,
                        'original_value': value,
                        'normalized_value': normalized,
                        'method': method,
                        'message': message
                    })

            # Update DataFrame with string values (class is categorical, not numeric)
            if normalized is not None:
                df.at[idx, class_column] = str(normalized)
            else:
                df.at[idx, class_column] = ''  # Empty string instead of None for string column

        # Generate report
        report = {
            'status': 'completed',
            'statistics': stats,
            'conversions': self.conversions,
            'invalid_values': self.invalid_values,
            'total_conversions': stats['letter'] + stats['roman'] + stats['nepali'],
            'success_rate': ((stats['total_rows'] - stats['invalid']) / stats['total_rows'] * 100) if stats['total_rows'] > 0 else 0
        }

        return df, report

    def get_summary(self, report: Dict[str, Any]) -> str:
        """
        Generate a human-readable summary of class normalization

        Args:
            report: Report dictionary from normalize_dataframe()

        Returns:
            Formatted summary string
        """
        if report['status'] == 'skipped':
            return report['message']

        stats = report['statistics']
        lines = [
            "CLASS NORMALIZATION SUMMARY:",
            f"Total rows: {stats['total_rows']}",
            f"  - Already numeric (1-4): {stats['numeric']}",
            f"  - Letter format (A-D): {stats['letter']}",
            f"  - Roman numerals (I-IV): {stats['roman']}",
            f"  - Nepali characters (क-घ): {stats['nepali']}",
            f"  - Empty/null: {stats['empty']}",
            f"  - Invalid values: {stats['invalid']}",
            f"Total conversions: {report['total_conversions']}",
            f"Success rate: {report['success_rate']:.1f}%"
        ]

        if report['invalid_values']:
            lines.append(f"\nWARNING: {len(report['invalid_values'])} invalid class values found:")
            for item in report['invalid_values'][:5]:  # Show first 5
                lines.append(f"  Row {item['row']}: {item['message']}")
            if len(report['invalid_values']) > 5:
                lines.append(f"  ... and {len(report['invalid_values']) - 5} more")

        return '\n'.join(lines)
