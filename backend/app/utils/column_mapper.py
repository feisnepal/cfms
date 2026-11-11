"""
Column Mapper Utility for Tree Inventory CSV Uploads

This module provides intelligent column mapping to handle various naming conventions,
languages (English/Nepali), typos, and formatting variations in uploaded CSV files.

Features:
- Fuzzy string matching for similar column names
- Nepali Unicode normalization support
- Case-insensitive matching
- User preference learning
- Confidence scoring
"""
# why: maps CSV column headers to DB field names via lookup table
# constraint: supports Nepali and English header names
# NOTE: fuzzy matching for common variations

import re
import unicodedata
from typing import Dict, List, Optional, Tuple
from fuzzywuzzy import fuzz


# Comprehensive mapping dictionary with all possible variations
COLUMN_MAPPING = {
    "species": [
        # English variations - full forms
        "species", "species name", "tree species", "plant species",
        "scientific name", "botanical name", "latin name", "binomial name",
        "taxonomic name", "genus species",

        # English variations - short forms
        "name", "tree name", "plant name", "specie", "spp", "sp",
        "tree type", "wood species",

        # Common/vernacular names
        "common name", "local name", "vernacular name", "nepali name",

        # Nepali variations (Devanagari)
        "प्रजाती", "प्रजाति", "प्रजाती नाम", "प्रजातीको नाम",
        "वैज्ञानिक नाम", "बैज्ञानिक नाम", "बैज्ञानीक नाम",
        "वैज्ञानीक नाम", "नाम", "रुखको नाम", "वनस्पतिको नाम",
        "स्थानीय नाम", "नेपाली नाम", "रूख",
    ],

    "dia_cm": [
        # Full forms - diameter
        "diameter cm", "diameter centimeter", "diameter centimetre",
        "diameter in cm", "diameter in centimeter",

        # DBH (Diameter at Breast Height) variations
        "dbh", "dbh cm", "dbh_cm", "dbh(cm)", "dbh (cm)", "dbh-cm",
        "diameter at breast height", "diameter at breast height cm",
        "breast height diameter", "breast height diameter cm",

        # Abbreviations - dia
        "dia", "dia cm", "dia_cm", "dia(cm)", "dia (cm)", "dia-cm",
        "diam", "diam cm", "diameter",

        # Different measurement points
        "diameter base", "diameter mid", "stump diameter",
        "basal diameter", "bole diameter", "stem diameter",

        # Various formatting
        "diameter[cm]", "diameter - cm", "diameter: cm", "dia. cm",
        "dia in cm", "d cm", "d(cm)",

        # Common typos
        "diamter", "diametr", "diameer", "dbh cm",

        # Nepali variations (Devanagari)
        "व्यास", "व्यास से मी", "व्यास सेमी", "डी बी एच",
        "व्यास सेन्टिमिटर", "व्यास सेंटीमीटर",
        "छातीको उचाइमा व्यास", "छातीमा व्यास",
    ],

    "height_m": [
        # Full forms - height
        "height m", "height meter", "height metre", "height in m",
        "height in meter", "height in metre",
        "tree height", "tree height m", "tree height meter",

        # Abbreviations - ht
        "height", "height_m", "height_meter", "height(m)", "height (m)",
        "height[m]", "height - m", "height: m",
        "ht", "ht m", "ht_m", "ht(m)", "ht (m)",

        # Different units spelled out
        "height mt", "height mtr", "height_mt", "height_mtr",
        "height(meter)", "height (meter)", "height(metre)", "height (metre)",

        # Different height types
        "total height", "bole height", "merchantable height",
        "commercial height", "clear bole height", "stem height",

        # Various formatting
        "h m", "h(m)", "h_m", "tree ht m",

        # Common typos
        "hieght", "heigth", "hight", "heigt",

        # Nepali variations (Devanagari)
        "उचाइ", "उचाइ मि", "उचाइ मी", "उचाइ मिटर", "उचाइ मीटर",
        "रुखको उचाइ", "उचाइ म", "ऊंचाई", "ऊचाइ",
    ],

    "class": [
        # English variations - class
        "class", "quality class", "qc", "tree class", "stem class",

        # Quality variations
        "quality", "quality grade", "grade", "timber class",
        "wood quality", "stem quality", "log class", "quality rating",

        # Grades with numbers/letters
        "grade a", "grade b", "grade c",
        "class 1", "class 2", "class 3",
        "quality 1", "quality 2", "quality 3",

        # Nepali variations (Devanagari)
        "गुणस्तर", "क्लास", "गुणस्तर वर्ग", "श्रेणी", "वर्ग",
        "क्लास १", "क्लास २", "क्लास ३",
        "गुणस्तर श्रेणी",
    ],

    "LONGITUDE": [
        # Full forms
        "longitude", "long", "lng", "lon",

        # Coordinate naming
        "x coordinate", "x coord", "x-coordinate", "x_coordinate",
        "x", "x value", "x position",

        # UTM specific
        "easting", "east", "utm x", "utm_x", "utm easting",
        "utm east", "utm longitude",

        # GPS variations
        "gps longitude", "gps long", "gps x", "gps lon",
        "gps lng", "gps east", "gps easting",

        # Decimal degrees
        "lon dd", "long dd", "longitude dd", "longitude decimal",
        "long decimal", "decimal longitude",

        # Various formatting
        "long.", "lon.", "lng.", "longitude(dd)", "long (dd)",

        # Nepali variations (Devanagari)
        "देशान्तर", "देशान्तर रेखा", "देशांतर", "देशान्तर रेखांश",
        "लङ्गीट्यूड", "लांगिच्यूड",
    ],

    "LATITUDE": [
        # Full forms
        "latitude", "lat", "lati",

        # Coordinate naming
        "y coordinate", "y coord", "y-coordinate", "y_coordinate",
        "y", "y value", "y position",

        # UTM specific
        "northing", "north", "utm y", "utm_y", "utm northing",
        "utm north", "utm latitude",

        # GPS variations
        "gps latitude", "gps lat", "gps y", "gps lati",
        "gps north", "gps northing",

        # Decimal degrees
        "lat dd", "latitude dd", "latitude decimal",
        "lat decimal", "decimal latitude",

        # Various formatting
        "lat.", "lati.", "latitude(dd)", "lat (dd)",

        # Nepali variations (Devanagari)
        "अक्षाँस", "अक्षांश", "अक्षांश रेखा", "अक्षाश",
        "अक्षांश रेखांश", "ल्याटिच्यूड", "लाटिट्यूड",
    ],
}


