"""NTFP inventory, phase 5b: the annual harvest plan and its links to cost-benefit and the yearly plan (``/ntfp/harvest-plan``)."""
from app.models.cost_benefit import CBABenefitItem, CostBenefitAnalysis
from app.models.ntfp_method import NtfpHarvestPlan
from app.models.op_data_cache import OpDataCache
from app.models.yearly_activities import PotentialActivity, ProposedYearlyActivity
from app.services.cost_benefit.repopulate import repopulate_scenario
from app.services.ntfp_harvest_service import COLLECTION_ACTIVITY_EN
from tests.integration.test_ntfp_design_api import BODY, _calc, _register, _seed_profiles
from tests.integration.test_ntfp_results_api import _upload_counts

TIMUR = "zanthoxylum armatum"


def _surveyed(client, db, with_weights=True):
    """A forest with a design, counts of 3 on every plot, and (optionally) timur weights."""
    _seed_profiles(db)
    headers, uid = _register(client)
    calc = _calc(db, uid)
    design = client.post(f"/api/calculations/{calc.id}/ntfp/design", json=BODY, headers=headers).json()
    first = next(p["plot_number"] for p in design["plots"] if TIMUR in p["species_keys"])
    weights = [(first, TIMUR, 800, 300), (first, TIMUR, 900, 330)] if with_weights else None
    _upload_counts(client, headers, calc, weights=weights)
    return headers, uid, calc


def _put(client, headers, calc, rows):
    return client.put(f"/api/calculations/{calc.id}/ntfp/harvest-plan", json={"rows": rows}, headers=headers)


def _row(qty, **kw):
    return {"species_key": TIMUR, "part_group": "ङ", "annual_quantity": qty, "unit": "kg", "weight_basis": "dry", **kw}


def test_only_surveyed_parts_can_be_planned(client, db):
    headers, _, calc = _surveyed(client, db, with_weights=False)
    got = client.get(f"/api/calculations/{calc.id}/ntfp/harvest-plan", headers=headers).json()
    assert got["rows"] == [] and got["totals"]["rows_planned"] == 0
    r = _put(client, headers, calc, [_row(10)])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "harvest.unknown_row"


def test_the_plan_page_shows_stock_rate_and_the_plan_with_its_value(client, db):
    headers, _, calc = _surveyed(client, db)
    rows = client.get(f"/api/calculations/{calc.id}/ntfp/harvest-plan", headers=headers).json()["rows"]
    row = next(r for r in rows if r["species_key"] == TIMUR)
    assert row["part_group"] == "ङ" and row["stock_dry_kg"] > 0 and row["stock_fresh_kg"] > row["stock_dry_kg"]
    rate = row["price"]["npr_per_unit"]
    assert row["price"]["basis"] == "schedule7" and row["plan"] is None

    r = _put(client, headers, calc, [_row(100)])
    assert r.status_code == 200, r.text
    got = r.json()
    planned = next(x for x in got["rows"] if x["species_key"] == TIMUR)
    assert planned["plan"]["annual_quantity"] == 100 and planned["value_npr_per_year"] == round(100 * rate, 2)
    assert got["totals"] == {"rows_planned": 1, "kg_per_year": 100.0, "value_npr_per_year": round(100 * rate, 2)}


def test_an_owner_price_replaces_the_rate(client, db):
    headers, _, calc = _surveyed(client, db)
    got = _put(client, headers, calc, [_row(100, price_override=40)]).json()
    planned = next(x for x in got["rows"] if x["species_key"] == TIMUR)
    assert planned["price"]["basis"] == "owner" and planned["value_npr_per_year"] == 4000.0


def test_refusals_write_nothing(client, db):
    headers, _, calc = _surveyed(client, db)
    assert _put(client, headers, calc, [_row(100)]).status_code == 200
    stock = next(r for r in client.get(f"/api/calculations/{calc.id}/ntfp/harvest-plan", headers=headers).json()["rows"] if r["species_key"] == TIMUR)["stock_dry_kg"]
    r = _put(client, headers, calc, [_row(stock + 1)])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "harvest.exceeds_stock"
    r = _put(client, headers, calc, [_row(5), _row(6)])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "harvest.duplicate"
    assert _put(client, headers, calc, [_row(-1)]).status_code == 422                       # refused by the request model
    assert _put(client, headers, calc, [_row(5, unit="litre")]).status_code == 422
    assert client.get(f"/api/calculations/{calc.id}/ntfp/harvest-plan", headers=headers).json()["totals"]["kg_per_year"] == 100.0   # the earlier plan stands


def test_saving_replaces_the_plan_and_zero_removes_a_row(client, db):
    headers, _, calc = _surveyed(client, db)
    _put(client, headers, calc, [_row(100)])
    _put(client, headers, calc, [_row(250)])
    assert db.query(NtfpHarvestPlan).filter_by(calculation_id=calc.id).count() == 1
    assert client.get(f"/api/calculations/{calc.id}/ntfp/harvest-plan", headers=headers).json()["totals"]["kg_per_year"] == 250.0
    _put(client, headers, calc, [_row(0)])
    assert db.query(NtfpHarvestPlan).filter_by(calculation_id=calc.id).count() == 0


