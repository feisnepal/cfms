"""RUSLE soil-loss — the ``raster_surface`` render + the fixture preview (P2)."""

from __future__ import annotations

import numpy as np
import pytest

from app.services.operational_plan import _thememap_fixture as fx
from app.services.operational_plan.soil_erosion_config import (
    DEFAULT_PARAMS,
    SoilErosionParams,
    _deep_merge,
)
from app.services.operational_plan.thematic_map_spec import resolve_spec
from app.services.operational_plan.thematic_overlay import (
    _draw_raster_surface,
    render_from_fixture,
)

SPEC = resolve_spec("thememap:soil__annual_loss")


def test_spec_shape():
    assert SPEC.source == "soil_grid"
    assert SPEC.viz == "raster_surface"
    assert SPEC.section == "S9"
    assert SPEC.requires == ["raster_zonal", "soil_data"]
    assert SPEC.fixed_breaks == [5.0, 10.0, 20.0, 40.0, 80.0]


def test_fixture_render_is_a_real_png():
    png = render_from_fixture(SPEC).getvalue()
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 5000  # a placeholder would be much smaller


def test_draw_raster_surface_legend_spans_severity_classes():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from app.core import semantic_palettes as sp

    from app.services.operational_plan.soil_erosion_config import SEVERITY_LABELS_NE

    res = fx.soil_loss_result()
    breaks = list(res.params.severity_breaks)
    colours = sp.sample_ramp("reds", len(breaks) + 1)
    fig, ax = plt.subplots()
    rows = _draw_raster_surface(
        ax,
        res.a,
        res.grid.bounds,
        breaks,
        colours,
        fx.BOUNDARY,
        labels_ne=SEVERITY_LABELS_NE,
    )
    plt.close(fig)
    # the fixture gradient runs 2 → ~90 t/ha/yr → every class present
    assert len(rows) == len(breaks) + 1
    assert all(isinstance(c, str) and c.startswith("#") for c, _ in rows)
    assert "न्यून" in rows[0][1] and "अति गम्भीर" in rows[-1][1]


def test_draw_raster_surface_follows_custom_breaks():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from app.core import semantic_palettes as sp

    res = fx.soil_loss_result()
    breaks = [15.0]  # 2 classes only
    colours = sp.sample_ramp("reds", 2)
    fig, ax = plt.subplots()
    rows = _draw_raster_surface(
        ax, res.a, res.grid.bounds, breaks, colours, fx.BOUNDARY
    )
    plt.close(fig)
    assert len(rows) == 2
    assert rows[0][1].startswith("0–15")
    assert rows[1][1].startswith("≥15")


def test_nodata_grid_would_placeholder():
    from app.services.operational_plan.thematic_overlay import _compose_soil_grid

    res = fx.soil_loss_result()
    res.a[:] = np.nan
    png = _compose_soil_grid(
        res, SPEC, "", fx.BBOX, fx.BOUNDARY, 96, allow_tiles=False
    ).getvalue()
    assert png[:8] == b"\x89PNG\r\n\x1a\n"  # a captioned placeholder, still a PNG


# ── the API's 422 gate is `SoilErosionParams(**merged)` — test that core ──
def test_partial_override_merge_and_validate():
    base = SoilErosionParams().model_dump()
    good = _deep_merge(
        base, {"slope_length_cap_m": 60.0, "r_method": "annual_regression"}
    )
    p = SoilErosionParams(**good)
    assert p.slope_length_cap_m == 60.0
    assert p.r_method == "annual_regression"


@pytest.mark.parametrize(
    "bad",
    [
        {"severity_breaks": [20, 10, 5]},
        {"mfi_arnoldus_coeffs": {"a": -1}},
        {"c_by_esa_class": {10: 2.0}},
        {"r_method": "bogus"},
        {"slope_length_cap_m": 5.0},
        {"nonexistent_key": 1},
    ],
)
def test_bad_override_is_rejected(bad):
    merged = _deep_merge(SoilErosionParams().model_dump(), bad)
    with pytest.raises(Exception):
        SoilErosionParams(**merged)


def test_default_params_provenance_all_default():
    assert set(DEFAULT_PARAMS._provenance.values()) == {"default"}
    assert DEFAULT_PARAMS.is_customised() is False


# ── P5 — user-group variant + factor small-multiples ──────────────────────
@pytest.mark.parametrize(
    "key",
    [
        "soil__annual_loss__user_group",
        "soil__factor_r",
        "soil__factor_k",
        "soil__factor_ls",
        "soil__factor_c",
    ],
)
def test_p5_specs_render_a_real_png_from_the_fixture(key):
    spec = resolve_spec(f"thememap:{key}")
    assert spec is not None and spec.source == "soil_grid"
    png = render_from_fixture(spec).getvalue()
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 5000


def test_soil_band_dispatch():
    from app.services.operational_plan.thematic_overlay import _soil_band_for

    assert _soil_band_for(resolve_spec("thememap:soil__annual_loss")) == "a"
    assert _soil_band_for(resolve_spec("thememap:soil__annual_loss__user_group")) == "a"
    assert _soil_band_for(resolve_spec("thememap:soil__factor_ls")) == "__factor_ls"


def test_quantile_breaks_are_increasing():
    import numpy as np

    from app.services.operational_plan.thematic_overlay import _quantile_breaks

    arr = np.linspace(1, 100, 400).reshape(20, 20)
    b = _quantile_breaks(arr, 5)
    assert len(b) == 4
    assert all(b[i] < b[i + 1] for i in range(len(b) - 1))
    assert _quantile_breaks(np.full((5, 5), np.nan), 5) == [0.0]
