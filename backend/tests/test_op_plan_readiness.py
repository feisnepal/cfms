"""A plan can say which of its own variables have no data — P0, plan §7.1.

The gap this closes: `resolve_node_content` substitutes `""` for both an unknown
key and a key with no data, so a statutory document renders a blank where a
measured figure belongs and nothing anywhere records it. The forest-scoped
`variable-catalog` cannot substitute either — it reports every registered key,
not the tokens this document uses, so a plan that uses three variables looks
identical to a plan that is genuinely ready.

Three buckets, because "not ready" has three causes and only one is actionable:

    missing      no data here            -> the user can go and collect it
    unmet_maps   spec `requires` unmet   -> delegated to prereq_check
    unverified   chart/table/map token   -> nothing checks it renders

The last one is the subtle one. Chart tokens are dispatched by `op_docx_builder`
and never resolved by the registry, so dropping them would let a plan whose only
defect is an unrenderable chart report "all variables resolved".
"""
from __future__ import annotations

import uuid

import pytest

from app.services.operational_plan.plan_readiness import classify_tokens, plan_readiness


# ── classify_tokens ───────────────────────────────────────────────────────
def _tree(*contents, children=None):
    return [{"title_en": "s", "content": c, "children": children or []} for c in contents]


def test_classify_splits_the_three_token_kinds():
    values, maps, opaque = classify_tokens(
        _tree(
            "Area is {{forest_area}} ha.",
            "See {{thememap:unit__growing_stock}}.",
            "Chart {{chart:volume_trend}} and table {{table:blocks}}.",
        )
    )
    assert values == {"forest_area"}
    assert maps == {"thememap:unit__growing_stock"}
    assert opaque == {"chart:volume_trend", "table:blocks"}


def test_classify_keeps_the_full_suffix_with_its_token():
    _values, maps, _opaque = classify_tokens(_tree("{{thememap:unit__growing_stock:full}}"))
    assert maps == {"thememap:unit__growing_stock:full"}


def test_classify_walks_nested_children():
    values, maps, opaque = classify_tokens(
        _tree("{{a}}", children=_tree("{{b}}", children=_tree("{{thememap:x}} {{chart:c}}")))
    )
    assert values == {"a", "b"}
    assert maps == {"thememap:x"}
    assert opaque == {"chart:c"}


def test_classify_walks_tree_node_objects():
    class Node:
        def __init__(self, content, children=()):
            self.content = content
            self.children = list(children)

    values, maps, _opaque = classify_tokens([Node("{{outer}}", [Node("{{opsmap:m}}")])])
    assert values == {"outer"}
    assert maps == {"opsmap:m"}


def test_classify_ignores_prose_and_empty_trees():
    assert classify_tokens([]) == (set(), set(), set())
    assert classify_tokens(None) == (set(), set(), set())
    assert classify_tokens(_tree("No tokens here.", "")) == (set(), set(), set())


def test_opsmap_and_thememap_are_map_tokens_not_values():
    # The bug `template_utils._extract_variables` has: it keeps these as if they
    # were plain values, which is why map failures were never reported.
    values, maps, _ = classify_tokens(_tree("{{thememap:a}} {{opsmap:b}}"))
    assert values == set()
    assert maps == {"thememap:a", "opsmap:b"}


# ── resolve_keys: absent vs None vs value ─────────────────────────────────
def test_resolve_keys_distinguishes_unknown_from_unresolvable(monkeypatch):
    """`resolve_node_content` collapses both to "". Readiness must not.

    A key missing from the result is a typo. A key present with the value None
    is registered but has no data. They need different messages.
    """
    from app.services.operational_plan.variable_registry import VARIABLE_REGISTRY
    from app.services.operational_plan.variable_resolver import VariableResolver

    known_key = next(iter(VARIABLE_REGISTRY))
    resolver = VariableResolver(None, None, None)
    monkeypatch.setattr(resolver, "_resolve_single", lambda var_def: None)

    out = resolver.resolve_keys([known_key, "definitely_not_registered_xyz"])
    assert known_key in out and out[known_key] is None
    assert "definitely_not_registered_xyz" not in out


def test_resolve_keys_returns_values_and_swallows_exceptions(monkeypatch):
    from app.services.operational_plan.variable_registry import VARIABLE_REGISTRY
    from app.services.operational_plan.variable_resolver import VariableResolver

    good, raising = list(VARIABLE_REGISTRY)[:2]
    resolver = VariableResolver(None, None, None)

    def _single(var_def):
        if var_def.key == raising:
            raise RuntimeError("collector blew up")
        return 42

    monkeypatch.setattr(resolver, "_resolve_single", _single)
    out = resolver.resolve_keys([good, raising])
    assert out[good] == 42
    assert out[raising] is None  # a broken collector is "no data", not a 500


# ── plan_readiness ────────────────────────────────────────────────────────
class _Plan:
    def __init__(self, sections):
        self.sections = sections
        self.calculation_id = uuid.uuid4()
        self.status = "draft"


