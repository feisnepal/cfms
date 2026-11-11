"""SUSTAINABLE_FOREST_MANAGEMENT_PLAN P8 — the SFM variable-coverage gate.

Every block the Sustainable Forest Management tab renders (headline numbers,
maps, tables, narrative) MUST be an OP template variable a designer can drop
into a plan. This fails the build if a future tab block ships without one.

The manifest is ``app.api.sustainable_fm.SFM_VARIABLE_GROUPS`` (the same source
the in-context reference page reads) + the ``sfm__*`` thematic map specs.
"""

from __future__ import annotations

import re
import uuid

import pytest

from app.api.sustainable_fm import SFM_VARIABLE_GROUPS
from app.services.operational_plan.seed_data import get_default_seed_tree
from app.services.operational_plan.thematic_map_spec import BUILTIN_THEMEMAP_SPECS
from app.services.operational_plan.tree_models import TreeOperations
from app.services.operational_plan.variable_enrichment import SUB_GROUPS
from app.services.operational_plan.variable_registry import get_variable
from app.services.operational_plan.variable_resolver import VariableResolver

_MANIFEST_KEYS = [k for _gid, _ne, _en, keys in SFM_VARIABLE_GROUPS for k in keys]

# an empty-state collector payload — every sfm_* key present, tables [], scalars ""
_RAW = {
    "sustainable_fm": {k: ([] if k.endswith("_table") else "") for k in _MANIFEST_KEYS}
}


def _resolver() -> VariableResolver:
    r = VariableResolver(db=None, calculation_id=uuid.uuid4(), plan=None)
    r._raw_data = _RAW
    return r


@pytest.mark.parametrize("key", _MANIFEST_KEYS)
def test_every_manifest_key_is_a_registered_variable(key):
    assert get_variable(key) is not None, f"{key} is on the tab but not registered"


@pytest.mark.parametrize("key", _MANIFEST_KEYS)
def test_every_manifest_key_has_an_enrichment_sub_group(key):
    assert SUB_GROUPS.get(key, "").startswith("3.10"), key


@pytest.mark.parametrize("key", _MANIFEST_KEYS)
def test_every_manifest_key_resolves_without_error(key):
    # None is fine (no data); an exception is not
    _resolver()._resolve_single(get_variable(key))


def test_manifest_covers_numbers_tables_and_narrative():
    gids = {gid for gid, _ne, _en, _keys in SFM_VARIABLE_GROUPS}
    assert {"numbers", "tables", "narrative"} <= gids


def test_the_three_sfm_map_specs_are_registered_thematic_specs():
    page_maps = [
        s.token for k, s in BUILTIN_THEMEMAP_SPECS.items() if k.startswith("sfm__")
    ]
    assert set(page_maps) == {
        "thememap:sfm__forest_type",
        "thememap:sfm__orientation",
        "thememap:sfm__gs_vs_threshold",
    }


def _seed_310_tokens() -> set[str]:
    for node in TreeOperations.flatten(get_default_seed_tree()):
        if "Sustainable Forest Management" in (node.title_en or ""):
            return set(re.findall(r"\{\{([^}]+)\}\}", node.content or ""))
    raise AssertionError("the ३.१० subsection is missing from the seed tree")


def test_seed_310_uses_only_registered_sfm_tokens_or_a_map_spec():
    for tok in _seed_310_tokens():
        if tok.startswith("thememap:"):
            assert tok.split(":", 1)[1] in BUILTIN_THEMEMAP_SPECS, tok
        else:
            assert get_variable(tok) is not None, tok


def test_seed_310_carries_no_non_sfm_hazard_or_rusle_token():
    stray = [
        t
        for t in _seed_310_tokens()
        if not t.startswith(("sfm_", "thememap:sfm__"))
        and (
            "hazard" in t
            or "erosion" in t
            or "soil_loss" in t
            or "lsi_" in t
            or "fs_" in t
        )
    ]
    assert stray == [], f"the ३.१० subsection leaked a hazard/rusle token: {stray}"


def test_manifest_keys_reach_the_seed_310_subsection():
    """Every manifest number/table/narrative key is either placed in the seed
    ३.१० subsection or is deliberately designer-only (dominant_type_en,
    working_circle_table) — those two are the only allowed absences."""
    placed = _seed_310_tokens()
    allowed_absent = {"sfm_dominant_type_en", "sfm_working_circle_table"}
    missing = [k for k in _MANIFEST_KEYS if k not in placed and k not in allowed_absent]
    assert missing == [], f"manifest keys not in the seed ३.१०: {missing}"
