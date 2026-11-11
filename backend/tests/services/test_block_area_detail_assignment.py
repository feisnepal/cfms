"""calculate_block_area_details: sub-area -> unit assignment.

Protected / Private areas are subtracted from each analysed unit by matching
the sub-area's stored block label to the unit name. In compartment mode the
units are renamed (C1..Cn) while the sub-areas still carry the parent block's
name, so nothing matched and the Protected / Private columns collapsed to 0
on every row. The function now detects that label mismatch and falls back to
pure geometric assignment.

These tests stub `db.execute` so the ESA WorldCover raster queries return
zero pixels -- the Protected / Private accumulation is pure Shapely and needs
no database.
"""
from app.services.tree_cover_analysis import calculate_block_area_details


class _FakeRow:
    total_pixels = 0
    tree_pixels = 0


class _FakeExec:
    def first(self):
        return _FakeRow()


class _FakeDB:
    """Minimal stand-in: every raster query yields zero pixels."""

    def execute(self, *args, **kwargs):
        return _FakeExec()


def _square(x0, y0, x1, y1):
    return {
        "type": "Polygon",
        "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]],
    }


# Two side-by-side unit squares spanning lon 84.0-84.2, lat 28.0-28.1.
_UNIT_A = {"block_name": "C1", "area_hectares": 100.0, "geometry": _square(84.00, 28.00, 84.10, 28.10)}
_UNIT_B = {"block_name": "C2", "area_hectares": 100.0, "geometry": _square(84.10, 28.00, 84.20, 28.10)}

# A protected patch entirely inside C1, and a private patch entirely inside C2.
_PROTECTED = {
    "name": "Protected Area",
    "category": "protected",
    "blockName": "Parent Block",  # <-- does not match C1 / C2
    "blockBreakdown": [{"blockName": "Parent Block"}],
    "geometry": _square(84.02, 28.02, 84.05, 28.05),
}
_PRIVATE = {
    "name": "Private Land",
    "category": "private_land",
    "blockName": "Parent Block",
    "blockBreakdown": [{"blockName": "Parent Block"}],
    "geometry": _square(84.12, 28.02, 84.15, 28.05),
}


def test_falls_back_to_geometry_when_labels_do_not_match_units():
    rows = calculate_block_area_details(_FakeDB(), [_UNIT_A, _UNIT_B], [_PROTECTED, _PRIVATE])
    by_name = {r["block_name"]: r for r in rows}

    # C1 gets the protected patch, C2 gets the private patch -- even though the
    # sub-areas are tagged with "Parent Block".
    assert by_name["C1"]["protected_area_ha"] > 0
    assert by_name["C1"]["private_land_area_ha"] == 0
    assert by_name["C2"]["private_land_area_ha"] > 0
    assert by_name["C2"]["protected_area_ha"] == 0


def test_label_match_path_is_unchanged_for_block_forests():
    # Sub-areas correctly tagged with the unit names -> the name gate runs and
    # geometry fallback stays OFF (a sub-area is only counted on its own block).
    prot = {**_PROTECTED, "blockName": "C1", "blockBreakdown": [{"blockName": "C1"}]}
    priv = {**_PRIVATE, "blockName": "C2", "blockBreakdown": [{"blockName": "C2"}]}
    rows = calculate_block_area_details(_FakeDB(), [_UNIT_A, _UNIT_B], [prot, priv])
    by_name = {r["block_name"]: r for r in rows}

    assert by_name["C1"]["protected_area_ha"] > 0
    assert by_name["C1"]["private_land_area_ha"] == 0
    assert by_name["C2"]["private_land_area_ha"] > 0
    assert by_name["C2"]["protected_area_ha"] == 0


def test_no_sub_areas_is_a_clean_noop():
    rows = calculate_block_area_details(_FakeDB(), [_UNIT_A, _UNIT_B], [])
    for r in rows:
        assert r["protected_area_ha"] == 0
        assert r["private_land_area_ha"] == 0
