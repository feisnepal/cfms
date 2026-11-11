"""
FRTC 26-Class Forest Type Map — Single Source of Truth
======================================================

Consolidates forest type definitions that were previously duplicated across:
  - analysis.py (analyze_forest_type, analyze_forest_type_geometry)
  - tile_service.py (_get_forest_type_color)

Usage:
    from app.core.forest_types import (
        FRTC_FOREST_TYPES,
        get_forest_type_name,
        get_forest_type_color,
        get_forest_type_name_np,
    )
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ForestType:
    """Single forest type definition."""
    code: int
    name_en: str
    name_np: str
    color_hex: str  # RGB hex for map tiles / charts
    description: Optional[str] = None


# ── FRTC 26-Class Forest Types ─────────────────────────────
# Source: **FRTC, Kathmandu** — "Forest type classification for Nepal".
# Owner-supplied 2026-09-30 (RS-0.2, which had been BLOCKED on data since 2026-09-29).
# 26 classes, pixel 0.000269495 dd (30 m), Byte, categorical.
#
# **Code 26 is "Unclassified"**, not a forest type. This is the single most
# consequential entry: 26 is 423k of 545k pixels in the test window
# (`FRTC_BLOCKED_REASON`), so ~78% of the raster falls in it. The legend's own
# name for it is "Non forest"; the owner directed (2026-10-01, RS-9.5) that the
# UI say "Unclassified" instead -- given the RS-4.1a finding that 26 is ~90%
# co-located with closed-canopy forest (ESA class 10), "Non forest" would be a
# false claim on the map, while "Unclassified" states only what is actually
# known: FRTC did not assign this pixel one of the 25 named types. The
# previous dict called 26 "Protected Forest", which was wrong in a different
# way (mislabelled the majority of the raster as a specific forest status).
#
# **FRTC 26 is NOT interchangeable with NASA 2020 code 0.** Both are *called*
# non-forest, and that is the whole of the evidence. They are different
# products with different definitions and different granularity, and the same
# numeric code already means something else in each: code 0 is non-forest in
# `nasa_forest_2020`, NoData in `nepal_forest_health`, and sea/water in
# `esa_world_cover`. Whether FRTC 26 should be an `anonymous_code` is therefore
# an open question for RS-1.3 to settle **from FRTC's own distribution**, not a
# conclusion inherited from NASA. Each source's vocabulary is decided on its own
# evidence.
#
# **`name_np` is a best effort.** The owner supplied English only. Transliterated
# binomials and standard ecological terms were used, and the admin translations
# page is the intended place to correct them -- but note that page edits the
# `translations` table (i18n keys), while these are Python constants, so they are
# not yet reachable from it. Recorded as a follow-up.
#
# **Colours carry over per code.** The legend supplies none, and colour is a
# rendering decision rather than legend data, so each code keeps its hex -- but
# it now belongs to a different name. Residual on RS-0.2.

FRTC_FOREST_TYPES: dict[int, ForestType] = {
    1: ForestType(1, "Shorea robusta Forest", "शोरिया रोबस्टा वन", "#228B22"),
    2: ForestType(2, "Tropical Mixed Broadleaved Forest", "उष्णकटिबन्धीय मिश्रित चाँडोपात वन", "#6B8E23"),
    3: ForestType(3, "Subtropical Mixed Broadleaved Forest", "उपोष्णकटिबन्धीय मिश्रित चाँडोपात वन", "#8FBC8F"),
    4: ForestType(4, "Shorea robusta - Mixed Broadleaved Forest", "शोरिया रोबस्टा - मिश्रित चाँडोपात वन", "#2E8B57"),
    5: ForestType(5, "Abies Mixed Forest", "एबिस मिश्रित वन", "#3CB371"),
    6: ForestType(6, "Upper Temperate Coniferous Forest", "माथिल्लो समशीतोष्ण सदाबहार वन", "#20B2AA"),
    7: ForestType(7, "Cool Temperate Mixed Broadleaved Forest", "सन्तुलित समशीतोष्ण मिश्रित चाँडोपात वन", "#008B8B"),
    8: ForestType(8, "Castanopsis Lower Temperate Mixed Broadleaved Forest", "कास्टानोप्सिस निचो समशीतोष्ण मिश्रित चाँडोपात वन", "#5F9EA0"),
    9: ForestType(9, "Pinus roxburghii Forest", "पाइनस रक्सबर्गी वन", "#4682B4"),
    10: ForestType(10, "Alnus Forest", "अल्नस वन", "#6495ED"),
    11: ForestType(11, "Schima Forest", "स्किमा वन", "#87CEEB"),
    12: ForestType(12, "Pinus roxburghii - Mixed Broadleaved Forest", "पाइनस रक्सबर्गी - मिश्रित चाँडोपात वन", "#B0C4DE"),
    13: ForestType(13, "Pinus wallichiana Forest", "पाइनस वालिचियाना वन", "#DAA520"),
    14: ForestType(14, "Warm Temperate Mixed Broadleaved Forest", "न्यानो समशीतोष्ण मिश्रित चाँडोपात वन", "#D2691E"),
    15: ForestType(15, "Upper Temperate Quercus Forest", "माथिल्लो समशीतोष्ण क्वेरकस वन", "#00CED1"),
    16: ForestType(16, "Rhododendron arboreum Forest", "रोडोडेन्ड्रोन आर्बोरियम वन", "#1E90FF"),
    17: ForestType(17, "Temperate Rhododendron Mixed Broadleaved Forest", "समशीतोष्ण रोडोडेन्ड्रोन मिश्रित चाँडोपात वन", "#A9A9A9"),
    18: ForestType(18, "Dalbergia sissoo-Senegalia catechu Forest", "दालबर्गिया सिसु - सेनेगालिया क्याटेचु वन", "#F0F8FF"),
    19: ForestType(19, "Terminalia - Tropical Mixed Broadleaved Forest", "टर्मिनालिया - उष्णकटिबन्धीय मिश्रित चाँडोपात वन", "#F5DEB3"),
    20: ForestType(20, "Temperate Mixed Broadleaved Forest", "समशीतोष्ण मिश्रित चाँडोपात वन", "#CD5C5C"),
    21: ForestType(21, "Tropical Deciduous Indigenous Riverine Forest", "उष्णकटिबन्धीय पतझड आदिवासी नदीग्राम वन", "#4169E1"),
    22: ForestType(22, "Tropical Riverine Forest", "उष्णकटिबन्धीय नदीग्राम वन", "#32CD32"),
    23: ForestType(23, "Lower Temperate Mixed robusta Forest", "निचो समशीतोष्ण मिश्रित रोबस्टा वन", "#006400"),
    24: ForestType(24, "Pinus roxburghii - Shorea robusta Forest", "पाइनस रक्सबर्गी - शोरिया रोबस्टा वन", "#556B2F"),
    25: ForestType(25, "Lower Temperate Pinus roxburghii - Quercus Forest", "निचो समशीतोष्ण पाइनस रक्सबर्गी - क्वेरकस वन", "#8B4513"),
    26: ForestType(26, "Unclassified", "अवर्गीकृत", "#483D8B"),
}

# ── Quick Lookup Helpers ─────────────────────────────────────

def get_forest_type(code: int) -> ForestType:
    """Return ForestType by code. Raises KeyError if unknown."""
    return FRTC_FOREST_TYPES[code]


def get_forest_type_class(code: int) -> ForestType:
    """ForestType by code, falling back to Unknown — for render paths.

    ``rasters.forest_type`` can carry a code no legend registers, and a
    per-unit map must degrade to "Unknown" rather than raise mid-render.
    Mirrors :func:`get_esa_land_cover`; use :func:`get_forest_type` where a
    missing code should be an error.
    """
    return FRTC_FOREST_TYPES.get(
        code, ForestType(code, "Unknown", "अज्ञात", "#808080")
    )


def get_forest_type_name(code: int) -> str:
    """English name for a forest type code."""
    return FRTC_FOREST_TYPES.get(code, ForestType(code, "Unknown", "अज्ञात", "#808080")).name_en


def get_forest_type_name_np(code: int) -> str:
    """Nepali name for a forest type code."""
    return FRTC_FOREST_TYPES.get(code, ForestType(code, "Unknown", "अज्ञात", "#808080")).name_np


def get_forest_type_color(code: int) -> str:
    """Hex color for map rendering / charts."""
    return FRTC_FOREST_TYPES.get(code, ForestType(code, "Unknown", "अज्ञात", "#808080")).color_hex


def get_forest_type_by_name(name: str) -> Optional[ForestType]:
    """Lookup by English name (case-insensitive)."""
    name_lower = name.lower()
    for ft in FRTC_FOREST_TYPES.values():
        if ft.name_en.lower() == name_lower:
            return ft
    return None


# ── ESA WorldCover Land Cover (10-class) ─────────────────────
# Consolidated from analysis.py duplicates

@dataclass(frozen=True)
class LandCoverClass:
    code: int
    name_en: str
    name_np: str
    color_hex: str


ESA_WORLD_COVER: dict[int, LandCoverClass] = {
    10: LandCoverClass(10, "Tree cover", "वृक्ष आवरण", "#006400"),
    20: LandCoverClass(20, "Shrubland", "झाडी", "#FFBB22"),
    30: LandCoverClass(30, "Grassland", "घाँसे मैदान", "#FFFF4C"),
    40: LandCoverClass(40, "Cropland", "कृषि भूमि", "#F096FF"),
    50: LandCoverClass(50, "Built-up", "बस्ती", "#FA0000"),
    60: LandCoverClass(60, "Bare / sparse vegetation", "बाँझो/कम वनस्पति", "#B4B4B4"),
    70: LandCoverClass(70, "Snow and ice", "हिउँ र बरफ", "#F0F0F0"),
    80: LandCoverClass(80, "Permanent water bodies", "स्थायी पानीको स्रोत", "#0064C8"),
    90: LandCoverClass(90, "Herbaceous wetland", "घाँसे चिसोचिसो भूमि", "#0096A0"),
    95: LandCoverClass(95, "Mangroves", "सुन्दरी वन", "#00CF75"),
    100: LandCoverClass(100, "Moss and lichen", "मस र लाइकेन", "#FAE6A0"),
}


def get_esa_land_cover(code: int) -> LandCoverClass:
    return ESA_WORLD_COVER.get(code, LandCoverClass(code, "Unknown", "अज्ञात", "#808080"))


# ── Satellite forest-health class (rasters.nepal_forest_health, 1..5) ────
# 0 = NoData, so it is never a class. NDVI band ranges are the definition:
# class *is* an NDVI threshold band, not a computed index, so the label for a
# unit is a dominant *class*, never a mean of class codes.

@dataclass(frozen=True)
class RasterClass:
    """One class of a categorical raster (integer codes, 0 = NoData)."""

    code: int
    name_en: str
    name_np: str
    color_hex: str
    ndvi_range: Optional[str] = None


FOREST_HEALTH_CLASSES: dict[int, RasterClass] = {
    1: RasterClass(1, "Stressed", "तनावग्रस्त", "#DC143C", "NDVI < 0.2"),
    2: RasterClass(2, "Poor", "कमजोर", "#FF8C00", "NDVI 0.2-0.4"),
    3: RasterClass(3, "Moderate", "मध्यम", "#FFD700", "NDVI 0.4-0.6"),
    4: RasterClass(4, "Healthy", "स्वस्थ", "#90EE90", "NDVI 0.6-0.8"),
    5: RasterClass(5, "Excellent", "उत्कृष्ट", "#228B22", "NDVI > 0.8"),
}

# ── NASA forest quality (rasters.nasa_forest_2020, 1..3) ────────────────
# Code 0 is **non-forest**, not NoData (RS-2.5): it is real, mappable ground
# (grassland, bare soil, urban) that simply is not forest, and it is measured at
# 1-48% of a real forest boundary and 100% of a 4.4 ha one. It is therefore
# absent from this vocabulary on purpose -- the label lives on the spec, in
# app/services/raster_class_vectorize.py, where the geometry is carved too.
# The live band declares no NoData value at all, so 0 survives as a real class.

NASA_FOREST_QUALITY: dict[int, RasterClass] = {
    1: RasterClass(1, "Primary Forest", "प्राथमिक वन (पुरानो वन)", "#00FF00"),
    2: RasterClass(2, "Young Secondary Forest", "कम उमेरको दोस्रो पुस्ताको वन", "#FF0000"),
    3: RasterClass(3, "Old Secondary Forest", "पुरानो दोस्रो पुस्ताको वन", "#6666FF"),
}


def get_forest_health(code: int) -> RasterClass:
    return FOREST_HEALTH_CLASSES.get(code, RasterClass(code, "Unknown", "अज्ञात", "#808080"))


def get_nasa_forest_quality(code: int) -> RasterClass:
    return NASA_FOREST_QUALITY.get(code, RasterClass(code, "Unknown", "अज्ञात", "#808080"))
