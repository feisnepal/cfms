"""
Unit tests for column_mapper.py

Tests the intelligent column mapping functionality for tree inventory CSV uploads.
"""

import pytest
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.utils.column_mapper import ColumnMapper, COLUMN_MAPPING


class TestColumnNormalization:
    """Test column name normalization"""

    def setup_method(self):
        """Set up test fixtures"""
        self.mapper = ColumnMapper()

    def test_normalize_lowercase(self):
        """Test conversion to lowercase"""
        assert self.mapper.normalize("SPECIES") == "species"
        assert self.mapper.normalize("Species") == "species"
        assert self.mapper.normalize("SPeCiEs") == "species"

    def test_normalize_special_characters(self):
        """Test removal of special characters"""
        assert self.mapper.normalize("DBH (cm)") == "dbh cm"
        assert self.mapper.normalize("Height_m") == "height_m"  # Underscores are kept as word chars
        assert self.mapper.normalize("Species-Name") == "species name"
        assert self.mapper.normalize("Dia[cm]") == "dia cm"
        assert self.mapper.normalize("Height:m") == "height m"

    def test_normalize_whitespace(self):
        """Test whitespace handling"""
        assert self.mapper.normalize("  Species  Name  ") == "species name"
        assert self.mapper.normalize("Height   m") == "height m"
        assert self.mapper.normalize("\tDBH\t") == "dbh"

    def test_normalize_unicode(self):
        """Test Unicode normalization (Nepali characters)"""
        # Nepali text should be preserved after normalization
        assert self.mapper.normalize("प्रजाती") == "प्रजाती"
        assert self.mapper.normalize("व्यास") == "व्यास"
        assert self.mapper.normalize("उचाइ") == "उचाइ"


class TestColumnMatching:
    """Test fuzzy column matching"""

    def setup_method(self):
        """Set up test fixtures"""
        self.mapper = ColumnMapper()

    def test_exact_match_english(self):
        """Test exact matches for English column names"""
        assert self.mapper.find_best_match("species") == ("species", 100)
        assert self.mapper.find_best_match("dbh") == ("dia_cm", 100)
        assert self.mapper.find_best_match("height") == ("height_m", 100)
        assert self.mapper.find_best_match("longitude") == ("LONGITUDE", 100)
        assert self.mapper.find_best_match("latitude") == ("LATITUDE", 100)

    def test_case_insensitive_match(self):
        """Test case-insensitive matching"""
        assert self.mapper.find_best_match("SPECIES") == ("species", 100)
        assert self.mapper.find_best_match("DBH") == ("dia_cm", 100)
        assert self.mapper.find_best_match("HEIGHT") == ("height_m", 100)

    def test_common_variations(self):
        """Test common column name variations"""
        # Species variations
        assert self.mapper.find_best_match("Species Name")[0] == "species"
        assert self.mapper.find_best_match("Scientific Name")[0] == "species"
        assert self.mapper.find_best_match("Tree Species")[0] == "species"

        # Diameter variations
        assert self.mapper.find_best_match("DBH (cm)")[0] == "dia_cm"
        assert self.mapper.find_best_match("Diameter cm")[0] == "dia_cm"
        assert self.mapper.find_best_match("dia_cm")[0] == "dia_cm"

        # Height variations
        assert self.mapper.find_best_match("Height (m)")[0] == "height_m"
        assert self.mapper.find_best_match("Height meter")[0] == "height_m"
        assert self.mapper.find_best_match("Tree height m")[0] == "height_m"

        # Class variations
        assert self.mapper.find_best_match("Quality")[0] == "class"
        assert self.mapper.find_best_match("Quality Class")[0] == "class"
        assert self.mapper.find_best_match("Grade")[0] == "class"

        # Longitude variations
        assert self.mapper.find_best_match("Long")[0] == "LONGITUDE"
        assert self.mapper.find_best_match("Lng")[0] == "LONGITUDE"
        assert self.mapper.find_best_match("X")[0] == "LONGITUDE"
        assert self.mapper.find_best_match("Easting")[0] == "LONGITUDE"

        # Latitude variations
        assert self.mapper.find_best_match("Lat")[0] == "LATITUDE"
        assert self.mapper.find_best_match("Y")[0] == "LATITUDE"
        assert self.mapper.find_best_match("Northing")[0] == "LATITUDE"

    def test_nepali_column_names(self):
        """Test Nepali column name matching"""
        # These should match even with Nepali text
        assert self.mapper.find_best_match("प्रजाती")[0] == "species"
        assert self.mapper.find_best_match("व्यास")[0] == "dia_cm"
        assert self.mapper.find_best_match("उचाइ")[0] == "height_m"
        assert self.mapper.find_best_match("गुणस्तर")[0] == "class"

    def test_typo_matching(self):
        """Test fuzzy matching for common typos"""
        # Common typos should still match (with lower confidence)
        match = self.mapper.find_best_match("Hieght")  # typo for Height
        assert match is not None
        assert match[0] == "height_m"

        match = self.mapper.find_best_match("Diamter")  # typo for Diameter
        assert match is not None
        assert match[0] == "dia_cm"

    def test_no_match(self):
        """Test that unrelated columns return None"""
        # Use completely unrelated terms with no forestry connection
        assert self.mapper.find_best_match("customer_id") is None
        assert self.mapper.find_best_match("invoice_number") is None
        assert self.mapper.find_best_match("zzzqqqwww") is None

    def test_confidence_threshold(self):
        """Test that low confidence matches are rejected"""
        # With high threshold, weak matches should be rejected
        result = self.mapper.find_best_match("customer_id", threshold=90)
        assert result is None