class ColumnMapper:
    """
    Intelligent column mapper for tree inventory CSV uploads.

    Handles:
    - Case variations (upper, lower, mixed)
    - Special characters and formatting
    - Nepali Unicode text
    - Fuzzy matching for typos
    - Confidence scoring
    """

    def __init__(self):
        """Initialize column mapper with standard column definitions"""
        self.required_columns = ["species", "dia_cm", "height_m", "LONGITUDE", "LATITUDE"]
        self.optional_columns = ["class"]
        self.all_standard_columns = self.required_columns + self.optional_columns
        self.mapping_dict = COLUMN_MAPPING
        # Preferred column name substrings for tie-breaking
        # When multiple columns map to the same standard column with equal priority,
        # the one containing a preferred pattern wins (more semantically accurate).
        self.preferred_patterns = {
            "species": ["scientific", "botanical", "latin"],
        }

    def normalize(self, col: str) -> str:
        """
        Normalize column name for matching.

        Steps:
        1. Unicode normalization (handle Nepali characters)
        2. Convert to lowercase
        3. Remove special characters (keep spaces)
        4. Collapse multiple spaces
        5. Trim whitespace

        Args:
            col: Original column name

        Returns:
            Normalized column name

        Examples:
            >>> mapper = ColumnMapper()
            >>> mapper.normalize("DBH (cm)")
            'dbh cm'
            >>> mapper.normalize("Species_Name")
            'species name'
            >>> mapper.normalize("प्रजाती")
            'प्रजाती'
        """
        # Unicode normalization (NFKD = compatibility decomposition)
        col = unicodedata.normalize('NFKD', col)

        # Convert to lowercase
        col = col.lower()

        # Remove special characters but keep spaces and Nepali characters
        # Keep: alphanumeric, spaces, Nepali Unicode range (U+0900 to U+097F)
        col = re.sub(r'[^\w\s\u0900-\u097F]', ' ', col)

        # Replace multiple spaces with single space
        col = re.sub(r'\s+', ' ', col)

        # Trim leading/trailing whitespace
        col = col.strip()

        return col

    def find_best_match(self, csv_col: str, threshold: int = 70) -> Optional[Tuple[str, int]]:
        """
        Find best matching standard column for a CSV column.

        Uses fuzzy string matching with configurable threshold.

        Args:
            csv_col: Column name from uploaded CSV
            threshold: Minimum confidence score (0-100) to accept match

        Returns:
            Tuple of (standard_column, confidence_score) or None if no match

        Examples:
            >>> mapper = ColumnMapper()
            >>> mapper.find_best_match("Species Name")
            ('species', 100)
            >>> mapper.find_best_match("DBH")
            ('dia_cm', 100)
            >>> mapper.find_best_match("xyz123")
            None
        """
        normalized_csv = self.normalize(csv_col)
        best_match = None
        best_score = 0

        # Check each standard column and its variations
        for std_col, variations in self.mapping_dict.items():
            for variation in variations:
                norm_variation = self.normalize(variation)

                # Exact match gets 100% confidence
                if normalized_csv == norm_variation:
                    return (std_col, 100)

                # Fuzzy match using Levenshtein distance
                score = fuzz.ratio(normalized_csv, norm_variation)

                # Also try partial matching (for substrings)
                partial_score = fuzz.partial_ratio(normalized_csv, norm_variation)

                # Use the higher score
                final_score = max(score, partial_score)

                if final_score > best_score:
                    best_score = final_score
                    best_match = std_col

        # Return match only if above threshold
        if best_score >= threshold:
            return (best_match, best_score)

        return None

    def auto_map_columns(
        self,
        csv_columns: List[str],
        threshold: int = 70
    ) -> Dict:
        """
        Automatically map CSV columns to standard columns.

        Args:
            csv_columns: List of column names from uploaded CSV
            threshold: Minimum confidence score (0-100) to accept match

        Returns:
            Dictionary with keys:
            - mapped: {csv_col: std_col} for successful mappings
            - unmapped: [csv_col] for columns that couldn't be mapped
            - confidence: {csv_col: score} for all mapped columns
            - suggestions: {csv_col: [(std_col, score), ...]} for unmapped columns
            - duplicates: {std_col: [csv_col, ...]} for duplicate mappings

        Examples:
            >>> mapper = ColumnMapper()
            >>> result = mapper.auto_map_columns([
            ...     "Species Name", "DBH", "Height(m)", "Quality", "Long", "Lat"
            ... ])
            >>> result['mapped']
            {'Species Name': 'species', 'DBH': 'dia_cm', ...}
        """
        mapped = {}
        unmapped = []
        confidence = {}
        suggestions = {}

        # First pass: Find best matches
        for csv_col in csv_columns:
            match = self.find_best_match(csv_col, threshold)

            if match:
                std_col, score = match
                mapped[csv_col] = std_col
                confidence[csv_col] = score
            else:
                unmapped.append(csv_col)
                # Generate suggestions for unmapped columns
                suggestions[csv_col] = self._get_suggestions(csv_col)

        # Check for duplicate mappings (multiple CSV columns mapped to same standard column)
        duplicates = self._check_duplicates(mapped)

        # AUTO-RESOLVE DUPLICATES: Keep best match using smart tie-breaking
        if duplicates:
            for std_col, csv_cols in duplicates.items():
                # Smart tie-breaking: prefer exact matches, then highest confidence,
                # then longest name, then preferred semantic patterns.
                def match_priority(col):
                    conf = confidence[col]
                    is_exact = (self.normalize(col) == self.normalize(std_col))
                    col_len = len(col)
                    patterns = self.preferred_patterns.get(std_col, [])
                    has_preferred = any(p in col.lower() for p in patterns)
                    # Return tuple (all DESC — max() picks the best)
                    return (is_exact, conf, col_len, has_preferred)

                # Find best mapping using priority
                best_csv_col = max(csv_cols, key=match_priority)

                # Demote other mappings to unmapped with suggestions
                for csv_col in csv_cols:
                    if csv_col != best_csv_col:
                        # Move to unmapped
                        unmapped.append(csv_col)
                        # Remove from mapped
                        del mapped[csv_col]
                        # Add suggestions showing it was close to std_col
                        suggestions[csv_col] = [(std_col, confidence[csv_col])] + self._get_suggestions(csv_col, top_n=2)
                        # Remove confidence
                        del confidence[csv_col]

            # Recalculate duplicates after resolution
            duplicates = self._check_duplicates(mapped)

        # Validate required columns are present
        missing_required = self._check_missing_required(mapped)

        return {
            "mapped": mapped,
            "unmapped": unmapped,
            "confidence": confidence,
            "suggestions": suggestions,
            "duplicates": duplicates,
            "missing_required": missing_required,
        }

    def _get_suggestions(self, csv_col: str, top_n: int = 3) -> List[Tuple[str, int]]:
        """
        Get top N suggestions for an unmapped column.

        Args:
            csv_col: Column name that couldn't be mapped
            top_n: Number of suggestions to return

        Returns:
            List of (standard_column, confidence_score) tuples, sorted by score
        """
        normalized_csv = self.normalize(csv_col)
        all_scores = []

        for std_col, variations in self.mapping_dict.items():
            max_score = 0
            for variation in variations:
                norm_variation = self.normalize(variation)
                score = fuzz.ratio(normalized_csv, norm_variation)
                partial_score = fuzz.partial_ratio(normalized_csv, norm_variation)
                max_score = max(max_score, score, partial_score)

            all_scores.append((std_col, max_score))

        # Sort by score descending and return top N
        all_scores.sort(key=lambda x: x[1], reverse=True)
        return all_scores[:top_n]

    def _check_duplicates(self, mapping: Dict[str, str]) -> Dict[str, List[str]]:
        """
        Check for duplicate mappings (multiple CSV columns mapped to same standard column).

        Args:
            mapping: Dictionary of {csv_col: std_col}

        Returns:
            Dictionary of {std_col: [csv_col1, csv_col2, ...]} for duplicates
        """
        reverse_map = {}
        for csv_col, std_col in mapping.items():
            if std_col not in reverse_map:
                reverse_map[std_col] = []
            reverse_map[std_col].append(csv_col)

        # Return only those with multiple mappings, but allow multiple columns to map to '_ignore'
        duplicates = {
            std_col: csv_cols
            for std_col, csv_cols in reverse_map.items()
            if len(csv_cols) > 1 and std_col != '_ignore'
        }

        return duplicates

    def _check_missing_required(self, mapping: Dict[str, str]) -> List[str]:
        """
        Check if all required columns are mapped.

        Args:
            mapping: Dictionary of {csv_col: std_col}

        Returns:
            List of required standard columns that are missing
        """
        mapped_values = set(mapping.values())
        missing = [
            col for col in self.required_columns
            if col not in mapped_values
        ]
        return missing

    def validate_mapping(self, mapping: Dict[str, str]) -> Dict:
        """
        Validate a user-confirmed mapping.

        Checks:
        - All required columns are present
        - No duplicate mappings
        - All standard columns are valid

        Args:
            mapping: User-confirmed {csv_col: std_col} mapping

        Returns:
            Dictionary with keys:
            - valid: bool indicating if mapping is valid
            - errors: List of error messages
            - warnings: List of warning messages
        """
        errors = []
        warnings = []

        # Check for duplicates
        duplicates = self._check_duplicates(mapping)
        if duplicates:
            for std_col, csv_cols in duplicates.items():
                errors.append(
                    f"Column '{std_col}' is mapped from multiple CSV columns: "
                    f"{', '.join(csv_cols)}. Please choose only one."
                )

        # Check for missing required columns
        missing = self._check_missing_required(mapping)
        if missing:
            errors.append(
                f"Missing required columns: {', '.join(missing)}. "
                f"Please map these columns to proceed."
            )

        # Check for invalid standard columns
        for csv_col, std_col in mapping.items():
            if std_col not in self.all_standard_columns:
                warnings.append(
                    f"Column '{csv_col}' is mapped to unknown standard column '{std_col}'. "
                    f"This column will be ignored."
                )

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }

    def apply_mapping(self, df, mapping: Dict[str, str]) -> Dict:
        """
        Apply confirmed mapping to a pandas DataFrame.

        Args:
            df: pandas DataFrame with original CSV columns
            mapping: Dictionary of {csv_col: std_col}

        Returns:
            Dictionary with keys:
            - df: Renamed DataFrame
            - renamed_columns: List of columns that were renamed
            - preserved_columns: List of columns not in mapping (kept as-is)
        """
        import pandas as pd

        # Separate mapped and unmapped columns
        mapped_cols = set(mapping.keys())
        all_cols = set(df.columns)
        preserved_cols = list(all_cols - mapped_cols)

        # Drop existing columns whose names collide with mapping targets to prevent
        # duplicate columns (e.g., GPKG geometry extraction creates LONGITUDE/LATITUDE
        # AND user maps lon/lat attribute columns → rename creates two LONGITUDE cols)
        conflicting = [v for k, v in mapping.items() if v != k and v in df.columns]
        if conflicting:
            df = df.drop(columns=conflicting)

        # Rename columns according to mapping
        df_renamed = df.rename(columns=mapping)

        return {
            "df": df_renamed,
            "renamed_columns": list(mapping.keys()),
            "preserved_columns": preserved_cols,
        }


