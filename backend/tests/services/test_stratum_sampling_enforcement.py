"""SS-1.2: Guideline-2061 stratum floor, per-stratum plot size, and min-5 enforcement."""
import json
import pytest
from unittest.mock import MagicMock, patch
from decimal import Decimal
from shapely.geometry import Polygon

CALC_ID = "123e4567-e89b-12d3-a456-426614174000"

POLY_50HA = Polygon([(0, 0), (0.03, 0), (0.03, 0.03), (0, 0.03)]).wkt   # ~50 ha
POLY_20HA = Polygon([(0.04, 0), (0.05, 0), (0.05, 0.02), (0.04, 0.02)]).wkt  # ~20 ha
POLY_10HA = Polygon([(0.06, 0), (0.07, 0), (0.07, 0.015), (0.06, 0.015)]).wkt
POLY_5HA  = Polygon([(0.08, 0), (0.085, 0), (0.085, 0.01), (0.08, 0.01)]).wkt
POLY_80HA = Polygon([(0.09, 0), (0.12, 0), (0.12, 0.05), (0.09, 0.05)]).wkt

_FAKE_WKTS = [POLY_50HA, POLY_20HA, POLY_10HA, POLY_5HA, POLY_80HA]
_NAMES = ["B1", "B2", "B3", "B4", "B5"]
_AREAS = [50.0, 20.0, 10.0, 5.0, 80.0]


def _make_calc(result_data=None):
    c = MagicMock()
    c.id = CALC_ID
    c.result_data = result_data or {"sub_areas": []}
    c.boundary_geom = MagicMock()
    return c


def _blocks():
    return [(i + 1, wkt, name, area)
            for i, (wkt, name, area) in enumerate(zip(_FAKE_WKTS, _NAMES, _AREAS))]


_STRATA = {
    "B1": "production", "B2": "production",
    "B3": "conservation", "B4": "production", "B5": "protection",
}


def _zone_areas(area_ha):
    """Return a mock zone_areas dict with full block as productive."""
    return {
        "productive_area_ha": area_ha,
        "protected_area_ha": 0.0,
        "private_land_area_ha": 0.0,
        "block_geometry": Polygon([(0, 0), (0.01, 0), (0.01, 0.01), (0, 0.01)]),
        "productive_geometry": Polygon([(0, 0), (0.01, 0), (0.01, 0.01), (0, 0.01)]),
        "protected_geometry": None,
    }


def _patch_zone_areas_for_blocks():
    """Patch calculate_zone_net_areas to return full productive for each block."""
    side_effects = [_zone_areas(a) for a in _AREAS]
    return patch("app.services.sampling.calculate_zone_net_areas", side_effect=side_effects)


# ---------------------------------------------------------------------------
# Floor enforcement
# ---------------------------------------------------------------------------

@patch("app.services.sampling.classify_calc_units", return_value=_STRATA)
@patch("app.services.sampling.get_sample_count_from_guideline", return_value=20)
@patch("app.services.sampling.generate_systematic_grid", return_value=[(float(i), float(i)) for i in range(30)])
@patch("app.services.sampling.get_excluded_areas_for_calculation", return_value=[])
def test_below_floor_on_production_stratum_rejects(_mock_excl, _mock_grid, _mock_guideline, _mock_classify):
    """A production stratum block with intensity 1.0% (< floor 2.0%) â†’ SFM_INTENSITY_BELOW_FLOOR."""
    from app.services.sampling import create_sampling_design_guideline_2061

    db = MagicMock()
    db.query().filter().first.return_value = _make_calc()
    with _patch_zone_areas_for_blocks():
        with patch("app.services.sampling.extract_blocks_from_calculation", return_value=_blocks()):
            with pytest.raises(ValueError, match="SFM_INTENSITY_BELOW_FLOOR") as exc_info:
                create_sampling_design_guideline_2061(
                    db=db, calculation_id=CALC_ID,
                    productive_intensity=2.0, sample_protected_zone=False,
                    plot_size_sqm=500,
                    per_block_intensity={"B2": 1.0},  # 1.0 < floor 2.0 for production
                    preview=True,
                )
    payload = json.loads(str(exc_info.value).split("SFM_INTENSITY_BELOW_FLOOR: ", 1)[1])
    assert payload["unit"] == "B2"
    assert payload["stratum"] == "production"
    assert payload["floor"] == 2.0
    assert payload["value"] == 1.0