def test_saving_clears_the_plans_cache(client, db):
    headers, _, calc = _surveyed(client, db)
    db.add(OpDataCache(calculation_id=calc.id, data={"_cache_version": 1}))
    db.commit()
    _put(client, headers, calc, [_row(10)])
    assert db.query(OpDataCache).filter_by(calculation_id=calc.id).count() == 0


# ── cost-benefit ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _benefits(db, cba):
    db.expire_all()
    return {b.source_link: b for b in db.query(CBABenefitItem).filter(CBABenefitItem.cba_id == cba.id, CBABenefitItem.source == "ntfp").all()}


def test_the_harvest_plan_becomes_cost_benefit_benefit_rows_and_follows_the_plan(client, db):
    headers, _, calc = _surveyed(client, db)
    cba = CostBenefitAnalysis(calculation_id=calc.id, name="Base", is_base_scenario=True)
    db.add(cba)
    db.commit()
    repopulate_scenario(cba.id, db)
    assert _benefits(db, cba) == {}                                          # no harvest plan: no NTFP benefit

    rate = next(r for r in client.get(f"/api/calculations/{calc.id}/ntfp/harvest-plan", headers=headers).json()["rows"] if r["species_key"] == TIMUR)["price"]["npr_per_unit"]
    _put(client, headers, calc, [_row(100)])
    repopulate_scenario(cba.id, db)
    got = _benefits(db, cba)
    assert list(got) == [f"ntfp:{TIMUR}:ङ"]
    b = got[f"ntfp:{TIMUR}:ङ"]
    assert float(b.quantity) == 100.0 and float(b.unit_price) == rate and float(b.amount_per_year) == round(100 * rate, 2)
    assert (b.year_from, b.year_to) == (1, 10) and "सुक्खा" in b.description

    _put(client, headers, calc, [_row(200, weight_basis="fresh")])
    repopulate_scenario(cba.id, db)
    b = _benefits(db, cba)[f"ntfp:{TIMUR}:ङ"]
    assert float(b.quantity) == 200.0 and "ताजा" in b.description

    _put(client, headers, calc, [])
    repopulate_scenario(cba.id, db)
    assert _benefits(db, cba) == {}                                          # the plan is gone: so is the row


def test_a_manual_cost_benefit_row_is_never_touched(client, db):
    headers, _, calc = _surveyed(client, db)
    cba = CostBenefitAnalysis(calculation_id=calc.id, name="Base", is_base_scenario=True)
    db.add(cba)
    db.commit()
    db.add(CBABenefitItem(cba_id=cba.id, source="ntfp", description="my own", year_from=1, year_to=10, quantity=1, unit_price=1, amount_per_year=1, source_link=None))
    db.commit()
    _put(client, headers, calc, [_row(100)])
    repopulate_scenario(cba.id, db)
    assert db.query(CBABenefitItem).filter(CBABenefitItem.cba_id == cba.id, CBABenefitItem.description == "my own").count() == 1


# ── the yearly plan ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def _master(db):
    m = db.query(PotentialActivity).filter(PotentialActivity.name_en == COLLECTION_ACTIVITY_EN).first()
    if m is None:
        m = PotentialActivity(activities="गैरकाष्ठ वनपैदावार संकलन", name_en=COLLECTION_ACTIVITY_EN, unit="के.जी.", map_kind="ntfp_zone")
        db.add(m)
        db.commit()
    return m


def test_the_collection_line_is_made_once_with_the_total_kilograms(client, db):
    headers, _, calc = _surveyed(client, db)
    master = _master(db)
    url = f"/api/calculations/{calc.id}/ntfp/harvest-plan/yearly-plan"
    r = client.post(url, headers=headers)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "harvest.nothing_planned"    # nothing planned yet

    _put(client, headers, calc, [_row(100)])
    r = client.post(url, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["created"] is True and r.json()["quantity"] == 100.0
    line = db.query(ProposedYearlyActivity).filter_by(calculation_id=calc.id, potential_activity_id=master.id).one()
    assert float(line.default_quantity) == 100.0 and float(line.default_yearly_budget) == 0.0
    assert len(line.year_details) == 10 and all(float(d.quantity) == 100.0 for d in line.year_details)   # every year of the plan

    _put(client, headers, calc, [_row(300)])
    again = client.post(url, headers=headers).json()
    assert again["created"] is False and again["quantity"] == 100.0       # the owner's line is not overwritten
    assert db.query(ProposedYearlyActivity).filter_by(calculation_id=calc.id, potential_activity_id=master.id).count() == 1


def test_a_stranger_cannot_read_or_change_the_plan(client, db):
    headers, _, calc = _surveyed(client, db)
    other, _ = _register(client)
    base = f"/api/calculations/{calc.id}/ntfp/harvest-plan"
    assert client.get(base, headers=other).status_code == 403
    assert client.put(base, json={"rows": []}, headers=other).status_code == 403
    assert client.post(base + "/yearly-plan", headers=other).status_code == 403
