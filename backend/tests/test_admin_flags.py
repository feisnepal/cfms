"""
Hardening 3.12 / S2-33 — /admin/flags endpoint.

The flag system used to be unreadable: `feature_flags.all()` returned the lazy
`_cache`, which stays `{}` until some other code probes a flag, so the startup
log line always printed "Feature flags: {}". The endpoint must report the real
state of every registered flag and be super-admin-only.
"""
import uuid

from app.models.user import User, UserRole


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


def _normal_user(client) -> dict:
    email = _uniq("user")
    _register(client, email)
    return _login(client, email)


def _super_user(client, db) -> dict:
    email = _uniq("super")
    uid = _register(client, email)
    user = db.query(User).filter(User.id == uid).first()
    user.role = UserRole.SUPER_ADMIN
    db.commit()
    return _login(client, email)


def test_admin_flags_reports_every_registered_flag(client, db):
    """The response has exactly the registered flags, all resolved as booleans."""
    import app.core.feature_flags as ff

    headers = _super_user(client, db)
    resp = client.get("/api/v1/admin/flags", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == set(ff.FLAG_REGISTRY), (
        f"flag names in response differ from FLAG_REGISTRY: "
        f"response={sorted(body)} registry={list(ff.FLAG_REGISTRY)}"
    )
    assert all(isinstance(v, bool) for v in body.values())


def test_admin_flags_requires_super_admin(client):
    headers = _normal_user(client)
    resp = client.get("/api/v1/admin/flags", headers=headers)
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["code"] == "auth.insufficient_permissions"


def test_admin_flags_requires_authentication(client):
    resp = client.get("/api/v1/admin/flags")
    assert resp.status_code in (401, 403), resp.text


def test_admin_flags_exposed_on_legacy_api_mount(client, db):
    """The /api shim must serve the same handler (deprecation header included)."""
    headers = _super_user(client, db)
    resp = client.get("/api/admin/flags", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("Deprecation", "").startswith("@/api/v1")
    from app.core.feature_flags import FLAG_REGISTRY

    assert set(resp.json().keys()) == set(FLAG_REGISTRY)