class TestAutoMapping:
    """Test automatic column mapping"""

    def setup_method(self):
        """Set up test fixtures"""
        self.mapper = ColumnMapper()

    def test_perfect_match_csv(self):
        """Test CSV with perfect column names"""
        csv_columns = ["species", "dia_cm", "height_m", "class", "LONGITUDE", "LATITUDE"]
        result = self.mapper.auto_map_columns(csv_columns)

        assert len(result["mapped"]) == 6
        assert len(result["unmapped"]) == 0
        assert len(result["missing_required"]) == 0
        assert all(score == 100 for score in result["confidence"].values())

    def test_common_variations_csv(self):
        """Test CSV with common column name variations"""
        csv_columns = [
            "Species Name",
            "DBH",
            "Height(m)",
            "Quality",
            "Long",
            "Lat"
        ]
        result = self.mapper.auto_map_columns(csv_columns)

        assert result["mapped"]["Species Name"] == "species"
        assert result["mapped"]["DBH"] == "dia_cm"
        assert result["mapped"]["Height(m)"] == "height_m"
        assert result["mapped"]["Quality"] == "class"
        assert result["mapped"]["Long"] == "LONGITUDE"
        assert result["mapped"]["Lat"] == "LATITUDE"

        assert len(result["unmapped"]) == 0
        assert len(result["missing_required"]) == 0

    def test_partial_match_csv(self):
        """Test CSV with some unmapped columns"""
        csv_columns = [
            "Species Name",
            "DBH",
            "Height(m)",
            "Unknown Column",  # Should not map
            "Long",
            "Lat"
        ]
        result = self.mapper.auto_map_columns(csv_columns)

        assert len(result["mapped"]) == 5
        assert "Unknown Column" in result["unmapped"]
        assert len(result["suggestions"]["Unknown Column"]) == 3  # Should get 3 suggestions

    def test_missing_required_columns(self):
        """Test CSV missing required columns"""
        csv_columns = [
            "Species Name",
            "DBH",
            "Height(m)"
            # Missing LONGITUDE and LATITUDE
        ]
        result = self.mapper.auto_map_columns(csv_columns)

        assert "LONGITUDE" in result["missing_required"]
        assert "LATITUDE" in result["missing_required"]

    def test_duplicate_mapping(self):
        """Test detection of duplicate mappings"""
        csv_columns = [
            "Species",
            "Species Name",  # Both map to 'species'
            "DBH",
            "Height(m)",
            "Long",
            "Lat"
        ]
        result = self.mapper.auto_map_columns(csv_columns)

        # Both "Species" and "Species Name" match the 'species' standard column,
        # so a duplicate is detected and auto-resolved: the best match is kept in
        # `mapped` and the loser is demoted to `unmapped`.
        assert result["mapped"]["Species"] == "species"
        assert "Species Name" in result["unmapped"]

        # Auto-resolution keeps the best match, so no duplicate remains afterward.
        assert "species" not in result["duplicates"]

    def test_extra_columns(self):
        """Test CSV with extra columns that should be preserved"""
        csv_columns = [
            "Species Name",
            "DBH",
            "Height(m)",
            "Plot Number",  # Extra column
            "Date",  # Extra column
            "Long",
            "Lat"
        ]
        result = self.mapper.auto_map_columns(csv_columns)

        # Required columns should be mapped
        assert len(result["mapped"]) >= 5

        # Extra columns should be in unmapped (but could be kept in final data)
        assert "Plot Number" in result["unmapped"] or "Plot Number" in result["mapped"]


