"""Adaptive NE / EN narration for the SFM section (P3; polished in P9).

``SUSTAINABLE_FOREST_MANAGEMENT_PLAN.md`` §5 P3.

Three blocks — methodology / findings / prescription — built from the assembled
``result_data['sfm']`` dict. Pure string assembly, no DB.
"""

from __future__ import annotations

from typing import Any

_NE = "ne"
_EN = "en"


def _fmt(n: Any, unit: str = "") -> str:
    try:
        return f"{float(n):,.1f}{unit}"
    except (TypeError, ValueError):
        return "—"


def _has_inner_terai(sfm: dict[str, Any]) -> bool:
    return any(
        (z or {}).get("inner_terai")
        for z in (sfm.get("zone_by_block", {}) or {}).values()
    )


def _has_protection_series(sfm: dict[str, Any]) -> bool:
    """A protection-stratum felling-series row — 0 harvest sitting on 0 area
    (its hectares live in ``protection_area_ha``, not the series)."""
    return any(
        s.get("annual_harvest_m3") == 0.0 and s.get("area_ha") == 0.0
        for s in (sfm.get("felling_series", []) or [])
    )


def methodology(sfm: dict[str, Any]) -> dict[str, str]:
    src = sfm.get("source", "prior")
    if not (sfm.get("blocks") or []):
        return {
            _NE: "यस वनको कुनै खण्ड/कम्पार्टमेन्ट वर्गीकृत भएको छैन।",
            _EN: "No block / compartment of this forest has been classified.",
        }
    src_ne = {
        "stem_mapping": "रुख नक्साङ्कन (पूर्ण गणना)",
        "field_inventory": "क्षेत्र इन्भेन्ट्री (नमुना प्लट)",
        "prior": "पूर्व अनुमान (इन्भेन्ट्री नभएको)",
        "mixed": "मिश्रित स्रोत",
    }.get(src, src)
    src_en = {
        "stem_mapping": "stem mapping (full census)",
        "field_inventory": "field inventory (sample plots)",
        "prior": "prior estimate (no inventory)",
        "mixed": "mixed sources",
    }.get(src, src)
    ne = (
        "प्रत्येक खण्ड/कम्पार्टमेन्टलाई दिगो वन व्यवस्थापन कार्यविधि, २०७९ अनुसूची-१ का "
        "१४ वन प्रकारमध्ये एकमा वर्गीकरण गरिएको छ — भौगोलिक अवस्था (भौतिक भू-दृश्य), "
        f"भिरालो वर्ग (< १९° / १९–३१° / ३१–४५° / > ४५°) र मुख्य प्रजाति ({src_ne}) का आधारमा। "
        "उत्पादन नियमन छाती व्यास ≥ ४० से.मि. का रुखको जम्मा मौज्दातमा आधारित छ; "
        "औसत वार्षिक वृद्धि (MAI) प्रयोग गरिएको छैन। यो परिमाण कटान श्रृंखला "
        "(एउटै वन प्रकारका खण्डहरूको समूह) अनुसार गणना गरिएको हो।"
    )
    en = (
        "Each block / compartment is classified into one of the 14 forest types of "
        "अनुसूची-१ of the Sustainable Forest Management Procedure, 2079, from its "
        "physiography, slope band (< 19° / 19–31° / 31–45° / > 45°) and dominant "
        f"species ({src_en}). Yield is regulated on the growing stock of trees "
        "≥ 40 cm DBH — Mean Annual Increment is not used. The figure is computed "
        "per felling series (blocks of the same forest type)."
    )
    if src in ("field_inventory", "mixed"):
        ne += (
            " क्षेत्र इन्भेन्ट्रीमा व्यास वर्गको सीमा ४० से.मि.मा नपर्ने हुँदा ≥ ४० से.मि. "
            "मौज्दात व्यास-वर्ग वितरणबाट अनुमानित हो।"
        )
        en += (
            " With sample-plot data the DBH classes do not fall exactly on the "
            "40 cm boundary, so the ≥ 40 cm growing stock is estimated from the "
            "DBH-class distribution."
        )
    if _has_inner_terai(sfm):
        ne += (
            " केही एकाइ भित्री मधेशमा पर्छन् (चुरे र मधेश बीच); अनुसूची-१ ले तराई र "
            "भित्री मधेशलाई उस्तै व्यवहार गर्ने हुँदा यसले प्रिस्क्रिप्सन बदल्दैन।"
        )
        en += (
            " Some units fall in the Inner Terai (between the Chure and the "
            "Madhesh); अनुसूची-१ treats Terai and Inner Terai identically, so this "
            "does not change the prescription."
        )
    return {_NE: ne, _EN: en}


