"""Complex-script text shaping for matplotlib output (P2).

matplotlib's default Agg text stack renders glyph-by-glyph with no HarfBuzz, so
Devanagari conjuncts (क्ष, त्र, ज्ञ) and matra reordering come out wrong even
when the font contains every glyph (which `app.core.fonts` now guarantees).

``mplcairo`` renders through cairo, which *does* shape via HarfBuzz. We do not
switch the global matplotlib backend (other modules already did
``matplotlib.use("Agg")`` at import and switching mid-process is fragile) —
instead we swap a single figure's canvas to cairo just before saving, via
:func:`save_figure`. When ``mplcairo`` is not installed this is a no-op and the
figure saves through Agg exactly as before (correct font, imperfect shaping).

    from app.core.text_shaping import save_figure
    save_figure(fig, buf, format="png", dpi=dpi, facecolor="white")
"""

from __future__ import annotations

import logging
from functools import lru_cache

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _cairo_canvas_cls():
    try:
        from mplcairo.base import FigureCanvasCairo

        return FigureCanvasCairo
    except Exception:  # noqa: BLE001 -- optional dep; Agg fallback is fine
        return None


@lru_cache(maxsize=1)
def shaping_backend() -> str:
    """``"mplcairo"`` when HarfBuzz shaping is available, else ``"agg"``."""
    return "mplcairo" if _cairo_canvas_cls() is not None else "agg"


def apply(fig) -> bool:
    """Swap *fig*'s canvas to cairo in place. Returns True if it took effect.

    Safe to call more than once; a figure already on a cairo canvas is left
    alone.
    """
    cls = _cairo_canvas_cls()
    if cls is None:
        return False
    if type(fig.canvas).__name__ == cls.__name__:
        return True
    try:
        fig.set_canvas(cls(fig))
        return True
    except Exception:  # noqa: BLE001 -- never let a shaping tweak break a render
        logger.warning(
            "mplcairo canvas swap failed; falling back to Agg", exc_info=True
        )
        return False


@lru_cache(maxsize=1)
def _mplcairo_has_harfbuzz() -> bool:
    """``mplcairo`` present *and* built with HarfBuzz.

    The Windows wheels of mplcairo 0.6 report ``harfbuzz: None`` — cairo still
    renders, but complex-script shaping (i-matra reorder, reph, conjuncts) is
    NOT applied, so Devanagari comes out wrong. Only trust the cairo path when
    HarfBuzz is actually linked.
    """
    if _cairo_canvas_cls() is None:
        return False
    try:
        from mplcairo import get_versions

        return bool(get_versions().get("harfbuzz"))
    except Exception:  # noqa: BLE001
        return False


# U+0900–U+097F Devanagari (+ the U+A8E0–U+A8FF extended block).
import re as _re  # noqa: E402

_DEVANAGARI = _re.compile(r"[ऀ-ॿ꣠-ꣿ]")


@lru_cache(maxsize=1)
def _harfbuzz_available() -> bool:
    try:
        import uharfbuzz  # noqa: F401
        from fontTools.ttLib import TTFont  # noqa: F401
        from fontTools.pens.basePen import BasePen  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def manual_shaping_active() -> bool:
    """True when ``save_figure`` will HarfBuzz-shape Devanagari text itself
    (mplcairo can't, but ``uharfbuzz`` + ``fontTools`` are importable)."""
    return not _mplcairo_has_harfbuzz() and _harfbuzz_available()


@lru_cache(maxsize=16)
def _hb_font(font_path: str):
    import uharfbuzz as hb

    face = hb.Face(hb.Blob.from_file_path(font_path))
    return hb.Font(face), face.upem


@lru_cache(maxsize=16)
def _ft_glyphset(font_path: str):
    from fontTools.ttLib import TTFont

    tt = TTFont(font_path, fontNumber=0, lazy=True)
    return tt.getGlyphSet(), tt.getGlyphOrder()


def _shape_to_path(text: str, font_path: str):
    """HarfBuzz-shaped *text* → (matplotlib ``Path`` in point units, advance_pt).

    Path origin is the text's left edge on the baseline, y-up.
    """
    import numpy as np
    import uharfbuzz as hb
    from fontTools.pens.basePen import BasePen
    from matplotlib.path import Path as _Path

    class _Pen(BasePen):
        def __init__(self, gs):
            super().__init__(gs)
            self.v: list = []
            self.c: list = []

        def _moveTo(self, p):
            self.v.append(p)
            self.c.append(_Path.MOVETO)

        def _lineTo(self, p):
            self.v.append(p)
            self.c.append(_Path.LINETO)

        def _curveToOne(self, p1, p2, p3):
            self.v += [p1, p2, p3]
            self.c += [_Path.CURVE4] * 3

        def _qCurveToOne(self, p1, p2):
            self.v += [p1, p2]
            self.c += [_Path.CURVE3] * 2

        def _closePath(self):
            self.v.append((0.0, 0.0))
            self.c.append(_Path.CLOSEPOLY)

    font, upem = _hb_font(font_path)
    gs, order = _ft_glyphset(font_path)
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(font, buf)

    s = 1.0 / upem  # to em; caller scales by size_pt
    verts: list = []
    codes: list = []
    x = 0.0
    for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
        pen = _Pen(gs)
        try:
            gs[order[info.codepoint]].draw(pen)
        except Exception:  # noqa: BLE001 -- a missing outline just leaves a gap
            pass
        dx = (x + pos.x_offset) * s
        dy = pos.y_offset * s
        for (vx, vy), c in zip(pen.v, pen.c):
            verts.append((vx * s + dx, vy * s + dy))
            codes.append(c)
        x += pos.x_advance
    if not verts:
        return _Path(np.empty((0, 2)), []), x * s
    return _Path(np.asarray(verts, float), codes), x * s


