"""Regression fixture for the हिमाल.kmz bug report.

Importing हिमाल.kmz into the Block layer should produce 5 named blocks
(एलम्बर / चुलम्वर / तिलम्बर / पुलम्वर / दुलम्बर) — one division line ends by
intersecting ANOTHER division line rather than crossing the outer boundary,
which the old sequential `shapely.ops.split`-per-line implementation could
not handle (it produced only 2). See `test_feature_to_polygon_matrix.py`'s
`test_case_c_line_ending_on_another_line_partitions_correctly` for a minimal
synthetic repro of the same topology.

`testData/` is git-ignored (real survey files, not committed), so this whole
module skips when it isn't present on the machine running the tests — it is
a local regression check against the real files, not a CI gate.
"""

from pathlib import Path

import pytest

from app.services.file_processor import read_kml, read_kmz, process_geometry_list

_SFM_DATA_DIR = Path(__file__).resolve().parents[3] / "testData" / "SFM_data"

pytestmark = pytest.mark.skipif(
    not _SFM_DATA_DIR.is_dir(),
    reason="testData/SFM_data is git-ignored real survey data, not present on this machine",
)

# file -> expected block_count via process_geometry_list(purpose="blocks")
_EXPECTED_BLOCK_COUNTS = {
    "Churiya.kml": 6,
    "Churiya_5block.kmz": 5,
    "Dun.kmz": 5,
    "Mahabharat.kmz": 5,
    "Mahabharat_outer_line.kmz": 1,
    "Mahabharat_outer_polygon.kmz": 1,
    "Terai_outer_polygon.kml": 1,
    "Terai_poly_line_Unnamed.kml": 5,
    "Terai_poly_line_named.kml": 5,
    "हिमाल.kmz": 5,
}


def _read(filename: str):
    path = _SFM_DATA_DIR / filename
    if filename.lower().endswith(".kmz"):
        return read_kmz(str(path))
    return read_kml(str(path))


@pytest.mark.parametrize("filename,expected", sorted(_EXPECTED_BLOCK_COUNTS.items()))
def test_block_count_matches_expected(filename, expected):
    geoms, attrs, _crs = _read(filename)
    _, metadata = process_geometry_list(geoms, attrs, purpose="blocks")
    assert (
        metadata.get("block_count") == expected
    ), f"{filename}: expected {expected} blocks, got {metadata.get('block_count')}"


def test_himal_blocks_are_named_after_the_five_label_points():
    geoms, attrs, _crs = _read("हिमाल.kmz")
    _, metadata = process_geometry_list(geoms, attrs, purpose="blocks")
    names = {b["name"] for b in metadata["blocks"]}
    assert names == {"एलम्बर", "चुलम्वर", "तिलम्बर", "पुलम्वर", "दुलम्बर"}
