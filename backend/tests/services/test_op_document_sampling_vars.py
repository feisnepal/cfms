"""OP variable integrity regression tests (SAMPLING_PAGE_REWORK, Phase H.1).

Confirms the sampling OP variables still resolve in the variable registry:
`map:sampling_plot(_topo/_satellite)` map-placeholder variables and every
`sampling_*` variable registered by the sampling engines (Phases A-G added
no new OP keys, so this guards against accidental key drift).

Resolution exercises the same code path the OP document builder uses —
    op_docx_builder._resolve_var_from_raw -> variable_registry.get_variable
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.services.operational_plan.variable_registry import (
    get_variable,
    get_variables_by_category,
    get_all_variables,
)

# map: placeholders emitted by plan_map_service for the sampling maps
SAMPLE_MAP_KEYS = [
    "map:sampling_plot",
    "map:sampling_plot_topo",
    "map:sampling_plot_satellite",
]

# every sampling_* variable registered in the registry (source="sampling")
EXPECTED_SAMPLING_KEYS = {
    "sampling_available",
    "sampling_type",
    "sampling_total_points",
    "sampling_total_blocks",
    "sampling_plot_shape",
    "sampling_plot_radius_m",
    "sampling_intensity_per_ha",
    "sampling_requested_intensity",
    "sampling_actual_intensity",
    "sampling_block_summary",
    "sampling_point_locations",
    "sampling_forest_area_ha",
    "sampling_plot_area_sqm",
    "sampling_total_sampled_area_ha",
}


def test_sample_map_placeholders_resolve():
    """map:sampling_plot(_topo/_satellite) are registered as A/data-cat dicts."""
    for key in SAMPLE_MAP_KEYS:
        v = get_variable(key)
        assert v is not None, f"{key} missing from variable registry"
        assert v.category == "A", f"{key} should be category A, got {v.category}"
        assert v.var_type == "dict", f"{key} should be dict type, got {v.var_type}"
        assert v.source == "maps", f"{key} source should be maps, got {v.source}"


def test_all_sampling_variables_resolve():
    """Every sampling_* variable used by the sampling engines is registered."""
    for key in EXPECTED_SAMPLING_KEYS:
        v = get_variable(key)
        assert v is not None, f"{key} missing from variable registry"
        assert v.category == "A", f"{key} should be category A, got {v.category}"
        assert v.source == "sampling", f"{key} source should be sampling, got {v.source}"


def test_all_sampling_variables_are_category_a_catalog():
    """Registry category listing matches the expected sampling_* set."""
    cat_a = {v.key for v in get_variables_by_category("A")}
    for key in EXPECTED_SAMPLING_KEYS:
        assert key in cat_a, f"{key} not surfaced via get_variables_by_category('A')"


def test_sampling_variables_do_not_drift_extra_keys():
    """No unexpected sampling_* extra keys quietly added (drift guard)."""
    registered = {v.key for v in get_all_variables()}
    actual_sampling = {k for k in registered if k.startswith("sampling_")}
    assert actual_sampling == EXPECTED_SAMPLING_KEYS, (
        f"sampling_* key drift: extra={sorted(actual_sampling - EXPECTED_SAMPLING_KEYS)} "
        f"missing={sorted(EXPECTED_SAMPLING_KEYS - actual_sampling)}"
    )