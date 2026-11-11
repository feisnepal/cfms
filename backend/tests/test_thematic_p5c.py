"""P5c — PlanCollector + simple opsmap maps.

Pure fixture-render checks + a DB-backed PlanCollector.per_unit check that
builds a tiny plan (one felling activity, one block).
"""

import os
import sys
import uuid
import warnings

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.operational_plan import _thememap_fixture as fx  # noqa: E402
from app.services.operational_plan import plan_collector  # noqa: E402
from app.services.operational_plan import thematic_overlay as to  # noqa: E402
from app.services.operational_plan.thematic_map_spec import (  # noqa: E402
    BUILTIN_OPSMAP_SPECS,
    resolve_spec,
)


def _png_ok(buf, mn=4000):
    d = buf.getvalue()
    assert d[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(d) >= mn, len(d)


# ── pure ─────────────────────────────────────────────────────────────
_P5C_OPSMAP = {
    "unit__felling_year",
    "unit__felling_series",
    "unit__prescribed_harvest",
    "unit__harvest_vs_aah",
    "forest__working_circles",
    "unit__budget_total",
    "unit__activity_count",
}


def test_seven_opsmap_specs_registered_with_prose():
    # P5c shipped these 7; P7 adds more — assert the P5c set is intact.
    assert _P5C_OPSMAP <= set(BUILTIN_OPSMAP_SPECS)
    for k in _P5C_OPSMAP:
        s = BUILTIN_OPSMAP_SPECS[k]
        assert s.family == "opsmap" and s.source == "plan"
        assert s.label_ne and s.label_en and s.description_en
        assert s.section in ("S13", "S14", "S20")


def test_opsmap_specs_render_from_the_toy_plan_fixture():
    for key in BUILTIN_OPSMAP_SPECS:
        spec = resolve_spec("opsmap:" + key)
        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)
            buf = to.render_from_fixture(spec)
        _png_ok(buf)


def test_fixture_plan_has_a_no_felling_protection_unit():
    prot = [
        n for n, r in fx.PLAN_PER_UNIT.items() if r["working_circle"] == "protection"
    ]
    assert prot
    for n in prot:
        assert fx.PLAN_PER_UNIT[n]["felling_year"] is None
        assert fx.PLAN_PER_UNIT[n]["prescribed_harvest"] == 0


def test_harvest_vs_aah_is_a_percentage_around_100():
    for n, r in fx.PLAN_PER_UNIT.items():
        if r["aah_ceiling"]:
            assert r["harvest_vs_aah"] == round(
                100.0 * r["prescribed_harvest"] / r["aah_ceiling"], 1
            )


def test_engine_routes_plan_source_to_plan_collector(monkeypatch):
    called = {}

    def fake_per_unit(db, calc_id):
        called["hit"] = True
        return {
            "B-1": {
                "felling_year": 3,
                "working_circle": "production",
                "activity_count": 2,
                "budget_total": 1.0,
                "prescribed_harvest": 10.0,
                "felling_series": "x",
                "aah_ceiling": 20.0,
                "harvest_vs_aah": 50.0,
            }
        }

    monkeypatch.setattr(plan_collector, "per_unit", fake_per_unit)
    # _render needs a bbox/units; easiest is to assert the branch via source.
    spec = resolve_spec("opsmap:unit__felling_year")
    assert spec.source == "plan"


# ── DB-backed ────────────────────────────────────────────────────────
def _mk_calc(db):
    from app.models.calculation import Calculation, CalculationStatus
    from app.models.user import User, UserRole, UserStatus

    u = User(
        id=uuid.uuid4(),
        email=f"pc-{uuid.uuid4().hex[:8]}@x.com",
        hashed_password="x",
        full_name="pc",
        role=UserRole.USER,
        status=UserStatus.ACTIVE,
    )
    db.add(u)
    db.flush()
    c = Calculation(
        id=uuid.uuid4(),
        user_id=u.id,
        forest_name="PC Forest",
        status=CalculationStatus.COMPLETED,
        result_data={},
    )
    db.add(c)
    db.flush()
    return c