def findings(sfm: dict[str, Any]) -> dict[str, str]:
    summ = sfm.get("forest_summary", {}) or {}
    blocks = sfm.get("blocks", []) or []
    series = sfm.get("felling_series", []) or []
    if not blocks:
        return {
            _NE: "वर्गीकरण नबनेकोले कुनै नतिजा उपलब्ध छैन।",
            _EN: "No findings — the classification has not been built.",
        }
    n_types = len({b.get("effective_type_no") for b in blocks if b.get("effective_type_no") is not None})
    dom = summ.get("dominant_type_no")
    prod = summ.get("production_area_ha", 0.0)
    prot = summ.get("protection_area_ha", 0.0)
    total = summ.get("total_annual_harvest_m3", 0.0)
    n_review = sum(1 for b in blocks if b.get("needs_review"))

    ne = (
        f"वनमा {len(blocks)} एकाइ, {n_types} वन प्रकार पहिचान भए (प्रमुख: सि.नं. {dom})। "
        f"उत्पादनशील क्षेत्रफल {_fmt(prod, ' हे.')}, संरक्षण क्षेत्रफल {_fmt(prot, ' हे.')}। "
        f"{len([s for s in series if s.get('annual_harvest_m3') is not None])} कटान श्रृंखलाबाट "
        f"जम्मा वार्षिक स्वीकार्य कटान परिमाण {_fmt(total, ' घन.मी.')}।"
    )
    en = (
        f"{len(blocks)} units, {n_types} forest types (dominant: type {dom}). "
        f"Production area {_fmt(prod, ' ha')}, protection area {_fmt(prot, ' ha')}. "
        f"Total allowable annual harvest across {len([s for s in series if s.get('annual_harvest_m3') is not None])} "
        f"felling series: {_fmt(total, ' m³')}."
    )
    if n_review:
        ne += f" {n_review} एकाइको वर्गीकरण पुनरावलोकन आवश्यक।"
        en += f" {n_review} unit(s) need classification review."
    if _has_protection_series(sfm):
        ne += " संरक्षण कार्य वृत्तमा परेका एकाइमा नियमित कटान शून्य (सल्भेज बाहेक)।"
        en += (
            " Units in the protection working circle carry zero regular harvest "
            "(salvage only)."
        )
    if sfm.get("source") == "prior":
        ne += " इन्भेन्ट्री नभएकोले प्रिस्क्रिप्सन सूचक मात्र हो।"
        en += " Without an inventory the prescription is indicative only."
    return {_NE: ne, _EN: en}


def prescription(sfm: dict[str, Any]) -> dict[str, str]:
    series = sfm.get("felling_series", []) or []
    lines_ne: list[str] = []
    lines_en: list[str] = []
    for s in series:
        t = s.get("type_no")
        if s.get("annual_harvest_m3") == 0.0 and s.get("area_ha") == 0.0:
            lines_ne.append(f"सि.नं. {t}: संरक्षणमुखी — सल्भेज कटान मात्र।")
            lines_en.append(f"Type {t}: protection — salvage felling only.")
            continue
        cyc = s.get("C") or s.get("R")
        cyc_ne = f"कटान चक्र {cyc} वर्ष" if s.get("C") else f"पुनरोत्पादन अवधि {cyc} वर्ष"
        cyc_en = (
            f"felling cycle {cyc} yr" if s.get("C") else f"regeneration period {cyc} yr"
        )
        h = s.get("annual_harvest_m3")
        if h is not None:
            lines_ne.append(
                f"सि.नं. {t}: {cyc_ne}, {s.get('N')} कटान क्षेत्र; "
                f"वार्षिक कटान ~{_fmt(h, ' घन.मी.')}"
                + (f" (मौज्दातको {s.get('pct')}%)" if s.get("pct") else "")
                + "।"
            )
            lines_en.append(
                f"Type {t}: {cyc_en}, {s.get('N')} felling areas; "
                f"annual harvest ~{_fmt(h, ' m³')}"
                + (f" ({s.get('pct')}% of growing stock)" if s.get("pct") else "")
                + "."
            )
        else:
            lines_ne.append(
                f"सि.नं. {t}: रुख संख्यामा आधारित नियमन "
                f"(लक्षित {s.get('note_ne') or 'बाँकी रुख/हे.'})।"
            )
            lines_en.append(
                f"Type {t}: stem-count regulation ({s.get('note_en') or ''})."
            )
    if not lines_ne:
        lines_ne.append("कुनै कटान श्रृंखला छैन।")
        lines_en.append("No felling series.")
    if _has_protection_series(sfm):
        lines_ne.append("संरक्षण कार्य वृत्त — कटान शून्य।")
        lines_en.append("Protection working circle — zero harvest.")
    return {_NE: " ".join(lines_ne), _EN: " ".join(lines_en)}


def all_blocks(sfm: dict[str, Any]) -> dict[str, dict[str, str]]:
    return {
        "methodology": methodology(sfm),
        "findings": findings(sfm),
        "prescription": prescription(sfm),
    }


__all__ = ["methodology", "findings", "prescription", "all_blocks"]
