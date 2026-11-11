"""Species x stage tables and chart data for the Rambhadevi-style operational plan.

The field inventory already holds, per unit and species, the per-hectare count of regeneration,
sapling, pole and tree stems plus their basal area and volume (`field_inventory_mgmt_data
._get_species_breakdown`). The approved plans print that as three families of tables
(regeneration / pole / tree), once per unit and once for the whole forest, and as bar charts.

Everything here is read-only and derived: no new input, nothing stored.

    build_species_stage_data(rows, block_areas) -> dict of keys merged into the field_inventory block
"""

from typing import Any, Dict, List, Optional

# why: rows are Nepali-keyed because the OP table renderer prints the dict keys as column headers
_UNIT = "खण्ड"
_SPECIES = "प्रजाती"
_TOTAL = "जम्मा"


def _name(row: Dict[str, Any]) -> str:
    return (row.get("species_local") or "").strip() or (row.get("species_scientific") or "").strip() or "—"


def _pct(value: float, total: float) -> float:
    return round(value / total * 100, 1) if total else 0.0


def _weighted(rows: List[Dict[str, Any]], block_areas: Dict[str, float], fields: List[str]) -> List[Dict[str, Any]]:
    """Forest-wide species rows: area-weighted mean of each per-hectare field over the units.

    A species absent from a unit counts as 0 per hectare there, so the weight is the whole forest area.
    """
    total_area = sum(a for a in block_areas.values() if a) or 0.0
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        area = block_areas.get(r.get("block_name"), 0.0) if total_area else 1.0
        slot = out.setdefault(_name(r), {"name": _name(r), **{f: 0.0 for f in fields}})
        for f in fields:
            slot[f] += float(r.get(f) or 0) * area
    denom = total_area or float(len({r.get("block_name") for r in rows}) or 1)
    for slot in out.values():
        for f in fields:
            slot[f] = slot[f] / denom
    return list(out.values())


def _regen_rows(units: List[Dict[str, Any]], name_key: Optional[str]) -> List[Dict[str, Any]]:
    tot_r = sum(u["regen_count_per_ha"] for u in units)
    tot_s = sum(u["sapling_count_per_ha"] for u in units)
    rows = []
    for u in sorted(units, key=lambda x: -x["regen_count_per_ha"]):
        row = {}
        if name_key:
            row[_UNIT] = u["unit"]
        row.update({
            _SPECIES: u["name"],
            "विरुवा_प्रति_हेक्टर": round(u["regen_count_per_ha"]),
            "विरुवा_प्रतिशत": _pct(u["regen_count_per_ha"], tot_r),
            "लाथ्रा_प्रति_हेक्टर": round(u["sapling_count_per_ha"]),
            "लाथ्रा_प्रतिशत": _pct(u["sapling_count_per_ha"], tot_s),
        })
        rows.append(row)
    total_row = {_SPECIES: _TOTAL, "विरुवा_प्रति_हेक्टर": round(tot_r), "विरुवा_प्रतिशत": 100.0 if tot_r else 0.0,
                 "लाथ्रा_प्रति_हेक्टर": round(tot_s), "लाथ्रा_प्रतिशत": 100.0 if tot_s else 0.0}
    if name_key:
        total_row = {_UNIT: units[0]["unit"] if units else "", **total_row}
    rows.append(total_row)
    return rows


def _stage_rows(units: List[Dict[str, Any]], stage: str, name_key: Optional[str]) -> List[Dict[str, Any]]:
    cnt, ba, tim, fw = (f"{stage}_count_per_ha", f"{stage}_basal_area_m2_per_ha",
                        f"{stage}_timber_m3_per_ha", f"{stage}_firewood_m3_per_ha")
    rows = []
    tot = {k: sum(u[k] for u in units) for k in (cnt, ba, tim, fw)}
    for u in sorted(units, key=lambda x: -x[cnt]):
        row = {}
        if name_key:
            row[_UNIT] = u["unit"]
        row.update({
            _SPECIES: u["name"],
            "संख्या_प्रति_हेक्टर": round(u[cnt]),
            "बेसल_एरिया_व.मि": round(u[ba], 2),
            "काठ_आयतन_घ.मि": round(u[tim], 2),
            "दाउरा_आयतन_घ.मि": round(u[fw], 2),
            "जम्मा_आयतन_घ.मि": round(u[tim] + u[fw], 2),
        })
        rows.append(row)
    total_row = {_SPECIES: _TOTAL, "संख्या_प्रति_हेक्टर": round(tot[cnt]), "बेसल_एरिया_व.मि": round(tot[ba], 2),
                 "काठ_आयतन_घ.मि": round(tot[tim], 2), "दाउरा_आयतन_घ.मि": round(tot[fw], 2),
                 "जम्मा_आयतन_घ.मि": round(tot[tim] + tot[fw], 2)}
    if name_key:
        total_row = {_UNIT: units[0]["unit"] if units else "", **total_row}
    rows.append(total_row)
    return rows


_FIELDS = [
    "regen_count_per_ha", "sapling_count_per_ha", "pole_count_per_ha", "tree_count_per_ha",
    "pole_basal_area_m2_per_ha", "tree_basal_area_m2_per_ha",
    "pole_timber_m3_per_ha", "pole_firewood_m3_per_ha", "tree_timber_m3_per_ha", "tree_firewood_m3_per_ha",
]