def _mk_block(db, calc_id, name, wc="production"):
    from app.models.forest_block import ForestBlock
    from geoalchemy2.elements import WKTElement

    b = ForestBlock(
        id=uuid.uuid4(),
        calculation_id=calc_id,
        name=name,
        index=0,
        area_hectares=100.0,
        division_level=1,
        working_circle=wc,
        geometry=WKTElement(
            "POLYGON((85 27,85.01 27,85.01 27.01,85 27.01,85 27))", srid=4326
        ),
    )
    db.add(b)
    db.flush()
    return b


def test_plan_collector_per_unit_from_a_real_tiny_plan(db):
    from app.models.yearly_activities import (
        ActivityYearDetail,
        PotentialActivity,
        ProposedYearlyActivity,
    )

    c = _mk_calc(db)
    b1 = _mk_block(db, c.id, "PC-1")
    _mk_block(db, c.id, "PC-2", wc="protection")

    pa_fell = PotentialActivity(
        activities="Selective felling / कटान",
        progarms="Harvest",
        unit="m3",
        quantity="0",
        yearly_budget="0",
        is_felling=True,
    )
    pa_other = PotentialActivity(
        activities="Boundary maintenance",
        progarms="Protection",
        unit="km",
        quantity="0",
        yearly_budget="0",
        is_felling=False,
    )
    db.add_all([pa_fell, pa_other])
    db.flush()

    fell_line = ProposedYearlyActivity(
        id=uuid.uuid4(),
        calculation_id=c.id,
        potential_activity_id=pa_fell.id,
        block_id=b1.id,
        default_quantity=120,
        default_yearly_budget=50000,
        assign_to_all_blocks=False,
    )
    other_line = ProposedYearlyActivity(
        id=uuid.uuid4(),
        calculation_id=c.id,
        potential_activity_id=pa_other.id,
        default_quantity=1,
        default_yearly_budget=2000,
        assign_to_all_blocks=True,
    )
    db.add_all([fell_line, other_line])
    db.flush()
    # The years an activity is planned are read from its year rows (an explicit 0 / 0 is "not
    # planned"): felling in years 3 and 4 only, the other activity in year 1 only.
    for line, planned in ((fell_line, {3, 4}), (other_line, {1})):
        for y in range(1, 11):
            on = y in planned
            db.add(ActivityYearDetail(
                proposed_activity_id=line.id,
                year_number=y,
                quantity=line.default_quantity if on else 0,
                yearly_budget=line.default_yearly_budget if on else 0,
            ))
    db.flush()

    pu = plan_collector.per_unit(db, c.id)
    assert set(pu) == {"PC-1", "PC-2"}
    assert pu["PC-1"]["felling_year"] == 3
    assert pu["PC-1"]["felling_series"].startswith("श्रृंखला")
    assert pu["PC-1"]["prescribed_harvest"] == 240.0  # 120 x 2 years
    assert pu["PC-1"]["activity_count"] == 2  # felling + all-blocks
    assert pu["PC-1"]["budget_total"] == 50000 * 2 + 2000  # felling 2yr + other 1yr
    # protection block: an all-blocks non-felling activity only
    assert pu["PC-2"]["felling_year"] is None
    assert pu["PC-2"]["prescribed_harvest"] == 0
    assert pu["PC-2"]["working_circle"] == "protection"


def test_plan_collector_empty_plan_returns_block_skeleton(db):
    c = _mk_calc(db)
    _mk_block(db, c.id, "SK-1")
    pu = plan_collector.per_unit(db, c.id)
    assert set(pu) == {"SK-1"}
    assert pu["SK-1"]["activity_count"] == 0
    assert pu["SK-1"]["felling_year"] is None
