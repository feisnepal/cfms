"""Per-unit analysis storage (owner rule 2026-10-10): flattening, and the "analysis run on the CURRENT units" status."""
from app.services.unit_analysis_service import flatten


def test_flatten_keeps_scalars_formats_distributions_and_drops_bookkeeping():
    out = flatten({
        "wkt": "POLYGON(...)", "extent": {"N": 1}, "potential_species": [1, 2],
        "elevation_mean_m": 1234.5678, "province": "Bagmati", "ward": 3,
        "landcover_percentages": {"Forest": 71.2, "Shrub": 3.0, "Water": 0},
        "limiting_factors": ["a", "b"], "empty": None, "blank": "",
    })
    assert out["an_elevation_mean_m"] == 1234.57
    assert out["an_province"] == "Bagmati" and out["an_ward"] == 3
    assert out["an_landcover_percentages"] == "Forest 71.2%; Shrub 3%"  # largest first, zero dropped
    assert out["an_limiting_factors"] == "a; b"  # names, not a bare count
    assert "an_limiting_factors_count" not in out
    assert not {"an_wkt", "an_extent", "an_potential_species", "an_empty", "an_blank"} & set(out)


def test_mirror_overwrites_matching_entries_only():
    from app.services.unit_analysis_service import mirror_into_result_data

    units = [{"id": "a", "block_name": "SC1", "elevation_mean_m": 1}, {"block_id": "b"}, {"id": "zzz"}]
    raw = {"a": {"elevation_mean_m": 1500.5, "landcover_percentages": {"Forest": 80}}, "b": {"ward": 3}}
    assert mirror_into_result_data(units, raw) == 2
    assert units[0]["elevation_mean_m"] == 1500.5 and units[0]["block_name"] == "SC1"  # unit's own fields survive
    assert units[0]["landcover_percentages"] == {"Forest": 80}  # structured value, not the table text
    assert units[1]["ward"] == 3 and "ward" not in units[2]
