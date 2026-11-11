"""Regulation-category species tables for the operational plan.

Same per-hectare species x stage tables as `species_stage_tables`, but the rows are the
Forest Regulation categories instead of individual species: codes 1-21 by name, every other
species as "Other species" (Terai spp / Hill spp by the forest's region, see
`core.regulation_species`). Separate variables (`fi_reg_*`); the species-wise tables are untouched.

    build_regulation_stage_data(rows, block_areas, region) -> dict of keys merged into the field_inventory block
"""

import re
from typing import Any, Dict, List, Optional

from app.core.regulation_species import TERAI, annotate_regulation_rows
from app.services.operational_plan import species_stage_tables as sst

# fi_species_*_table -> fi_reg_species_*_table, fi_unit_species_*_table -> fi_reg_unit_species_*_table
_RENAME = (("fi_unit_species_", "fi_reg_unit_species_"), ("fi_species_", "fi_reg_species_"))


def _reg_key(key: str) -> str:
    for old, new in _RENAME:
        if key.startswith(old):
            return new + key[len(old):]
    return key


def _regulation_rows(rows: List[Dict[str, Any]], region: str, include_other: bool = True) -> List[Dict[str, Any]]:
    """Sum the per-ha fields of every species in the same (unit, category): one row per pair."""
    rows = annotate_regulation_rows([dict(r) for r in rows], region)
    other_label = "अन्य प्रजाति (तराई)" if region == TERAI else "अन्य प्रजाति (पहाड)"
    merged: Dict[tuple, Dict[str, Any]] = {}
    for r in rows:
        if not include_other and r["regulation_code"] in (22, 23):
            continue
        label = other_label if r["regulation_code"] in (22, 23) else r["regulation_name"]
        slot = merged.setdefault(
            (r.get("block_name"), label),
            {"block_name": r.get("block_name"), "species_local": label, "species_scientific": label,
             **{f: 0.0 for f in sst._FIELDS}},
        )
        for f in sst._FIELDS:
            slot[f] += float(r.get(f) or 0)
    return list(merged.values())


def build_regulation_stage_data(
    rows: List[Dict[str, Any]], block_areas: Optional[Dict[str, float]], region: str,
    include_other: bool = True,
) -> Dict[str, Any]:
    """Table keys for one forest's regulation-category breakdown ({} when there are no rows).

    include_other=False keeps only the classified species (codes 1-21)."""
    if not rows:
        return {}
    data = sst.build_species_stage_data(_regulation_rows(rows, region, include_other), block_areas)
    return {_reg_key(k): v for k, v in data.items() if k.endswith(("_table", "_chart_data"))}


def build_all_variants(rows: List[Dict[str, Any]], block_areas: Optional[Dict[str, float]], region: str) -> Dict[str, Any]:
    """`fi_reg_*` (all categories) and `fi_regc_*` (classified species only, codes 1-21)."""
    out = build_regulation_stage_data(rows, block_areas, region)
    classified = build_regulation_stage_data(rows, block_areas, region, include_other=False)
    out.update({k.replace("fi_reg_", "fi_regc_", 1): v for k, v in classified.items()})
    return out


# chart_key -> (data key, label field, value field, title, y label)
_CHART_BASES = {
    "species_pole_count_bar": ("pole", "count_per_ha", "पोलको प्रति हेक्टर संख्या", "संख्या/हे."),
    "species_pole_volume_bar": ("pole", "volume_m3_per_ha", "पोलको प्रति हेक्टर आयतन", "घ.मि./हे."),
    "species_tree_count_bar": ("tree", "count_per_ha", "रुखको प्रति हेक्टर संख्या", "संख्या/हे."),
    "species_tree_volume_bar": ("tree", "volume_m3_per_ha", "रुखको प्रति हेक्टर आयतन", "घ.मि./हे."),
}
_GROUP = {"fi_reg": "नियमावली प्रजाति वर्ग", "fi_regc": "वर्गीकृत प्रजाति"}
CHART_SPECS = {
    f"{p}_{name}": (f"{p}_species_{stage}_chart_data", "label", value, f"{g} अनुसार {title}", ylab)
    for p, g in _GROUP.items()
    for name, (stage, value, title, ylab) in _CHART_BASES.items()
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


def narration(field_inventory: Dict[str, Any], prefix: str) -> Optional[str]:
    """Nepali paragraph on the forest-wide tree stock by group; prefix 'fi_reg' (all) or 'fi_regc' (classified)."""
    rows = (field_inventory or {}).get(f"{prefix}_species_tree_per_ha_table") or []
    body = [r for r in rows if r.get(sst._SPECIES) != sst._TOTAL and (r.get("संख्या_प्रति_हेक्टर") or 0) > 0]
    total = next((r for r in rows if r.get(sst._SPECIES) == sst._TOTAL), None)
    if not body or not total:
        return None
    from app.utils.number_format import format_devanagari as fmt

    def vol(r: Dict[str, Any]) -> float:
        return float(r.get("जम्मा_आयतन_घ.मि") or 0)

    tot_vol = float(total.get("जम्मा_आयतन_घ.मि") or 0)
    top = sorted(body, key=vol, reverse=True)[:3]
    scope = "नियमावलीले तोकेको २१ प्रजाति र अन्य प्रजाति" if prefix == "fi_reg" else "नियमावलीले तोकेका २१ प्रजाति"
    parts = [
        f"{scope} अनुसार वर्गीकरण गर्दा रुखको जम्मा मौज्दात {fmt(tot_vol, 2)} घ.मि. प्रति हेक्टर "
        f"र {fmt(float(total.get('संख्या_प्रति_हेक्टर') or 0), 0)} रुख प्रति हेक्टर रहेको छ।"
    ]
    shares = [f"{r[sst._SPECIES]} {fmt(vol(r), 2)} घ.मि. ({fmt(vol(r) / tot_vol * 100, 1)}%)" for r in top if tot_vol]
    if shares:
        parts.append("सबैभन्दा बढी आयतन क्रमशः " + ", ".join(shares) + " रहेको छ।")
    return " ".join(parts)


COLUMN_ORDER = {_reg_key(k): v for k, v in sst.COLUMN_ORDER.items()}
COLUMN_ORDER.update({re.sub("fi_reg_", "fi_regc_", k, count=1): v for k, v in list(COLUMN_ORDER.items())})