@patch("app.services.sampling.classify_calc_units", return_value=_STRATA)
@patch("app.services.sampling.get_sample_count_from_guideline", return_value=20)
@patch("app.services.sampling.generate_systematic_grid", return_value=[(float(i), float(i)) for i in range(30)])
@patch("app.services.sampling.get_excluded_areas_for_calculation", return_value=[])
def test_global_intensity_below_production_floor_rejects(_mock_excl, _mock_grid, _mock_guideline, _mock_classify):
    """Global 1.0% (valid per validate_guideline_parameters) but < production floor 2.0% â†’ reject."""
    from app.services.sampling import create_sampling_design_guideline_2061

    db = MagicMock()
    db.query().filter().first.return_value = _make_calc()
    with _patch_zone_areas_for_blocks():
        with patch("app.services.sampling.extract_blocks_from_calculation", return_value=_blocks()):
            with pytest.raises(ValueError, match="SFM_INTENSITY_BELOW_FLOOR"):
                create_sampling_design_guideline_2061(
                    db=db, calculation_id=CALC_ID,
                    productive_intensity=1.0, sample_protected_zone=False,
                    plot_size_sqm=500, preview=True,
                )


@patch("app.services.sampling.classify_calc_units", return_value=_STRATA)
@patch("app.services.sampling.get_sample_count_from_guideline", return_value=20)
@patch("app.services.sampling.generate_systematic_grid", return_value=[(float(i), float(i)) for i in range(30)])
@patch("app.services.sampling.get_excluded_areas_for_calculation", return_value=[])
def test_above_floor_accepts(_mock_excl, _mock_grid, _mock_guideline, _mock_classify):
    """Intensity at or above the floor â†’ accepted without error."""
    from app.services.sampling import create_sampling_design_guideline_2061

    db = MagicMock()
    db.query().filter().first.return_value = _make_calc()
    with _patch_zone_areas_for_blocks():
        with patch("app.services.sampling.extract_blocks_from_calculation", return_value=_blocks()):
            resp = create_sampling_design_guideline_2061(
                db=db, calculation_id=CALC_ID,
                productive_intensity=2.0, sample_protected_zone=False,
                plot_size_sqm=500, preview=True,
            )
    assert resp.response.total_blocks > 0


@patch("app.services.sampling.classify_calc_units", return_value=_STRATA)
@patch("app.services.sampling.get_sample_count_from_guideline", return_value=20)
@patch("app.services.sampling.generate_systematic_grid", return_value=[(float(i), float(i)) for i in range(30)])
@patch("app.services.sampling.get_excluded_areas_for_calculation", return_value=[])
def test_conservation_block_accepts_one_percent(_mock_excl, _mock_grid, _mock_guideline, _mock_classify):
    """A conservation stratum block explicitly set to 1.0% (its floor) → accepted."""
    from app.services.sampling import create_sampling_design_guideline_2061

    db = MagicMock()
    db.query().filter().first.return_value = _make_calc()
    with _patch_zone_areas_for_blocks():
        with patch("app.services.sampling.extract_blocks_from_calculation", return_value=_blocks()):
            resp = create_sampling_design_guideline_2061(
                db=db, calculation_id=CALC_ID,
                productive_intensity=2.0, sample_protected_zone=False,
                plot_size_sqm=500, preview=True,
                per_block_intensity={"B3": 1.0},  # conservation floor = 1.0
            )
    assert resp.response.total_blocks > 0
    b3 = next(b for b in resp.response.blocks_info if b.block_name == "B3")
    assert b3.stratum == "conservation"
    assert float(b3.floor_intensity_pct) == 1.0


# ---------------------------------------------------------------------------
# Per-block stratum fields
# ---------------------------------------------------------------------------

