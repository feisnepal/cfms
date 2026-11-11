"""Semantic colour SSOT for maps and charts (THEMATIC_MAP_VARIABLES_PLAN §3.3, Appendix C.2).

The one place a colour *means* something. Imported by the thematic map engine,
the chart generators (later), and mirrored verbatim to the frontend as
``frontend/src/lib/semanticPalettes.ts`` — ``tests/test_semantic_palettes.py``
fails the build if the two drift.

Contents:
  * ``RAMPS``           — 8 sequential/qualitative ramps, byte-identical to
                          ``frontend/src/lib/colorRamps.ts``.
  * ``SEQUENTIAL``      — semantic name → ramp key (``"_r"`` = reversed).
  * ``CATEGORICAL`` / ``CATEGORICAL_OTHER`` / ``HATCH`` — nominal/ordinal schemes,
                          each class carrying a matplotlib ``hatch=`` string so the
                          map survives greyscale printing.
  * ``DIVERGING``       — 5-stop diverging schemes (neutral midpoint).
  * ``BIVARIATE``       — 3×3 (9-swatch) matrices.
  * helpers: ``sample_ramp``, ``equal_breaks``, ``quantile_breaks``,
             ``jenks_breaks``, ``resolve_palette``, ``hatch_for``.

Break helpers mirror ``colorRamps.ts`` exactly (RGB-linear interpolation,
``round4``) so a workspace choropleth and a report choropleth of the same
measure are directly comparable.
"""

from __future__ import annotations

from typing import Iterable, Optional

from app.core.forest_types import FRTC_FOREST_TYPES

# ── no-data ────────────────────────────────────────────────────────────────
NO_DATA_FILL = "#e0e0e0"
NO_DATA_HATCH = ".."
NO_DATA_LABEL_NE = "कुनै तथ्याङ्क छैन"
NO_DATA_LABEL_EN = "No data"

# ── sequential / qualitative ramps — verbatim from colorRamps.ts ───────────
RAMPS: dict[str, list[str]] = {
    "blues": ["#eff3ff", "#bdd7e7", "#6baed6", "#3182bd", "#08519c"],
    "greens": ["#edf8e9", "#bae4b3", "#74c476", "#31a354", "#006d2c"],
    "reds": ["#fee5d9", "#fcae91", "#fb6a4a", "#de2d26", "#a50f15"],
    "oranges": ["#feedde", "#fdbe85", "#fd8d3c", "#e6550d", "#a63603"],
    "purples": ["#f2f0f7", "#cbc9e2", "#9e9ac8", "#756bb1", "#54278f"],
    "greys": ["#f7f7f7", "#cccccc", "#969696", "#636363", "#252525"],
    "spectral": ["#d7191c", "#fdae61", "#ffffbf", "#abdda4", "#2b83ba"],
    "viridis": ["#440154", "#3b528b", "#21918c", "#5ec962", "#fde725"],
    # multi-hue sequential ramps: a single-hue ramp's first classes are near-white and its steps blur together; these change hue
    # as well as lightness, so five classes can be told apart (ColorBrewer YlGn / YlGnBu / BuPu / YlOrBr / YlOrRd)
    "ylgn": ["#ffffcc", "#c2e699", "#78c679", "#31a354", "#006837"],
    "ylgnbu": ["#ffffcc", "#a1dab4", "#41b6c4", "#2c7fb8", "#253494"],
    "bupu": ["#edf8fb", "#b3cde3", "#8c96c6", "#8856a7", "#810f7c"],
    "ylorbr": ["#ffffd4", "#fed98e", "#fe9929", "#d95f0e", "#993404"],
    "ylorrd": ["#ffffb2", "#fecc5c", "#fd8d3c", "#f03b20", "#bd0026"],
}
RAMP_NAMES = tuple(RAMPS.keys())

# semantic sequential measure → ramp key ("<key>_r" reverses the ramp)
SEQUENTIAL: dict[str, str] = {
    "growing_stock": "ylgn",
    "carbon": "viridis",
    "increment": "ylgnbu",
    "basal_area": "bupu",
    "stems": "ylorbr",
    "density": "ylorrd",
    "access": "greys_r",
}

