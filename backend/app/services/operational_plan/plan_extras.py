"""Derived scalars and tables for the Rambhadevi-style operational plan ("plan extras").

Everything here is READ-ONLY and derived from data the system already holds (committee, households,
yearly plan, stem mapping, rasters, hydrology). Nothing new is asked of the user; where the data is
missing a value is simply absent (None / empty list) so the template shows nothing rather than a guess.

Entry point (called once from ``data_collector.collect_all_op_data``):

    collect_plan_extras(db, calculation_id, raw) -> dict     # stored as raw["plan_extras"]

Variables are registered in ``variable_registry`` with ``source="plan_extras"``.
RAMBHADEVI_SFM_RENEW_TEMPLATE_PLAN.md §4 lists what each one replaces in the printed plan.
"""

import logging
import re
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_DEV = str.maketrans("0123456789", "०१२३४५६७८९")
_ORDINAL_NE = ["प्रथम", "दोस्रो", "तेस्रो", "चौथो", "पाँचौं", "छैटौं", "सातौं", "आठौं", "नवौं", "दसौं"]

# Table-27 style groupings of activity names (plan lines are classified by the master-list wording)
_RE_PREPARATORY = re.compile(r"तयारी\s*कटान|preparatory", re.I)
_RE_THINNING = re.compile(r"थिनिङ|पत्ल्याउने|सुधार\s*कटान|एक्ल्याउने|thinning", re.I)
_RE_ENHANCE = re.compile(r"अभिवृद्धि|enhancement", re.I)
_RE_REGEN_FELLING = re.compile(r"वार्षिक\s*कार्यक्षेत्र|पुनरुत्पादन\s*कटान|regeneration\s*felling", re.I)
_RE_NOT_REGEN_FELLING = re.compile(r"क्षेत्रमा|पश्चात|अवशेष|तयारी|तारबार|आगलागी|अभिवृद्धि")


def _np(n: Any, nd: int = 0) -> str:
    try:
        return f"{float(n):.{nd}f}".translate(_DEV)
    except (TypeError, ValueError):
        return ""


def fy_labels(fy_start: Optional[str], years: int = 10) -> List[str]:
    """['२०८२/८३', '२०८३/८४', ...] from a first fiscal-year text such as '२०८२/०८३'; [] when unparseable."""
    if not fy_start:
        return []
    digits = str(fy_start).translate(str.maketrans("०१२३४५६७८९", "0123456789"))
    m = re.search(r"(\d{4})", digits)
    if not m:
        return []
    y = int(m.group(1))
    return [f"{y + i}/{(y + i + 1) % 100:02d}".translate(_DEV) for i in range(years)]


# ── committee ────────────────────────────────────────────────────────────────
def committee_scalars(raw: Dict[str, Any]) -> Dict[str, Any]:
    members = (raw.get("committees", {}).get("user_committee", {}) or {}).get("members", []) or []
    return {
        "uc_female_members": sum(1 for m in members if m.get("gender") == "महिला"),
        "uc_male_members": sum(1 for m in members if m.get("gender") == "पुरूष"),
    }


# ── households ───────────────────────────────────────────────────────────────
_PROSPERITY_ORDER = ["अति विपन्न", "अति बिपन्न", "विपन्न", "बिपन्न", "मध्यम", "सम्पन्न"]


def caste_prosperity_table(db: Session, calculation_id: str) -> List[Dict[str, Any]]:
    """Caste x prosperity household counts. Household rows only - a summary has no cross-tab (rule 2026-10-05:
    use ``household_aggregate.get_aggregate`` for totals; the cross-tab needs the rows)."""
    from app.models.household_information import HouseholdInformation

    rows = (
        db.query(HouseholdInformation.caste_classification_ne, HouseholdInformation.prosperity_level)
        .filter(HouseholdInformation.calculation_id == calculation_id)
        .all()
    )
    if not rows:
        return []
    levels = sorted({p or "मध्यम" for _, p in rows},
                    key=lambda p: _PROSPERITY_ORDER.index(p) if p in _PROSPERITY_ORDER else 99)
    grid: Dict[str, Dict[str, int]] = {}
    for caste, level in rows:
        grid.setdefault(caste or "अन्य", {}).setdefault(level or "मध्यम", 0)
        grid[caste or "अन्य"][level or "मध्यम"] += 1
    out = []
    for caste in sorted(grid):
        row: Dict[str, Any] = {"जातजाति": caste}
        for lv in levels:
            row[lv] = grid[caste].get(lv, 0)
        row["जम्मा"] = sum(grid[caste].values())
        out.append(row)
    total: Dict[str, Any] = {"जातजाति": "जम्मा"}
    for lv in levels:
        total[lv] = sum(r[lv] for r in out)
    total["जम्मा"] = sum(r["जम्मा"] for r in out)
    out.append(total)
    return out


