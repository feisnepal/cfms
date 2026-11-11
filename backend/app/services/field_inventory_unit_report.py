"""Field inventory by sub-unit: one row per undivided unit, a roll-up row for every divided parent, and a forest total.

The inventory is stored per UNDIVIDED unit only (sampling, the summary and every map work on that level), so a divided parent
such as ``blocks-1`` has no row of its own. This report puts the parent back as a roll-up of its children:

  * per-hectare figures are the AREA-WEIGHTED mean over the children that have data (a 21 ha child counts more than a 9 ha one);
  * totals (stems, growing stock, MAI, AAH) are per-hectare x area, summed over the children;
  * ``covered_pct`` is the share of the parent's area that has inventory behind it, so a roll-up from half the children says so;
  * a roll-up has no condition (Good / Moderate / Weak belongs to a unit's own sampling, it is not an average).

The numbers are the very values the maps and the Operational Plan read (``thematic_overlay._load_unit_values``), so this report,
the workspace maps and the document cannot disagree. Read-only; never computes the inventory.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

# (key in the stored summary, key in the report, decimals)
PER_HA = (
    ("regeneration_per_ha", "regeneration_per_ha", 0),
    ("sapling_per_ha", "sapling_per_ha", 0),
    ("pole_per_ha", "pole_per_ha", 0),
    ("tree_per_ha", "tree_per_ha", 0),
    ("total_growing_stock_m3_per_ha", "growing_stock_m3_per_ha", 1),
    ("basal_area_m2_per_ha", "basal_area_m2_per_ha", 2),
    ("mai_total_m3_per_ha", "mai_m3_per_ha", 2),
    ("aah_total_m3_per_ha", "aah_m3_per_ha", 2),
)
TOTAL_OF = {  # report key -> total key (per-ha x area)
    "growing_stock_m3_per_ha": "growing_stock_m3",
    "mai_m3_per_ha": "mai_m3",
    "aah_m3_per_ha": "aah_m3",
}

def _num(v: Any) -> Optional[float]:
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def _leaf_row(u: dict, rec: Optional[dict]) -> dict:
    row: Dict[str, Any] = {
        "name": u["name"], "kind": "unit", "depth": u["depth"], "parent": u["parent"], "area_ha": round(u["area_ha"], 2),
        "has_data": rec is not None, "plots": int((rec or {}).get("total_sample_plots") or 0),
        "forest_condition": (rec or {}).get("forest_condition") or None,
        "regeneration_condition": (rec or {}).get("regeneration_condition") or None, "covered_pct": 100.0 if rec else 0.0,
    }
    for src, key, nd in PER_HA:
        v = _num((rec or {}).get(src))
        row[key] = None if v is None else round(v, nd)
    for per_ha, tot in TOTAL_OF.items():
        v = row.get(per_ha)
        row[tot] = None if v is None else round(v * u["area_ha"], 1)
    return row


def _rollup(u: dict, kids: List[dict]) -> dict:
    """A divided unit from its (already built) children rows, which may themselves be roll-ups."""
    withdata = [k for k in kids if k["has_data"] and k["area_ha"] > 0]
    area_with = sum(k["area_ha"] for k in withdata)
    row: Dict[str, Any] = {
        "name": u["name"], "kind": "rollup", "depth": u["depth"], "parent": u["parent"], "area_ha": round(u["area_ha"], 2),
        "has_data": bool(withdata), "plots": sum(k["plots"] for k in kids),
        "forest_condition": None, "regeneration_condition": None,
        "covered_pct": round(100.0 * area_with / u["area_ha"], 1) if u["area_ha"] > 0 else 0.0,
    }
    for _src, key, nd in PER_HA:
        pts = [(k[key], k["area_ha"]) for k in withdata if k.get(key) is not None]
        w = sum(a for _v, a in pts)
        row[key] = round(sum(v * a for v, a in pts) / w, nd) if w > 0 else None
    for per_ha, tot in TOTAL_OF.items():
        vals = [k[tot] for k in withdata if k.get(tot) is not None]
        row[tot] = round(sum(vals), 1) if vals else None
    return row


def build(db: Session, calculation_id: Any, values: Optional[dict] = None) -> Dict[str, Any]:
    """The report: ``rows`` in tree order (parent, then its children), ``total`` for the forest, and ``leaf_count``.

    ``values`` is the stored per-unit inventory (name -> record); it is loaded from the same function the maps use when not given.
    """
    from app.services.operational_plan import thematic_overlay as to

    cid = str(calculation_id)
    if values is None:
        values = to._load_unit_values(db, calculation_id)
    if not values:
        return {"state": "not_computed", "rows": [], "total": None, "leaf_count": 0}

    from app.services.forest_units.hierarchy import unit_hierarchy

    raw = unit_hierarchy(db, calculation_id)
    by_id = {u["id"]: u for u in raw}
    for u in raw:
        u["parent"] = by_id[u["parent_id"]]["name"] if u["parent_id"] in by_id else None
    children: Dict[str, List[dict]] = {}
    for u in raw:
        if u["parent_id"]:
            children.setdefault(u["parent_id"], []).append(u)

    built: Dict[str, dict] = {}

    def build_unit(u: dict) -> dict:
        if u["id"] in built:
            return built[u["id"]]
        kids = children.get(u["id"]) or []
        row = _rollup(u, [build_unit(k) for k in kids]) if kids else _leaf_row(u, values.get(u["name"]))
        built[u["id"]] = row
        return row

    top = [u for u in raw if not u["parent_id"]]
    for u in top:
        build_unit(u)

    rows: List[dict] = []

    def walk(u: dict) -> None:
        rows.append(built[u["id"]])
        for k in children.get(u["id"]) or []:
            walk(k)

    for u in top:
        walk(u)

    leaves = [r for r in built.values() if r["kind"] == "unit"]
    total = _rollup({"name": "", "depth": 0, "parent": None, "area_ha": sum(t["area_ha"] for t in (built[u["id"]] for u in top))},
                    [built[u["id"]] for u in top])
    total["name"] = "total"
    total["kind"] = "total"
    return {"state": "ready", "rows": rows, "total": total, "leaf_count": len(leaves)}


COLUMNS = (
    ("name", "Unit"), ("kind", "Row"), ("parent", "Parent"), ("area_ha", "Area (ha)"), ("plots", "Plots"),
    ("regeneration_per_ha", "Regeneration /ha"), ("sapling_per_ha", "Saplings /ha"), ("pole_per_ha", "Poles /ha"),
    ("tree_per_ha", "Trees /ha"), ("growing_stock_m3_per_ha", "Growing stock (m3/ha)"), ("growing_stock_m3", "Growing stock (m3)"),
    ("basal_area_m2_per_ha", "Basal area (m2/ha)"), ("mai_m3_per_ha", "MAI (m3/ha/yr)"), ("mai_m3", "MAI (m3/yr)"),
    ("aah_m3_per_ha", "AAH (m3/ha/yr)"), ("aah_m3", "AAH (m3/yr)"), ("forest_condition", "Forest condition"),
    ("regeneration_condition", "Regeneration condition"), ("covered_pct", "Covered by inventory (%)"),
)
_ROW_LABEL = {"unit": "undivided unit", "rollup": "roll-up of sub-units", "total": "forest total"}


def to_xlsx(report: Dict[str, Any], findings: Optional[List[dict]] = None) -> bytes:
    """The report as an Excel workbook: sheet 1 the rows, sheet 2 the inventory problems (when there are any)."""
    from io import BytesIO

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "Sub-unit report"
    ws.append([label for _k, label in COLUMNS])
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="E8F5E9")
        c.alignment = Alignment(wrap_text=True, vertical="top")
    for row in list(report.get("rows") or []) + ([report["total"]] if report.get("total") else []):
        ws.append([_ROW_LABEL.get(row[k], row[k]) if k == "kind" else row.get(k) for k, _l in COLUMNS])
        if row["kind"] != "unit":
            for c in ws[ws.max_row]:
                c.font = Font(bold=True)
    for i, (_k, label) in enumerate(COLUMNS, start=1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = 22 if i <= 3 else max(12, len(label) + 2)
    ws.freeze_panes = "B2"
    ws.append([])
    ws.append(["Per-hectare figures of a roll-up are the area-weighted mean of its sub-units that have data; totals are per-hectare x area."])
    if findings:
        pw = wb.create_sheet("Problems")
        pw.append(["Severity", "Problem", "Unit", "What"])
        for c in pw[1]:
            c.font = Font(bold=True)
        for f in findings:
            pw.append([f["severity"], f["code"], f["unit"], f["message"]])
        pw.column_dimensions["D"].width = 90
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
