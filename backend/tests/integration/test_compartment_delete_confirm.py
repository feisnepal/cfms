"""FS-4a.9 (D13) -- DELETE /compartments/{compartment_id} requires
``confirm_children=true`` when the compartment has sub-units below it, at
ANY depth (A1). Once confirmed, ``passive_deletes=True`` on
``ForestBlock.compartments`` lets Postgres's own ON DELETE CASCADE remove
every descendant recursively -- this endpoint's old hand-rolled
one-level-deep child loop is gone.
"""
import uuid

from shapely import wkt as shp_wkt
from shapely.geometry import box

from app.models.calculation import Calculation, CalculationStatus
from app.models.forest_block import ForestBlock


def _register(client):
    email = f"compdelete-{uuid.uuid4().hex[:8]}@example.com"
    client.post("/api/auth/register", json={
        "email": email, "password": "TestPass123!", "full_name": "Compartment Delete Tester",
    })
    resp = client.post("/api/auth/login", json={"email": email, "password": "TestPass123!"})
    assert resp.status_code == 200, resp.text
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    return headers, me.json()["id"]


def _calc(db, user_id, boundary=box(2, 2, 6, 6)):
    calc = Calculation(
        id=uuid.uuid4(),
        user_id=user_id,
        forest_name="Compartment Delete Forest",
        boundary_geom=shp_wkt.dumps(boundary),
        status=CalculationStatus.PROCESSING,
        is_draft=True,
    )
    db.add(calc)
    db.commit()
    db.refresh(calc)
    return calc


def _row(db, calc, geom, name, index, **kwargs):
    row = ForestBlock(
        id=uuid.uuid4(),
        calculation_id=calc.id,
        name=name,
        geometry=shp_wkt.dumps(geom),
        area_hectares=1.0,
        index=index,
        is_compartment=True,
        **kwargs,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_delete_compartment_with_no_children_needs_no_confirm(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid)
    c1 = _row(db, calc, box(2, 2, 4, 6), "Compartment 1", 0, division_level=1)
    db.expire_all()

    resp = client.delete(f"/api/v1/compartments/{c1.id}", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["deleted"] is True
    assert body["children_deleted"] == 0

    db.expire_all()
    assert db.query(ForestBlock).filter(ForestBlock.id == c1.id).first() is None


def test_delete_compartment_with_subcompartment_requires_confirm(client, db):
    headers, uid = _register(client)
    calc = _calc(db, uid)
    parent = _row(db, calc, box(2, 2, 4, 6), "Compartment 1", 0, division_level=1)
    child = _row(
        db, calc, box(2, 2, 3, 6), "Compartment 1-SC1", 1,
        division_level=2, parent_block_id=parent.id,
    )
    parent_id, child_id = parent.id, child.id
    db.expire_all()

    resp = client.delete(f"/api/v1/compartments/{parent_id}", headers=headers)
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "blocks.has_children_confirm_required"
    assert detail["count"] == 1

    db.expire_all()
    assert db.query(ForestBlock).filter(ForestBlock.id == parent_id).first() is not None
    assert db.query(ForestBlock).filter(ForestBlock.id == child_id).first() is not None


def test_delete_compartment_confirm_cascades_through_every_generation(client, db):
    """A1: nesting is not capped at one sub-level -- the old code only ever
    walked/deleted direct children, silently orphaning a grandchild. This
    pins that a grandchild is BOTH counted in the 409 AND removed once
    confirmed."""
    headers, uid = _register(client)
    calc = _calc(db, uid)
    parent = _row(db, calc, box(2, 2, 4, 6), "Compartment 1", 0, division_level=1)
    child = _row(
        db, calc, box(2, 2, 3, 6), "Compartment 1-SC1", 1,
        division_level=2, parent_block_id=parent.id,
    )
    grandchild = _row(
        db, calc, box(2, 2, 2.5, 6), "Compartment 1-SC1-SC1", 2,
        division_level=3, parent_block_id=child.id,
    )
    # Captured before any commit expires these ORM instances.
    parent_id, child_id, grandchild_id = parent.id, child.id, grandchild.id
    db.expire_all()

    resp = client.delete(f"/api/v1/compartments/{parent_id}", headers=headers)
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["count"] == 2  # child + grandchild

    resp2 = client.delete(
        f"/api/v1/compartments/{parent_id}?confirm_children=true", headers=headers
    )
    assert resp2.status_code == 200, resp2.text
    assert resp2.json()["children_deleted"] == 2

    db.expire_all()
    assert db.query(ForestBlock).filter(ForestBlock.id == parent_id).first() is None
    assert db.query(ForestBlock).filter(ForestBlock.id == child_id).first() is None
    assert db.query(ForestBlock).filter(ForestBlock.id == grandchild_id).first() is None