# ── yearly plan lines ────────────────────────────────────────────────────────
def plan_lines(db: Session, calculation_id: str) -> List[Dict[str, Any]]:
    """One dict per (proposed activity, year): the yearly plan flattened for the derived tables."""
    from app.models.yearly_activities import ActivityYearDetail, PotentialActivity, ProposedYearlyActivity

    acts = db.query(ProposedYearlyActivity).filter(ProposedYearlyActivity.calculation_id == calculation_id).all()
    if not acts:
        return []
    pot = {p.id: p for p in db.query(PotentialActivity).filter(
        PotentialActivity.id.in_({a.potential_activity_id for a in acts})).all()}
    details: Dict[Any, Dict[int, Any]] = {}
    for yd in db.query(ActivityYearDetail).filter(
            ActivityYearDetail.proposed_activity_id.in_([a.id for a in acts])).all():
        details.setdefault(yd.proposed_activity_id, {})[yd.year_number] = yd
    block_names = {
        r[0]: r[1] for r in db.execute(
            text("SELECT id, block_name FROM forest_blocks WHERE calculation_id = :c"), {"c": str(calculation_id)}
        )
    }
    lines: List[Dict[str, Any]] = []
    for a in acts:
        p = pot.get(a.potential_activity_id)
        if p is None:
            continue
        yd_map = details.get(a.id, {})
        years = sorted(yd_map) or sorted(a.year_numbers or []) or list(range(1, 11))
        for y in years:
            yd = yd_map.get(y)
            qty = float(yd.quantity) if yd is not None and yd.quantity is not None else float(a.default_quantity or 0)
            bud = float(yd.yearly_budget) if yd is not None and yd.yearly_budget is not None else float(a.default_yearly_budget or 0)
            bid = (yd.block_id if yd is not None and yd.block_id else a.block_id)
            lines.append({
                "activity": p.activities or "", "program": p.progarms or "", "unit": p.unit or "",
                "map_kind": p.map_kind or "", "is_felling": bool(p.is_felling), "potential_id": p.id,
                "sn": p.sn or "", "year": y, "quantity": qty, "budget": bud,
                "block": block_names.get(bid, "") if bid else "",
            })
    return lines


FIRE_LINE_KINDS = {"boundary": "नयाँ निर्माण (सिमाना)", "road": "विद्यमान बाटो", "drawn": "कोरिएको"}


def fire_line_summary(result_data: Dict[str, Any]) -> Dict[str, Any]:
    """The fire lines as they are stored (FL-6): a table with one row each, and the totals split into what already exists
    (roads) and what is still to be constructed (boundary strips and lines drawn by the owner).

    Reads ``result_data['sub_areas']`` only - never builds the strips, as the OP never builds the SFM classification. Returns
    ``{}`` when the fire lines were never generated (so a placed ``{{token}}`` says "no data"), and zeros with an empty table
    when they were generated and there are none (the owner unticked them all).
    """
    rd = result_data or {}
    strips = [sa for sa in rd.get("sub_areas") or [] if sa.get("category") == "fire_line"]
    if not strips and (rd.get("fire_line_status") or {}).get("state") != "ok":
        return {}

    def kind(sa):
        return "drawn" if sa.get("origin") != "auto" else ("road" if sa.get("source") == "road" else "boundary")

    order = {"boundary": 0, "road": 1, "drawn": 2}
    strips.sort(key=lambda sa: (order[kind(sa)], str(sa.get("name") or "")))
    rows = []
    tot = {k: {"n": 0, "km": 0.0, "ha": 0.0} for k in order}
    for i, sa in enumerate(strips, start=1):
        k = kind(sa)
        length_m = float(sa.get("length_m") or 0)
        ha = float(sa.get("area_hectares") or 0)
        units = ", ".join(b.get("blockName") for b in (sa.get("blockBreakdown") or [])[:3] if b.get("blockName"))
        rows.append({
            "सि.न.": _np(i), "नाम": sa.get("name") or "", "प्रकार": FIRE_LINE_KINDS[k], "एकाइ": units,
            "लम्बाइ_मि": round(length_m), "औसत_चौडाइ_मि": round(ha * 10_000 / length_m, 1) if length_m else "",
            "क्षेत्रफल_हे": round(ha, 3),
        })
        tot[k]["n"] += 1
        tot[k]["km"] += length_m / 1000.0
        tot[k]["ha"] += ha
    new_km = tot["boundary"]["km"] + tot["drawn"]["km"]
    new_ha = tot["boundary"]["ha"] + tot["drawn"]["ha"]
    return {
        "fire_line_table": rows,
        "fire_line_count": len(strips),
        "fire_line_total_km": round(new_km + tot["road"]["km"], 2),
        "fire_line_total_ha": round(new_ha + tot["road"]["ha"], 2),
        "fire_line_existing_km": round(tot["road"]["km"], 2),
        "fire_line_existing_ha": round(tot["road"]["ha"], 2),
        "fire_line_new_km": round(new_km, 2),
        "fire_line_new_ha": round(new_ha, 2),
    }


def river_bank_summary(result_data: Dict[str, Any]) -> Dict[str, Any]:
    """The river banks as stored (RB-4): a table with one row each and the totals, plus the fire lines and river banks TOGETHER
    with their overlap counted once.

    A river bank is a PROTECTION area (not productive), so its area is also what leaves production. Reads ``result_data`` only.
    ``{}`` when the banks were never generated (a placed ``{{token}}`` then says "no data"); zeros and an empty table when they
    were generated and there are none (no river, or every bank unticked).
    """
    rd = result_data or {}
    banks = [sa for sa in rd.get("sub_areas") or [] if sa.get("category") == "river_bank"]
    if not banks and (rd.get("river_bank_status") or {}).get("state") != "ok":
        return {}
    banks.sort(key=lambda sa: (str(sa.get("river_name") or ""), str(sa.get("name") or "")))
    rows = []
    for i, sa in enumerate(banks, start=1):
        length_m = float(sa.get("length_m") or 0)
        ha = float(sa.get("area_hectares") or 0)
        units = ", ".join(b.get("blockName") for b in (sa.get("blockBreakdown") or []) if b.get("blockName"))
        rows.append({
            "सि.न.": _np(i), "नाम": sa.get("name") or "", "खोला": sa.get("river_name") or "", "एकाइ": units,
            "लम्बाइ_मि": round(length_m), "औसत_चौडाइ_मि": round(ha * 10_000 / length_m, 1) if length_m else "",
            "क्षेत्रफल_हे": round(ha, 3),
        })
    total_km = sum(float(sa.get("length_m") or 0) for sa in banks) / 1000.0
    total_ha = sum(float(sa.get("area_hectares") or 0) for sa in banks)
    out: Dict[str, Any] = {
        "river_bank_table": rows, "river_bank_count": len(banks),
        "river_bank_total_km": round(total_km, 2), "river_bank_total_ha": round(total_ha, 2),
    }
    out.update(_strips_together(rd))
    return out


