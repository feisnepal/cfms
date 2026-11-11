"""
Super-admin per-forest cost aggregation tests (CB-2).

Covers permissions (super_admin-only), the SQLAlchemy JSONB aggregation
(per-forest sums, grand total, currency), and the forest_name fallback to the
calculation id. Every user gets a unique email so repeated pytest runs never
collide, and each forest is owned by a distinct user so no ownership shim can
accidentally pass a non-super-admin through.
"""
import uuid

import pytest

from app.models.user import User, UserRole
from app.models.calculation import Calculation
from app.services.calculation_cost_service import CPU_COST_PER_HOUR, MEMORY_COST_PER_GB_HOUR


# The report lists EVERY forest with a cost estimate and the tests assert the exact rows, so each test starts on empty
# ground (see conftest `forget_forests`): a calculation another test committed - the re-analyse one - must not leak in.
pytestmark = pytest.mark.usefixtures("forget_forests")


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


def _role_user(client, db, role: UserRole) -> dict:
    email = _uniq(role.value)
    uid = _register(client, email)
    user = db.query(User).filter(User.id == uid).first()
    user.role = role
    db.commit()
    return _login(client, email)


def _super_user(client, db) -> dict:
    return _role_user(client, db, UserRole.SUPER_ADMIN)


def _calc(db, owner_id, forest_name, cost_estimate, completed_at=None):
    calc = Calculation(id=uuid.uuid4(), user_id=owner_id, forest_name=forest_name)
    if cost_estimate is not None:
        calc.cost_estimate = dict(cost_estimate)
    if completed_at is not None:
        calc.completed_at = completed_at
    db.add(calc)
    db.commit()
    return calc


def _estimate(cpu_seconds, peak_memory_mb, currency="USD"):
    cpu_hours = cpu_seconds / 3600.0
    memory_gb = peak_memory_mb / 1024.0
    return {
        "cpu_seconds": round(cpu_seconds, 3),
        "peak_memory_mb": round(peak_memory_mb, 1),
        "cpu_cost": round(cpu_hours * CPU_COST_PER_HOUR, 6),
        "memory_cost": round((memory_gb * cpu_hours) * MEMORY_COST_PER_GB_HOUR, 6),
        "total_cost": round(
            cpu_hours * CPU_COST_PER_HOUR
            + (memory_gb * cpu_hours) * MEMORY_COST_PER_GB_HOUR,
            6,
        ),
        "currency": currency,
    }


def _get(client, headers=None):
    return client.get("/api/admin/costs/forests", headers=headers)


def test_requires_super_admin(client):
    headers = _normal_user(client)
    resp = _get(client, headers)
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["code"] == "auth.insufficient_permissions"


def test_org_admin_forbidden(client, db):
    headers = _role_user(client, db, UserRole.ORG_ADMIN)
    resp = _get(client, headers)
    assert resp.status_code == 403, resp.text


def test_anonymous_forbidden(client):
    resp = _get(client)
    assert resp.status_code == 401, resp.text