def build_species_stage_data(rows: List[Dict[str, Any]], block_areas: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """Return the table / chart keys for one forest's species breakdown rows ({} when there are none)."""
    if not rows:
        return {}
    block_areas = block_areas or {}
    forest = _weighted(rows, block_areas, _FIELDS)
    forest_units = [{"unit": "", **s} for s in forest]

    out: Dict[str, Any] = {
        "fi_species_regen_per_ha_table": _regen_rows(forest_units, None),
        "fi_species_pole_per_ha_table": _stage_rows(forest_units, "pole", None),
        "fi_species_tree_per_ha_table": _stage_rows(forest_units, "tree", None),
    }
    by_unit: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        by_unit.setdefault(r.get("block_name") or "", []).append(
            {"unit": r.get("block_name") or "", "name": _name(r), **{f: float(r.get(f) or 0) for f in _FIELDS}}
        )
    regen_u, pole_u, tree_u = [], [], []
    for unit in sorted(by_unit):
        us = by_unit[unit]
        regen_u += _regen_rows(us, "unit")
        pole_u += _stage_rows(us, "pole", "unit")
        tree_u += _stage_rows(us, "tree", "unit")
    out["fi_unit_species_regen_per_ha_table"] = regen_u
    out["fi_unit_species_pole_per_ha_table"] = pole_u
    out["fi_unit_species_tree_per_ha_table"] = tree_u

    # chart data: forest-wide, one entry per species that has the stage at all
    def series(count_key: str, vol_keys: List[str]) -> List[Dict[str, Any]]:
        items = [{"label": s["name"], "count_per_ha": round(s[count_key], 1),
                  "volume_m3_per_ha": round(sum(s[k] for k in vol_keys), 2)} for s in forest if s[count_key] > 0]
        return sorted(items, key=lambda x: -x["count_per_ha"])

    out["fi_species_pole_chart_data"] = series("pole_count_per_ha", ["pole_timber_m3_per_ha", "pole_firewood_m3_per_ha"])
    out["fi_species_tree_chart_data"] = series("tree_count_per_ha", ["tree_timber_m3_per_ha", "tree_firewood_m3_per_ha"])
    return out


# chart_key -> (data key in the field_inventory block, label field, value field, title, y label)
CHART_SPECS = {
    "fi_unit_regen_per_ha_bar": ("fi_unit_regen_chart_data", "label", "regen_per_ha", "खण्ड अनुसार बिरुवाको प्रति हेक्टर संख्या", "संख्या/हे."),
    "fi_unit_sapling_per_ha_bar": ("fi_unit_regen_chart_data", "label", "sapling_per_ha", "खण्ड अनुसार लाथ्राको प्रति हेक्टर संख्या", "संख्या/हे."),
    "fi_species_pole_count_bar": ("fi_species_pole_chart_data", "label", "count_per_ha", "प्रजाति अनुसार पोलको प्रति हेक्टर संख्या", "संख्या/हे."),
    "fi_species_pole_volume_bar": ("fi_species_pole_chart_data", "label", "volume_m3_per_ha", "प्रजाति अनुसार पोलको प्रति हेक्टर आयतन", "घ.मि./हे."),
    "fi_species_tree_count_bar": ("fi_species_tree_chart_data", "label", "count_per_ha", "प्रजाति अनुसार रुखको प्रति हेक्टर संख्या", "संख्या/हे."),
    "fi_species_tree_volume_bar": ("fi_species_tree_chart_data", "label", "volume_m3_per_ha", "प्रजाति अनुसार रुखको प्रति हेक्टर आयतन", "घ.मि./हे."),
}


def chart_series(field_inventory: Dict[str, Any], chart_key: str):
    """(labels, values, title, y_label) for one of CHART_SPECS, or None when there is nothing to plot."""
    spec = CHART_SPECS.get(chart_key)
    if not spec or not field_inventory:
        return None
    data_key, label_f, value_f, title, ylab = spec
    items = [d for d in (field_inventory.get(data_key) or []) if d.get(value_f) is not None]
    if not items:
        return None
    return [str(d[label_f]) for d in items], [d[value_f] for d in items], title, ylab


# column order per variable (see table_columns.py - JSONB loses key order)
_REGEN_COLS = [_UNIT, _SPECIES, "विरुवा_प्रति_हेक्टर", "विरुवा_प्रतिशत", "लाथ्रा_प्रति_हेक्टर", "लाथ्रा_प्रतिशत"]
_STAGE_COLS = [_UNIT, _SPECIES, "संख्या_प्रति_हेक्टर", "बेसल_एरिया_व.मि", "काठ_आयतन_घ.मि", "दाउरा_आयतन_घ.मि", "जम्मा_आयतन_घ.मि"]
COLUMN_ORDER = {
    "fi_species_regen_per_ha_table": _REGEN_COLS, "fi_unit_species_regen_per_ha_table": _REGEN_COLS,
    "fi_species_pole_per_ha_table": _STAGE_COLS, "fi_unit_species_pole_per_ha_table": _STAGE_COLS,
    "fi_species_tree_per_ha_table": _STAGE_COLS, "fi_unit_species_tree_per_ha_table": _STAGE_COLS,
}
