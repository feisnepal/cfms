"""
Phase 2 — Batch 2a API tests: bilingual error details on converted surfaces.

Endpoints converted in batch 2a (`api/auth.py`, `api/boundary.py`,
`api/blocks.py`, `utils/auth.py`) must return the dict shape
`{code, message, message_np}` (Nepali-first target) while keeping the old
English backbone in `message`. Every user is given a unique email so repeated
pytest runs / leftover test-DB rows never collide.
"""
import uuid

from app.models.calculation import Calculation


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


def _register(client, email: str, password: str = "TestPass123!"):
    resp = client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "full_name": "Tester"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _login(client, email: str, password: str = "TestPass123!"):
    resp = client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _auth_client(client, email=None, password="TestPass123!"):
    email = email or _uniq("user")
    _register(client, email, password)
    return _login(client, email, password)


def _assert_bilingual_detail(resp, code: str):
    data = resp.json()["detail"]
    assert data["code"] == code
    assert data["message"], "en message empty"
    assert data["message_np"], "ne message empty"
    assert data["message"] != data["message_np"]


def test_login_invalid_credentials_bilingual(client):
    _register(client, _uniq("fresh"))
    resp = client.post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": "wrong"},
    )
    assert resp.status_code == 401
    _assert_bilingual_detail(resp, "auth.invalid_credentials")
    assert resp.json()["detail"]["message"] == "Incorrect email or password"
    assert resp.json()["detail"]["message_np"] == "इमेल वा पासवर्ड गलत छ"


def test_register_duplicate_email_bilingual(client):
    email = _uniq("dup")
    assert client.post(
        "/api/auth/register",
        json={"email": email, "password": "TestPass123!", "full_name": "Dup"},
    ).status_code == 201
    resp = client.post(
        "/api/auth/register",
        json={"email": email, "password": "TestPass123!", "full_name": "Dup"},
    )
    assert resp.status_code == 400
    _assert_bilingual_detail(resp, "auth.email_already_registered")
    assert resp.json()["detail"]["message_np"] == "इमेल पहिले नै दर्ता भइसकेको छ"


def test_change_password_wrong_current_bilingual(client):
    headers = _auth_client(client)
    resp = client.post(
        "/api/auth/change-password",
        headers=headers,
        json={"old_password": "NotThePassword!", "new_password": "NewPass123!"},
    )
    assert resp.status_code == 400
    _assert_bilingual_detail(resp, "auth.wrong_current_password")


def test_change_password_success_bilingual(client):
    email = _uniq("cp")
    _register(client, email)
    headers = _login(client, email)
    resp = client.post(
        "/api/auth/change-password",
        headers=headers,
        json={"old_password": "TestPass123!", "new_password": "NewPass123!"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["message"] == "Password changed successfully"
    assert body["message_np"] == "पासवर्ड सफलतापूर्वक परिवर्तन भयो"
    # re-login with the NEW password proves it took effect
    assert _login(client, email, "NewPass123!")
    resp = client.post(
        "/api/auth/login",
        json={"email": email, "password": "TestPass123!"},
    )
    assert resp.status_code == 401


def test_blocks_not_authorized_bilingual(client, db):
    headers = _auth_client(client)
    owner_id = _register(client, _uniq("owner"))

    calc = Calculation(user_id=owner_id, forest_name="Other Forest", status="completed")
    db.add(calc)
    db.commit()
    db.refresh(calc)

    resp = client.get(f"/api/blocks/calculations/{calc.id}/polygons", headers=headers)
    assert resp.status_code == 403
    _assert_bilingual_detail(resp, "blocks.not_authorized_calculation")


def test_boundary_status_only_dfo_bilingual(client):
    headers = _auth_client(client)
    resp = client.patch(
        "/api/forests/00000000-0000-0000-0000-000000000000/boundary-status",
        headers=headers,
        json={"status": "validated"},
    )
    assert resp.status_code == 403
    _assert_bilingual_detail(resp, "boundary.only_dfo_can_change_status")


def test_boundary_disputes_only_dfo_bilingual(client):
    headers = _auth_client(client)
    resp = client.get("/api/admin/boundary-disputes", headers=headers)
    assert resp.status_code == 403
    _assert_bilingual_detail(resp, "boundary.only_dfo_access")


def test_block_not_found_keeps_legacy_constant(client):
    headers = _auth_client(client)
    # CalculationErrors.NOT_FOUND compat constant is intentionally unchanged
    resp = client.get(
        "/api/blocks/calculations/00000000-0000-0000-0000-000000000000/blocks",
        headers=headers,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Calculation not found"