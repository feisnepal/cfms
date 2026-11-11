"""Cost-Benefit Analysis API (CBA_MODULE_PLAN.md P3).

Covers scenario CRUD, cost/benefit item CRUD, auto-populate, compute, clone,
set-base, compare and export-data, plus access control and the OpDataCache
invalidation contract.
"""

from __future__ import annotations

import uuid

from app.models.calculation import Calculation
from app.models.field_inventory import (
    FieldInventoryBlockSummary,
    FieldInventoryCalculation,
)
from app.models.op_data_cache import OpDataCache
from app.models.user import User
from app.models.yearly_activities import PotentialActivity, ProposedYearlyActivity


def _owner(client, db):
    email = f"cba-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "TestPass123!", "full_name": "CBA"},
    )
    resp = client.post(
        "/api/auth/login", json={"email": email, "password": "TestPass123!"}
    )
    assert resp.status_code == 200, resp.text
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    user = db.query(User).filter(User.email == email).first()
    return headers, user


def _calc(db, user):
    c = Calculation(user_id=user.id, uploaded_filename="cba.csv", forest_name="CBA CF")
    db.add(c)
    db.commit()
    return c


def _seed_sources(db, calc, user):
    for prog, name, budget in [
        ("वन संवर्द्धन", "Thinning", 5000),
        ("उद्यम विकास", "Nursery", 8000),
    ]:
        pa = PotentialActivity(progarms=prog, activities=name, display_order=0)
        db.add(pa)
        db.flush()
        db.add(
            ProposedYearlyActivity(
                calculation_id=calc.id,
                potential_activity_id=pa.id,
                default_quantity=1,
                default_yearly_budget=budget,
            )
        )
    fic = FieldInventoryCalculation(
        calculation_id=calc.id, user_id=user.id, uploaded_filename="fi.csv"
    )
    db.add(fic)
    db.flush()
    db.add(
        FieldInventoryBlockSummary(
            field_inventory_calculation_id=fic.id,
            block_name="Block A",
            total_sample_plots=3,
            tree_timber_m3_per_ha=50,
            pole_timber_m3_per_ha=0,
            tree_firewood_m3_per_ha=30,
            pole_firewood_m3_per_ha=0,
            co2_equivalent_tco2_per_ha=10,
        )
    )
    db.commit()


