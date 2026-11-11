"""The Field Inventory page's view of the regulation-species tables: the same data the OP document prints.

    build_view(db, fi_calc_id, calculation_id) -> {region, variants: {all, classified}}

Each variant lists its tables, charts and narration together with the `{{token}}` that places each one in an OP template, so
the page shows a result and the token to copy beside it. Nothing is computed here that the OP does not compute: the tables
come from `species_regulation_tables.build_all_variants` and the columns from `table_columns.ordered_headers`.
"""

from typing import Any, Dict, List

from app.services.operational_plan import species_regulation_tables as srt
from app.services.operational_plan.table_columns import ordered_headers
from app.services.operational_plan.variable_registry import VARIABLE_REGISTRY

_TABLE_ORDER = (
    "species_regen_per_ha_table", "species_pole_per_ha_table", "species_tree_per_ha_table",
    "unit_species_regen_per_ha_table", "unit_species_pole_per_ha_table", "unit_species_tree_per_ha_table",
)
_VARIANTS = (("all", "fi_reg"), ("classified", "fi_regc"))


def _variant(data: Dict[str, Any], prefix: str) -> Dict[str, Any]:
    tables: List[Dict[str, Any]] = []
    for base in _TABLE_ORDER:
        key = f"{prefix}_{base}"
        rows = data.get(key) or []
        var = VARIABLE_REGISTRY.get(key)
        tables.append({
            "key": key, "token": "{{%s}}" % key, "label": var.label_ne if var else key,
            "headers": ordered_headers(key, rows) if rows else [], "rows": rows,
        })
    charts: List[Dict[str, Any]] = []
    for base in ("species_pole_count_bar", "species_pole_volume_bar", "species_tree_count_bar", "species_tree_volume_bar"):
        key = f"{prefix}_{base}"
        series = srt.chart_series(data, key)
        if not series:
            continue
        labels, values, title, ylab = series
        charts.append({"key": key, "token": "{{chart:%s}}" % key, "title": title, "y_label": ylab,
                       "labels": labels, "values": values})
    return {
        "prefix": prefix,
        "narration": {"token": "{{section:%s_species_narration:full}}" % prefix, "text": srt.narration(data, prefix)},
        "tables": tables,
        "charts": charts,
    }


def build_view(db, fi_calc_id: Any, calculation_id: Any) -> Dict[str, Any]:
    from app.core.regulation_species import region_for_field_inventory
    from app.services.field_inventory_mgmt_data import _get_species_breakdown
    from app.services.operational_plan.data_collector import _fetch_block_effective_areas

    region = region_for_field_inventory(db, fi_calc_id)
    block_areas = _fetch_block_effective_areas(db, str(calculation_id))
    data = srt.build_all_variants(_get_species_breakdown(db, fi_calc_id), block_areas, region)
    return {"region": region, "variants": {name: _variant(data, prefix) for name, prefix in _VARIANTS}}