def _strips_together(rd: Dict[str, Any]) -> Dict[str, Any]:
    """Fire lines + river banks as ONE area: the union, and how much the two share (square metres in the forest's UTM zone)."""
    from shapely.geometry import shape
    from shapely.ops import unary_union

    from app.services import strip_geometry as sg

    fire = [sa for sa in rd.get("sub_areas") or [] if sa.get("category") == "fire_line" and sa.get("geometry")]
    bank = [sa for sa in rd.get("sub_areas") or [] if sa.get("category") == "river_bank" and sa.get("geometry")]
    if not fire and not bank:
        return {"fire_line_river_bank_combined_ha": 0.0, "fire_line_river_bank_overlap_ha": 0.0}
    try:
        f_geoms = [shape(sa["geometry"]) for sa in fire]
        b_geoms = [shape(sa["geometry"]) for sa in bank]
        metric = sg.Metric.for_geometry(unary_union(f_geoms + b_geoms))
        f_m = [metric.to_m(g) for g in f_geoms]
        b_m = [metric.to_m(g) for g in b_geoms]
        fire_u = unary_union(f_m) if f_m else None
        bank_u = unary_union(b_m) if b_m else None
        overlap = sg.overlap_ha(fire_u, bank_u)
        return {"fire_line_river_bank_combined_ha": round(sg.combined_area_ha(f_m, b_m), 2),
                "fire_line_river_bank_overlap_ha": round(overlap, 2)}
    except Exception:  # noqa: BLE001 -- an unreadable stored geometry must not take the whole OP down; the figure is simply absent
        logger.exception("plan_extras: fire lines and river banks could not be combined")
        return {}


def _group_by(lines: List[Dict[str, Any]], pred) -> Dict[int, List[Dict[str, Any]]]:
    out: Dict[int, List[Dict[str, Any]]] = {}
    for ln in lines:
        if ln["quantity"] > 0 and pred(ln):
            out.setdefault(ln["year"], []).append(ln)
    return out


def _is_regen_felling(ln) -> bool:
    return bool(_RE_REGEN_FELLING.search(ln["activity"])) and not _RE_NOT_REGEN_FELLING.search(ln["activity"]) \
        or "वार्षिक कार्यक्षेत्र" in ln["activity"]


def silviculture_schedule(lines: List[Dict[str, Any]], fy: List[str]) -> List[Dict[str, Any]]:
    """Per plan year: where regeneration felling / preparatory felling / thinning / regeneration enhancement happen."""
    classes = [
        ("पुनरुत्पादन_कटान", _is_regen_felling),
        ("पुनरुत्पादन_तयारी_कटान", lambda ln: bool(_RE_PREPARATORY.search(ln["activity"]))),
        ("थिनिङ्ग_तथा_सुधार_कटान", lambda ln: bool(_RE_THINNING.search(ln["activity"]))),
        ("पुनरुत्पादन_अभिवृद्धि", lambda ln: bool(_RE_ENHANCE.search(ln["activity"]))),
    ]
    grouped = {name: _group_by(lines, pred) for name, pred in classes}
    if not any(grouped.values()):
        return []
    out = []
    for y in range(1, 11):
        row: Dict[str, Any] = {"बर्ष": _ORDINAL_NE[y - 1], "आ.व.": fy[y - 1] if len(fy) >= y else ""}
        for name, by_year in grouped.items():
            items = by_year.get(y, [])
            row[f"{name}_स्थान"] = ", ".join(sorted({i["block"] for i in items if i["block"]}))
            ha = sum(i["quantity"] for i in items if i["unit"].startswith(("हे", "ha")))
            row[f"{name}_हेक्टर"] = round(ha, 2) if ha else ""
        out.append(row)
    return out


