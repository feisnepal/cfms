"""The units an activity can be assigned to (YEARLY_ACTIVITIES plan P5): `GET /calculations/{id}/plan-units`.

The yearly-activities pages' block chooser used a map feed that lists the forest boundary and the legacy `result_data`
arrays, so a forest whose units are compartments (`forest_blocks`) showed none. This reads the real units."""

from __future__ import annotations

import uuid

from geoalchemy2.shape import from_shape
from shapely.geometry import box, mapping

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.user import User

BASE = "/api/yearly-activities"


def _login(client, db):
    email = f"units-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "TestPass123!", "full_name": "Units Tester"},
    )
    resp = client.post(
        "/api/auth/login", json={"email": email, "password": "TestPass123!"}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}, db.query(
        User
    ).filter(User.email == email).first()


def _unit(db, calc, name, west, parent=None):
    row = ForestBlock(
        id=uuid.uuid4(),
        calculation_id=calc.id,
        name=name,
        block_name=name,
        geometry=from_shape(box(west, 27.0, west + 0.1, 27.1), srid=4326),
        area_hectares=1.0,
        index=0,
        parent_block_id=parent.id if parent is not None else None,
    )
    db.add(row)
    db.flush()
    return row


def _calc(db, user, sub_areas=None):
    calc = Calculation(
        user_id=user.id,
        uploaded_filename="x.csv",
        forest_name="Units CF",
        result_data={"sub_areas": sub_areas or []},
    )
    db.add(calc)
    db.commit()
    return calc


def _units(client, headers, calc):
    resp = client.get(f"{BASE}/calculations/{calc.id}/plan-units", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_the_leaf_units_are_listed_in_natural_order_and_a_divided_block_is_not(
    client, db
):
    headers, user = _login(client, db)
    calc = _calc(db, user)
    parent = _unit(db, calc, "Block-1", 85.0)  # divided into compartments
    _unit(db, calc, "C-10", 85.0, parent=parent)
    _unit(db, calc, "C-2", 85.0, parent=parent)
    _unit(db, calc, "Block-2", 85.5)  # an undivided block is a unit itself
    db.commit()

    units = _units(client, headers, calc)

    assert [u["block_name"] for u in units] == ["Block-2", "C-2", "C-10"]
    assert all(set(u) == {"block_id", "block_name", "sub_areas"} for u in units)
    assert all(u["sub_areas"] == [] for u in units)


def test_a_sub_area_with_a_block_is_listed_under_it(client, db):
    headers, user = _login(client, db)
    sub_id = str(uuid.uuid4())
    calc = _calc(db, user)
    unit = _unit(db, calc, "C-1", 85.0)
    calc.result_data = {
        "sub_areas": [
            {
                "id": sub_id,
                "name": "Landslide",
                "category": "protected",
                "blockId": str(unit.id),
            }
        ]
    }
    db.commit()

    (only,) = _units(client, headers, calc)

    assert only["sub_areas"] == [
        {"id": sub_id, "name": "Landslide", "category": "protected"}
    ]


def test_a_sub_area_that_names_no_block_goes_under_the_unit_it_overlaps_most(
    client, db
):
    headers, user = _login(client, db)
    inside_c2 = str(uuid.uuid4())
    nowhere = str(uuid.uuid4())
    calc = _calc(db, user)
    _unit(db, calc, "C-1", 85.0)
    c2 = _unit(db, calc, "C-2", 85.5)
    calc.result_data = {
        "sub_areas": [
            {
                "id": inside_c2,
                "name": "Patch",
                "category": "x",
                "geometry": mapping(box(85.52, 27.02, 85.54, 27.04)),
            },
            {
                "id": nowhere,
                "name": "Far away",
                "category": "x",
                "geometry": mapping(box(80.0, 20.0, 80.1, 20.1)),
            },
            {"id": "not-a-uuid", "name": "Broken", "category": "x"},
        ]
    }
    db.commit()

    units = {u["block_name"]: u for u in _units(client, headers, calc)}

    assert [s["id"] for s in units["C-2"]["sub_areas"]] == [inside_c2]
    assert (
        units["C-1"]["sub_areas"] == []
    )  # the far-away one overlaps no unit: left out, not an error
    assert units["C-2"]["block_id"] == str(c2.id)


def test_only_the_owner_gets_the_units(client, db):
    headers, user = _login(client, db)
    calc = _calc(db, user)
    _unit(db, calc, "C-1", 85.0)
    db.commit()
    intruder, _ = _login(client, db)

    denied = client.get(f"{BASE}/calculations/{calc.id}/plan-units", headers=intruder)

    assert denied.status_code == 404  # D9: nobody but the owner, a super-admin included
