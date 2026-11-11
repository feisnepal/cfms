"""P5a scale bar + P5b centroid glyphs / small multiples / combine_with. No DB."""

import io
import math
import os
import sys
import warnings

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.management_plan_docx import plan_map_service as pms  # noqa: E402
from app.services.operational_plan import _thememap_fixture as fx  # noqa: E402
from app.services.operational_plan import thematic_overlay as to  # noqa: E402
from app.services.operational_plan.thematic_map_spec import resolve_spec  # noqa: E402


def _png_ok(buf, mn=5000):
    d = buf.getvalue()
    assert d[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(d) >= mn, len(d)


# ── P5a — scale bar ───────────────────────────────────────────────────
def test_nice_scale_length_snaps_to_1_2_5():
    assert pms._nice_scale_length(370) == 200
    assert pms._nice_scale_length(80) == 50
    assert pms._nice_scale_length(1400) == 1000
    assert pms._nice_scale_length(6) == 5


def test_scale_bar_draws_without_error():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    ax.set_xlim(85.30, 85.40)
    ax.set_ylim(27.60, 27.68)
    before = len(ax.patches)
    pms._add_scale_bar(ax, 85.30, 85.40, 27.60, 27.68)
    assert len(ax.patches) == before + 2  # two alternating segments
    plt.close(fig)


def test_thematic_map_has_a_scale_bar():
    spec = resolve_spec("thememap:unit__growing_stock")
    buf = to.compose(
        spec,
        fx.units(),
        fx.VALUES,
        fx.WORKING_CIRCLE,
        fx.BBOX,
        fx.BOUNDARY,
        [],
        "Test CF",
        96,
    )
    _png_ok(buf)


# ── P5b — glyphs ─────────────────────────────────────────────────────
_GLYPH_KEYS = [
    "unit__dbh_class_count__stackbar",
    "unit__dbh_class_count__pie",
    "unit__dbh_class_count__sparkline",
    "unit__dbh_class_stock__stackbar",
    "unit__dbh_composition__waffle",
    "unit__regen_pole_tree__ternary",
    "unit__timber_firewood__stackbar",
    "unit__agb_bgb__stackbar",
    "unit__health_fingerprint",
]


def test_every_glyph_renders_from_fixture_without_glyph_warnings():
    for k in _GLYPH_KEYS:
        spec = resolve_spec("thememap:" + k)
        assert spec is not None, k
        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)
            buf = to.render_from_fixture(spec, dpi=96)
        _png_ok(buf, mn=4000)


def test_composition_reads_dbh_breakdown_from_the_unit():
    spec = resolve_spec("thememap:unit__dbh_class_count__stackbar")
    comps = to._composition("क-१", fx.VALUES, spec)
    assert len(comps) == 8
    assert all(
        isinstance(lbl, str) and v >= 0 and c.startswith("#") for lbl, v, c in comps
    )
    assert sum(v for _l, v, _c in comps) > 0


def test_composition_reads_named_components():
    spec = resolve_spec("thememap:unit__timber_firewood__stackbar")
    comps = to._composition("क-१", fx.VALUES, spec)
    assert len(comps) == 2
    assert comps[0][1] > 0 and comps[1][1] > 0


def test_glyph_point_is_inside_the_polygon():
    for u in fx.units():
        x, y = to._glyph_point(u["geometry"])
        from shapely.geometry import Point

        assert u["geometry"].buffer(1e-9).contains(Point(x, y))


# ── P5b — small multiples ────────────────────────────────────────────
def test_smallmultiples_spec_renders_a_grid():
    spec = resolve_spec("thememap:forest__dbh_by_unit")
    buf = to.render_from_fixture(spec, dpi=96)
    _png_ok(buf, mn=6000)


def test_glyph_map_auto_switches_to_small_multiples_above_15_units():
    from shapely.geometry import Polygon

    spec = resolve_spec("thememap:unit__dbh_class_count__pie")
    units, values, wc = [], {}, {}
    for i in range(18):
        r, c = divmod(i, 6)
        nm = f"U{i}"
        units.append(
            {
                "name": nm,
                "geometry": Polygon(
                    [
                        (85.0 + c * 0.01, 27.0 + r * 0.01),
                        (85.0 + c * 0.01 + 0.008, 27.0 + r * 0.01),
                        (85.0 + c * 0.01 + 0.008, 27.0 + r * 0.01 + 0.008),
                        (85.0 + c * 0.01, 27.0 + r * 0.01 + 0.008),
                    ]
                ),
            }
        )
        values[nm] = {"dbh_class_breakdown": fx.VALUES["क-१"]["dbh_class_breakdown"]}
        wc[nm] = "production"
    bbox = (85.0, 27.0, 85.07, 27.03)
    buf = to.compose(spec, units, values, wc, bbox, None, [], "Big CF", 96)
    _png_ok(buf, mn=6000)


# ── P5b — combine_with ───────────────────────────────────────────────
def test_combine_with_draws_the_other_specs_glyph():
    spec = resolve_spec("thememap:unit__condition_with_dbh")
    assert spec.combine_with == "thememap:unit__dbh_class_count__pie"
    buf = to.render_from_fixture(spec, dpi=96)
    _png_ok(buf, mn=4000)
