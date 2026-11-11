"""The sampling screen's Dominant land cover column: derived from the unit's stored analysis, never recomputed."""
from app.services.sampling_unit_plan import LOW_FOREST_PCT, landcover_summary


def test_dominant_class_share_and_largest_first_breakdown():
    s = landcover_summary({"landcover_dominant": "Forest", "landcover_percentages": {"Cropland": 8, "Forest": 82.04, "Shrub": 10}})
    assert s["landcover_dominant"] == "Forest"
    assert s["landcover_dominant_pct"] == 82.0
    assert [b["name"] for b in s["landcover_breakdown"]] == ["Forest", "Shrub", "Cropland"]
    assert s["forest_pct"] == 82.0


def test_forest_share_sums_every_forest_class_and_flags_low_forest():
    s = landcover_summary({"landcover_percentages": {"Needleleaf forest": 10, "Broadleaf Forest": 5, "Cropland": 85}})
    assert s["forest_pct"] == 15.0 < LOW_FOREST_PCT
    assert s["landcover_dominant"] == "Cropland"  # no stored dominant: the largest class


def test_an_unanalysed_unit_has_nothing_to_show():
    for raw in (None, {}, {"landcover_percentages": {}}, {"landcover_percentages": {"x": "n/a"}}):
        s = landcover_summary(raw)
        assert s["landcover_dominant"] is None and s["landcover_breakdown"] == [] and s["forest_pct"] is None
