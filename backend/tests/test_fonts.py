"""Devanagari font resolution (app.core.fonts) — P0.

No DB, no fixtures. Guarantees the backend can always find a font that
*contains* the Devanagari block, on any host — the repo bundles one.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core import fonts  # noqa: E402


def test_a_devanagari_font_is_resolved():
    path = fonts.devanagari_font_path()
    assert path, "no Devanagari font resolved — the bundled TTF is missing?"
    assert os.path.isfile(path), path


def test_bundled_font_is_preferred_on_ci():
    # The repo ships backend/app/assets/fonts/NotoSansDevanagari-Regular.ttf,
    # so a clean checkout must resolve to it (never a host font).
    assert fonts.font_source() == "bundled", (
        f"expected the bundled font, got source={fonts.font_source()!r} "
        f"path={fonts.devanagari_font_path()!r}"
    )


def test_resolved_font_covers_the_devanagari_block():
    from fontTools.ttLib import TTFont

    cmap = TTFont(fonts.devanagari_font_path()).getBestCmap()
    for cp, what in [
        (0x0915, "KA"),
        (0x0937, "SSA"),
        (0x094D, "VIRAMA"),
        (0x0930, "RA"),
    ]:
        assert (
            cp in cmap
        ), f"resolved font is missing U+{cp:04X} ({what}) — not a Devanagari font"


def test_resolved_font_has_gsub_for_conjuncts():
    from fontTools.ttLib import TTFont

    tt = TTFont(fonts.devanagari_font_path())
    assert (
        "GSUB" in tt
    ), "font has no GSUB table — conjunct shaping impossible even with a shaper"


def test_configure_matplotlib_is_idempotent_and_names_the_family():
    fam1 = fonts.configure_matplotlib_devanagari()
    fam2 = fonts.configure_matplotlib_devanagari()
    assert fam1 and fam1 == fam2
    import matplotlib.pyplot as plt

    assert plt.rcParams["font.sans-serif"][0] == fam1


def test_font_prop_helpers():
    fp = fonts.dev_font_prop(11)
    assert fp.get_size() == 11
    bp = fonts.dev_bold_font_prop(9)
    assert bp.get_size() == 9
    assert bp.get_weight() in ("bold", 700)
