"""FEATURE_KIND — controlled vocabulary + symbology for ``ActivityDrawnFeature``.

THEMATIC_MAP_VARIABLES_PLAN §3.4B / Appendix C.6 / P7. ``properties.kind`` on a
drawn feature is free text today; this module is the single source of truth for
the canonical kinds, a best-effort alias map from the free text seen in the
wild, and the matplotlib symbol each kind renders with on an ``opsmap`` map.

No enum column / migration — ``kind`` stays a JSON convention. The frontend
activity-drawing UI should offer :data:`CANONICAL_KINDS` as a picker (owed);
until it does, :func:`resolve_kind` maps whatever text is stored.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureStyle:
    geom: str  # "point" | "line" | "polygon" | "any"
    marker: str  # matplotlib marker (point) — "" otherwise
    linestyle: str  # matplotlib linestyle (line/polygon edge)
    size: float  # marker size (pt) or line width (px)
    color: str
    hatch: str
    alpha: float
    label_ne: str
    label_en: str
    zorder: int


def _p(marker, size, color, ne, en, *, z=8):  # point
    return FeatureStyle("point", marker, "None", size, color, "", 1.0, ne, en, z)


def _l(ls, width, color, ne, en, *, z=6):  # line
    return FeatureStyle("line", "", ls, width, color, "", 1.0, ne, en, z)


def _poly(hatch, alpha, color, ne, en, *, ls="-", z=4):  # polygon
    return FeatureStyle("polygon", "", ls, 1.0, color, hatch, alpha, ne, en, z)


# ── the C.6 table — canonical kinds (z-order rises down the table) ────────
KINDS: dict[str, FeatureStyle] = {
    "coupe": _poly("", 0.55, "#e6550d", "कटान क्षेत्र", "Coupe / felling area", z=3),
    "plantation": _poly("\\\\", 0.35, "#10b981", "रोपण क्षेत्र", "Planting / enrichment"),
    "anr_area": _poly("..", 0.30, "#84cc17", "प्राकृतिक पुनरुत्पादन", "ANR area"),
    "grazing_closure": _poly("xx", 0.30, "#b08968", "चरन बन्द", "Grazing closure"),
    "biodiversity_block": _poly(
        "", 0.35, "#06b6d4", "जैविक विविधता", "Biodiversity block"
    ),
    "water_source_protection": _poly(
        "", 0.40, "#0ea5e9", "मूल संरक्षण क्षेत्र", "Water-source protection"
    ),
    "wildlife_corridor": _poly("//", 0.30, "#a855f7", "जैविक मार्ग", "Wildlife corridor"),
    "ntfp_zone": _poly("oo", 0.28, "#8a6d3b", "गैरकाष्ठ वन पैदावार क्षेत्र", "NTFP zone"),
    "propoor_plot": _poly("++", 0.32, "#f59e0b", "विपन्न वर्ग भूखण्ड", "Pro-poor plot"),
    "agroforestry_area": _poly("--", 0.30, "#65a30d", "कृषिवन क्षेत्र", "Agroforestry"),
    "silviculture_area": _poly("||", 0.30, "#0f766e", "वन सम्बर्दन क्षेत्र", "Silviculture area"),
    "encroachment": FeatureStyle(
        "polygon",
        "",
        "-",
        1.5,
        "#c62828",
        "xx",
        0.0,
        "अतिक्रमण",
        "Encroachment",
        4,
    ),
    "river_bank": _poly("", 0.45, "#1e40af", "खोला किनार (संरक्षण क्षेत्र)", "River bank (protection area)", z=5),
    "road": _l("-", 2.6, "#8d5524", "नयाँ बाटो", "Road / track"),
    "trail": _l("--", 1.6, "#8d5524", "गोरेटो", "Trail / footpath"),
    "fire_line": _l((0, (6, 3)), 2.0, "#c62828", "आगो नियन्त्रण रेखा", "Fire line"),
    "patrol_route": _l(":", 1.8, "#6a1b9a", "गस्ती मार्ग", "Patrol route"),
    "nursery": _p("*", 13, "#2e7d32", "नर्सरी", "Nursery", z=9),
    "depot": _p("s", 9, "#795548", "डिपो", "Timber depot"),
    "check_post": _p("^", 10, "#1565c0", "चेकपोस्ट", "Check / guard post"),
    "fire_tower": _p("^", 11, "#c62828", "अग्नि टावर", "Fire / view tower", z=9),
    "water_hole": _p("o", 8, "#0ea5e9", "पानी पोखरी", "Water hole / pond"),
    "signboard": _p("P", 8, "#616161", "सूचना पाटी / सीमा स्तम्भ", "Signboard / marker"),
    "seed_stand": _p("X", 9, "#33691e", "बीउ रूख", "Seed stand / mother tree"),
    "ecotourism_site": _p("D", 8, "#ec4899", "पर्यापर्यटन स्थल", "Ecotourism site"),
    "religious_cultural": _p("p", 9, "#8b5cf6", "धार्मिक स्थल", "Religious / cultural"),
    "permanent_sample_plot": _p("o", 9, "#08519c", "स्थायी नमूना प्लट", "Permanent plot"),
    "monitoring_point": _p("o", 7, "#3182bd", "अनुगमन बिन्दु", "Monitoring point"),
    "community_infrastructure": _p("h", 9, "#475569", "सामुदायिक संरचना", "Community infrastructure"),
}

# free-text → canonical
ALIASES: dict[str, str] = {
    "felling_area": "coupe",
    "felling": "coupe",
    "harvest_area": "coupe",
    "coupe_area": "coupe",
    "enrichment": "plantation",
    "planting": "plantation",
    "plantation_area": "plantation",
    "enrichment_planting": "plantation",
    "anr": "anr_area",
    "natural_regeneration": "anr_area",
    "grazing_close": "grazing_closure",
    "grazing_closed": "grazing_closure",
    "rotational_grazing": "grazing_closure",
    "biodiversity": "biodiversity_block",
    "conservation_block": "biodiversity_block",
    "water_source": "water_source_protection",
    "spring_protection": "water_source_protection",
    "corridor": "wildlife_corridor",
    "ntfp": "ntfp_zone",
    "ntfp_area": "ntfp_zone",
    "fodder_zone": "ntfp_zone",
    "grass_zone": "ntfp_zone",
    "resin_zone": "ntfp_zone",
    "propoor": "propoor_plot",
    "pro_poor": "propoor_plot",
    "pro-poor": "propoor_plot",
    "agroforestry": "agroforestry_area",
    "track": "road",
    "forest_road": "road",
    "new_road": "road",
    "footpath": "trail",
    "foot_trail": "trail",
    "path": "trail",
    "fire_break": "fire_line",
    "firebreak": "fire_line",
    "fireline": "fire_line",
    "patrol": "patrol_route",
    "ranger_route": "patrol_route",
    "nursery_site": "nursery",
    "timber_depot": "depot",
    "collection_point": "depot",
    "guard_post": "check_post",
    "checkpost": "check_post",
    "view_tower": "fire_tower",
    "lookout_tower": "fire_tower",
    "pond": "water_hole",
    "waterhole": "water_hole",
    "boundary_marker": "signboard",
    "boundary_pillar": "signboard",
    "sign_board": "signboard",
    "mother_tree_reserve": "seed_stand",
    "mother_tree": "seed_stand",
    "seed_source": "seed_stand",
    "ecotourism": "ecotourism_site",
    "tourism_site": "ecotourism_site",
    "religious_site": "religious_cultural",
    "cultural_site": "religious_cultural",
    "psp": "permanent_sample_plot",
    "permanent_plot": "permanent_sample_plot",
    "photo_point": "monitoring_point",
    "monitoring": "monitoring_point",
}

GENERIC: dict[str, FeatureStyle] = {
    "point": _p("o", 6, "#616161", "अन्य बिन्दु", "Other point", z=7),
    "line": _l("-.", 1.4, "#616161", "अन्य रेखा", "Other line", z=5),
    "polygon": _poly("//", 0.25, "#616161", "अन्य क्षेत्र", "Other area", z=3),
}

CANONICAL_KINDS = tuple(KINDS)


def _norm(raw: str | None) -> str:
    return (raw or "").strip().lower().replace(" ", "_").replace("-", "_")


def resolve_kind(raw: str | None, feature_type: str) -> str:
    """Canonical kind for a stored ``properties.kind`` (or ``""`` for the
    generic marker of *feature_type*: point / line / polygon)."""
    k = _norm(raw)
    if k in KINDS:
        return k
    if k in ALIASES:
        return ALIASES[k]
    return ""  # → GENERIC[feature_type] via style_for


def resolve_feature_kind(feature_kind: str | None, activity_kind: str | None, feature_type: str) -> str:
    """The kind a drawn feature is symbolised as: its own ``properties.kind`` if that names one (the user's explicit choice, kept
    whatever the shape), else the default of the activity it belongs to (``potential_activities.map_kind``), else ``""``
    (the generic point / line / polygon symbol).

    An activity may be drawn in another shape than its kind's own (owner, 2026-10-15: block marking is a line though a signboard is a
    point); its default symbol is then not pasted on the other shape - the generic symbol of the shape is used instead.
    """
    own = resolve_kind(feature_kind, feature_type)
    if own:
        return own
    default = resolve_kind(activity_kind, feature_type)
    shape = (feature_type or "").lower()
    if default and KINDS[default].geom not in ("any", shape) and shape in ("point", "line", "polygon"):
        return ""
    return default


def style_for(kind: str, feature_type: str) -> FeatureStyle:
    if kind in KINDS:
        return KINDS[kind]
    ft = (feature_type or "").lower()
    if ft in ("point", "line", "polygon"):
        return GENERIC[ft]
    return GENERIC["point"]


__all__ = [
    "FeatureStyle",
    "KINDS",
    "ALIASES",
    "GENERIC",
    "CANONICAL_KINDS",
    "resolve_kind",
    "resolve_feature_kind",
    "style_for",
]