@patch("app.services.sampling.classify_calc_units", return_value=_STRATA)
@patch("app.services.sampling.get_sample_count_from_guideline", return_value=20)
@patch("app.services.sampling.generate_systematic_grid", return_value=[(float(i), float(i)) for i in range(30)])
@patch("app.services.sampling.get_excluded_areas_for_calculation", return_value=[])
def test_block_info_contains_stratum_floor_plotsize(_mock_excl, _mock_grid, _mock_guideline, _mock_classify):
    """Each block_info carries stratum, floor_intensity_pct, and plot_size_sqm."""
    from app.services.sampling import create_sampling_design_guideline_2061

    db = MagicMock()
    db.query().filter().first.return_value = _make_calc()
    with _patch_zone_areas_for_blocks():
        with patch("app.services.sampling.extract_blocks_from_calculation", return_value=_blocks()):
            resp = create_sampling_design_guideline_2061(
                db=db, calculation_id=CALC_ID,
                productive_intensity=2.0, sample_protected_zone=False,
                plot_size_sqm=500, preview=True,
            )
    blocks = {b.block_name: b for b in resp.response.blocks_info}
    b1 = blocks["B1"]
    assert b1.stratum == "production"
    assert float(b1.floor_intensity_pct) == 2.0
    assert b1.plot_size_sqm == 500

    b3 = blocks["B3"]
    assert b3.stratum == "conservation"
    assert float(b3.floor_intensity_pct) == 1.0
    assert b3.plot_size_sqm == 500

    b5 = blocks["B5"]
    assert b5.stratum == "protection"
    assert float(b5.floor_intensity_pct) == 0.5
    assert b5.plot_size_sqm == 100


@patch("app.services.sampling.classify_calc_units", return_value=_STRATA)
@patch("app.services.sampling.get_sample_count_from_guideline", return_value=20)
@patch("app.services.sampling.generate_systematic_grid", return_value=[(float(i), float(i)) for i in range(30)])
@patch("app.services.sampling.get_excluded_areas_for_calculation", return_value=[])
def test_per_stratum_plot_size_changes_sample_count(_mock_excl, _mock_grid, _mock_guideline, _mock_classify):
    """Protection stratum block uses 100 mÂ² plots, reflected in block_info."""
    from app.services.sampling import create_sampling_design_guideline_2061

    db = MagicMock()
    db.query().filter().first.return_value = _make_calc()
    with _patch_zone_areas_for_blocks():
        with patch("app.services.sampling.extract_blocks_from_calculation", return_value=_blocks()):
            resp = create_sampling_design_guideline_2061(
                db=db, calculation_id=CALC_ID,
                productive_intensity=2.0, sample_protected_zone=False,
                plot_size_sqm=500, preview=True,
            )
    blocks = {b.block_name: b for b in resp.response.blocks_info}
    b5 = blocks["B5"]
    assert b5.plot_size_sqm == 100
    assert b5.samples_generated >= 5


@patch("app.services.sampling.classify_calc_units", return_value=_STRATA)
@patch("app.services.sampling.get_sample_count_from_guideline", return_value=20)
@patch("app.services.sampling.generate_systematic_grid", return_value=[(float(i), float(i)) for i in range(30)])
@patch("app.services.sampling.get_excluded_areas_for_calculation", return_value=[])
def test_min_5_floor_applies_even_when_table_returns_less(_mock_excl, _mock_grid, _mock_guideline, _mock_classify):
    """Very small blocks that the guideline table returns <5 still get at least 5 samples."""
    # Override guideline to return 2 for B4 (5ha block)
    def _guideline_side_effect(db, block_area_hectares, intensity_percent, plot_size_sqm):
        if block_area_hectares < 6:
            return 2
        return 20

    _mock_guideline.side_effect = _guideline_side_effect

    from app.services.sampling import create_sampling_design_guideline_2061

    db = MagicMock()
    db.query().filter().first.return_value = _make_calc()
    with _patch_zone_areas_for_blocks():
        with patch("app.services.sampling.extract_blocks_from_calculation", return_value=_blocks()):
            resp = create_sampling_design_guideline_2061(
                db=db, calculation_id=CALC_ID,
                productive_intensity=2.0, sample_protected_zone=False,
                plot_size_sqm=500, preview=True,
            )

    for b in resp.response.blocks_info:
        if b.samples_generated > 0:
            assert b.samples_generated >= 5, (
                f"{b.block_name} ({b.stratum}) got {b.samples_generated} samples < 5"
            )