def _font_path_for(text_artist) -> "str | None":
    """Resolve the on-disk .ttf a text artist should shape with — its
    ``FontProperties`` file if we can, else the bundled Devanagari face."""
    from app.core.fonts import devanagari_bold_font_path, devanagari_font_path

    bold = "bold" in str(getattr(text_artist, "get_fontweight", lambda: "")()).lower()
    try:
        import matplotlib.font_manager as fm

        fp = text_artist.get_fontproperties()
        path = fm.findfont(fp, fallback_to_default=False)
        if path and path.lower().endswith((".ttf", ".otf")):
            # only use it if it actually has Devanagari coverage
            from fontTools.ttLib import TTFont

            cmap = TTFont(path, fontNumber=0, lazy=True).getBestCmap()
            if any(0x0900 <= cp <= 0x097F for cp in cmap):
                return path
    except Exception:  # noqa: BLE001
        pass
    return (devanagari_bold_font_path() if bold else None) or devanagari_font_path()


def _manual_shape(fig) -> int:
    """Replace every Devanagari ``Text`` artist on *fig* with a HarfBuzz-shaped
    outline (``PathPatch``). Returns the count replaced. Best-effort per artist.
    """
    from matplotlib.patches import PathPatch
    from matplotlib.path import Path as _Path
    from matplotlib.text import Text
    from matplotlib.transforms import Affine2D

    # a full draw so every artist has a finalised transform / position
    fig.canvas.draw()
    dpi = float(fig.dpi)  # dpi at layout time; may differ from savefig(dpi=…)
    done = 0

    for art in list(fig.findobj(Text)):
        s = art.get_text()
        if not s or not _DEVANAGARI.search(s) or not art.get_visible():
            continue
        try:
            font_path = _font_path_for(art)
            if not font_path:
                continue
            size_pt = float(art.get_fontsize())
            path_em, _adv = _shape_to_path(s, font_path)
            if len(path_em.vertices) == 0:
                continue

            # Work in INCHES so the result is dpi-independent — savefig(dpi=…)
            # rescales the figure, and an IdentityTransform (raw px) patch would
            # not follow. path in em → inches via size_pt/72.
            verts_in = path_em.vertices * (size_pt / 72.0)
            bb_x0, bb_y0 = verts_in.min(axis=0)
            bb_x1, bb_y1 = verts_in.max(axis=0)

            ha = art.get_horizontalalignment()
            va = art.get_verticalalignment()
            off_x = {
                "left": -bb_x0,
                "center": -(bb_x0 + bb_x1) / 2.0,
                "right": -bb_x1,
            }.get(ha, -bb_x0)
            off_y = {
                "baseline": 0.0,
                "bottom": -bb_y0,
                "center": -(bb_y0 + bb_y1) / 2.0,
                "center_baseline": -(bb_y0 + bb_y1) / 2.0,
                "top": -bb_y1,
            }.get(va, 0.0)

            # anchor: display px (at layout dpi) → inches
            anchor_in = art.get_transform().transform(art.get_unitless_position()) / dpi
            rot = float(art.get_rotation())

            tr = (
                Affine2D().translate(off_x, off_y).rotate_deg(rot).translate(*anchor_in)
                + fig.dpi_scale_trans  # inches → display, re-evaluated per draw
            )

            patch = PathPatch(
                _Path(verts_in, path_em.codes),
                transform=tr,
                facecolor=art.get_color(),
                edgecolor="none",
                alpha=art.get_alpha(),
                zorder=art.get_zorder(),
                clip_on=False,
            )
            # keep any white halo the label had
            pe = art.get_path_effects()
            if pe:
                patch.set_path_effects(pe)
            fig.add_artist(patch)
            art.set_visible(False)
            done += 1
        except Exception:  # noqa: BLE001 -- fall back to the (unshaped) artist
            logger.warning("manual shaping failed for %r", s[:40], exc_info=True)
    return done


def save_figure(fig, fname, **savefig_kw) -> None:
    """``fig.savefig`` with HarfBuzz shaping for Devanagari.

    Prefers mplcairo when it is built with HarfBuzz; otherwise shapes the
    Devanagari text artists to outlines ourselves (uharfbuzz + fontTools) so
    matras / reph / conjuncts render correctly on plain Agg too.
    """
    if _mplcairo_has_harfbuzz():
        apply(fig)
    elif manual_shaping_active():
        try:
            # ``bbox_inches="tight"`` re-runs layout at save time, which would
            # shift text relative to the path patches we add. Freeze the tight
            # bbox now (in inches) and pass that fixed box instead.
            if savefig_kw.get("bbox_inches") == "tight":
                pad = savefig_kw.pop("pad_inches", 0.1) or 0.0
                try:
                    fig.canvas.draw()
                    r = fig.canvas.get_renderer()
                    savefig_kw["bbox_inches"] = fig.get_tightbbox(r).padded(pad)
                except Exception:  # noqa: BLE001 -- fall back to a full-figure save
                    savefig_kw.pop("bbox_inches", None)
            _manual_shape(fig)
        except Exception:  # noqa: BLE001 -- never let shaping break a render
            logger.warning("manual Devanagari shaping pass failed", exc_info=True)
    else:
        apply(fig)  # cairo-without-harfbuzz is still a bit better than Agg
    fig.savefig(fname, **savefig_kw)
