"""A compartment forest's trees are labelled with its compartments, never with a stale plain block.

Regression: the analysis page showed "Block-3" for trees sitting in "ब्लक ४". The forest carried both
stale plain-block rows (Block-1..N, which the map does not show) and the compartments the user sees;
the tree labeller always preferred the plain block.
"""
import uuid

import pytest
from geoalchemy2.shape import from_shape
from shapely.geometry import box

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock

BOUNDARY = box(85.2290, 27.6790, 85.2330, 27.6820)


def _login(client, db):
    from app.models.user import User

    email = f"ul-{uuid.uuid4().hex[:10]}@example.com"
    client.post("/api/auth/register", json={"email": email, "password": "TestPass123!", "full_name": "UL"})
    r = client.post("/api/auth/login", json={"email": email, "password": "TestPass123!"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, db.query(User).filter(User.email == email).first()


def _unit(db, calc, *, name, geom, is_compartment, index):
    u = ForestBlock(
        calculation_id=calc.id, name=name, block_name=name,
        compartment_code=name if is_compartment else None,
        geometry=from_shape(geom, srid=4326), area_hectares=10.0, area_sqm=100000.0,
        index=index, is_compartment=is_compartment, division_level=1, is_locked=False, child_count=0,
    )
    db.add(u)
    db.flush()
    return u


def _csv() -> bytes:
    rows = [f"{85.2300 + i * 0.0003},{27.6800 + i * 0.0002},Shorea robusta,{22 + i},{14 + i}" for i in range(6)]
    return ("longitude,latitude,species,dia_cm,height_m\n" + "\n".join(rows) + "\n").encode()


@pytest.fixture()
def mixed_forest(client, db):
    """Compartment forest that still carries a stale plain block over the same ground."""
    headers, user = _login(client, db)
    calc = Calculation(user_id=user.id, forest_name=f"UL {uuid.uuid4().hex[:6]}", structure_locked=False,
                       is_draft=False, boundary_geom=from_shape(BOUNDARY, srid=4326))
    db.add(calc)
    db.flush()
    _unit(db, calc, name="Block-3", geom=BOUNDARY, is_compartment=False, index=0)          # stale, invisible
    _unit(db, calc, name="ब्लक १", geom=BOUNDARY, is_compartment=True, index=1)            # what the map shows
    db.commit()
    return headers, calc


def _process(client, headers, calc_id):
    content = _csv()
    up = client.post("/api/inventory/upload", headers=headers, data={"calculation_id": str(calc_id)},
                     files={"file": ("t.csv", content, "text/csv")})
    assert up.status_code == 200, up.text
    iid = up.json()["inventory_id"]
    pr = client.post(f"/api/inventory/{iid}/process", headers=headers, files={"file": ("t.csv", content, "text/csv")})
    assert pr.status_code == 200, pr.text
    return iid


def test_trees_are_labelled_with_the_compartment_not_the_stale_block(client, db, mixed_forest):
    headers, calc = mixed_forest
    iid = _process(client, headers, calc.id)
    trees = client.get(f"/api/inventory/{iid}/trees?page_size=50", headers=headers).json()["trees"]
    assert trees, "no trees stored"
    assert {t["block_name"] for t in trees} == {"ब्लक १"}


def test_analysis_never_mentions_the_stale_block(client, db, mixed_forest):
    from app.services.operational_plan.data_collector import get_tree_mapping_analysis_data

    headers, calc = mixed_forest
    _process(client, headers, calc.id)
    data = get_tree_mapping_analysis_data(db, str(calc.id))
    assert data["sm_available"]
    rows = data["sm_hierarchy_summary"]
    assert rows and all("Block-" not in str(r) for r in rows), rows
    assert [r["compartment"] for r in rows] == ["ब्लक १"]
    # area comes from the compartment itself now that there is no plain-block area to divide by
    assert rows[0]["area_ha"] == 10.0
    assert rows[0]["trees_per_ha"] != "-"


def test_a_plain_block_forest_is_unchanged(client, db):
    headers, user = _login(client, db)
    calc = Calculation(user_id=user.id, forest_name=f"UB {uuid.uuid4().hex[:6]}", structure_locked=False,
                       is_draft=False, boundary_geom=from_shape(BOUNDARY, srid=4326))
    db.add(calc)
    db.flush()
    _unit(db, calc, name="Block-1", geom=BOUNDARY, is_compartment=False, index=0)
    db.commit()
    iid = _process(client, headers, calc.id)
    trees = client.get(f"/api/inventory/{iid}/trees?page_size=50", headers=headers).json()["trees"]
    assert {t["block_name"] for t in trees} == {"Block-1"}
