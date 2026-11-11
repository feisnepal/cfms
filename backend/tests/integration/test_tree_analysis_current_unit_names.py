"""The tree analysis names every tree's unit as the attribute table does: the unit's CURRENT name, and the LEAF unit that contains the tree.

Regression (owner, 2026-10-15): the Tree inventory showed "बनस्खन्डी - Compartment 1 > बनस्खन्डी - Compartment 1-SC2_merged" while the attribute
table lists a, b, c ... The trees carry a snapshot of unit names written when they were assigned: a unit renamed afterwards left its old name
on its trees, and a tree could be filed under a unit that has since been divided (the table lists only the undivided ones).
"""
import uuid

from geoalchemy2.shape import from_shape
from shapely.geometry import box
from sqlalchemy import text

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.user import User
from app.services.operational_plan.data_collector import get_tree_mapping_analysis_data

WEST, EAST, SOUTH, NORTH = 85.2290, 85.2330, 27.6790, 27.6820
MID = (WEST + EAST) / 2
WHOLE = box(WEST, SOUTH, EAST, NORTH)
LEFT = box(WEST, SOUTH, MID, NORTH)
RIGHT = box(MID, SOUTH, EAST, NORTH)


def _login(client, db):
    email = f"tn-{uuid.uuid4().hex[:10]}@example.com"
    client.post("/api/auth/register", json={"email": email, "password": "TestPass123!", "full_name": "Tree Names"})
    r = client.post("/api/auth/login", json={"email": email, "password": "TestPass123!"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, db.query(User).filter(User.email == email).first()


def _unit(db, calc, name, geom, *, level, parent=None, index=0):
    u = ForestBlock(
        calculation_id=calc.id, name=name, block_name=name, compartment_code=name, geometry=from_shape(geom, srid=4326),
        area_hectares=5.0, area_sqm=50000.0, index=index, is_compartment=True, division_level=level,
        parent_block_id=parent.id if parent else None, is_locked=False, child_count=0,
    )
    db.add(u)
    db.flush()
    return u


def _csv() -> bytes:
    # 3 trees in the left half, 3 in the right half
    left = [f"{WEST + 0.0002 + i * 0.0003},{SOUTH + 0.0010 + i * 0.0002},Shorea robusta,{22 + i},{14 + i}" for i in range(3)]
    right = [f"{MID + 0.0002 + i * 0.0003},{SOUTH + 0.0010 + i * 0.0002},Shorea robusta,{30 + i},{16 + i}" for i in range(3)]
    return ("longitude,latitude,species,dia_cm,height_m\n" + "\n".join(left + right) + "\n").encode()


def _forest_with_trees(client, db):
    headers, user = _login(client, db)
    calc = Calculation(user_id=user.id, forest_name=f"TN {uuid.uuid4().hex[:6]}", structure_locked=False, is_draft=False,
                       boundary_geom=from_shape(WHOLE, srid=4326))
    db.add(calc)
    db.flush()
    top = _unit(db, calc, "C-1", WHOLE, level=1)
    left = _unit(db, calc, "a", LEFT, level=2, parent=top, index=1)
    right = _unit(db, calc, "b", RIGHT, level=2, parent=top, index=2)
    top.child_count = 2
    db.commit()
    content = _csv()
    up = client.post("/api/inventory/upload", headers=headers, data={"calculation_id": str(calc.id)}, files={"file": ("t.csv", content, "text/csv")})
    assert up.status_code == 200, up.text
    iid = up.json()["inventory_id"]
    pr = client.post(f"/api/inventory/{iid}/process", headers=headers, files={"file": ("t.csv", content, "text/csv")})
    assert pr.status_code == 200, pr.text
    return calc, top, left, right, iid


def _rows(db, calc):
    data = get_tree_mapping_analysis_data(db, str(calc.id))
    assert data["sm_available"]
    return {r["unit_name"]: r["tree_count"] for r in data["sm_hierarchy_summary"]}


def test_trees_are_filed_under_the_leaf_units_the_attribute_table_lists(client, db):
    calc, top, left, right, _ = _forest_with_trees(client, db)
    assert _rows(db, calc) == {"a": 3, "b": 3}  # never the divided parent "C-1"


def test_a_unit_renamed_after_the_trees_were_assigned_shows_its_new_name(client, db):
    calc, top, left, right, _ = _forest_with_trees(client, db)
    assert _rows(db, calc) == {"a": 3, "b": 3}
    db.query(ForestBlock).filter(ForestBlock.id == left.id).update({"name": "north", "block_name": "north"})
    db.commit()
    rows = _rows(db, calc)
    assert rows == {"north": 3, "b": 3}, rows
    assert "a" not in rows  # the old name is gone from every row


def test_the_parent_renamed_too_never_leaks_its_old_name(client, db):
    calc, top, left, right, _ = _forest_with_trees(client, db)
    db.query(ForestBlock).filter(ForestBlock.id == top.id).update({"name": "q", "block_name": "q"})
    db.commit()
    data = get_tree_mapping_analysis_data(db, str(calc.id))
    assert "C-1" not in str(data["sm_hierarchy_summary"])
    assert {r["compartment"] for r in data["sm_hierarchy_summary"]} == {"q"}


def test_trees_filed_under_a_divided_unit_move_to_the_leaf_that_contains_them(client, db):
    calc, top, left, right, iid = _forest_with_trees(client, db)
    # what an older assignment (or a merge) left behind: every tree filed under the divided parent
    db.execute(
        text("UPDATE public.inventory_trees SET extra_columns = COALESCE(extra_columns, '{}'::jsonb) || jsonb_build_object("
             "'compartment_name', 'C-1', 'parent_compartment_name', NULL, 'division_level', 1) WHERE inventory_calculation_id = :i"),
        {"i": iid},
    )
    db.commit()
    assert _rows(db, calc) == {"a": 3, "b": 3}


def test_a_consistent_forest_is_left_alone(client, db):
    calc, top, left, right, iid = _forest_with_trees(client, db)
    before = db.execute(text("SELECT count(*) FROM public.inventory_trees WHERE inventory_calculation_id = :i"), {"i": iid}).scalar()
    assert _rows(db, calc) == {"a": 3, "b": 3}
    assert _rows(db, calc) == {"a": 3, "b": 3}  # asking again changes nothing
    assert db.execute(text("SELECT count(*) FROM public.inventory_trees WHERE inventory_calculation_id = :i"), {"i": iid}).scalar() == before
