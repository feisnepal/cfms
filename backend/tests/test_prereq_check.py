"""PrerequisiteChecker pure logic (P1 / §3.9.1). No DB.

The DB predicates (_has_processed_field_inventory, …) are covered by the
DB-backed overlay tests; here we exercise the aggregation + status machine.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.operational_plan import prereq_check as pc  # noqa: E402


def test_empty_requires_is_met():
    r = pc.check(None, None, [])
    assert r.met and r.status == "available" and r.copyable


def test_unknown_tag_is_unmet_not_silently_passed():
    r = pc.check(None, None, ["totally_made_up"])
    assert not r.met
    assert r.status == "partial"
    assert "totally_made_up" in r.unmet
    assert "Unknown prerequisite" in r.reason_en


def test_not_available_tag_is_red_and_not_copyable():
    r = pc.check(None, None, ["flow_accumulation"])
    assert not r.met
    assert r.status == "unavailable"
    assert not r.copyable
    assert "flow_accumulation" in r.unavailable
    assert r.reason_ne  # bilingual reason present


def test_mixed_tags_report_all_reasons():
    r = pc.check(None, None, ["flow_accumulation", "totally_made_up"])
    assert r.status == "unavailable"  # any unavailable wins
    assert r.unavailable == ["flow_accumulation"]
    assert r.unmet == ["totally_made_up"]


def test_known_db_tags_exist():
    for tag in ("field_inventory", "sub_areas", "compartments", "protected_sub_area"):
        assert tag in pc._CHECKS
        _pred, en, ne = pc._CHECKS[tag]
        assert en and ne


def test_check_spec_reads_requires_off_the_spec():
    from app.services.operational_plan.thematic_map_spec import resolve_spec

    spec = resolve_spec("thememap:unit__area")  # source="geometry", requires=[]
    r = pc.check_spec(None, None, spec)
    assert r.met
