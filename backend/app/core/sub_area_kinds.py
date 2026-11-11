"""Sub-area kinds that are strips, not zones (FIRELINE_RIVERBANK_PLAN.md).

A sub-area is a zone: the zones partition the land by use and may not overlap. A strip (today the fire line, later the river
bank) is a protective feature laid ACROSS those zones, so it is stored as a sub-area entry (``result_data['sub_areas']``) with
its own category but follows different rules: it may overlap anything, it is built by the strip service rather than picked
from the category list, and it is kept out of every consumer that reads sub-area outlines.

``SubAreaCategory.catalog()`` stays the 13 categories a user can pick, import or paste. The strips are listed here and merged
only where something must RENDER them (palette, labels, layer styles). ``tests/core/test_sub_area_kinds.py`` keeps the
backend and frontend lists in agreement.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

FIRE_LINE = "fire_line"
RIVER_BANK = "river_bank"

#: category keys that are strips. A second kind is one more entry here and in STRIP_CATALOG.
STRIP_CATEGORIES = (FIRE_LINE, RIVER_BANK)

#: what counts as a protection area, i.e. NOT productive. The owner's `protected` zones, and the river bank (owner, 2026-10-19).
#: One definition: every place that asks "is this protection?" uses this, never `== "protected"`.
PROTECTION_SUB_AREA_CATEGORIES = ("protected", RIVER_BANK)

STRIP_CATALOG: List[Dict[str, Any]] = [
    {"key": FIRE_LINE, "label": "Fire line", "label_np": "अग्नी रेखा", "color": "#c62828", "is_excluded": False, "is_strip": True},
    {"key": RIVER_BANK, "label": "River bank", "label_np": "खोला किनार", "color": "#1e40af", "is_excluded": False, "is_strip": True},
]


def is_strip_category(category: Optional[str]) -> bool:
    return category in STRIP_CATEGORIES


def is_protection_category(category: Optional[str]) -> bool:
    return category in PROTECTION_SUB_AREA_CATEGORIES


def is_strip(sub_area: Dict[str, Any]) -> bool:
    """True for a ``result_data['sub_areas']`` entry that is a strip."""
    return is_strip_category((sub_area or {}).get("category"))


def zones_and_protection(sub_areas: Optional[Iterable[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """The zones plus the strips that are protection areas (the river bank). For the area figures: a fire line changes no area,
    a river bank takes its ground out of production."""
    return [sa for sa in (sub_areas or []) if not is_strip(sa) or is_protection_category(sa.get("category"))]


def real_sub_areas(sub_areas: Optional[Iterable[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """The zones: ``result_data['sub_areas']`` without its strips. Use this wherever sub-area outlines or counts are read."""
    return [sa for sa in (sub_areas or []) if not is_strip(sa)]
