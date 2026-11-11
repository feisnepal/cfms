"""Devanagari font resolution — the single source of truth for map/chart text.

Replaces five near-identical ``_DEVANAGARI_FONT_PATHS`` blocks scattered across
the map/chart services (``map_generator.py``, ``plan_map_service.py``,
``field_inventory_mgmt_maps.py``, ``field_inventory_mgmt_charts.py``,
``report/map_generator.py``). Each of those hard-coded ``C:/Windows/Fonts/*``
paths and silently fell back to Latin (tofu) on a Linux VPS.

Resolution order:
    1. the bundled font   ``backend/app/assets/fonts/NotoSansDevanagari-*.ttf``
    2. ``fc-match`` (fontconfig, present on most Linux hosts)
    3. ``matplotlib.font_manager.findfont`` by well-known family name
    4. Windows system paths (dev boxes)

The chosen path is resolved once and logged. Callers use:
    ``configure_matplotlib_devanagari()``  — set rcParams (call at import time)
    ``dev_font_prop(size)``                 — a ``FontProperties`` for a text call
    ``devanagari_font_path()`` / ``devanagari_font_name()``

Complex-script *shaping* (conjuncts क्ष / त्र / ज्ञ, matra reordering) is a
separate concern handled by the ``mplcairo`` + libraqm backend — see
``app.core.text_shaping`` (P2). This module only guarantees a font that
*contains* the Devanagari glyphs is registered.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# backend/app/core/fonts.py -> backend/app/assets/fonts
_ASSETS_FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

# Mukta (EkType, OFL) covers Devanagari AND Latin AND common typographic
# punctuation (·  —  ×  ≤  ≥  °  m³) in one file. That matters for the P2
# mplcairo/HarfBuzz path, which shapes with a single resolved font and does
# NOT do matplotlib's per-glyph fallback — a Devanagari-only font there tofus
# every Latin character (forest names, "MAI", "EPSG:4326").
_BUNDLED_REGULAR = _ASSETS_FONT_DIR / "Mukta-Regular.ttf"
_BUNDLED_BOLD = _ASSETS_FONT_DIR / "Mukta-Bold.ttf"
# Pure-Devanagari fallback, still bundled.
_BUNDLED_FALLBACK = _ASSETS_FONT_DIR / "NotoSansDevanagari-Regular.ttf"

# Well-known family names to probe via fontconfig / matplotlib.
_FAMILY_CANDIDATES = (
    "Mukta",
    "Noto Sans Devanagari",
    "Nirmala UI",
    "Mangal",
    "Lohit Devanagari",
    "Samyak Devanagari",
    "Kalimati",
    "Arial Unicode MS",
)

# Windows system fallbacks (dev boxes only).
_WINDOWS_PATHS = (
    r"C:/Windows/Fonts/Nirmala.ttc",
    r"C:/Windows/Fonts/NirmalaB.ttf",
    r"C:/Windows/Fonts/mangal.ttf",
    r"C:/Windows/Fonts/Kokila.ttf",
    r"C:/Windows/Fonts/ARIALUNI.TTF",
)


def _probe_fc_match(family: str) -> Optional[str]:
    """Ask fontconfig for a file that provides *family*. Linux only, best effort."""
    fc = shutil.which("fc-match")
    if not fc:
        return None
    try:
        out = subprocess.run(
            [fc, "-f", "%{file}", family],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        path = (out.stdout or "").strip()
        if path and os.path.exists(path):
            return path
    except (
        Exception
    ):  # noqa: BLE001 -- fontconfig may be absent/broken; treat as "no match"
        logger.debug("fc-match probe for %r failed", family, exc_info=True)
    return None


def _probe_matplotlib(family: str) -> Optional[str]:
    """Ask matplotlib's font manager for *family*; None if it would fall back."""
    try:
        from matplotlib import font_manager as fm

        path = fm.findfont(family, fallback_to_default=False)
        if path and os.path.exists(path):
            return path
    except Exception:  # noqa: BLE001 -- findfont raises when the family is absent
        pass
    return None


@lru_cache(maxsize=1)
def _resolve() -> tuple[Optional[str], Optional[str], str]:
    """Return ``(regular_path, bold_path, source)``; paths are None if nothing found."""
    # 1. bundled
    if _BUNDLED_REGULAR.exists():
        bold = str(_BUNDLED_BOLD) if _BUNDLED_BOLD.exists() else str(_BUNDLED_REGULAR)
        return str(_BUNDLED_REGULAR), bold, "bundled"

    # 2. fontconfig
    for fam in _FAMILY_CANDIDATES:
        hit = _probe_fc_match(fam)
        if hit:
            return hit, hit, f"fc-match:{fam}"

    # 3. matplotlib
    for fam in _FAMILY_CANDIDATES:
        hit = _probe_matplotlib(fam)
        if hit:
            return hit, hit, f"matplotlib:{fam}"

    # 4. Windows
    for p in _WINDOWS_PATHS:
        if os.path.exists(p):
            return p, p, "windows"

    return None, None, "none"