def felling_yield_by_year(lines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Timber (cft) and firewood (chatta) yield per plan year, one row per felling / collection activity."""
    rows = []
    seen: Dict[str, Dict[str, Any]] = {}
    for ln in lines:
        if not (ln["is_felling"] or ln["map_kind"] == "coupe") or not ln["unit"].startswith(("क्यु", "घ.फि", "चट्टा")):
            continue
        key = ln["activity"] + "|" + ln["unit"]
        row = seen.get(key)
        if row is None:
            row = {"क्रियाकलाप": ln["activity"], "इकाई": ln["unit"], **{f"बर्ष_{_np(i)}": 0 for i in range(1, 11)}, "जम्मा": 0}
            seen[key] = row
            rows.append(row)
        k = f"बर्ष_{_np(ln['year'])}"
        row[k] = round(row[k] + ln["quantity"], 2)
    for r in rows:
        r["जम्मा"] = round(sum(r[f"बर्ष_{_np(i)}"] for i in range(1, 11)), 2)
    return rows


def fire_line_plan(lines: List[Dict[str, Any]], fy: List[str]) -> List[Dict[str, Any]]:
    """Fire-line construction / maintenance by year (km) with the units they cross."""
    by_year = _group_by(lines, lambda ln: ln["map_kind"] == "fire_line" and ln["unit"].startswith("कि"))
    if not by_year:
        return []
    out, total = [], 0.0
    for n, y in enumerate(sorted(by_year), 1):
        items = by_year[y]
        km = sum(i["quantity"] for i in items)
        total += km
        where = ", ".join(sorted({i["block"] for i in items if i["block"]}))
        what = " / ".join(sorted({i["activity"] for i in items}))
        out.append({"सि.न.": _np(n), "आ.व.": fy[y - 1] if len(fy) >= y else _np(y),
                    "क्रियाकलाप": f"{where} {what}".strip(), "परिमाण_कि.मी": round(km, 2)})
    out.append({"सि.न.": "जम्मा", "आ.व.": "", "क्रियाकलाप": "", "परिमाण_कि.मी": round(total, 2)})
    return out


def annual_budget_table(lines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The 'वार्षिक क्रियाकलाप तथा बजेट' table: per programme, per activity a quantity row and a budget row
    (budget in thousands of rupees, as the printed plan), plus a grand-total row per year."""
    if not lines:
        return []
    programs: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for ln in lines:
        act = programs.setdefault(ln["program"] or "अन्य", {}).setdefault(
            ln["activity"], {"unit": ln["unit"], "q": [0.0] * 10, "b": [0.0] * 10, "sn": ln["potential_id"]})
        if 1 <= ln["year"] <= 10:
            act["q"][ln["year"] - 1] += ln["quantity"]
            act["b"][ln["year"] - 1] += ln["budget"]
    rows: List[Dict[str, Any]] = []
    grand = [0.0] * 10

    def year_cols(vals, nd):
        return {f"बर्ष_{_np(i + 1)}": (round(v, nd) if v else "") for i, v in enumerate(vals)}

    for pn, (prog, acts) in enumerate(programs.items(), 1):
        rows.append({"क्र.सं.": _np(pn), "कार्यक्रमको_नाम": prog, "इकाई": "", "दर_हजारमा": "",
                     **{f"बर्ष_{_np(i)}": "" for i in range(1, 11)}, "जम्मा": ""})
        for an, (name, a) in enumerate(sorted(acts.items(), key=lambda kv: kv[1]["sn"]), 1):
            tq, tb = sum(a["q"]), sum(a["b"])
            if not tq and not tb:
                continue  # planned but with nothing in any year: not a budget line
            rate = round(tb / tq / 1000, 2) if tq else ""
            rows.append({"क्र.सं.": f"{_np(pn)}.{_np(an)}", "कार्यक्रमको_नाम": name, "इकाई": a["unit"],
                         "दर_हजारमा": rate, **year_cols(a["q"], 2), "जम्मा": round(tq, 2)})
            rows.append({"क्र.सं.": "", "कार्यक्रमको_नाम": "", "इकाई": "बजेट", "दर_हजारमा": "",
                         **year_cols([b / 1000 for b in a["b"]], 2), "जम्मा": round(tb / 1000, 2)})
            grand = [g + b / 1000 for g, b in zip(grand, a["b"])]
    rows.append({"क्र.सं.": "", "कार्यक्रमको_नाम": "कुल बजेट (हजारमा)", "इकाई": "", "दर_हजारमा": "",
                 **year_cols(grand, 2), "जम्मा": round(sum(grand), 2)})
    return rows


# ── field inventory summary tables ───────────────────────────────────────────
_COND_NE = {"Good": "राम्रो", "Moderate": "ठिकै", "Weak": "कमसल", "Poor": "कमसल", "Excellent": "उत्तम"}


def _cond(word: Optional[str]) -> str:
    return _COND_NE.get(word or "", word or "")


def unit_per_ha_summary_table(fi: Dict[str, Any], block_areas: Dict[str, float]) -> List[Dict[str, Any]]:
    """One row per unit - area, stems per ha by stage, basal area, volume, growing stock - and a weighted
    forest row. This is the 'प्रति हेक्टर वनको अवस्था' table printed in the summary and in 4.2.1."""
    blocks = fi.get("fi_block_summaries") or []
    if not blocks:
        return []
    rows = []
    for b in blocks:
        name = b.get("block_name", "")
        if not name:
            continue  # the collector also stores a nameless forest-wide row; the weighted row below replaces it
        rows.append({
            "सव_कम्पार्टमेन्ट": name,
            "क्षेत्रफल_हेक्टर": round(block_areas.get(name, 0.0), 2),
            "विरुवा_प्रति_हेक्टर": round(b.get("regeneration_per_ha") or 0),
            "लाथ्रा_प्रति_हेक्टर": round(b.get("sapling_per_ha") or 0),
            "पोल_प्रति_हेक्टर": round(b.get("pole_per_ha") or 0),
            "रुख_प्रति_हेक्टर": round(b.get("tree_per_ha") or 0),
            "आधारको_क्षेत्रफल_व.मि": round(b.get("basal_area_m2_per_ha") or 0, 2),
            "पोल_आयतन_घ.मि": round(b.get("pole_total_m3_per_ha") or 0, 2),
            "रुख_आयतन_घ.मि": round(b.get("tree_total_m3_per_ha") or 0, 2),
            "काठ_घ.मि": round((b.get("pole_timber_m3_per_ha") or 0) + (b.get("tree_timber_m3_per_ha") or 0), 2),
            "दाउरा_घ.मि": round((b.get("pole_firewood_m3_per_ha") or 0) + (b.get("tree_firewood_m3_per_ha") or 0), 2),
            "वनको_मौज्दात_घ.मि": round(b.get("total_volume_m3_per_ha") or 0, 2),
        })
    total_area = sum(r["क्षेत्रफल_हेक्टर"] for r in rows)

    def wavg(key):
        return round(sum(r[key] * r["क्षेत्रफल_हेक्टर"] for r in rows) / total_area, 2) if total_area else ""

    avg = {"सव_कम्पार्टमेन्ट": "जम्मा औषत", "क्षेत्रफल_हेक्टर": round(total_area, 2)}
    for key in rows[0]:
        if key not in avg:
            avg[key] = round(wavg(key)) if key.endswith("प्रति_हेक्टर") and wavg(key) != "" else wavg(key)
    rows.append(avg)
    return rows


def forest_state_table(fi: Dict[str, Any]) -> List[Dict[str, Any]]:
    """'वनको वर्तमान अवस्था': the four stages with per-ha count, timber volume and the condition words."""
    if not fi.get("available"):
        return []
    regen_c, forest_c = _cond(fi.get("fi_regeneration_condition")), _cond(fi.get("fi_forest_condition"))
    rows = [
        ("विरुवा", fi.get("fi_regeneration_per_ha"), "", regen_c),
        ("लाथ्रा", fi.get("fi_sapling_per_ha"), "", regen_c),
        ("पोल", fi.get("fi_pole_per_ha"), "", forest_c),
        ("रुख", fi.get("fi_tree_per_ha"), "", forest_c),
    ]
    out = []
    for n, (stage, count, vol, cond) in enumerate(rows, 1):
        out.append({"क्र.स": _np(n), "वन_पैदावारको_विवरण": stage,
                    "संख्या_प्रति_हेक्टर": round(count or 0), "अवस्था": cond})
    out.append({"क्र.स": "", "वन_पैदावारको_विवरण": "वनको मौज्दात (घ.मि. प्रति हेक्टर)",
                "संख्या_प्रति_हेक्टर": round(fi.get("fi_growing_stock_m3_per_ha") or 0, 2), "अवस्था": forest_c})
    return out


# ── coordinate tables (annexes 2, 3a, 3b) ────────────────────────────────────
def fieldbook_coordinate_tables(db: Session, calculation_id: str) -> Dict[str, Any]:
    """Outer-boundary points (SN, X, Y) and internal unit-divider points (SN, X, Y, units) in UTM metres."""
    from app.models.fieldbook import Fieldbook

    pts = (db.query(Fieldbook).filter(Fieldbook.calculation_id == calculation_id)
           .order_by(Fieldbook.point_number).all())
    if not pts:
        return {}

    def xy(p):
        return (round(float(p.easting_utm)) if p.easting_utm is not None else "",
                round(float(p.northing_utm)) if p.northing_utm is not None else "")

    outer = [p for p in pts if (p.boundary_class or "outer") == "outer"]
    internal = [p for p in pts if p.boundary_class == "internal"]
    return {
        "fieldbook_outer_table": [
            {"SN": p.point_label or i, "X": xy(p)[0], "Y": xy(p)[1]} for i, p in enumerate(outer, 1)],
        "fieldbook_internal_table": [
            {"SN": p.point_label or i, "X": xy(p)[0], "Y": xy(p)[1],
             "Sub/Compartment": ", ".join(p.adjacent_units or [])} for i, p in enumerate(internal, 1)],
    }


def plot_utm_coordinate_table(db: Session, calculation_id: str, epsg: Optional[int]) -> List[Dict[str, Any]]:
    """Sample-plot centres (SP_Num, X, Y) in UTM metres; the field-inventory plots when there are any."""
    epsg = epsg or 32644
    rows = db.execute(
        text(
            """
            SELECT p.sample_plot_number,
                   ST_X(ST_Transform(p.location::geometry, :epsg)), ST_Y(ST_Transform(p.location::geometry, :epsg))
              FROM field_inventory_sample_plots p
              JOIN field_inventory_calculations f ON f.id = p.field_inventory_calculation_id
             WHERE f.calculation_id = :cid AND p.location IS NOT NULL
             ORDER BY p.sample_plot_number
            """
        ),
        {"cid": str(calculation_id), "epsg": int(epsg)},
    ).all()
    return [{"SP_Num": n, "X": round(x), "Y": round(y)} for n, x, y in rows]


# ── stem mapping ─────────────────────────────────────────────────────────────
_TREE_HEADERS = ["S.N", "Tag no", "X_cod", "Y_cod", "प्रजाति", "DBH (cm)", "DBH Class", "Height (m)", "Class",
                 "Basal Area (m2)", "Stem volume (m3)", "Branch volume (m3)", "Gross volume (m3)",
                 "Wood volume (m3)", "Firewood volume (m3)", "Wood volume (cft)", "Firewood volume (chatta)"]


def _top_species(raw_rows) -> Optional[str]:
    """The species with the most trees among ``raw_rows`` (None when there are none)."""
    counts: Dict[str, int] = {}
    for r in raw_rows:
        counts[r["sp"]] = counts.get(r["sp"], 0) + 1
    return max(counts, key=counts.get) if counts else None


def stem_lists(db: Session, calculation_id: str) -> Dict[str, Any]:
    """Felling (FT), mother (MT) and protected (PT) tree lists of the stem-mapped area + the scalars the
    plan quotes ('120 trees a year', '24 mother trees per ha', '17 species')."""
    rows = db.execute(
        text(
            """
            SELECT t.row_number, COALESCE(NULLIF(t.local_name, ''), t.species) AS sp, t.dia_cm, t.height_m,
                   t.dbh_class, t.tree_class, t.stem_volume, t.branch_volume, t.gross_volume, t.net_volume,
                   t.firewood_m3, t.net_volume_cft, t.firewood_chatta, t.remark, t.stand_type, t.block_name,
                   ST_X(ST_Transform(t.location::geometry, COALESCE(ic.projection_epsg, 32644))) AS x,
                   ST_Y(ST_Transform(t.location::geometry, COALESCE(ic.projection_epsg, 32644))) AS y
              FROM inventory_trees t
              JOIN inventory_calculations ic ON ic.id = t.inventory_calculation_id
             WHERE ic.calculation_id = :cid AND t.stand_type = 'Tree'
             ORDER BY t.row_number NULLS LAST
            """
        ),
        {"cid": str(calculation_id)},
    ).mappings().all()
    if not rows:
        return {}

    def to_row(i: int, r) -> Dict[str, Any]:
        d = float(r["dia_cm"] or 0)
        f = lambda v, nd=2: round(float(v), nd) if v is not None else ""  # noqa: E731
        return dict(zip(_TREE_HEADERS, [
            i, r["row_number"] if r["row_number"] is not None else "", round(r["x"] or 0), round(r["y"] or 0),
            r["sp"], round(d), r["dbh_class"] or "", f(r["height_m"], 1), r["tree_class"] or "",
            round(3.14159265 * (d / 200) ** 2, 2), f(r["stem_volume"]), f(r["branch_volume"]), f(r["gross_volume"]),
            f(r["net_volume"]), f(r["firewood_m3"]), f(r["net_volume_cft"]), f(r["firewood_chatta"], 3),
        ]))

    def pick(kind: Optional[str]):
        sel = [r for r in rows if (r["remark"] or None) == kind] if kind else [r for r in rows if not r["remark"]]
        return [to_row(i, r) for i, r in enumerate(sel, 1)], sel

    ft, ft_raw = pick("Felling Tree")
    mt, mt_raw = pick("Mother Tree")
    pt, _ = pick(None)
    # area of the stem-mapped unit(s): the leaf units that actually carry the mapped trees
    units = sorted({r["block_name"] for r in rows if r["block_name"]})
    area = float(db.execute(
        text(
            """
            SELECT COALESCE(SUM(b.area_hectares), 0)
              FROM forest_blocks b
             WHERE b.id IN (SELECT DISTINCT t.unit_id FROM inventory_trees t
                              JOIN inventory_calculations ic ON ic.id = t.inventory_calculation_id
                             WHERE ic.calculation_id = :cid AND t.unit_id IS NOT NULL)
            """
        ),
        {"cid": str(calculation_id)},
    ).scalar() or 0)
    if not area and units:
        area = float(db.execute(
            text("SELECT COALESCE(SUM(area_hectares), 0) FROM forest_blocks WHERE calculation_id = :c AND block_name = ANY(:n)"),
            {"c": str(calculation_id), "n": units},
        ).scalar() or 0)
    return {
        "sm_felling_tree_list": ft, "sm_mother_tree_list": mt, "sm_protected_tree_list": pt,
        "sm_felling_annual_trees": round(len(ft) / 10) if ft else None,
        "sm_mother_trees_per_ha": round(len(mt) / area) if mt and area else None,
        "sm_species_count": len({r["sp"] for r in ft_raw}) if ft_raw else None,
        "sm_top_species": _top_species(ft_raw),
        "sm_tree_total": len(rows),
        "sm_felling_tree_total": len(ft),
        "sm_mother_tree_total": len(mt),
        "sm_protected_tree_total": len(pt),
        "sm_stem_mapped_units": ", ".join(units),
    }


# ── rasters / hazard / hydrology / sampling ──────────────────────────────────
_ASPECT_NE = {"N": "उत्तर", "NE": "उत्तर पूर्व", "E": "पूर्व", "SE": "दक्षिण पूर्व",
              "S": "दक्षिण", "SW": "दक्षिण पश्चिम", "W": "पश्चिम", "NW": "उत्तर पश्चिम"}
_ASPECT_ORDER = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
_SLOPE_CLASSES = ["gentle", "moderate", "steep", "very_steep"]
_SLOPE_LO = {"gentle": 0, "moderate": 19, "steep": 31, "very_steep": 45}   # core.constants SLOPE_*_MAX_DEG
_SLOPE_HI = {"gentle": 19, "moderate": 31, "steep": 45}


def aspect_dominant_names(ra: Dict[str, Any], min_pct: float = 10.0) -> Optional[str]:
    pct = (ra.get("aspect") or {}).get("percentages") or {}
    keep = [k for k in _ASPECT_ORDER if (pct.get(k) or 0) >= min_pct]
    return ", ".join(_ASPECT_NE[k] for k in keep) or None


def slope_range_deg(ra: Dict[str, Any]) -> Optional[str]:
    """Class-based: the lowest present class's lower band to the highest present class's upper band."""
    pct = (ra.get("slope") or {}).get("percentages") or {}
    present = [c for c in _SLOPE_CLASSES if (pct.get(c) or 0) > 0]
    if not present:
        return None
    lo = _SLOPE_LO[present[0]]
    hi = _SLOPE_HI.get(present[-1])
    if hi:
        return f"{_np(lo)} देखि {_np(hi)} डिग्री"
    return f"{_np(lo)} देखि ४५ डिग्री भन्दा बढी" if present[-1] == "very_steep" and lo < 45 else "४५ डिग्री भन्दा बढी"


def soil_texture_names(ra: Dict[str, Any], min_pct: float = 10.0) -> Optional[str]:
    pct = (ra.get("soil") or {}).get("percentages") or {}
    keep = [k for k, v in sorted(pct.items(), key=lambda kv: -kv[1]) if (v or 0) >= min_pct]
    return ", ".join(keep) or ((ra.get("soil") or {}).get("dominant_type") or None)


def erosion_status_word(se: Dict[str, Any]) -> Optional[str]:
    """The soil-loss severity class (the same 6 labels the map legend uses) of the forest's mean loss."""
    mean = se.get("soil_loss_mean_t_ha")
    if mean is None or not se.get("soil_loss_available", True):
        return None
    from app.services.operational_plan.soil_erosion_config import SEVERITY_LABELS_NE

    idx = 0
    for brk in (se.get("soil_loss_severity_breaks") or [5, 10, 20, 40, 80]):
        if mean >= brk:
            idx += 1
    return SEVERITY_LABELS_NE[idx] if idx < len(SEVERITY_LABELS_NE) else None


def drainage_summary(db: Session, calculation_id: str) -> Optional[str]:
    from app.services.operational_plan.raster_zonal import hydro_lines_for_forest

    # hydro_lines_for_forest swallows its own SQL error, which would leave the transaction aborted
    if not db.execute(text("SELECT to_regclass('river.river84')")).scalar():
        return None
    names = sorted({nm for _g, nm in hydro_lines_for_forest(db, calculation_id) if nm})
    if not names:
        return None
    return f"यस वन क्षेत्रभित्र वा सिमानामा {_np(len(names))} खोला/खोल्सी ({', '.join(names)}) पर्दछन् ।"


def nested_plot_radii(raw: Dict[str, Any]) -> Optional[str]:
    """Radii (m) of the nested circular plots from their areas: regeneration, sapling, pole, tree."""
    fi = raw.get("field_inventory") or {}
    areas = [fi.get(k) for k in ("regeneration_area_sqm", "sapling_area_sqm", "pole_area_sqm", "tree_area_sqm")]
    if not all(areas):
        return None
    return " / ".join(f"{(a / 3.14159265) ** 0.5:.2f}" for a in areas)


# ── entry point ──────────────────────────────────────────────────────────────
def _module_safe(name: str, fn, default):
    """Run one derived block. Each runs in a SAVEPOINT: a failing query rolls back to it, so one broken
    table cannot abort the transaction the rest of the collection (and the document build) still needs."""
    try:
        db = getattr(fn, "__db__", None)
        with (db.begin_nested() if db is not None else _NullCtx()):
            return fn()
    except Exception:
        logger.exception("plan_extras: %s could not be built", name)
        return default


class _NullCtx:
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def collect_plan_extras(db: Session, calculation_id: str, raw: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}

    def _safe(name, fn, default, _db=db):  # noqa: F811 -- the module-level _safe, bound to this session
        fn.__db__ = _db
        return _module_safe(name, fn, default)

    out.update(_safe("committee scalars", lambda: committee_scalars(raw), {}))
    out["hh_caste_prosperity_table"] = _safe("caste x prosperity", lambda: caste_prosperity_table(db, calculation_id), [])

    fy_start = _safe("fiscal year", lambda: _fy_start(db, calculation_id), None)
    fy = fy_labels(fy_start)
    lines = _safe("plan lines", lambda: plan_lines(db, calculation_id), [])
    out["ya_silviculture_schedule_table"] = silviculture_schedule(lines, fy)
    out["ya_felling_by_year_table"] = felling_yield_by_year(lines)
    out["fire_line_plan_table"] = fire_line_plan(lines, fy)
    out.update(_safe("fire lines", lambda: fire_line_summary(_stored_result_data(db, calculation_id)), {}))
    out.update(_safe("river banks", lambda: river_bank_summary(_stored_result_data(db, calculation_id)), {}))
    out["ya_annual_budget_table"] = annual_budget_table(lines)
    sched = out["ya_silviculture_schedule_table"]
    first = next((r for r in sched if r.get("पुनरुत्पादन_कटान_स्थान")), None)
    out["sfm_regeneration_felling_unit"] = first["पुनरुत्पादन_कटान_स्थान"] if first else None
    first_pf = next((r for r in sched if r.get("पुनरुत्पादन_तयारी_कटान_स्थान")), None)
    out["sfm_preparatory_felling_unit"] = first_pf["पुनरुत्पादन_तयारी_कटान_स्थान"] if first_pf else None
    cft = [ln for ln in lines if ln["is_felling"] and ln["year"] == 1 and ln["unit"].startswith(("क्यु", "घ.फि"))]
    chatta = [ln for ln in lines if ln["is_felling"] and ln["year"] == 1 and ln["unit"].startswith("चट्टा")]
    out["sfm_annual_yield_timber_cft"] = round(sum(ln["quantity"] for ln in cft)) if cft else None
    out["sfm_annual_yield_firewood_chatta"] = round(sum(ln["quantity"] for ln in chatta), 1) if chatta else None
    if any(out[k] is None for k in ("sfm_regeneration_felling_unit", "sfm_preparatory_felling_unit",
                                    "sfm_annual_yield_timber_cft", "sfm_annual_yield_firewood_chatta")):
        # no felling activity in the yearly plan: fall back to what the SFM classification decided; a plan line still wins
        from app.services.operational_plan import silviculture_derived

        sfm = (_safe("stored SFM", lambda: _stored_result_data(db, calculation_id), {}) or {}).get("sfm") or {}
        fb = silviculture_derived.felling_from_sfm(sfm)
        for key, fb_key in (("sfm_regeneration_felling_unit", "regeneration_felling_unit"),
                            ("sfm_preparatory_felling_unit", "preparatory_felling_unit"),
                            ("sfm_annual_yield_timber_cft", "annual_yield_timber_cft"),
                            ("sfm_annual_yield_firewood_chatta", "annual_yield_firewood_chatta")):
            if out[key] is None:
                out[key] = fb[fb_key]

    out.update(_safe("stem lists", lambda: stem_lists(db, calculation_id), {}))

    fi = raw.get("field_inventory") or {}
    areas = _safe("unit areas", lambda: _unit_areas(db, calculation_id), {})
    out["demand_poles_count"] = ((raw.get("demand_supply") or {}).get("demand") or {}).get("poles_count")
    out.update(_safe("unit counts", lambda: unit_counts(db, calculation_id), {}))
    main = list(fi.get("fi_dominant_species") or []) + list(fi.get("fi_co_dominant_species") or [])
    if not main:   # no dominant / co-dominant classification: the three most abundant species by composition
        comp = fi.get("fi_species_composition") or {}
        main = [k for k, _v in sorted(comp.items(), key=lambda kv: -float(kv[1] or 0))[:3]] if isinstance(comp, dict) else []
    out["fi_main_species_names"] = ", ".join(main) or None
    out["fi_other_species_names"] = ", ".join(fi.get("fi_associated_species") or []) or None
    thin = [r for r in sched if r.get("थिनिङ्ग_तथा_सुधार_कटान_स्थान")]
    thin_units = {u.strip() for r in thin for u in r["थिनिङ्ग_तथा_सुधार_कटान_स्थान"].split(",") if u.strip()}
    out["ya_thinning_unit_count"] = len(thin_units) or None
    out["ya_thinning_area_ha"] = round(sum(r.get("थिनिङ्ग_तथा_सुधार_कटान_हेक्टर") or 0 for r in thin), 2) or None
    out["fi_unit_per_ha_summary_table"] = _safe("per-ha summary", lambda: unit_per_ha_summary_table(fi, areas), [])
    out["fi_forest_state_table"] = _safe("forest state", lambda: forest_state_table(fi), [])
    out.update(_safe("fieldbook coordinates", lambda: fieldbook_coordinate_tables(db, calculation_id), {}))
    epsg = (raw.get("basic_info") or {}).get("utm_zone")
    out["plot_utm_coordinate_table"] = _safe("sample-plot coordinates", lambda: plot_utm_coordinate_table(db, calculation_id, epsg), [])

    ra = raw.get("raster_analysis") or {}
    out["aspect_dominant_names"] = aspect_dominant_names(ra)
    out["slope_range_deg"] = slope_range_deg(ra)
    out["soil_texture_names"] = soil_texture_names(ra)
    out["erosion_status_word"] = erosion_status_word(raw.get("soil_erosion") or {})
    out["drainage_summary"] = _safe("drainage summary", lambda: drainage_summary(db, calculation_id), None)
    out["nested_plot_radii_m"] = nested_plot_radii(raw)
    hist = ra.get("landcover_historical") or {}
    out["hansen2000_dominant"] = hist.get("hansen2000_dominant")
    out["hansen2000_percentages"] = hist.get("hansen2000_percentages")
    return out


def _fy_start(db: Session, calculation_id: str) -> Optional[str]:
    from app.models.forest_metadata import ForestMetadata

    row = db.query(ForestMetadata).filter(ForestMetadata.calculation_id == calculation_id).first()
    return row.fy_start if row else None


# column order per variable (see table_columns.py - JSONB loses key order)
_YEARS = [f"बर्ष_{_np(i)}" for i in range(1, 11)]
_SCHED = ["बर्ष", "आ.व."] + [f"{c}_{u}" for c in ("पुनरुत्पादन_कटान", "पुनरुत्पादन_तयारी_कटान", "थिनिङ्ग_तथा_सुधार_कटान", "पुनरुत्पादन_अभिवृद्धि") for u in ("स्थान", "हेक्टर")]


def _caste_cols(keys):
    levels = sorted((k for k in keys if k not in ("जातजाति", "जम्मा")),
                    key=lambda p: _PROSPERITY_ORDER.index(p) if p in _PROSPERITY_ORDER else 99)
    return ["जातजाति"] + levels + ["जम्मा"]


COLUMN_ORDER = {
    "hh_caste_prosperity_table": _caste_cols,
    "ya_silviculture_schedule_table": _SCHED,
    "ya_felling_by_year_table": ["क्रियाकलाप", "इकाई"] + _YEARS + ["जम्मा"],
    "fire_line_plan_table": ["सि.न.", "आ.व.", "क्रियाकलाप", "परिमाण_कि.मी"],
    "fire_line_table": ["सि.न.", "नाम", "प्रकार", "एकाइ", "लम्बाइ_मि", "औसत_चौडाइ_मि", "क्षेत्रफल_हे"],
    "river_bank_table": ["सि.न.", "नाम", "खोला", "एकाइ", "लम्बाइ_मि", "औसत_चौडाइ_मि", "क्षेत्रफल_हे"],
    "ya_annual_budget_table": ["क्र.सं.", "कार्यक्रमको_नाम", "इकाई", "दर_हजारमा"] + _YEARS + ["जम्मा"],
    "sm_felling_tree_list": _TREE_HEADERS, "sm_mother_tree_list": _TREE_HEADERS, "sm_protected_tree_list": _TREE_HEADERS,
    "fi_unit_per_ha_summary_table": [
        "सव_कम्पार्टमेन्ट", "क्षेत्रफल_हेक्टर", "विरुवा_प्रति_हेक्टर", "लाथ्रा_प्रति_हेक्टर", "पोल_प्रति_हेक्टर",
        "रुख_प्रति_हेक्टर", "आधारको_क्षेत्रफल_व.मि", "पोल_आयतन_घ.मि", "रुख_आयतन_घ.मि", "काठ_घ.मि", "दाउरा_घ.मि",
        "वनको_मौज्दात_घ.मि"],
    "fi_forest_state_table": ["क्र.स", "वन_पैदावारको_विवरण", "संख्या_प्रति_हेक्टर", "अवस्था"],
    "fieldbook_outer_table": ["SN", "X", "Y"],
    "fieldbook_internal_table": ["SN", "X", "Y", "Sub/Compartment"],
    "plot_utm_coordinate_table": ["SP_Num", "X", "Y"],
}


def _stored_result_data(db: Session, calculation_id: str) -> Dict[str, Any]:
    from app.models.calculation import Calculation

    row = db.query(Calculation.result_data).filter(Calculation.id == calculation_id).first()
    return (row[0] or {}) if row else {}


def unit_counts(db: Session, calculation_id: str) -> Dict[str, Any]:
    """Leaf units (not divided further) and the compartments they belong to.

    ``unit_count`` = leaf units ('सब-कम्पार्टमेन्ट' when the forest has two levels); ``unit_parent_count`` = the
    distinct parents of those leaves, or the leaf count itself for a flat forest. The legacy ``calculations.total_blocks``
    is 0 for forests drawn after the structure rule, so it is not used.
    """
    from app.services.forest_units.hierarchy import unit_hierarchy

    leaf_rows = [u for u in unit_hierarchy(db, calculation_id) if not u["kids"]]
    leaves = len(leaf_rows)
    parents = len({u["parent_id"] for u in leaf_rows if u["parent_id"]})
    return {"unit_count": leaves or None, "unit_parent_count": (parents or leaves) or None}


def _unit_areas(db: Session, calculation_id: str) -> Dict[str, float]:
    from app.services.operational_plan.data_collector import _fetch_block_effective_areas

    return _fetch_block_effective_areas(db, calculation_id)