class TestMappingValidation:
    """Test mapping validation"""

    def setup_method(self):
        """Set up test fixtures"""
        self.mapper = ColumnMapper()

    def test_valid_mapping(self):
        """Test validation of a correct mapping"""
        mapping = {
            "Species Name": "species",
            "DBH": "dia_cm",
            "Height(m)": "height_m",
            "Long": "LONGITUDE",
            "Lat": "LATITUDE"
        }
        result = self.mapper.validate_mapping(mapping)

        assert result["valid"] is True
        assert len(result["errors"]) == 0

    def test_missing_required_validation(self):
        """Test validation catches missing required columns"""
        mapping = {
            "Species Name": "species",
            "DBH": "dia_cm",
            "Height(m)": "height_m"
            # Missing LONGITUDE and LATITUDE
        }
        result = self.mapper.validate_mapping(mapping)

        assert result["valid"] is False
        assert len(result["errors"]) > 0
        assert "LONGITUDE" in result["errors"][0]
        assert "LATITUDE" in result["errors"][0]

    def test_duplicate_mapping_validation(self):
        """Test validation catches duplicate mappings"""
        mapping = {
            "Species": "species",
            "Species Name": "species",  # Duplicate!
            "DBH": "dia_cm",
            "Height(m)": "height_m",
            "Long": "LONGITUDE",
            "Lat": "LATITUDE"
        }
        result = self.mapper.validate_mapping(mapping)

        assert result["valid"] is False
        assert len(result["errors"]) > 0
        assert "species" in result["errors"][0].lower()

    def test_invalid_standard_column(self):
        """Test validation warns about invalid standard columns"""
        mapping = {
            "Species Name": "species",
            "DBH": "dia_cm",
            "Height(m)": "height_m",
            "Random": "invalid_column",  # Invalid!
            "Long": "LONGITUDE",
            "Lat": "LATITUDE"
        }
        result = self.mapper.validate_mapping(mapping)

        assert len(result["warnings"]) > 0


class TestSuggestions:
    """Test column mapping suggestions"""

    def setup_method(self):
        """Set up test fixtures"""
        self.mapper = ColumnMapper()

    def test_suggestions_for_unmapped(self):
        """Test that suggestions are provided for unmapped columns"""
        suggestions = self.mapper._get_suggestions("Tree Height", top_n=3)

        assert len(suggestions) == 3
        assert suggestions[0][0] == "height_m"  # Best match
        assert all(isinstance(score, int) for _, score in suggestions)
        assert all(0 <= score <= 100 for _, score in suggestions)

    def test_suggestions_sorted_by_score(self):
        """Test that suggestions are sorted by confidence"""
        suggestions = self.mapper._get_suggestions("Diameter", top_n=3)

        # Scores should be in descending order
        scores = [score for _, score in suggestions]
        assert scores == sorted(scores, reverse=True)


