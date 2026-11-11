"""Structure-lock is visible on the read path, and create-single-block honours it.

Regression: `GET /api/forests/calculations/{id}` carried neither
`structure_locked` nor `map_lifecycle_status`, so the workspace only knew a
map was locked if the client had submitted it in that same session. An
already-locked forest therefore showed an editable UI and every restructure
failed with a 423 instead of a disabled control. And `create-single-block`
DELETEs every block before recreating one with no lock check at all.
"""
import uuid

from shapely import wkt as shp_wkt
from shapely.geometry import box

from app.models.calculation import Calculation, CalculationStatus
from app.models.forest_block import ForestBlock


def _register(client):
    email = f"struct-lock-{uuid.uuid4().hex[:8]}@example.com"
    client.post("/api/auth/register", json={
        "email": email, "password": "TestPass123!", "full_name": "Struct Lock",
    })
    resp = client.post("/api/auth/login", json={"email": email, "password": "TestPass123!"})
    assert resp.status_code == 200, resp.text
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    uid = client.get("/api/auth/me", headers=headers).json()["id"]
    return headers, uid


def _calc(db, user_id, *, locked=False):
    calc = Calculation(
        id=uuid.uuid4(),
        user_id=user_id,
        forest_name="Lock Forest",
        boundary_geom=shp_wkt.dumps(box(2, 2, 6, 6)),
        status=CalculationStatus.COMPLETED,
        is_draft=False,
        structure_locked=locked,
        map_lifecycle_status="completed" if locked else "draft",
    )
    db.add(calc)
    db.commit()
    db.refresh(calc)
    return calc


def test_get_calculation_reports_unlocked_state(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid, locked=False)

    body = client.get(f"/api/forests/calculations/{calc.id}", headers=headers).json()
    assert body["structure_locked"] is False
    assert body["map_lifecycle_status"] == "draft"
    assert body["structure_locked_at"] is None


def test_get_calculation_reports_a_lock_the_client_never_set(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid, locked=True)

    body = client.get(f"/api/forests/calculations/{calc.id}", headers=headers).json()
    assert body["structure_locked"] is True
    assert body["map_lifecycle_status"] == "completed"


def test_create_single_block_is_refused_on_a_locked_map(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid, locked=True)
    # a block that would be wiped if the guard were missing
    db.add(ForestBlock(
        id=uuid.uuid4(), calculation_id=calc.id, name="Block 1",
        geometry=shp_wkt.dumps(box(2, 2, 6, 6)), area_hectares=1.0, index=0,
        division_level=1,
    ))
    db.commit()

    resp = client.post(
        f"/api/forests/calculations/{calc.id}/create-single-block", headers=headers,
    )
    assert resp.status_code == 423, resp.text
    assert resp.json()["detail"]["code"] == "structure_locked"
    # the existing block is untouched
    assert db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).count() == 1


def test_create_single_block_still_works_when_unlocked(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid, locked=False)

    resp = client.post(
        f"/api/forests/calculations/{calc.id}/create-single-block", headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).count() == 1


def test_create_single_compartment_mirrors_create_single_block(client, db):
    """`is_compartment=true` -- "Import Compartment from Forest Boundary" --
    creates a compartment (not a block) spanning the boundary, and reconciles
    `result_data['compartments']`/`polygon_type` from it."""
    headers, uid = _register(client)
    calc = _calc(db, uid, locked=False)

    resp = client.post(
        f"/api/forests/calculations/{calc.id}/create-single-block",
        params={"is_compartment": True},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    rows = db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).all()
    assert len(rows) == 1
    assert rows[0].is_compartment is True
    assert rows[0].name == "C1"  # system names: C<n>, no forest name

    db.expire_all()
    calc = db.query(Calculation).filter(Calculation.id == calc.id).first()
    assert calc.result_data.get("polygon_type") == "compartment"
    assert calc.result_data.get("total_compartments") == 1
    assert len(calc.result_data.get("compartments", [])) == 1
    # the block-branch snapshot is untouched by a compartment import
    assert not calc.result_data.get("blocks")


def test_create_single_compartment_is_refused_on_a_locked_map(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid, locked=True)

    resp = client.post(
        f"/api/forests/calculations/{calc.id}/create-single-block",
        params={"is_compartment": True},
        headers=headers,
    )
    assert resp.status_code == 423, resp.text
    assert resp.json()["detail"]["code"] == "structure_locked"
