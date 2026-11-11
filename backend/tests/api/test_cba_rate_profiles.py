"""Org-wide CBA rate profile — super-admin API + re-populate integration
(CBA_MODULE_PLAN.md P8 / D4).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.models.calculation import Calculation
from app.models.cost_benefit import CBABenefitItem, CostBenefitAnalysis
from app.models.field_inventory import (
    FieldInventoryBlockSummary,
    FieldInventoryCalculation,
)
from app.models.user import User, UserRole
from app.services.cost_benefit.repopulate import repopulate_scenario


@pytest.fixture(autouse=True)
def _restore_org_rates(db):
    """These tests PUT the single shared `global` org-rate row and `client` commits it.
    Left at 11000, it leaks into every later CBA test (`test_cba_repopulate` expects the
    8000 fallback and got 11000 in a whole-suite run, green alone)."""
    yield
    db.rollback()
    db.execute(text("UPDATE cba_rate_profiles SET rates = '{}'::jsonb WHERE key = 'global'"))
    db.commit()


def _admin(client, db):
    email = f"cbaadm-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "TestPass123!", "full_name": "Admin"},
    )
    u = db.query(User).filter(User.email == email).first()
    u.role = UserRole.SUPER_ADMIN
    db.commit()
    resp = client.post(
        "/api/auth/login", json={"email": email, "password": "TestPass123!"}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _plain(client, db):
    email = f"cbausr-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "TestPass123!", "full_name": "User"},
    )
    resp = client.post(
        "/api/auth/login", json={"email": email, "password": "TestPass123!"}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_get_returns_rates_and_defaults(client, db):
    h = _admin(client, db)
    client.put("/api/admin/cba-rates", json={"rates": {}}, headers=h)  # reset
    r = client.get("/api/admin/cba-rates", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rates"] == {}
    assert body["defaults"]["timber_mixed"] == 8000
    assert body["defaults"]["fuelwood"] == 1500


def test_put_upserts_and_validates(client, db):
    h = _admin(client, db)
    r = client.put(
        "/api/admin/cba-rates",
        json={"rates": {"timber_mixed": 9500, "fuelwood": 1800}},
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["rates"] == {"timber_mixed": 9500.0, "fuelwood": 1800.0}

    # persists
    assert (
        client.get("/api/admin/cba-rates", headers=h).json()["rates"]["timber_mixed"]
        == 9500.0
    )

    # unknown key → 422
    assert (
        client.put(
            "/api/admin/cba-rates", json={"rates": {"gold": 1}}, headers=h
        ).status_code
        == 422
    )
    # negative → 422
    assert (
        client.put(
            "/api/admin/cba-rates",
            json={"rates": {"carbon": -5}},
            headers=h,
        ).status_code
        == 422
    )
    # null clears the key
    r = client.put(
        "/api/admin/cba-rates", json={"rates": {"timber_mixed": None}}, headers=h
    )
    assert "timber_mixed" not in r.json()["rates"]


def test_non_admin_is_forbidden(client, db):
    h = _plain(client, db)
    assert client.get("/api/admin/cba-rates", headers=h).status_code == 403
    assert (
        client.put("/api/admin/cba-rates", json={"rates": {}}, headers=h).status_code
        == 403
    )


def test_repopulate_uses_the_org_rate(client, db):
    h = _admin(client, db)
    client.put(
        "/api/admin/cba-rates",
        json={"rates": {"timber_mixed": 11000}},
        headers=h,
    )

    u = db.query(User).filter(User.role == UserRole.SUPER_ADMIN).first()
    calc = Calculation(user_id=u.id, uploaded_filename="x.csv")
    db.add(calc)
    db.flush()
    scn = CostBenefitAnalysis(
        calculation_id=calc.id, name="Base", is_base_scenario=True
    )
    db.add(scn)
    fic = FieldInventoryCalculation(
        calculation_id=calc.id, user_id=u.id, uploaded_filename="fi.csv"
    )
    db.add(fic)
    db.flush()
    db.add(
        FieldInventoryBlockSummary(
            field_inventory_calculation_id=fic.id,
            block_name="B",
            total_sample_plots=3,
            tree_timber_m3_per_ha=10,
            pole_timber_m3_per_ha=0,
            tree_firewood_m3_per_ha=0,
            pole_firewood_m3_per_ha=0,
            co2_equivalent_tco2_per_ha=0,
        )
    )
    db.commit()

    repopulate_scenario(scn.id, db)
    timber = (
        db.query(CBABenefitItem)
        .filter(CBABenefitItem.cba_id == scn.id, CBABenefitItem.source == "timber")
        .one()
    )
    assert float(timber.unit_price) == 11000.0  # org rate, not the 8000 fallback


def test_module_is_idempotency_exempt():
    from scripts.check_idempotency_coverage import EXEMPT

    assert "cba_rate_profiles" in EXEMPT
