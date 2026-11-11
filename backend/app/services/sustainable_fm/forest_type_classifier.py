"""Auto-propose one of the 14 अनुसूची-१ forest types for a block (P2).

``SUSTAINABLE_FOREST_MANAGEMENT_PLAN.md`` §5 P2 (refining research §4.5).

Input: a :class:`ZoneResult` (P1 ``zone_classifier``) + :class:`SfmBlockInputs`
(P1 ``species_assemblage``). Output: ``proposed_type_no`` + a confidence + a
``needs_review`` flag + short bilingual ``reasons``. The user overrides this in
the SFM tab (P4); everything downstream reads ``effective_type_no``.

Pure — no DB, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.services.sustainable_fm.sfm_config import SfmParams
from app.services.sustainable_fm.species_assemblage import SfmBlockInputs
from app.services.sustainable_fm.zone_classifier import ZoneResult

# Types the guideline manages as protection / restoration (no regular harvest).
PROTECTION_TYPES = frozenset({3, 6})
# Types where slope band 4 (> 45°) forces a salvage-only stratum -- अनुसूची-१'s
# own explicit wording for these four. Band 4 now forces Conservation for
# EVERY type (owner decision, 2026-09-14 -- SLOPE45_PROTECTION_TYPES is kept
# only to distinguish "guideline states this by name" from "system policy
# extends it" in orientation.py's reason text; it is no longer a gate).
SLOPE45_PROTECTION_TYPES = frozenset({8, 9, 10, 13})
# सि.नं. १२'s अनुसूची-१ objective cell reads as self-contradictory in the
# source scan on its own ("erosion-sensitive, संरक्षणलाई प्राथमिकता"
# immediately followed by a mismatched "(Production Oriented)" tag; verified
# against the original scan page, 2026-09-14) -- RESOLVED 2026-09-15: the
# owner consulted the responsible official directly, who confirmed सि.नं. १२
# is Production Oriented, matching its own harvest table (>200 m³/ha -> 1%,
# <200 m³/ha -> 0.5%, seed_sfm_prescriptions.py type_no=12) and the
# parenthetical tag, not the Nepali prose. Not ambiguous; kept as plain
# Production with no slope-band-3 override (the band-4 general policy in
# orientation.py still applies to it like every other type).
#
# This set stays empty and the machinery below stays wired (band 3 resolves
# a type in this set toward Conservation) purely in case a genuinely
# contested type turns up elsewhere in अनुसूची-१ later -- do not add सि.नं.
# १२ back without a new, equally concrete resolution.
AMBIGUOUS_ORIENTATION_TYPES: frozenset[int] = frozenset()

_PINE_GROUPS = frozenset({"PINE_ROX", "PINE_WALL", "PINE_PATULA"})
_BROADLEAF_GROUPS = frozenset(
    {"HILL_BROADLEAF", "TEMPERATE_BROADLEAF", "RIVERINE_ASSOC"}
)

# Confidence bands.
_C_STRONG = 0.85
_C_GOOD = 0.75
_C_FAIR = 0.6
_C_WEAK = 0.55
_C_FALLBACK = 0.35
_REVIEW_BELOW = 0.5

# Nepali names for the reason string (short forms).
_ZONE_NE = {
    "LOWLAND_SAL": "तराई/चुरे",
    "HILL": "पहाड",
    "TEMPERATE": "शितोष्ण",
    "HIGH_MOUNTAIN": "उच्च पहाड",
}
_GROUP_NE = {
    "SAL": "साल",
    "SISSOO_KHAIR": "सिसौ/खयर",
    "RIVERINE_ASSOC": "नदीतटीय प्रजाति",
    "PINE_ROX": "खोटे सल्ला",
    "PINE_WALL": "गोब्रे सल्ला",
    "PINE_PATULA": "पाटे सल्ला",
    "HILL_BROADLEAF": "पहाडी चौडापाते",
    "TEMPERATE_BROADLEAF": "शितोष्ण चौडापाते",
    "TEMPERATE_CONIFER": "शितोष्ण कोणधारी",
}

# rule 9 fallback: (dominant_group, sfm_zone) → type_no.
_FALLBACK: dict[tuple[Optional[str], str], int] = {
    ("SAL", "LOWLAND_SAL"): 1,
    ("SAL", "HILL"): 7,
    ("SAL", "TEMPERATE"): 7,
    ("SISSOO_KHAIR", "LOWLAND_SAL"): 5,
    ("RIVERINE_ASSOC", "LOWLAND_SAL"): 5,
    ("HILL_BROADLEAF", "HILL"): 11,
    ("HILL_BROADLEAF", "TEMPERATE"): 12,
    ("TEMPERATE_BROADLEAF", "TEMPERATE"): 12,
    ("TEMPERATE_BROADLEAF", "HILL"): 11,
    ("TEMPERATE_CONIFER", "HIGH_MOUNTAIN"): 13,
    ("TEMPERATE_CONIFER", "TEMPERATE"): 13,
}
_FALLBACK_BY_ZONE = {
    "LOWLAND_SAL": 1,
    "HILL": 11,
    "TEMPERATE": 12,
    "HIGH_MOUNTAIN": 13,
}


@dataclass(frozen=True)
class ClassifyResult:
    proposed_type_no: int
    confidence: float
    needs_review: bool
    reasons_ne: str
    reasons_en: str


def _dominant_band_share(zone: ZoneResult) -> float:
    return float(zone.slope_band_area_pct.get(zone.slope_band, 0.0))


def _reasons(
    inp: SfmBlockInputs, zone: ZoneResult, type_no: int, extra_ne: str, extra_en: str
) -> tuple[str, str]:
    parts_ne: list[str] = []
    parts_en: list[str] = []
    if inp.dominant_group and inp.dominant_species:
        top = inp.dominant_species[0]
        g_ne = _GROUP_NE.get(inp.dominant_group, inp.dominant_group)
        parts_ne.append(f"{g_ne} प्रधान ({top.share_pct:.0f}%)")
        parts_en.append(f"{inp.dominant_group} dominant ({top.share_pct:.0f}%)")
    elif inp.dominant_group:
        parts_ne.append(
            f"{_GROUP_NE.get(inp.dominant_group, inp.dominant_group)} प्रधान"
        )
        parts_en.append(f"{inp.dominant_group} dominant")
    if zone.dom_phys:
        parts_ne.append(_ZONE_NE.get(zone.sfm_zone, zone.sfm_zone))
        parts_en.append(zone.dom_phys)
    if zone.sfm_zone == "LOWLAND_SAL" and inp.dominant_group == "SAL":
        parts_ne.append(f"भिरालो वर्ग {zone.slope_band}")
        parts_en.append(f"slope band {zone.slope_band}")
    if extra_ne:
        parts_ne.append(extra_ne)
        parts_en.append(extra_en)
    parts_ne.append(f"→ सि.नं. {type_no}")
    parts_en.append(f"→ type {type_no}")
    return " · ".join(parts_ne), " · ".join(parts_en)


def classify(
    zone: ZoneResult, inp: SfmBlockInputs, params: SfmParams
) -> ClassifyResult:
    """The decision tree. First matching rule wins; rule 9 always returns
    something with ``needs_review=True``."""
    g = inp.dominant_group
    band_share = _dominant_band_share(zone)

    # 1 — degraded तराई / भित्री मधेश (crown density < 20 %)
    if inp.crown_density_pct < 20 and zone.sfm_zone == "LOWLAND_SAL" and g == "SAL":
        conf = 0.8 if inp.invasive_present else _C_FAIR
        extra_ne = "छत्र घनत्व < २०%" + (" · मिचाहा" if inp.invasive_present else "")
        extra_en = "crown density < 20%" + (
            " · invasives" if inp.invasive_present else ""
        )
        return _mk(6, conf, inp, zone, extra_ne, extra_en)

    # 2 — riverine
    if inp.riparian and g in {"SISSOO_KHAIR", "RIVERINE_ASSOC"}:
        return _mk(5, _C_GOOD, inp, zone, "नदी नजिक", "near a river")

    # 3 — Sal
    if g == "SAL":
        if zone.sfm_zone == "LOWLAND_SAL":
            type_no = {1: 1, 2: 2, 3: 3, 4: 3}[zone.slope_band]
            conf = _C_STRONG if band_share >= 60.0 else _C_FAIR
            return _mk(type_no, conf, inp, zone, "", "")
        if zone.sfm_zone in {"HILL", "TEMPERATE"}:
            return _mk(7, _C_GOOD, inp, zone, "", "")

    # 4 — sissoo / khair plantation
    if g == "SISSOO_KHAIR" and inp.origin == "plantation":
        return _mk(4, 0.8, inp, zone, "वृक्षारोपण", "plantation")

    # 5 — pines
    if g in _PINE_GROUPS:
        if inp.conversion_target:
            return _mk(
                14, 0.9, inp, zone, "रूपान्तरणका लागि छानिएको", "flagged for conversion"
            )
        if inp.origin == "plantation":
            return _mk(9, 0.8, inp, zone, "वृक्षारोपण", "plantation")
        if inp.codominant_group in _BROADLEAF_GROUPS:
            return _mk(
                10, _C_WEAK, inp, zone, "चौडापातेसँग मिश्रित", "mixed with broadleaf"
            )
        return _mk(8, 0.8, inp, zone, "प्राकृतिक", "natural")

    # 6 — hill broadleaf
    if g == "HILL_BROADLEAF" and zone.sfm_zone == "HILL":
        return _mk(11, _C_GOOD - 0.05, inp, zone, "", "")

    # 7 — temperate broadleaf
    if g == "TEMPERATE_BROADLEAF" and _in_range(zone.mean_altitude_m, 1800.0, 3000.0):
        return _mk(12, 0.65, inp, zone, "", "")

    # 8 — temperate conifer
    if g == "TEMPERATE_CONIFER" and (zone.mean_altitude_m or 0.0) >= 2400.0:
        return _mk(13, _C_GOOD - 0.05, inp, zone, "", "")

    # 9 — fallback
    type_no = _FALLBACK.get((g, zone.sfm_zone)) or _FALLBACK_BY_ZONE.get(
        zone.sfm_zone, 1
    )
    reasons_ne, reasons_en = _reasons(
        inp, zone, type_no, "नजिकको मिलान", "nearest match"
    )
    return ClassifyResult(
        proposed_type_no=type_no,
        confidence=_C_FALLBACK,
        needs_review=True,
        reasons_ne=reasons_ne,
        reasons_en=reasons_en,
    )


def _in_range(v: Optional[float], lo: float, hi: float) -> bool:
    return v is not None and lo <= v <= hi


def _mk(
    type_no: int,
    conf: float,
    inp: SfmBlockInputs,
    zone: ZoneResult,
    extra_ne: str,
    extra_en: str,
) -> ClassifyResult:
    # a prior-only (no inventory) proposal is always advisory
    review = conf < _REVIEW_BELOW or inp.source == "prior"
    reasons_ne, reasons_en = _reasons(inp, zone, type_no, extra_ne, extra_en)
    return ClassifyResult(
        proposed_type_no=type_no,
        confidence=round(conf, 2),
        needs_review=review,
        reasons_ne=reasons_ne,
        reasons_en=reasons_en,
    )


__all__ = [
    "PROTECTION_TYPES",
    "SLOPE45_PROTECTION_TYPES",
    "AMBIGUOUS_ORIENTATION_TYPES",
    "ClassifyResult",
    "classify",
]