@pytest.fixture()
def stub_resolver(monkeypatch):
    """Replace the registry resolution with a fixed value map."""
    import app.services.operational_plan.variable_resolver as vr

    def _install(values):
        class _Stub:
            def __init__(self, db, calculation_id, plan):
                pass

            def resolve_keys(self, keys):
                # Mirrors the real contract: only registered keys come back.
                return {k: values.get(k) for k in keys if k in values}

        monkeypatch.setattr(vr, "VariableResolver", _Stub)

    return _install


@pytest.fixture()
def stub_specs(monkeypatch):
    """Control `resolve_spec` and `check_spec` so map tokens need no DB."""
    import app.services.operational_plan.prereq_check as pc
    import app.services.operational_plan.thematic_map_spec as tms

    def _install(known: dict, met_by_token: dict):
        monkeypatch.setattr(tms, "resolve_spec", lambda key: known.get(key))
        seen = []

        def _check_spec(db, calc_id, spec):
            seen.append(spec)
            token_met = met_by_token.get(getattr(spec, "token", None), True)
            return pc.PrereqResult(
                status="available" if token_met else "partial",
                met=token_met,
                unmet=[] if token_met else ["field_inventory"],
                reason_en="No field inventory has been processed for this forest.",
                reason_ne="यस वनको क्षेत्र सर्वेक्षण प्रशोधन भइसकेको छैन।",
                hint_en="Upload and process a field inventory for this forest.",
                hint_ne="क्षेत्र सर्वेक्षण अपलोड गरी प्रशोधन गर्नुहोस्।",
            )

        monkeypatch.setattr(pc, "check_spec", _check_spec)
        return seen

    return _install


def test_ready_plan_reports_nothing_missing(stub_resolver, stub_specs):
    stub_resolver({"forest_area": 12.5})
    stub_specs({}, {})
    plan = _Plan({"tree": _tree("Area {{forest_area}} ha. {{thememap:m}}")})
    # thememap:m is not a known spec here, so expect it reported as unknown.
    out = plan_readiness(None, None, plan)
    assert out["total"] == 1
    assert out["resolved"] == 1
    assert out["missing"] == []
    assert out["ready"] is False  # the unknown map token blocks it
    assert out["unmet_maps"][0]["status"] == "unavailable"


def test_missing_data_and_unknown_key_are_distinguished(stub_resolver, stub_specs):
    stub_resolver({"has_data": 1, "no_data": None})
    stub_specs({}, {})
    plan = _Plan({"tree": _tree("{{has_data}} {{no_data}} {{typo_key}}")})
    out = plan_readiness(None, None, plan)
    by_key = {m["key"]: m for m in out["missing"]}
    assert set(by_key) == {"no_data", "typo_key"}
    assert by_key["no_data"]["known"] is True
    assert by_key["typo_key"]["known"] is False
    assert by_key["no_data"]["reason_ne"] and by_key["typo_key"]["reason_ne"]
    assert by_key["no_data"]["reason_en"] != by_key["typo_key"]["reason_en"]
    assert out["total"] == 3
    assert out["resolved"] == 1
    assert out["ready"] is False


def test_chart_and_table_tokens_are_counted_not_dropped(stub_resolver, stub_specs):
    """A plan whose only defect is an unrenderable chart must not read as ready."""
    stub_resolver({"forest_area": 3})
    stub_specs({}, {})
    plan = _Plan({"tree": _tree("{{forest_area}} {{chart:c}} {{table:t}} {{map:m}}")})
    out = plan_readiness(None, None, plan)
    assert out["unverified"] == 3
    assert out["unverified_tokens"] == ["chart:c", "map:m", "table:t"]
    assert out["missing"] == []
    # `unverified` is deliberately NOT part of `ready`: it is not a data gap the
    # user can close, so it must not masquerade as one, nor be hidden.
    assert out["ready"] is True


def test_unmet_map_prereq_is_surfaced_with_its_hint(stub_resolver, stub_specs):
    class _Spec:
        token = "thememap:needs_inventory"

    stub_resolver({})
    stub_specs({"thememap:needs_inventory": _Spec()}, {"thememap:needs_inventory": False})
    plan = _Plan({"tree": _tree("{{thememap:needs_inventory}}")})
    out = plan_readiness(None, None, plan)
    assert out["ready"] is False
    entry = out["unmet_maps"][0]
    assert entry["token"] == "thememap:needs_inventory"
    assert entry["status"] == "partial"
    assert entry["hint_en"] and entry["hint_ne"]
    assert entry["reason_en"] and entry["reason_ne"]


def test_full_suffix_is_stripped_before_spec_lookup(stub_resolver, stub_specs):
    """`resolve_spec` splits on the first colon, so `:full` must come off first."""

    class _Spec:
        token = "thememap:x"

    stub_resolver({})
    seen = stub_specs({"thememap:x": _Spec()}, {"thememap:x": False})
    plan = _Plan({"tree": _tree("{{thememap:x:full}}")})
    out = plan_readiness(None, None, plan)
    assert out["unmet_maps"][0]["token"] == "thememap:x:full"
    assert len(seen) == 1  # the spec was found, not reported as unregistered