# ── categorical / ordinal schemes ────────────────────────────────────────
# hatch strings are matplotlib hatch patterns; "" = solid fill.
# One DISTINCT colour per size class (not shades of one hue, which cannot be told apart in a bar or a pie), ordered cool -> warm as the
# trees get bigger: purple, blue, green, lime, yellow, orange, red, dark brown.
_DBH8 = [
    "#6a51a3",
    "#2b83ba",
    "#1a9850",
    "#a6d854",
    "#ffd92f",
    "#fc8d62",
    "#e41a1c",
    "#7f2704",
]
_DBH8_KEYS = ["0_4", "4_10", "10_20", "20_30", "30_40", "40_50", "50_60", "60_plus"]
# Trees from 10 cm up (pole + tree classes): the SAME colours those classes have in every other size-class chart.
_DBH6 = _DBH8[2:]
_DBH6_KEYS = ["10_20", "20_30", "30_40", "40_50", "50_60", "60_plus"]
_DBH8_HATCH = ["..", "//", "\\\\", "xx", "++", "--", "oo", "**"]

_SPECIES_QUAL = [  # Okabe–Ito + Paul Tol muted — CVD-safe, print-safe
    "#E69F00",
    "#56B4E9",
    "#009E73",
    "#F0E442",
    "#0072B2",
    "#D55E00",
    "#CC79A7",
    "#999999",
    "#882255",
    "#44AA99",
    "#DDCC77",
    "#117733",
]

# 14 management categories (+ the strips) — the SSOT (plan_map_service.SUB_AREA_CATEGORIES
# should import from here in a later pass).
_SUBAREA_CATEGORY = {
    "protected": "#ef4444",
    "plantation": "#10b981",
    "pro-poor": "#f59e0b",
    "religious": "#8b5cf6",
    "biodiversity": "#06b6d4",
    "tourist": "#ec4899",
    "office": "#6b7280",
    "private_land": "#dc2626",
    "agroforestry": "#84cc17",
    "tree_strata": "#15803d",
    "water_hole": "#0ea5e9",
    "wildlife_corridor": "#a855f7",
    "agriculture": "#eab308",
    "settlement": "#f97316",
    "fire_line": "#c62828",  # a strip, not a zone: core/sub_area_kinds.py
    "river_bank": "#1e40af",
}
_SUBAREA_HATCH = {"private_land": "xx"}

CATEGORICAL: dict[str, dict[str, str]] = {
    "condition": {"Good": "#2e7d32", "Moderate": "#f9a825", "Weak": "#c62828"},
    # forest condition | regeneration condition: the HUE is the forest (green / amber / red), the SHADE is the regeneration
    # (dark = good, light = weak), so "good forest, weak regeneration" is a pale green and "weak forest, good regeneration" a dark red.
    "condition_pair": {
        "Good|Good": "#1b7837", "Good|Moderate": "#5aae61", "Good|Weak": "#b7e4b0",
        "Moderate|Good": "#c77700", "Moderate|Moderate": "#f5a623", "Moderate|Weak": "#fbe08a",
        "Weak|Good": "#a50f15", "Weak|Moderate": "#e5534b", "Weak|Weak": "#f7b6b0",
    },
    "growth_rate": {"Fast": "#2e7d32", "Moderate": "#f9a825", "Slow": "#795548"},
    "working_circle": {"production": "#3182bd", "protection": "#15803d"},
    "dbh_classes_3": {
        "regeneration": "#1b9e77",
        "advance_growth": "#d95f02",
        "mature_tree": "#7570b3",
    },
    "dbh_classes": dict(zip(_DBH8_KEYS, _DBH8)),
    "dbh_classes_10plus": dict(zip(_DBH6_KEYS, _DBH6)),
    "subarea_category": dict(_SUBAREA_CATEGORY),
    "species_qual": {str(i): c for i, c in enumerate(_SPECIES_QUAL)},
    "aspect": {
        "N": "#4575b4",
        "NE": "#74add1",
        "E": "#abd9e9",
        "SE": "#e0f3f8",
        "S": "#fee090",
        "SW": "#fdae61",
        "W": "#f46d43",
        "NW": "#d73027",
    },
    # S9 / P6z — reuses the `oranges` ramp so no new hex enters the SSOT.
    "slope_class": {
        "gentle": "#fdbe85",
        "moderate": "#fd8d3c",
        "steep": "#e6550d",
        "very_steep": "#a63603",
    },
    # S9 / P6z — dominant physiographic forest type. Keys and hexes both come
    # from core.forest_types.FRTC_FOREST_TYPES, i.e. the same vocabulary the
    # tile renderer draws with, so the OP map and the map beside it cannot
    # disagree (owner decision 2026-09-29; previously keyed by a local
    # 10-species dict that could not label 6 of the raster's 12 codes).
    "forest_type": {ft.name_en: ft.color_hex for ft in FRTC_FOREST_TYPES.values()},
    # SFM P5 — the 14 अनुसूची-१ forest types (keys "1".."14"). 12 from the
    # qualitative species palette + 2 dark ramp stops so all 14 read apart.
    "sfm_forest_type": {
        str(i + 1): c for i, c in enumerate([*_SPECIES_QUAL, "#08519c", "#a63603"])
    },
    # SFM P5 — working-circle orientation. Production/Protection reuse the
    # working_circle hexes; Conservation takes the amber from `condition`.
    "sfm_orientation": {
        "Production": "#3182bd",
        "Conservation": "#f9a825",
        "Protection": "#15803d",
    },
    # S9 / P6z — satellite forest-health classes (rasters.nepal_forest_health,
    # 1..5). Keys are the EN names from core.forest_types.FOREST_HEALTH_CLASSES
    # so the legend and the zonal record agree by construction.
    "forest_health_class": {
        "Stressed": "#DC143C",
        "Poor": "#FF8C00",
        "Moderate": "#FFD700",
        "Healthy": "#90EE90",
        "Excellent": "#228B22",
    },
    # S9 / P6z — NASA forest quality (rasters.nasa_forest_2020, 1..3). Keys
    # from core.forest_types.NASA_FOREST_QUALITY.
    "nasa_quality": {
        "Primary Forest": "#00FF00",
        "Young Secondary Forest": "#FF0000",
        "Old Secondary Forest": "#6666FF",
    },
}

