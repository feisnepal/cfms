"""Hazard & Erosion context aggregator (HAZARD_EROSION_CONTEXT_PLAN.md P0).

``GET /calculations/{id}/hazard-erosion/summary`` returns the header + prereq
pills + key numbers + map list, never raising on a data gap;
``POST .../recompute`` is a best-effort cache bust. Both run against the test
DB — the collectors degrade to ``available: False`` with no rasters.
"""

from __future__ import annotations

import uuid

from app.models.calculation import Calculation
from app.models.user import User


def _owner(client, db):
    email = f"he-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "TestPass123!", "full_name": "HE"},
    )
    resp = client.post(
        "/api/auth/login", json={"email": email, "password": "TestPass123!"}
    )
    assert resp.status_code == 200, resp.text
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    user = db.query(User).filter(User.email == email).first()
    return headers, user


def _calc(db, user):
    c = Calculation(user_id=user.id, forest_name=f"HE CF {uuid.uuid4().hex[:6]}")
    db.add(c)
    db.commit()
    return c


def test_summary_shape_on_a_data_less_forest(client, db):
    headers, user = _owner(client, db)
    c = _calc(db, user)
    r = client.get(f"/api/calculations/{c.id}/hazard-erosion/summary", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["calculation_id"] == str(c.id)
    assert body["physiography_zone"] is None  # no admin.physiography in the test DB
    assert body["has_user_group"] is False

    tags = {p["tag"] for p in body["prereqs"]}
    assert tags == {
        "raster_zonal",
        "soil_data",
        "geology",
        "household_data",
        "user_group_extent",
    }
    for p in body["prereqs"]:
        assert p["status"] in ("available", "partial", "unavailable")
        assert isinstance(p["met"], bool)

    assert body["soil"]["available"] is False
    assert body["hazard"]["available"] is False
    assert body["hazard"]["hh_count"] == 0

    keys = {m["key"] for m in body["maps"]}
    for expect in (
        "thememap:soil__annual_loss",
        "thememap:hazard__landslide_susceptibility",
        "thememap:hazard__factor_of_safety",
        "thememap:hh__vulnerability",
    ):
        assert expect in keys, expect
    # factor bands sort last
    fb = [m["is_factor_band"] for m in body["maps"]]
    assert fb == sorted(fb)
    # none are available without the rasters
    assert all(m["available"] is False for m in body["maps"])


def test_summary_404_for_unknown_calc(client, db):
    headers, _ = _owner(client, db)
    r = client.get(
        f"/api/calculations/{uuid.uuid4()}/hazard-erosion/summary", headers=headers
    )
    assert r.status_code == 404


def test_summary_403_for_a_stranger(client, db):
    headers_a, user_a = _owner(client, db)
    c = _calc(db, user_a)
    headers_b, _ = _owner(client, db)
    r = client.get(
        f"/api/calculations/{c.id}/hazard-erosion/summary", headers=headers_b
    )
    assert r.status_code == 403


def test_recompute_is_202_and_best_effort(client, db):
    headers, user = _owner(client, db)
    c = _calc(db, user)
    r = client.post(
        f"/api/calculations/{c.id}/hazard-erosion/recompute", headers=headers
    )
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "recompute queued"
    assert isinstance(r.json()["cleared"], list)


def test_recompute_403_for_a_stranger(client, db):
    headers_a, user_a = _owner(client, db)
    c = _calc(db, user_a)
    headers_b, _ = _owner(client, db)
    r = client.post(
        f"/api/calculations/{c.id}/hazard-erosion/recompute", headers=headers_b
    )
    assert r.status_code == 403


def test_module_is_idempotency_exempt():
    from scripts.check_idempotency_coverage import EXEMPT

    assert "hazard_erosion" in EXEMPT


def test_tables_shape_and_no_pii_on_a_data_less_forest(client, db):
    headers, user = _owner(client, db)
    c = _calc(db, user)
    r = client.get(f"/api/calculations/{c.id}/hazard-erosion/tables", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["calculation_id"] == str(c.id)
    for key in (
        "soil_loss_by_unit",
        "soil_loss_aoi_comparison",
        "lsi_area_by_class",
        "lsi_by_unit",
        "fs_by_unit",
        "hazard_aoi_comparison",
        "hh_priority_table",
        "hh_settlement_rollup_table",
        "hh_driver_counts",
    ):
        assert isinstance(body[key], list), key
    assert isinstance(body["fs_enabled"], bool)
    assert isinstance(body["has_user_group"], bool)

    # PII guard — no surname / caste / coordinate ever reaches the wire
    blob = r.text.lower()
    for bad in ("surname", "caste", "latitude", "longitude", "household_head"):
        assert bad not in blob, bad


def test_tables_404_and_403(client, db):
    headers, _ = _owner(client, db)
    r = client.get(
        f"/api/calculations/{uuid.uuid4()}/hazard-erosion/tables", headers=headers
    )
    assert r.status_code == 404

    headers_a, user_a = _owner(client, db)
    c = _calc(db, user_a)
    headers_b, _ = _owner(client, db)
    r = client.get(f"/api/calculations/{c.id}/hazard-erosion/tables", headers=headers_b)
    assert r.status_code == 403


def test_narration_shape_on_a_data_less_forest(client, db):
    headers, user = _owner(client, db)
    c = _calc(db, user)
    r = client.get(
        f"/api/calculations/{c.id}/hazard-erosion/narration", headers=headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["calculation_id"] == str(c.id)
    assert body["soil_available"] is False
    assert body["hazard_available"] is False
    for block in ("soil", "hazard"):
        b = body[block]
        for k in (
            "methodology_ne",
            "methodology_en",
            "findings_ne",
            "findings_en",
            "prescription_ne",
            "prescription_en",
        ):
            assert isinstance(b[k], str), (block, k)
        assert isinstance(b["assumptions_ne"], list)
        assert isinstance(b["assumptions_en"], list)


def _make_op(db, calc, tree=None, status="draft"):
    from app.models.operational_plan import OperationalPlan

    plan = OperationalPlan(
        calculation_id=calc.id,
        forest_name=calc.forest_name,
        sections={"tree": tree if tree is not None else []},
        plan_metadata={"language": "NP"},
        status=status,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


def test_insert_op_subsections_409_without_an_op(client, db):
    headers, user = _owner(client, db)
    c = _calc(db, user)
    r = client.post(
        f"/api/calculations/{c.id}/hazard-erosion/insert-op-subsections",
        headers=headers,
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "NO_OP"


def test_insert_op_subsections_appends_then_is_idempotent(client, db):
    headers, user = _owner(client, db)
    c = _calc(db, user)
    _make_op(db, c)

    r = client.post(
        f"/api/calculations/{c.id}/hazard-erosion/insert-op-subsections",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "inserted"
    assert set(body["inserted"]) == {
        "Soil Loss & Erosion Risk",
        "Slope Instability, Landslide Hazard & Household Vulnerability",
    }

    # the tree now carries both subsections
    from app.models.operational_plan import OperationalPlan

    db.expire_all()
    plan = db.query(OperationalPlan).filter_by(calculation_id=c.id).first()
    titles = {n["title_en"] for n in plan.sections["tree"]}
    assert "Soil Loss & Erosion Risk" in titles

    # second call is a no-op
    r2 = client.post(
        f"/api/calculations/{c.id}/hazard-erosion/insert-op-subsections",
        headers=headers,
    )
    assert r2.status_code == 200
    assert r2.json()["status"] == "already_present"
    assert r2.json()["inserted"] == []


def test_insert_op_subsections_409_when_plan_approved(client, db):
    headers, user = _owner(client, db)
    c = _calc(db, user)
    _make_op(db, c, status="approved")
    r = client.post(
        f"/api/calculations/{c.id}/hazard-erosion/insert-op-subsections",
        headers=headers,
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "PLAN_APPROVED"


# ── HAZARD_EROSION_VARIABLE_COVERAGE_PLAN P3 — the in-context variable reference ──


def test_variables_endpoint_groups_and_registration(client, db):
    from app.api.hazard_erosion import HAZARD_VARIABLE_GROUPS
    from app.services.operational_plan.variable_registry import get_variable

    headers, user = _owner(client, db)
    c = _calc(db, user)
    r = client.get(
        f"/api/calculations/{c.id}/hazard-erosion/variables", headers=headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["calculation_id"] == str(c.id)

    gids = [g["id"] for g in body["groups"]]
    assert gids == ["numbers", "maps", "tables", "charts", "narration"]

    # every non-map key the manifest lists is a registered variable
    for _gid, _ne, _en, keys in HAZARD_VARIABLE_GROUPS:
        for k in keys:
            assert get_variable(k) is not None, k

    non_map = [
        v["key"]
        for g in body["groups"]
        if g["id"] != "maps"
        for v in g["variables"]
    ]
    assert all(v.get("registered") for g in body["groups"] if g["id"] != "maps" for v in g["variables"])
    assert "hazard_erosion_full_narration" in non_map
    assert "chart:hazard_slope_class_split" in non_map
    # the maps group is populated from the thematic registry
    maps = next(g for g in body["groups"] if g["id"] == "maps")
    assert any(v["key"].startswith("thememap:hazard__") for v in maps["variables"])


def test_variable_catalog_keys_filter_returns_resolved(client, db):
    headers, user = _owner(client, db)
    c = _calc(db, user)
    r = client.get(
        f"/api/operational-plans/{c.id}/variable-catalog",
        params={"keys": "hazard_household_coord_source,hazard_erosion_by_unit_table"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    rows = {v["key"]: v for v in r.json()["variables"]}
    assert set(rows) == {"hazard_household_coord_source", "hazard_erosion_by_unit_table"}
    # the filtered response opts into carrying the raw resolved value
    assert "resolved" in rows["hazard_household_coord_source"]
    assert "sub_group" in rows["hazard_erosion_by_unit_table"]
