"""U05 — tree-cluster endpoint API tests (auth, rate limit, response shape)."""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.rate_limit import limiter as _global_limiter
from app.models.calculation import Calculation


def _ensure_trees_table(db) -> None:
    """The conftest's create_all can skip inventory_trees (Geography GiST)."""
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS inventory_trees (
            id UUID PRIMARY KEY,
            inventory_calculation_id UUID REFERENCES inventory_calculations(id) ON DELETE CASCADE NOT NULL,
            species VARCHAR(255) NOT NULL,
            dia_cm FLOAT NOT NULL,
            location geography(POINT,4326)
        )"""))
    db.commit()


def _seed_calc_with_tree(db, owner_email="testuser@example.com"):
    """Create a calc + inventory calc + trees for the auth user, return core calc id."""
    from app.models.inventory import InventoryCalculation
    from app.models.user import User
    user = db.query(User).filter(User.email == owner_email).first()
    if user is None:
        user_id = uuid.uuid4()
        db.add(User(id=user_id, email=owner_email, full_name="T", hashed_password="x"))
        db.flush()
        user = db.query(User).filter(User.email == owner_email).first()
    core_id = str(uuid.uuid4())
    db.add(Calculation(id=core_id, user_id=user.id, uploaded_filename="c.csv", is_draft=False))
    db.flush()
    ic = InventoryCalculation(
        id=uuid.uuid4(), calculation_id=core_id, user_id=user.id,
        uploaded_filename="i.csv", status="completed", grid_spacing_meters=20.0, total_trees=3,
    )
    db.add(ic)
    db.flush()
    for i in range(3):
        db.execute(text(
            "INSERT INTO inventory_trees (id, inventory_calculation_id, species, dia_cm, location) "
            "VALUES (:lid, :icid, :s, :d, :l)"
        ), {
            "lid": str(uuid.uuid4()), "icid": str(ic.id), "s": "A",
            "d": 10 + i, "l": "POINT(85.06 27.43)",
        })
    db.commit()
    return core_id


def test_requires_auth(client):
    resp = client.get(
        "/api/v1/calculations/00000000-0000-0000-0000-000000000000/tree-model/clusters?z=1&x=0&y=0"
    )
    assert resp.status_code in (401, 403)


def test_out_of_range_tile_400(client, auth_headers, db):
    _ensure_trees_table(db)
    cid = _seed_calc_with_tree(db)
    resp = client.get(
        f"/api/v1/calculations/{cid}/tree-model/clusters?z=8&x=999&y=999",
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_unknown_calc_404(client, auth_headers):
    resp = client.get(
        "/api/v1/calculations/11111111-1111-1111-1111-111111111111/tree-model/clusters?z=8&x=0&y=0",
        headers=auth_headers,
    )
    assert resp.status_code == 404


def test_rate_limit_429(client, auth_headers):
    _global_limiter._storage.reset()
    cid = "22222222-2222-2222-2222-222222222222"
    url = f"/api/v1/calculations/{cid}/tree-model/clusters?z=8&x=0&y=0"
    saw_429 = False
    for _ in range(40):  # far above 30/min
        resp = client.get(url, headers=auth_headers)
        if resp.status_code == 429:
            saw_429 = True
            break
    assert saw_429