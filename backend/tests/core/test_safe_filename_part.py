"""Forest names in export file names keep their Nepali spelling.

``str.isalnum()`` rejects Devanagari vowel signs and the virama (category M*), which
turned "परीक्षण वन" into "परकषण_वन" in every Total Tree Export file name.
"""
import pytest

from app.utils.file_export import safe_filename_part


@pytest.mark.parametrize("name,expected", [
    ("परीक्षण वन", "परीक्षण_वन"),          # vowel signs + virama survive; space -> _
    ("बृन्दाबन", "बृन्दाबन"),
    ("Babar Mahal Forest", "Babar_Mahal_Forest"),
    ("Sal-Forest_1", "Sal-Forest_1"),
    ("१२३ वन", "१२३_वन"),                  # Devanagari digits
])
def test_nepali_and_ascii_names_are_kept(name, expected):
    assert safe_filename_part(name) == expected


@pytest.mark.parametrize("name,expected", [
    ("a/b\\c:d*e?f\"g<h>i|j", "abcdefghij"),   # characters Windows forbids are dropped
    ("../../etc/passwd", "etcpasswd"),            # no path traversal
    ("वन/१", "वन१"),
])
def test_unsafe_characters_are_dropped(name, expected):
    assert safe_filename_part(name) == expected


@pytest.mark.parametrize("name", ["", "   ", None, "///"])
def test_nothing_usable_falls_back_to_default(name):
    assert safe_filename_part(name) == "forest"
    assert safe_filename_part(name, default="x") == "x"


def test_exports_are_written_with_the_full_nepali_name(tmp_path):
    """End to end through the real writers: the file on disk keeps the spelling."""
    import uuid
    from app.models.calculation import Calculation
    from app.services.tree_distribution import export_to_csv_flat

    class _Calc:
        forest_name = "परीक्षण वन"

    class _DB:
        def query(self, *_a):
            return self

        def filter(self, *_a):
            return self

        def first(self):
            return _Calc()

    trees = [{"tree_id": 1, "block_name": "B", "geometry": (85.0, 27.5)}]
    path, _ = export_to_csv_flat(trees, uuid.uuid4(), db=_DB(), output_dir=str(tmp_path))
    assert "परीक्षण_वन_AllTrees_" in path