class TestRealWorldScenarios:
    """Test real-world CSV scenarios"""

    def setup_method(self):
        """Set up test fixtures"""
        self.mapper = ColumnMapper()

    def test_forestry_template_1(self):
        """Test typical forestry CSV template format 1"""
        csv_columns = [
            "Plot No",
            "Tree No",
            "Species Name",
            "DBH (cm)",
            "Height (m)",
            "Quality Class",
            "GPS Long",
            "GPS Lat"
        ]
        result = self.mapper.auto_map_columns(csv_columns)

        # Required forestry columns should map
        assert result["mapped"]["Species Name"] == "species"
        assert result["mapped"]["DBH (cm)"] == "dia_cm"
        assert result["mapped"]["Height (m)"] == "height_m"
        assert result["mapped"]["Quality Class"] == "class"
        assert result["mapped"]["GPS Long"] == "LONGITUDE"
        assert result["mapped"]["GPS Lat"] == "LATITUDE"

        # Should have no missing required columns
        assert len(result["missing_required"]) == 0

    def test_forestry_template_2(self):
        """Test typical forestry CSV template format 2"""
        csv_columns = [
            "Scientific Name",
            "Diameter at Breast Height (cm)",
            "Total Height (m)",
            "Grade",
            "X Coordinate",
            "Y Coordinate"
        ]
        result = self.mapper.auto_map_columns(csv_columns)

        assert result["mapped"]["Scientific Name"] == "species"
        assert result["mapped"]["Diameter at Breast Height (cm)"] == "dia_cm"
        assert result["mapped"]["Total Height (m)"] == "height_m"
        assert result["mapped"]["Grade"] == "class"
        assert result["mapped"]["X Coordinate"] == "LONGITUDE"
        assert result["mapped"]["Y Coordinate"] == "LATITUDE"

        assert len(result["missing_required"]) == 0

    def test_nepali_template(self):
        """Test Nepali language CSV template"""
        csv_columns = [
            "प्रजाती नाम",
            "व्यास सेमी",
            "उचाइ मिटर",
            "गुणस्तर",
            "देशान्तर",
            "अक्षांश"
        ]
        result = self.mapper.auto_map_columns(csv_columns)

        # All Nepali columns should map correctly
        assert result["mapped"]["प्रजाती नाम"] == "species"
        assert result["mapped"]["व्यास सेमी"] == "dia_cm"
        assert result["mapped"]["उचाइ मिटर"] == "height_m"
        assert result["mapped"]["गुणस्तर"] == "class"
        assert result["mapped"]["देशान्तर"] == "LONGITUDE"
        assert result["mapped"]["अक्षांश"] == "LATITUDE"

        assert len(result["missing_required"]) == 0

    def test_mixed_language_template(self):
        """Test CSV with mixed English/Nepali columns"""
        csv_columns = [
            "प्रजाती",  # Nepali
            "DBH",  # English
            "Height(m)",  # English
            "गुणस्तर",  # Nepali
            "Long",  # English
            "Lat"  # English
        ]
        result = self.mapper.auto_map_columns(csv_columns)

        # All columns should map correctly regardless of language
        assert len(result["mapped"]) == 6
        assert len(result["missing_required"]) == 0


class TestEdgeCases:
    """Test edge cases and error handling"""

    def setup_method(self):
        """Set up test fixtures"""
        self.mapper = ColumnMapper()

    def test_empty_column_list(self):
        """Test with empty column list"""
        result = self.mapper.auto_map_columns([])

        assert len(result["mapped"]) == 0
        assert len(result["unmapped"]) == 0
        assert len(result["missing_required"]) == 5  # All required columns missing

    def test_single_column(self):
        """Test with single column"""
        result = self.mapper.auto_map_columns(["Species"])

        assert result["mapped"]["Species"] == "species"
        assert len(result["missing_required"]) == 4  # Missing other required

    def test_all_unmapped_columns(self):
        """Test with all unrecognizable columns"""
        csv_columns = ["col1", "col2", "col3", "col4", "col5", "col6"]
        result = self.mapper.auto_map_columns(csv_columns)

        assert len(result["mapped"]) == 0
        assert len(result["unmapped"]) == 6
        assert len(result["missing_required"]) == 5  # All required missing

    def test_very_long_column_names(self):
        """Test with very long column names"""
        long_name = "This is a very long column name for species information"
        result = self.mapper.find_best_match(long_name)

        # Should still match 'species' due to partial matching
        assert result is not None
        assert result[0] == "species"


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