def _create_scenario(client, headers, calc_id, **over):
    body = {"name": "Base Scenario", "discount_rate": 10.0}
    body.update(over)
    r = client.post(f"/api/calculations/{calc_id}/cba", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


# ── scenario CRUD ─────────────────────────────────────────────────────────


def test_first_scenario_is_base_and_lists(client, db):
    headers, user = _owner(client, db)
    calc = _calc(db, user)

    s1 = _create_scenario(client, headers, calc.id)
    assert s1["is_base_scenario"] is True
    s2 = _create_scenario(client, headers, calc.id, name="High Harvest")
    assert s2["is_base_scenario"] is False

    r = client.get(f"/api/calculations/{calc.id}/cba", headers=headers)
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 2
    assert {row["name"] for row in rows} == {"Base Scenario", "High Harvest"}
    assert rows[0]["cost_count"] == 0 and rows[0]["has_result"] is False


def test_get_update_delete_scenario(client, db):
    headers, user = _owner(client, db)
    calc = _calc(db, user)
    s = _create_scenario(client, headers, calc.id)

    r = client.get(f"/api/calculations/{calc.id}/cba/{s['id']}", headers=headers)
    assert r.status_code == 200
    assert r.json()["discount_rate"] == "10.00"

    r = client.put(
        f"/api/calculations/{calc.id}/cba/{s['id']}",
        json={"discount_rate": 12.5, "name": "Renamed"},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["discount_rate"] == "12.50"
    assert r.json()["name"] == "Renamed"

    r = client.delete(f"/api/calculations/{calc.id}/cba/{s['id']}", headers=headers)
    assert r.status_code == 204
    r = client.get(f"/api/calculations/{calc.id}/cba/{s['id']}", headers=headers)
    assert r.status_code == 404


# ── items ─────────────────────────────────────────────────────────────────


def test_cost_and_benefit_item_crud_computes_total(client, db):
    headers, user = _owner(client, db)
    calc = _calc(db, user)
    s = _create_scenario(client, headers, calc.id)

    r = client.post(
        f"/api/cba/{s['id']}/costs",
        json={
            "category": "Harvest",
            "description": "Felling",
            "year_from": 1,
            "year_to": 5,
            "amount_per_year": 20000,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    cost = r.json()
    assert float(cost["total_amount"]) == 100000.0  # 20000 * 5 years

    r = client.put(
        f"/api/cba/{s['id']}/costs/{cost['id']}",
        json={"amount_per_year": 30000},
        headers=headers,
    )
    assert float(r.json()["total_amount"]) == 150000.0

    r = client.post(
        f"/api/cba/{s['id']}/benefits",
        json={
            "source": "timber",
            "year_from": 1,
            "year_to": 10,
            "quantity": 12,
            "unit_price": 8000,
            "amount_per_year": 0,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    ben = r.json()
    assert float(ben["total_amount"]) == 960000.0  # 12*8000 * 10 years

    r = client.get(f"/api/cba/{s['id']}/costs", headers=headers)
    assert len(r.json()) == 1
    r = client.get(f"/api/cba/{s['id']}/benefits", headers=headers)
    assert len(r.json()) == 1

    r = client.delete(f"/api/cba/{s['id']}/costs/{cost['id']}", headers=headers)
    assert r.status_code == 204
    r = client.get(f"/api/cba/{s['id']}/costs", headers=headers)
    assert r.json() == []


# ── auto-populate / compute ──────────────────────────────────────────────


def test_auto_populate_then_compute(client, db):
    headers, user = _owner(client, db)
    calc = _calc(db, user)
    _seed_sources(db, calc, user)
    s = _create_scenario(client, headers, calc.id)

    r = client.post(f"/api/cba/{s['id']}/auto-populate", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["inserted"]["costs"] == 2
    assert r.json()["inserted"]["benefits"] == 3

    r = client.post(f"/api/cba/{s['id']}/compute", headers=headers)
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["npv"] is not None
    assert res["total_cost_pv"] is not None
    assert len(res["cash_flow_data"]) == 10

    # result surfaces in the list
    r = client.get(f"/api/calculations/{calc.id}/cba", headers=headers)
    assert r.json()[0]["has_result"] is True
    assert r.json()[0]["npv"] is not None


def test_export_data_shape(client, db):
    headers, user = _owner(client, db)
    calc = _calc(db, user)
    _seed_sources(db, calc, user)
    s = _create_scenario(client, headers, calc.id)
    client.post(f"/api/cba/{s['id']}/auto-populate", headers=headers)
    client.post(f"/api/cba/{s['id']}/compute", headers=headers)

    r = client.get(f"/api/cba/{s['id']}/export-data", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    inds = [row["indicator"] for row in data["summary_table"]]
    assert "Net Present Value (NPV)" in inds
    assert "Benefit-Cost Ratio (B/C)" in inds
    assert "Total Benefit (Undiscounted)" in inds
    assert len(data["cash_flow_table"]) == 10
    assert data["benefit_breakdown"]  # grouped by source
    assert {b["label"] for b in data["benefit_breakdown"]} <= {
        "timber",
        "fuelwood",
        "carbon",
    }


# ── clone / set-base / compare ───────────────────────────────────────────


def test_clone_deep_copies_items_and_resets_result(client, db):
    headers, user = _owner(client, db)
    calc = _calc(db, user)
    _seed_sources(db, calc, user)
    s = _create_scenario(client, headers, calc.id)
    client.post(f"/api/cba/{s['id']}/auto-populate", headers=headers)
    client.post(f"/api/cba/{s['id']}/compute", headers=headers)

    r = client.post(
        f"/api/calculations/{calc.id}/cba/{s['id']}/clone",
        json={},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    clone = r.json()
    assert clone["name"] == "Base Scenario (Copy)"
    assert clone["is_base_scenario"] is False
    assert clone["result"] is None
    assert len(clone["cost_items"]) == len(
        client.get(f"/api/cba/{s['id']}/costs", headers=headers).json()
    )
    # source_link carried over
    assert all(
        c["source_link"] and c["source_link"].startswith("activity:")
        for c in clone["cost_items"]
    )


def test_set_base_keeps_exactly_one_base(client, db):
    headers, user = _owner(client, db)
    calc = _calc(db, user)
    a = _create_scenario(client, headers, calc.id)
    b = _create_scenario(client, headers, calc.id, name="B")

    r = client.post(
        f"/api/calculations/{calc.id}/cba/{b['id']}/set-base", headers=headers
    )
    assert r.status_code == 200
    bases = [row for row in r.json() if row["is_base_scenario"]]
    assert len(bases) == 1 and bases[0]["id"] == b["id"]
    assert a  # (a is no longer base)


def test_compare_returns_metrics(client, db):
    headers, user = _owner(client, db)
    calc = _calc(db, user)
    _seed_sources(db, calc, user)
    a = _create_scenario(client, headers, calc.id)
    b = _create_scenario(client, headers, calc.id, name="B")
    for s in (a, b):
        client.post(f"/api/cba/{s['id']}/auto-populate", headers=headers)
        client.post(f"/api/cba/{s['id']}/compute", headers=headers)

    r = client.post(
        f"/api/calculations/{calc.id}/cba/compare",
        json={"cba_ids": [a["id"], b["id"]]},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) == 2
    for row in rows:
        assert row["npv"] is not None
        assert float(row["total_cost"]) > 0
        assert row["cost_count"] == 2


# ── access control + cache invalidation ─────────────────────────────────


def test_403_for_a_stranger_and_404_for_unknown(client, db):
    headers_a, user_a = _owner(client, db)
    calc = _calc(db, user_a)
    s = _create_scenario(client, headers_a, calc.id)

    headers_b, _ = _owner(client, db)
    assert (
        client.get(f"/api/calculations/{calc.id}/cba", headers=headers_b).status_code
        == 403
    )
    assert client.get(f"/api/cba/{s['id']}/costs", headers=headers_b).status_code == 403
    assert (
        client.get(
            f"/api/calculations/{calc.id}/cba/{uuid.uuid4()}",
            headers=headers_a,
        ).status_code
        == 404
    )


def test_mutations_invalidate_op_data_cache(client, db):
    headers, user = _owner(client, db)
    calc = _calc(db, user)
    s = _create_scenario(client, headers, calc.id)

    db.add(OpDataCache(calculation_id=calc.id, data={"x": 1}))
    db.commit()
    assert db.query(OpDataCache).filter_by(calculation_id=calc.id).count() == 1

    r = client.post(
        f"/api/cba/{s['id']}/costs",
        json={"category": "X", "year_from": 1, "year_to": 1, "amount_per_year": 1},
        headers=headers,
    )
    assert r.status_code == 201
    db.expire_all()
    assert db.query(OpDataCache).filter_by(calculation_id=calc.id).count() == 0


def test_module_is_idempotency_exempt():
    from scripts.check_idempotency_coverage import EXEMPT

    assert "cost_benefit" in EXEMPT
