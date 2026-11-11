"""The NTFP inventory as the operational plan sees it: table ``table_39`` (alias ``ntfp_inventory``) and the narrative ``section:ntfp_inventory``.

Source: ``ntfp_analysis_service.results`` (the stored design and the field records). Optional like the page it comes from: with no NTFP survey, or
no record yet, ``available`` is False and the table and the narrative say nothing: a template that does not use them renders exactly as before.

Numbers come out as Devanagari text (the table builder keeps a string with Devanagari digits as it is). An estimated price is not used here; this
table is about what the forest holds.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.ntfp_schedule7 import GROUPS
from app.utils.number_format import format_devanagari as fmt

logger = logging.getLogger(__name__)

_WARN_NE = {
    "few_plots": "सर्वेक्षण प्लट थोरै", "survey_incomplete": "सर्वेक्षण अपूर्ण", "not_found": "भेटिएन", "no_weights": "तौल लिइएको छैन",
    "no_dry_weights": "सुक्खा तौल छैन", "few_samples": "नमूना थोरै", "cf_differs_from_guideline": "रूपान्तरण गुणक मार्गदर्शनको भन्दा फरक",
}
_FEW = ("few_plots", "survey_incomplete", "not_found", "no_weights", "no_dry_weights", "few_samples", "cf_differs_from_guideline")


def _part_ne(group) -> str:
    return GROUPS[group][0].replace(" जाति", "") if group in GROUPS else "-"


def _n(x, d: int = 1) -> str:
    return "-" if x is None else fmt(x, d)


def _pair(a, b, d: int = 1) -> str:
    """``ताजा / सुक्खा``: fresh and dry figures in one cell; a missing dry figure stays a dash."""
    return f"{_n(a, d)} / {_n(b, d)}" if a is not None else "-"


def build_rows(results: Dict[str, Any]) -> List[Dict[str, str]]:
    """One row per (surveyed species, part weighed); a species with no weights gets one row with dashes for the weights."""
    rows: List[Dict[str, str]] = []
    sn = 0
    for sp in results["species"]:
        if not sp["plots_surveyed"]:
            continue
        name = sp.get("nepali_name") or sp["label"]
        if sp.get("scientific_name"):
            name = f"{name} ({sp['scientific_name']})"
        base = {
            "name": name, "plots": f"{fmt(sp['plots_surveyed'], 0)} / {fmt(sp['plots_present'], 0)}", "frequency": _n(sp["frequency_pct"], 1),
            "density": _n(sp["density_per_ha"], 1), "ivi": _n(sp["ivi"], 1),
        }
        parts = sp["parts"] or [None]
        for part in parts:
            sn += 1
            warns = list(sp["warnings"]) + (part["warnings"] if part else [])
            note = "; ".join(_WARN_NE[w] for w in dict.fromkeys(warns) if w in _WARN_NE)
            if part and part.get("price", {}).get("estimated"):
                note = (note + "; " if note else "") + "मूल्य दर अनुमानित"
            rows.append({
                "sn": fmt(sn, 0), **base, "part": _part_ne(part["part_group"]) if part else "-",
                "yield": _pair(part["yield_fresh_kg_ha"], part["yield_dry_kg_ha"]) if part else "-",
                "stock": _pair(part["stock_fresh_kg"], part["stock_dry_kg"], 0) if part else "-", "note": note,
            })
    return rows


def summary(results: Dict[str, Any]) -> Dict[str, Any]:
    surveyed = [s for s in results["species"] if s["plots_surveyed"]]
    ranked = sorted((s for s in surveyed if s["ivi"] is not None), key=lambda s: -s["ivi"])
    return {
        "species_designed": len(results["species"]), "species_surveyed": len(surveyed), "plots_in_design": results["plots_in_design"],
        "plots_recorded": results["survey"]["pairs_recorded"], "top": [{"name": s.get("nepali_name") or s["label"], "ivi": s["ivi"]} for s in ranked[:3]],
    }


def get_ntfp_inventory_data(db: Session, calculation_id) -> Dict[str, Any]:
    """``{available, table_rows, summary}``; ``{"available": False}`` when there is no design or no record."""
    from app.models.calculation import Calculation
    from app.services import ntfp_analysis_service as analysis_svc
    from app.services.ntfp_design_service import DesignError

    calc_id = UUID(str(calculation_id))
    calc = db.get(Calculation, calc_id)
    if calc is None:
        return {"available": False}
    try:
        results = analysis_svc.results(db, calc)
    except DesignError:
        return {"available": False}
    if not results["survey"]["pairs_recorded"]:
        return {"available": False}
    return {"available": True, "table_rows": build_rows(results), "summary": summary(results), "ivi_parts": results["ivi_parts"]}


def narrative(inv: Dict[str, Any]) -> str | None:
    """The paragraph for ``section:ntfp_inventory`` (Nepali), or None when there is no survey."""
    if not inv or not inv.get("available"):
        return None
    s = inv["summary"]
    top = ", ".join(f"{t['name']} ({fmt(t['ivi'], 1)})" for t in s["top"])
    text = (
        f"यस वनमा गैरकाष्ठ वन पैदावारको स्रोत सर्वेक्षण मार्गदर्शन, २०६९ अनुसार नमूना प्लट स्थापना गरी {fmt(s['species_surveyed'], 0)} प्रजातिको "
        f"सर्वेक्षण गरिएको छ। जम्मा {fmt(s['plots_in_design'], 0)} प्लटमध्ये {fmt(s['plots_recorded'], 0)} प्लट-प्रजाति जोडीको अभिलेख प्राप्त भएको छ। "
    )
    if top:
        text += f"आवृत्ति र घनत्वमा आधारित महत्त्व मूल्य सूचकाङ्क (IVI) सबैभन्दा बढी भएका प्रजातिहरू: {top}। "
    text += "प्रजातिगत आवृत्ति, घनत्व, उत्पादन र मौज्दात तालिकामा दिइएको छ।"
    return text