CATEGORICAL_OTHER: dict[str, str] = {
    "condition": "#bdbdbd",
    "condition_pair": "#bdbdbd",
    "growth_rate": "#bdbdbd",
    "dbh_classes_3": "#bdbdbd",
    "dbh_classes_10plus": "#bdbdbd",
    "species_qual": "#bdbdbd",
    "subarea_category": "#9e9e9e",
    "slope_class": "#bdbdbd",
    "forest_type": "#bdbdbd",
    "sfm_forest_type": "#bdbdbd",
    "sfm_orientation": "#bdbdbd",
}

# Nepali display labels for categorical legend values. The scheme keys above are
# the English DB values (``"Weak"``, ``"production"`` …); a map whose title and
# caption are Nepali must not then print an English legend. Only palettes whose
# values actually surface in a legend need an entry — anything unmapped falls
# back to the raw key via :func:`category_label`.
CATEGORY_LABELS_NE: dict[str, dict[str, str]] = {
    "condition": {"Good": "राम्रो", "Moderate": "मध्यम", "Weak": "कमजोर"},
    "condition_pair": {
        f"{f}|{r}": f"वन {n[f]} · पुनरुत्पादन {n[r]}"
        for f in ("Good", "Moderate", "Weak")
        for r in ("Good", "Moderate", "Weak")
        for n in [{"Good": "राम्रो", "Moderate": "मध्यम", "Weak": "कमजोर"}]
    },
    "growth_rate": {"Fast": "द्रुत", "Moderate": "मध्यम", "Slow": "मन्द"},
    "working_circle": {"production": "उत्पादन कार्य वृत्त", "protection": "संरक्षण कार्य वृत्त"},
    "dbh_classes_3": {
        "regeneration": "पुनरुत्पादन",
        "advance_growth": "बर्धिष्णु",
        "mature_tree": "परिपक्व रूख",
    },
    "slope_class": {
        "gentle": "मन्द",
        "moderate": "मध्यम",
        "steep": "भिरालो",
        "very_steep": "अति भिरालो",
    },
    # SFM P5 — short अनुसूची-१ type names (full names live on the DB rows).
    "sfm_forest_type": {
        "1": "तराई/शिवालिक साल (< १९°)",
        "2": "शिवालिक साल (१९–३१°)",
        "3": "शिवालिक साल (> ३१°)",
        "4": "सिसौ/खयर वृक्षारोपण",
        "5": "नदी तटीय वन",
        "6": "बिग्रेको तराई/भित्री मधेश वन",
        "7": "पहाडी साल वन",
        "8": "प्राकृतिक सल्ला वन",
        "9": "वृक्षारोपण सल्ला वन",
        "10": "सल्ला–चौडापाते मिश्रित",
        "11": "पहाडी चौडापाते मिश्रित",
        "12": "शितोष्ण चौडापाते मिश्रित",
        "13": "शितोष्ण कोणधारी वन",
        "14": "सल्लाबाट चौडापातेमा रूपान्तरित",
    },
    "sfm_orientation": {
        "Production": "उत्पादन",
        "Conservation": "संरक्षण",
        "Protection": "प्रतिरक्षा",
    },
}