@patch("app.services.sampling.classify_calc_units", return_value=_STRATA)
@patch("app.services.sampling.get_sample_count_from_guideline", return_value=20)
@patch("app.services.sampling.generate_systematic_grid", return_value=[(float(i), float(i)) for i in range(30)])
@patch("app.services.sampling.get_excluded_areas_for_calculation", return_value=[])
def test_minimum_enforced_flag_set_when_clamped(_mock_excl, _mock_grid, _mock_guideline, _mock_classify):
    """minimum_enforced=True when min-5 floor clamped the count."""
    def _guideline_side_effect(db, block_area_hectares, intensity_percent, plot_size_sqm):
        if block_area_hectares < 6:
            return 2  # Below 5 â†’ should be clamped
        return 20

    _mock_guideline.side_effect = _guideline_side_effect

    from app.services.sampling import create_sampling_design_guideline_2061

    db = MagicMock()
    db.query().filter().first.return_value = _make_calc()
    with _patch_zone_areas_for_blocks():
        with patch("app.services.sampling.extract_blocks_from_calculation", return_value=_blocks()):
            resp = create_sampling_design_guideline_2061(
                db=db, calculation_id=CALC_ID,
                productive_intensity=2.0, sample_protected_zone=False,
                plot_size_sqm=500, preview=True,
            )

    blocks = {b.block_name: b for b in resp.response.blocks_info}
    # B4 (5ha) gets count=2, clamped to 5 â†’ minimum_enforced=True
    assert blocks["B4"].minimum_enforced is True
    # B1 (50ha) gets count=20 â†’ minimum_enforced=False
    assert blocks["B1"].minimum_enforced is False


@patch("app.services.sampling.classify_calc_units", return_value=_STRATA)
@patch("app.services.sampling.get_sample_count_from_guideline", return_value=20)
@patch("app.services.sampling.generate_systematic_grid", return_value=[(float(i), float(i)) for i in range(30)])
@patch("app.services.sampling.get_excluded_areas_for_calculation", return_value=[])
def test_enforce_min_samples_production_false_skips_the_five_plot_floor(_mock_excl, _mock_grid, _mock_guideline, _mock_classify):
    """enforce_min_samples_production=False (owner request, 2026-09-15,
    refined the same day to be per-stratum) drops the flat 5-plot floor for
    Production units only -- a guideline-table count below 5 is no longer
    clamped for B4 (production, 5ha)."""
    def _guideline_side_effect(db, block_area_hectares, intensity_percent, plot_size_sqm):
        if block_area_hectares < 6:
            return 2  # would normally be clamped to 5
        return 20

    _mock_guideline.side_effect = _guideline_side_effect

    from app.services.sampling import create_sampling_design_guideline_2061

    db = MagicMock()
    db.query().filter().first.return_value = _make_calc()
    with _patch_zone_areas_for_blocks():
        with patch("app.services.sampling.extract_blocks_from_calculation", return_value=_blocks()):
            resp = create_sampling_design_guideline_2061(
                db=db, calculation_id=CALC_ID,
                productive_intensity=2.0, sample_protected_zone=False,
                plot_size_sqm=500, preview=True,
                enforce_min_samples_production=False,
            )

    blocks = {b.block_name: b for b in resp.response.blocks_info}
    assert blocks["B4"].samples_generated == 2


@patch("app.services.sampling.classify_calc_units", return_value=_STRATA)
@patch("app.services.sampling.get_sample_count_from_guideline", return_value=20)
@patch("app.services.sampling.generate_systematic_grid", return_value=[(float(i), float(i)) for i in range(30)])
@patch("app.services.sampling.get_excluded_areas_for_calculation", return_value=[])
def test_enforce_min_samples_conservation_is_independent_of_production(_mock_excl, _mock_grid, _mock_guideline, _mock_classify):
    """Disabling the floor for Production (B4) must not affect a Conservation
    unit (B3) in the same design -- each stratum's toggle is independent."""
    def _guideline_side_effect(db, block_area_hectares, intensity_percent, plot_size_sqm):
        return 2  # below 5 for every block regardless of area

    _mock_guideline.side_effect = _guideline_side_effect

    from app.services.sampling import create_sampling_design_guideline_2061

    db = MagicMock()
    db.query().filter().first.return_value = _make_calc()
    with _patch_zone_areas_for_blocks():
        with patch("app.services.sampling.extract_blocks_from_calculation", return_value=_blocks()):
            resp = create_sampling_design_guideline_2061(
                db=db, calculation_id=CALC_ID,
                productive_intensity=2.0, sample_protected_zone=False,
                plot_size_sqm=500, preview=True,
                per_block_intensity={"B3": 1.0},  # conservation floor = 1.0
                enforce_min_samples_production=False,
            )

    blocks = {b.block_name: b for b in resp.response.blocks_info}
    # B4 (production) -- floor disabled -> raw guideline count kept
    assert blocks["B4"].samples_generated == 2
    # B3 (conservation) -- floor still enforced -> clamped to 5
    assert blocks["B3"].samples_generated >= 5
    assert blocks["B4"].minimum_enforced is False