def test_empty_plan_is_ready_and_zeroed(stub_resolver, stub_specs):
    stub_resolver({})
    stub_specs({}, {})
    out = plan_readiness(None, None, _Plan({"tree": []}))
    assert out == {
        "total": 0,
        "resolved": 0,
        "missing": [],
        "empty_lists": [],
        "unverified": 0,
        "unverified_tokens": [],
        "unmet_maps": [],
        "ready": True,
    }


def test_empty_list_is_reported_but_does_not_block_ready(stub_resolver, stub_specs):
    """ND-7 (owner 2026-10-18): an empty list is a legitimate state, not a data gap."""
    stub_resolver({"forest_area": 3, "uc_members": []})
    stub_specs({}, {})
    plan = _Plan({"tree": _tree("{{forest_area}} {{uc_members}}")})
    out = plan_readiness(None, None, plan)
    assert out["missing"] == []
    assert [e["key"] for e in out["empty_lists"]] == ["uc_members"]
    assert out["total"] == 2
    assert out["resolved"] == 1  # only the non-empty value counts as resolved
    assert out["ready"] is True  # the empty list must not block the plan


def test_missing_sections_key_is_treated_as_empty(stub_resolver, stub_specs):
    stub_resolver({})
    stub_specs({}, {})
    assert plan_readiness(None, None, _Plan({}))["total"] == 0
    assert plan_readiness(None, None, _Plan({"tree": None}))["total"] == 0


def test_never_raises(monkeypatch):
    """A readiness check that 500s takes the page down with it."""

    class _Exploding:
        @property
        def sections(self):
            raise RuntimeError("sections is corrupt")

    out = plan_readiness(None, None, _Exploding())
    assert out["ready"] is False
    assert out["missing"] == []


def test_resolution_failure_degrades_to_all_missing(monkeypatch):
    """A collector blowing up must not be reported as "everything is fine"."""
    import app.services.operational_plan.variable_resolver as vr

    class _Boom:
        def __init__(self, db, calculation_id, plan):
            pass

        def resolve_keys(self, keys):
            raise RuntimeError("collector blew up")

    monkeypatch.setattr(vr, "VariableResolver", _Boom)
    out = plan_readiness(None, None, _Plan({"tree": _tree("{{forest_area}}")}))
    assert out["total"] == 1
    assert out["resolved"] == 0
    assert out["ready"] is False


# ── the new biodiversity predicate ────────────────────────────────────────
def test_biodiversity_tag_is_registered_with_a_predicate():
    from app.services.operational_plan.prereq_check import _TAGS

    tag = _TAGS["biodiversity_data"]
    assert tag.predicate is not None, "a None predicate renders as permanently red"
    for field in (tag.reason_en, tag.reason_ne, tag.hint_en, tag.hint_ne):
        assert field.strip()
    assert tag.reason_en != tag.reason_ne, "a bilingual tag with one language is a bug"


def test_biodiversity_predicate_reads_the_species_table(db):
    from app.models.biodiversity import BiodiversitySpecies, CalculationBiodiversity
    from app.models.calculation import Calculation
    from app.models.user import User
    from app.services.operational_plan.prereq_check import _has_biodiversity_data

    owner = User(
        email=f"biodiv-{uuid.uuid4().hex[:10]}@example.com",
        hashed_password="not-a-real-hash",
        full_name="Biodiversity Fixture",
    )
    db.add(owner)
    db.flush()
    calc = Calculation(
        user_id=owner.id, forest_name=f"Biodiv CF {uuid.uuid4().hex[:6]}"
    )
    db.add(calc)
    db.flush()

    assert _has_biodiversity_data(db, calc.id) is False

    species = BiodiversitySpecies(
        category="vegetation",
        sub_category="tree",
        nepali_name="पीलो",
        english_name="Yellow birch",
        scientific_name="Betula lutea",
    )
    db.add(species)
    db.flush()
    db.add(CalculationBiodiversity(calculation_id=calc.id, species_id=species.id))
    db.commit()

    assert _has_biodiversity_data(db, calc.id) is True
    # Scoped to the forest, not "any row anywhere".
    other = Calculation(
        user_id=owner.id, forest_name=f"Other CF {uuid.uuid4().hex[:6]}"
    )
    db.add(other)
    db.flush()
    assert _has_biodiversity_data(db, other.id) is False


def test_a_section_token_in_its_full_form_gets_the_registered_label():
    """The export warning listed "section:aspect_analysis:full" raw: the registry holds "section:aspect_analysis"."""
    from app.services.operational_plan.plan_readiness import _missing_entry

    entry = _missing_entry("section:aspect_analysis:full", True)
    assert entry["label_en"] == "Aspect Analysis Section"
    assert entry["label_ne"] != "section:aspect_analysis:full"