HATCH: dict[str, dict[str, str]] = {
    "condition": {"Good": "..", "Moderate": "//", "Weak": "xx"},
    "growth_rate": {"Fast": "..", "Moderate": "//", "Slow": "\\\\"},
    "working_circle": {"production": "", "protection": "////"},
    "dbh_classes_3": {
        "regeneration": "..",
        "advance_growth": "//",
        "mature_tree": "xx",
    },
    "dbh_classes": dict(zip(_DBH8_KEYS, _DBH8_HATCH)),
    "subarea_category": dict(_SUBAREA_HATCH),
    # SFM P5 — the two protection forest types carry a hatch so they read as
    # "no felling" even in greyscale; orientation Protection likewise.
    "sfm_forest_type": {"3": "xx", "6": "xx"},
    "sfm_orientation": {"Protection": "////"},
}

# ── diverging (neutral midpoint at the reference) ─────────────────────────
DIVERGING: dict[str, list[str]] = {
    "deviation": ["#ca0020", "#f4a582", "#f7f7f7", "#92c5de", "#0571b0"],
    "gain_loss": ["#c62828", "#ef9a9a", "#f5f5f5", "#a5d6a7", "#2e7d32"],
}

# ── bivariate 3×3 (row = A low→high bottom→top, col = B low→high left→right)
BIVARIATE: dict[str, list[str]] = {
    # Joshua Stevens green×purple
    "bivariate_gp": [
        "#e8e8e8",
        "#ace4e4",
        "#5ac8c8",  # A low
        "#dfb0d6",
        "#a5add3",
        "#5698b9",  # A mid
        "#be64ac",
        "#8c62aa",
        "#3b4994",  # A high
    ],
    # green×blue (product of two 3-step ramps)
    "bivariate_gg": [
        "#e8f4e8",
        "#b7dbb7",
        "#6ec06e",
        "#b9d9c8",
        "#8fbfb0",
        "#4f9d78",
        "#6db56d",
        "#4f9d78",
        "#1f6d4f",
    ],
}

# fixed named categorical renderer — mirrors frontend layerRenderers.CONDITION_RENDERER
CONDITION_CLASSES = ("Good", "Moderate", "Weak")


# ── helpers ──────────────────────────────────────────────────────────────
def _clamp255(n: float) -> int:
    return max(0, min(255, round(n)))


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(r: float, g: float, b: float) -> str:
    return "#" + "".join(f"{_clamp255(c):02x}" for c in (r, g, b))


def _round4(n: float) -> float:
    return round(n * 1e4) / 1e4


def _ramp_stops(name: str) -> list[str]:
    reverse = name.endswith("_r")
    key = name[:-2] if reverse else name
    stops = RAMPS.get(key) or SEQUENTIAL.get(key)
    if isinstance(stops, str):  # semantic alias → ramp key
        return _ramp_stops(stops)
    if stops is None:
        stops = RAMPS["blues"]
    return list(reversed(stops)) if reverse else list(stops)


