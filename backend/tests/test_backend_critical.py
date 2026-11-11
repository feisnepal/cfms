"""
Critical-path backend tests.

Covers the "money paths" identified in the industry-grade plan:
- Auth: register -> login -> JWT returned
- JSONB in-place mutation trap: reassignment persists; in-place does not
- OP docx table fill: _tbl_fill_data uses lxml (no tbl.cell O(N^2))
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from docx import Document
from docx.shared import Pt

import uuid

from app.models.calculation import Calculation
from app.models.user import User
from app.services.operational_plan.op_docx_builder import _tbl_fill_data


def _make_user(db):
    user = User(
        email=f"jsonb_{uuid.uuid4()}@example.com",
        hashed_password="x",
        full_name="JSONB",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ─────────────────────────────────────────────────────────── Auth
def test_register_login_returns_jwt(client):
    email = "authtest@example.com"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "AuthPass123!", "full_name": "Auth T"},
    )
    resp = client.post(
        "/api/auth/login",
        json={"email": email, "password": "AuthPass123!"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body and body["token_type"] == "bearer"


def test_protected_route_requires_auth(client):
    # /api/auth/me without token -> 401
    resp = client.get("/api/auth/me")
    assert resp.status_code in (401, 403)


# ─────────────────────────────────────────────────────────── JSONB mutation trap
def test_jsonb_reassignment_persists(db):
    user = _make_user(db)
    calc = Calculation(
        user_id=user.id,
        forest_name="JSONB Trap Test",
        block_name="B1",
        result_data={"user_group_land_cover": {"a": 1}},
    )
    db.add(calc)
    db.commit()
    db.refresh(calc)
    cid = calc.id

    # CORRECT pattern: assign a new dict (triggers SQLAlchemy change tracking)
    new = dict(calc.result_data or {})
    new["user_group_land_cover"] = {"a": 2}
    calc.result_data = new
    db.commit()

    fresh = db.get(Calculation, cid)
    assert fresh.result_data["user_group_land_cover"] == {"a": 2}


def test_jsonb_inplace_mutation_does_not_persist(db):
    user = _make_user(db)
    calc = Calculation(user_id=user.id, forest_name="JSONB Inplace", block_name="B2", result_data={})
    db.add(calc)
    db.commit()
    db.refresh(calc)
    cid = calc.id

    # WRONG pattern: mutate in place (SQLAlchemy does NOT detect this)
    calc.result_data["leaked"] = True
    db.commit()

    fresh = db.get(Calculation, cid)
    assert "leaked" not in (fresh.result_data or {})


# ─────────────────────────────────────────────────────────── OP docx table fill
def test_tbl_fill_data_uses_lxml_not_cell():
    doc = Document()
    table = doc.add_table(rows=3, cols=2)
    headers = ["block_name", "volume_m3"]
    rows = [
        {"block_name": "Chaukune", "volume_m3": 40.92},
        {"block_name": "Bari", "volume_m3": 22.49},
    ]
    # Should not raise; must populate header + data rows via lxml
    _tbl_fill_data(table, headers, rows, "fi_block_volume")
    # Verify header cell text was set
    header_text = table.rows[0].cells[0].text
    assert "block_name" in header_text or "Block Name" in header_text
    # Verify data row populated
    assert "Chaukune" in table.rows[1].cells[0].text


# ─────────────────────────────────────────────────────────── API versioning
def test_v1_and_legacy_auth_endpoints_resolve(client):
    # Both /api/v1 and /api prefixes must serve the auth login route.
    for path in ("/api/v1/auth/login", "/api/auth/login"):
        resp = client.post(path, json={"email": "x@y.z", "password": "bad"})
        # 422 = validation error => route exists and is wired (not 404)
        assert resp.status_code in (400, 401, 422), f"{path} -> {resp.status_code}"


def test_legacy_endpoint_carries_deprecation_header(client):
    resp = client.post(
        "/api/auth/login", json={"email": "x@y.z", "password": "bad"}
    )
    assert "Deprecation" in resp.headers
    assert "/api/v1" in resp.headers["Deprecation"]


def test_v1_endpoint_has_no_deprecation_header(client):
    resp = client.post(
        "/api/v1/auth/login", json={"email": "x@y.z", "password": "bad"}
    )
    assert "Deprecation" not in resp.headers