def test_aggregates_per_forest(client, db):
    super_headers = _super_user(client, db)
    owner_a = _register(client, _uniq("a"))
    owner_b = _register(client, _uniq("b"))

    # Forest A: two calculations (mixed cpu peak sizes).
    est_a1 = _estimate(30.0, 512.0)
    est_a2 = _estimate(60.0, 1024.0)
    _calc(db, owner_a, "Alpha Forest", est_a1)
    _calc(db, owner_a, "Alpha Forest", est_a2)

    # Forest B: one calculation.
    est_b = _estimate(120.0, 768.0)
    _calc(db, owner_b, "Beta Forest", est_b)

    # A calculation with no cost_estimate must be excluded entirely.
    _calc(db, owner_a, "Gamma Forest", None)

    resp = _get(client, super_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    by_name = {r["forest_name"]: r for r in body["rows"]}
    assert set(by_name) == {"Alpha Forest", "Beta Forest"}

    alpha = by_name["Alpha Forest"]
    assert alpha["calculation_count"] == 2
    assert alpha["total_cpu_seconds"] == round(30.0 + 60.0, 3)
    assert alpha["total_peak_memory_mb"] == round(512.0 + 1024.0, 1)
    assert alpha["total_cpu_cost"] == _estimate(30.0, 512.0)["cpu_cost"] + _estimate(60.0, 1024.0)["cpu_cost"]
    assert alpha["total_memory_cost"] == _estimate(30.0, 512.0)["memory_cost"] + _estimate(60.0, 1024.0)["memory_cost"]
    assert alpha["total_cost"] == _estimate(30.0, 512.0)["total_cost"] + _estimate(60.0, 1024.0)["total_cost"]
    assert alpha["currency"] == "USD"

    beta = by_name["Beta Forest"]
    assert beta["calculation_count"] == 1
    assert beta["total_cost"] == est_b["total_cost"]

    # Total cost descending: Beta (120s) beats Alpha (90s).
    assert body["rows"][0]["forest_name"] == "Beta Forest"

    total = sum(r["total_cost"] for r in body["rows"])
    assert abs(body["grand_total"] - total) < 1e-6
    assert body["currency"] == "USD"


def test_blank_forest_name_falls_back_to_id(client, db):
    super_headers = _super_user(client, db)
    owner = _register(client, _uniq("blank"))
    calc = _calc(db, owner, "", _estimate(10.0, 256.0))

    resp = _get(client, super_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    by_name = {r["forest_name"]: r for r in body["rows"]}
    # The blank-named calculation surfaces under its id, never as a blank row.
    assert str(calc.id) in by_name
    assert "" not in by_name


def test_forest_with_only_no_cost_calculations_is_excluded(client, db):
    super_headers = _super_user(client, db)
    owner = _register(client, _uniq("none"))
    _calc(db, owner, "Only No Cost Forest", None)

    resp = _get(client, super_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    by_name = {r["forest_name"]: r for r in body["rows"]}
    assert "Only No Cost Forest" not in by_name


def test_reanalyze_records_cost_estimate(client, db, monkeypatch):
    """CB-2: 'Re-run Analysis' writes a cost_estimate too, so re-analysed
    forests appear in /admin/costs (previously only the initial run did)."""
    from shapely.geometry import box
    from shapely.wkt import dumps as wkt_dumps

    from app.models.calculation import CalculationStatus

    email = _uniq("reanalyze")
    uid = _register(client, email)
    headers = _login(client, email)

    calc = Calculation(
        id=uuid.uuid4(),
        user_id=uid,
        forest_name=f"Reanalyze CF {uuid.uuid4().hex[:6]}",
        boundary_geom=wkt_dumps(box(2, 2, 6, 6)),
        status=CalculationStatus.COMPLETED,
        result_data={"area_hectares": 10.0},
        analysis_options={},
    )
    db.add(calc)
    db.commit()

    async def _fake_analyze(calc_id, session, options=None):
        return {"elevation_mean_m": 100.0}, 12

    monkeypatch.setattr("app.services.reanalysis_service.analyze_forest_boundary", _fake_analyze)

    resp = client.post(
        f"/api/forests/calculations/{calc.id}/reanalyze",
        json={"run_elevation": True},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    db.expire_all()
    fresh = db.query(Calculation).filter(Calculation.id == calc.id).first()
    est = fresh.cost_estimate
    assert isinstance(est, dict), est
    assert est["cpu_seconds"] == 12.0
    assert est["total_cost"] > 0
    assert {"cpu_seconds", "peak_memory_mb", "cpu_cost", "memory_cost",
            "total_cost", "currency"} <= set(est)

    # …and it now shows up in the per-forest report.
    super_headers = _super_user(client, db)
    body = _get(client, super_headers).json()
    assert fresh.forest_name in {r["forest_name"] for r in body["rows"]}