# Convenience function for quick testing
def test_mapper():
    """Test the column mapper with sample data"""
    mapper = ColumnMapper()

    # Test cases
    test_columns = [
        "Species Name",
        "DBH",
        "Height(m)",
        "Quality",
        "Long",
        "Lat",
        "प्रजाती",
        "व्यास से मी",
        "उचाइ मिटर",
    ]

    print("=" * 70)
    print("COLUMN MAPPER TEST")
    print("=" * 70)

    for col in test_columns:
        normalized = mapper.normalize(col)
        match = mapper.find_best_match(col)

        print(f"\nOriginal:    {col}")
        print(f"Normalized:  {normalized}")
        if match:
            std_col, score = match
            print(f"Matched:     {std_col} (confidence: {score}%)")
        else:
            print(f"Matched:     No match found")

    print("\n" + "=" * 70)
    print("AUTO-MAPPING RESULT")
    print("=" * 70)

    result = mapper.auto_map_columns(test_columns)

    print("\nMapped columns:")
    for csv_col, std_col in result["mapped"].items():
        conf = result["confidence"][csv_col]
        print(f"  {csv_col:20s} -> {std_col:15s} (confidence: {conf}%)")

    print("\nUnmapped columns:")
    for csv_col in result["unmapped"]:
        print(f"  {csv_col}")
        print(f"    Suggestions: {result['suggestions'][csv_col]}")

    if result["duplicates"]:
        print("\nDuplicate mappings:")
        for std_col, csv_cols in result["duplicates"].items():
            print(f"  {std_col}: {csv_cols}")

    if result["missing_required"]:
        print("\nMissing required columns:")
        for col in result["missing_required"]:
            print(f"  {col}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    test_mapper()
