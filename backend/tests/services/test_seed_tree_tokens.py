"""The default OP seed tree only uses registered variables.

Guards the template that `create_operational_plan` falls back to. Also pins
the protection-area subsection added for the protected-area sampling series
(#18-#22) so the `{{fi_protected_*}}` / `{{ti_protected_*}}` tokens stay in it.
"""
from __future__ import annotations

import re

from app.services.operational_plan.seed_data import get_default_seed_tree
from app.services.operational_plan.variable_registry import VARIABLE_REGISTRY

_TOKEN = re.compile(r"\{\{([^}]+)\}\}")


def _all_tokens():
    def walk(nodes):
        for n in nodes:
            for m in _TOKEN.findall(n.content or ""):
                yield m.strip()
            yield from walk(n.children or [])

    return set(walk(get_default_seed_tree()))


def test_seed_tree_has_no_unregistered_tokens():
    unknown = sorted(
        t for t in _all_tokens()
        if t not in VARIABLE_REGISTRY
        and not t.startswith(("chart:", "map:", "table:", "thememap:", "opsmap:"))
        and not t.endswith(":full")
    )
    assert unknown == [], f"seed tree references unregistered variables: {unknown}"


def test_protection_working_circle_tokens_are_in_the_seed_tree():
    """The ३.७ Protection Working Circle subsection (protected-area sampling +
    PROTECTION_WORKING_CIRCLE_PLAN.md P4)."""
    toks = _all_tokens()
    for t in (
        "fi_protected_stratum_note",
        "fi_protected_stratum_table",
        "fi_protected_growing_stock_m3_per_ha",
        "ti_protected_growing_stock_m3",
        # P4 — working-circle framing
        "fi_protection_units",
        "ti_production_area_ha",
        "ti_protection_working_circle_area_ha",
    ):
        assert t in toks, f"{t} missing from the default OP seed tree"
