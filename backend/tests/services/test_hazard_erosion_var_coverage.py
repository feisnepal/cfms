"""HAZARD_EROSION_VARIABLE_COVERAGE_PLAN P6 — the coverage gate.

Every block the Hazard & Erosion page renders (headline numbers, maps, tables,
charts, narrative) MUST be an OP template variable a designer can drop into a
plan. This test fails if a future page block ships without one.

The manifest is `app.api.hazard_erosion.HAZARD_VARIABLE_GROUPS` (the same source
the in-context reference page reads) + the map keys derived from the thematic
registry.
"""

from __future__ import annotations

import re
import uuid

import pytest

from app.api.hazard_erosion import HAZARD_VARIABLE_GROUPS
from app.services.operational_plan.seed_data import get_default_seed_tree
from app.services.operational_plan.thematic_map_spec import BUILTIN_THEMEMAP_SPECS
from app.services.operational_plan.tree_models import TreeOperations
from app.services.operational_plan.variable_enrichment import SUB_GROUPS
from app.services.operational_plan.variable_registry import (
    VARIABLE_ALIASES,
    get_variable,
)
from app.services.operational_plan.variable_resolver import VariableResolver

# every non-map key the page surfaces, flattened
_MANIFEST_KEYS = [k for _gid, _ne, _en, keys in HAZARD_VARIABLE_GROUPS for k in keys]

# a synthetic collector payload covering every legacy slot the aliases read
_RAW = {
    "soil_erosion": {
        k: (
            []
            if k.endswith(("_table", "_by_unit", "_comparison", "assumptions", "breaks"))
            else ("x" if "narration" in k or "note" in k or "method" in k or "factor" in k or "source" in k or "customised" in k or "enabled" in k or "units" in k else 1.0)
        )
        for k in VARIABLE_ALIASES.values()
    },
    "hazard_vuln": {},
}
# put every legacy key in BOTH blocks so the resolver's section pick always hits
_RAW["hazard_vuln"] = dict(_RAW["soil_erosion"])
_RAW["soil_erosion"]["hazard_erosion_full_narration"] = "x"


def _resolver() -> VariableResolver:
    r = VariableResolver(db=None, calculation_id=uuid.uuid4(), plan=None)
    r._raw_data = _RAW
    return r


@pytest.mark.parametrize("key", _MANIFEST_KEYS)
def test_every_manifest_key_is_a_registered_variable(key):
    assert get_variable(key) is not None, f"{key} is on the page but not registered"


@pytest.mark.parametrize("key", _MANIFEST_KEYS)
def test_every_manifest_key_has_an_enrichment_sub_group(key):
    assert SUB_GROUPS.get(key, "").startswith("9"), key


@pytest.mark.parametrize(
    "key", [k for k in _MANIFEST_KEYS if not k.startswith("chart:")]
)
def test_every_non_chart_manifest_key_resolves_without_error(key):
    # None is fine (no data); an exception is not
    _resolver()._resolve_single(get_variable(key))


def test_manifest_covers_all_four_families():
    fams = {k.split("_")[1] for k in _MANIFEST_KEYS if k.startswith("hazard_")}
    assert {"erosion", "landslide", "slope", "household"} <= fams


def test_page_map_keys_are_thematic_specs():
    page_maps = [
        s.token
        for k, s in BUILTIN_THEMEMAP_SPECS.items()
        if k.startswith(("soil__", "hazard__", "hh__"))
    ]
    assert len(page_maps) >= 15
    assert "thememap:hazard__landslide_susceptibility" in page_maps


def test_seed_subsections_use_only_registered_hazard_tokens():
    seed = get_default_seed_tree()
    tokens: set[str] = set()
    for node in TreeOperations.flatten(seed):
        tokens.update(re.findall(r"\{\{([^}]+)\}\}", node.content or ""))
    haz = [
        t
        for t in tokens
        if ("hazard" in t or "erosion" in t or t.startswith("chart:hazard"))
        and not t.startswith("thememap:")
    ]
    assert haz  # the seed does carry the subsections
    for t in haz:
        assert get_variable(t) is not None or t in VARIABLE_ALIASES, t


def test_no_legacy_prefix_token_left_in_the_seed_hazard_subsections():
    seed = get_default_seed_tree()
    legacy = {
        "soil_loss_by_unit",
        "soil_loss_aoi_comparison",
        "soil_loss_methodology_narration",
        "soil_loss_findings_narration",
        "soil_loss_prescription_narration",
        "lsi_area_by_class",
        "lsi_by_unit",
        "hazard_aoi_comparison",
        "hh_priority_table",
        "hh_settlement_rollup_table",
        "hh_driver_counts",
        "fs_by_unit",
    }
    for node in TreeOperations.flatten(seed):
        toks = set(re.findall(r"\{\{([^}]+)\}\}", node.content or ""))
        assert not (toks & legacy), f"{node.title_en}: {toks & legacy}"