@lru_cache(maxsize=1)
def _name() -> Optional[str]:
    path, _bold, _src = _resolve()
    if not path:
        return None
    try:
        from matplotlib.font_manager import FontProperties

        return FontProperties(fname=path).get_name()
    except Exception:  # noqa: BLE001 -- fall back to a literal name below
        return "Noto Sans Devanagari"


def devanagari_font_path() -> Optional[str]:
    """Absolute path to the resolved regular Devanagari font, or None."""
    return _resolve()[0]


def devanagari_bold_font_path() -> Optional[str]:
    """Absolute path to the resolved bold Devanagari font (regular if no bold)."""
    return _resolve()[1]


def devanagari_font_name() -> Optional[str]:
    """The matplotlib family name of the resolved font, or None."""
    return _name()


def font_source() -> str:
    """How the font was found: ``bundled`` | ``fc-match:*`` | ``matplotlib:*`` | ``windows`` | ``none``."""
    return _resolve()[2]


@lru_cache(maxsize=1)
def _register_with_matplotlib() -> Optional[str]:
    """addfont() the resolved file(s) so matplotlib can select the family. Returns the family name."""
    path, bold, _src = _resolve()
    if not path:
        return None
    try:
        from matplotlib import font_manager as fm

        fm.fontManager.addfont(path)
        if bold and bold != path:
            fm.fontManager.addfont(bold)
        return fm.FontProperties(fname=path).get_name()
    except (
        Exception
    ):  # noqa: BLE001 -- non-fatal; caller still has the path for FontProperties(fname=)
        logger.warning(
            "could not register Devanagari font with matplotlib", exc_info=True
        )
        return _name()


def configure_matplotlib_devanagari() -> Optional[str]:
    """Register the font and prepend it to ``font.sans-serif``. Idempotent.

    Call once at import time in each map/chart module (replacing the old
    per-module ``_DEVANAGARI_FONT_PATHS`` loop). Returns the family name, or
    None if no Devanagari font could be found anywhere.
    """
    fam = _register_with_matplotlib()
    src = font_source()
    if not fam:
        logger.warning(
            "No Devanagari font found (checked bundled / fc-match / matplotlib / "
            "Windows) — Nepali map & chart labels will render as tofu. Add "
            "backend/app/assets/fonts/NotoSansDevanagari-Regular.ttf "
            "(see that directory's README)."
        )
        return None
    try:
        import matplotlib.pyplot as plt

        plt.rcParams["font.family"] = "sans-serif"
        existing = list(plt.rcParams.get("font.sans-serif", []))
        if fam in existing:
            existing.remove(fam)
        plt.rcParams["font.sans-serif"] = [fam, *existing]
    except Exception:  # noqa: BLE001 -- rcParams tweak is best-effort
        logger.debug("could not update rcParams font.sans-serif", exc_info=True)
    logger.info("Devanagari font: %r (source: %s)", fam, src)
    return fam


# Latin fallback appended after the Devanagari family so matplotlib's per-glyph
# fallback (>= 3.6) covers the Latin characters the Devanagari-only Noto font
# lacks (forest names, "MAI", "m³", "EPSG:4326", …).
_LATIN_FALLBACK = "DejaVu Sans"


def dev_font_prop(size: float = 12):
    """A ``FontProperties`` that renders Devanagari (from the resolved font) and
    falls through to a Latin face for glyphs it lacks.

    Use for individual ``ax.text`` / ``set_title`` / legend calls that mix
    Devanagari and Latin. Falls back to a plain sized ``FontProperties`` when
    no Devanagari font was found.
    """
    from matplotlib.font_manager import FontProperties

    fam = _register_with_matplotlib()
    if fam:
        return FontProperties(family=[fam, _LATIN_FALLBACK], size=size)
    return FontProperties(size=size)


def dev_bold_font_prop(size: float = 12):
    """Bold variant of :func:`dev_font_prop`."""
    from matplotlib.font_manager import FontProperties

    fam = _register_with_matplotlib()
    if fam:
        return FontProperties(family=[fam, _LATIN_FALLBACK], size=size, weight="bold")
    return FontProperties(size=size, weight="bold")
