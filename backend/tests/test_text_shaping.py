"""Complex-script shaping for matplotlib output (P2 / §3.8). No DB.

mplcairo may or may not be installed on a given host; the module must work
either way (cairo shaping when present, Agg no-op fallback otherwise).
"""

import io
import os
import sys
import warnings

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from app.core import text_shaping as ts  # noqa: E402
from app.core.fonts import configure_matplotlib_devanagari, dev_font_prop  # noqa: E402

configure_matplotlib_devanagari()

_CONJUNCTS = "क्षत्रज्ञ श्री कर्म किन संरक्षित कम्पार्टमेन्ट"


def _fig():
    fig, ax = plt.subplots(figsize=(3, 1.5), dpi=100)
    ax.axis("off")
    ax.text(
        0.5, 0.5, _CONJUNCTS, ha="center", va="center", fontproperties=dev_font_prop(14)
    )
    return fig


def test_shaping_backend_reports_a_known_value():
    assert ts.shaping_backend() in ("mplcairo", "agg")


def test_save_figure_produces_a_valid_png_either_backend():
    fig = _fig()
    buf = io.BytesIO()
    ts.save_figure(fig, buf, format="png", dpi=100)
    plt.close(fig)
    data = buf.getvalue()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(data) > 1500


def test_no_missing_glyph_warnings_for_conjunct_string():
    fig = _fig()
    buf = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("error", UserWarning)
        ts.save_figure(fig, buf, format="png", dpi=100)
    plt.close(fig)


def test_apply_is_idempotent():
    fig = _fig()
    r1 = ts.apply(fig)
    r2 = ts.apply(fig)
    plt.close(fig)
    assert r1 == r2  # both True (mplcairo present) or both False (fallback)


def test_agg_fallback_when_mplcairo_absent(monkeypatch):
    # Simulate a host without mplcairo — save_figure must still yield a PNG.
    monkeypatch.setattr(ts, "_cairo_canvas_cls", lambda: None)
    ts.shaping_backend.cache_clear()
    assert ts.shaping_backend() == "agg"
    fig = _fig()
    buf = io.BytesIO()
    ts.save_figure(fig, buf, format="png", dpi=100)
    plt.close(fig)
    assert buf.getvalue()[:8] == b"\x89PNG\r\n\x1a\n"
    ts.shaping_backend.cache_clear()  # restore for other tests


def test_manual_shaping_replaces_devanagari_text_with_outlines():
    """When mplcairo can't shape (no HarfBuzz) but uharfbuzz + fontTools are
    importable, save_figure converts Devanagari Text artists to PathPatches so
    matras / reph / conjuncts render correctly on plain Agg."""
    if not ts.manual_shaping_active():
        import pytest

        pytest.skip("uharfbuzz/fontTools not available, or mplcairo has HarfBuzz")

    from matplotlib.patches import PathPatch
    from matplotlib.text import Text

    fig = _fig()  # one centred Devanagari string with i-matra + conjuncts
    buf = io.BytesIO()
    ts.save_figure(fig, buf, format="png", dpi=100)

    patches = [a for a in fig.findobj(PathPatch)]
    hidden_dev = [
        t
        for t in fig.findobj(Text)
        if t.get_text()
        and not t.get_visible()
        and any("ऀ" <= c <= "ॿ" for c in t.get_text())
    ]
    plt.close(fig)

    assert patches, "expected shaped outline PathPatch artists"
    assert hidden_dev, "original Devanagari Text artist should be hidden"
    assert buf.getvalue()[:8] == b"\x89PNG\r\n\x1a\n"


def test_shape_to_path_produces_a_nonempty_outline():
    """`_shape_to_path` returns real glyph outlines + a positive advance for a
    conjunct + i-matra string (proof HarfBuzz ran and fontTools drew it)."""
    if not ts._harfbuzz_available():
        import pytest

        pytest.skip("uharfbuzz/fontTools not available")

    from app.core.fonts import devanagari_font_path

    path, advance = ts._shape_to_path("शिक्षा", devanagari_font_path())
    assert advance > 0
    assert len(path.vertices) > 20  # several glyphs' worth of contour points
    # em units → sane magnitude (font size applied later by the caller)
    assert path.vertices.max() < 5.0


def test_mplcairo_actually_shapes_when_present():
    """When mplcairo is installed, cairo output differs from Agg for a
    conjunct string (different glyph runs after shaping)."""
    if ts.shaping_backend() != "mplcairo":
        import pytest

        pytest.skip("mplcairo not installed on this host")

    agg = io.BytesIO()
    f1 = _fig()
    f1.savefig(agg, format="png", dpi=100)
    plt.close(f1)

    cairo = io.BytesIO()
    f2 = _fig()
    ts.save_figure(f2, cairo, format="png", dpi=100)
    plt.close(f2)

    assert agg.getvalue() != cairo.getvalue()
