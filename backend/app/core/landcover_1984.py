"""1984 land-use classification — SSOT for the ``landcover.landcover_1984`` layer.

That table (digitised from ~1984 topo sheets) carries 20+ raw ``landuse_yr1984``
strings, many of them synonyms or typos ("Built up" / "Building" / "structure",
"Cultivated" / "cultivation", a blank " "). This module normalises them to a
small canonical set and gives each canonical class a colour + a bilingual label,
so the 1984 land-cover map and the ``{{landcover_1984_*}}`` variables agree.

Used by:
    services.analysis.analyze_landcover_1984_geometry
    services.operational_plan.data_collector._enrich_landcover_1984_from_polygons
    services.management_plan_docx.plan_map_service (the map renderer)
"""

from __future__ import annotations

# raw ``landuse_yr1984`` value (lower-cased, stripped) -> canonical class
_RAW_TO_CANON: dict[str, str] = {
    "forest": "Forest",
    "scattered tree": "Forest",
    "bush": "Shrub / Bush",
    "bamboo": "Shrub / Bush",
    "plantation": "Plantation",
    "nursery": "Plantation",
    "orchard": "Plantation",
    "cultivated": "Cultivated",
    "cultivation": "Cultivated",
    "grass": "Grassland",
    "swamp": "Wetland",
    "pond/lake": "Water body",
    "river": "Water body",
    "well": "Water body",
    "glacier": "Snow / Glacier",
    "snow": "Snow / Glacier",
    "barren land": "Barren / Rock",
    "rock outcrop": "Barren / Rock",
    "cutting/cliff": "Barren / Rock",
    "built up": "Built-up",
    "building": "Built-up",
    "structure": "Built-up",
    "runway": "Built-up",
}

# canonical class -> hex fill colour
LC1984_COLORS: dict[str, str] = {
    "Forest": "#2e7d32",
    "Plantation": "#81c784",
    "Shrub / Bush": "#c5e1a5",
    "Grassland": "#dce775",
    "Cultivated": "#ffd54f",
    "Wetland": "#4dd0e1",
    "Water body": "#4fc3f7",
    "Barren / Rock": "#bcaaa4",
    "Built-up": "#e57373",
    "Snow / Glacier": "#eceff1",
    "Other": "#cfd8dc",
}

# canonical class -> {"ne", "en"}
LC1984_LABELS: dict[str, dict[str, str]] = {
    "Forest": {"ne": "वन", "en": "Forest"},
    "Plantation": {"ne": "वृक्षारोपण", "en": "Plantation"},
    "Shrub / Bush": {"ne": "झाडी / बुट्यान", "en": "Shrub / Bush"},
    "Grassland": {"ne": "घाँसे मैदान", "en": "Grassland"},
    "Cultivated": {"ne": "खेतीयोग्य", "en": "Cultivated"},
    "Wetland": {"ne": "सिमसार", "en": "Wetland"},
    "Water body": {"ne": "जलाशय", "en": "Water body"},
    "Barren / Rock": {"ne": "बाँझो / चट्टान", "en": "Barren / Rock"},
    "Built-up": {"ne": "बस्ती / संरचना", "en": "Built-up"},
    "Snow / Glacier": {"ne": "हिउँ / हिमनदी", "en": "Snow / Glacier"},
    "Other": {"ne": "अन्य", "en": "Other"},
}


def normalize_lc1984(raw: str | None) -> str | None:
    """Canonical class for a raw ``landuse_yr1984`` value, or ``None`` to drop
    (blank / unknown-and-empty)."""
    if not raw:
        return None
    key = raw.strip().lower()
    if not key:
        return None
    return _RAW_TO_CANON.get(key, "Other")


def lc1984_color(canon: str) -> str:
    return LC1984_COLORS.get(canon, LC1984_COLORS["Other"])


def lc1984_label(canon: str, lang: str = "en") -> str:
    return LC1984_LABELS.get(canon, {}).get(lang, canon)