def sample_ramp(name: str, n: int) -> list[str]:
    """*n* evenly-spaced colours across a ramp (RGB-linear). Mirrors ``sampleRamp`` in TS."""
    stops = _ramp_stops(name)
    if n <= 0:
        return []
    if n == 1:
        return [stops[(len(stops) - 1) // 2]]
    out: list[str] = []
    for i in range(n):
        t = (i / (n - 1)) * (len(stops) - 1)
        lo = int(t)
        hi = min(len(stops) - 1, lo + 1)
        f = t - lo
        r1, g1, b1 = _hex_to_rgb(stops[lo])
        r2, g2, b2 = _hex_to_rgb(stops[hi])
        out.append(
            _rgb_to_hex(r1 + (r2 - r1) * f, g1 + (g2 - g1) * f, b1 + (b2 - b1) * f)
        )
    return out


def _finite_sorted(values: Iterable[float]) -> list[float]:
    nums = [float(v) for v in values if v is not None and _is_finite(v)]
    nums.sort()
    return nums


def _is_finite(v) -> bool:
    try:
        f = float(v)
        return f == f and f not in (float("inf"), float("-inf"))
    except (TypeError, ValueError):
        return False


def equal_breaks(values: Iterable[float], classes: int) -> list[float]:
    """``classes - 1`` equal-interval breaks. Mirrors ``equalBreaks`` in TS."""
    nums = _finite_sorted(values)
    if not nums or classes < 2:
        return []
    lo, hi = nums[0], nums[-1]
    step = (hi - lo) / classes
    return [_round4(lo + step * (i + 1)) for i in range(classes - 1)]


def quantile_breaks(values: Iterable[float], classes: int) -> list[float]:
    """``classes - 1`` quantile breaks. Mirrors ``quantileBreaks`` in TS."""
    nums = _finite_sorted(values)
    if not nums or classes < 2:
        return []
    breaks: list[float] = []
    for i in range(1, classes):
        pos = (len(nums) - 1) * (i / classes)
        lo = int(pos)
        hi = min(len(nums) - 1, lo + 1)
        breaks.append(_round4(nums[lo] + (nums[hi] - nums[lo]) * (pos - lo)))
    return breaks


def jenks_breaks(values: Iterable[float], classes: int) -> list[float]:
    """``classes - 1`` Fisher–Jenks natural breaks. Pure-python; falls back to
    ``quantile_breaks`` for large N to stay inside the map-gen time budget."""
    nums = _finite_sorted(values)
    if not nums or classes < 2:
        return []
    if len(nums) <= classes:
        return [_round4(v) for v in nums[1:]]
    if len(nums) > 800:  # O(n²·k) — cap for responsiveness
        return quantile_breaks(nums, classes)

    n = len(nums)
    k = classes
    mat1 = [[0] * (k + 1) for _ in range(n + 1)]
    mat2 = [[0.0] * (k + 1) for _ in range(n + 1)]
    for j in range(1, k + 1):
        mat1[1][j] = 1
        mat2[1][j] = 0.0
        for i in range(2, n + 1):
            mat2[i][j] = float("inf")
    for l in range(2, n + 1):
        s1 = s2 = w = 0.0
        for m in range(1, l + 1):
            i3 = l - m + 1
            val = nums[i3 - 1]
            w += 1
            s1 += val
            s2 += val * val
            variance = s2 - (s1 * s1) / w
            i4 = i3 - 1
            if i4 != 0:
                for j in range(2, k + 1):
                    if mat2[l][j] >= variance + mat2[i4][j - 1]:
                        mat1[l][j] = i3
                        mat2[l][j] = variance + mat2[i4][j - 1]
        mat1[l][1] = 1
        mat2[l][1] = variance
    kclass = [0.0] * (k + 1)
    kclass[k] = nums[-1]
    kclass[0] = nums[0]
    kk = n
    for j in range(k, 1, -1):
        idx = int(mat1[kk][j]) - 2
        kclass[j - 1] = nums[idx]
        kk = int(mat1[kk][j]) - 1
    return [_round4(v) for v in kclass[1:k]]


BREAK_METHODS = {
    "equal": equal_breaks,
    "quantile": quantile_breaks,
    "natural": jenks_breaks,
}


def resolve_palette(name: str, n: Optional[int] = None) -> list[str]:
    """Return a colour list for *name*.

    * a categorical scheme name → its class colours in declared order
    * a diverging / bivariate name → its stops
    * a sequential ramp / semantic key → *n* sampled colours (``n`` required)
    """
    if name in CATEGORICAL:
        return list(CATEGORICAL[name].values())
    if name in DIVERGING:
        return list(DIVERGING[name])
    if name in BIVARIATE:
        return list(BIVARIATE[name])
    if n is None:
        n = 5
    return sample_ramp(name, n)


def color_for_category(palette: str, value, *, fallback: bool = True) -> Optional[str]:
    """Colour for one categorical *value*; ``CATEGORICAL_OTHER`` (or None) if unmatched."""
    scheme = CATEGORICAL.get(palette, {})
    key = "" if value is None else str(value)
    if key in scheme:
        return scheme[key]
    return CATEGORICAL_OTHER.get(palette) if fallback else None


def hatch_for(palette: str, value) -> str:
    """matplotlib ``hatch=`` string for one categorical value ("" = solid)."""
    key = "" if value is None else str(value)
    return HATCH.get(palette, {}).get(key, "")


def category_label(palette: str, value, *, lang: str = "ne") -> str:
    """Display label for a categorical value. Nepali when known (see
    :data:`CATEGORY_LABELS_NE`), otherwise the raw key unchanged."""
    key = "" if value in (None, "") else str(value)
    if lang == "ne":
        return CATEGORY_LABELS_NE.get(palette, {}).get(key, key)
    return key


PROTECTION_HATCH = "////"
EXCLUDED_HATCH = "xx"
