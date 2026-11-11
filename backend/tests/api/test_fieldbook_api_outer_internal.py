"""The field book API serves outer/internal, junctions, labels and the summary the tab reads."""
import uuid

import pytest
from geoalchemy2.shape import from_shape
from shapely.geometry import box

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.services.fieldbook import generate_fieldbook_points

NS, NL, S = 83.5, 27.5, 0.01


def _login(client, db):
    from app.models.user import User

    email = f"fb-{uuid.uuid4().hex[:10]}@example.com"
    client.post("/api/auth/register", json={"email": email, "password": "TestPass123!", "full_name": "FB"})
    r = client.post("/api/auth/login", json={"email": email, "password": "TestPass123!"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, db.query(User).filter(User.email == email).first()


@pytest.fixture()
def book(client, db):
    headers, user = _login(client, db)
    a, b = box(NS, NL, NS + S, NL + S), box(NS + S, NL, NS + 2 * S, NL + S)
    calc = Calculation(user_id=user.id, forest_name=f"FB {uuid.uuid4().hex[:6]}", structure_locked=False, is_draft=False,
                       boundary_geom=from_shape(box(NS, NL, NS + 2 * S, NL + S), srid=4326))
    db.add(calc)
    db.flush()
    for i, (g, n) in enumerate(((a, "Block-1"), (b, "Block-2")), start=1):
        db.add(ForestBlock(calculation_id=calc.id, name=n, block_name=n, geometry=from_shape(g, srid=4326),
                           area_hectares=100.0, area_sqm=1_000_000.0, index=i, is_compartment=False,
                           division_level=1, is_locked=False, child_count=0))
    db.commit()
    generate_fieldbook_points(db, calc.id, interpolation_distance=50.0, extract_elevation=False)
    return headers, calc


def test_list_serves_the_new_point_fields(client, book):
    headers, calc = book
    r = client.get(f"/api/calculations/{calc.id}/fieldbook", headers=headers)
    assert r.status_code == 200, r.text
    pts = r.json()["points"]
    assert pts[0]["point_label"] == "O1" and pts[0]["boundary_class"] == "outer"
    assert {"junction_degree", "is_junction", "adjacent_units", "next_point_label", "remarks"} <= set(pts[0])
    junction = next(p for p in pts if p["is_junction"])
    assert junction["adjacent_units"] == ["Block-1", "Block-2"] and junction["remarks"] == "outer: Block-1, Block-2"
    internal = next(p for p in pts if p["boundary_class"] == "internal")
    assert internal["point_label"] == "I1" and internal["remarks"] == "internal: Block-1, Block-2"


def test_list_carries_the_summary_the_cards_read(client, book):
    headers, calc = book
    body = client.get(f"/api/calculations/{calc.id}/fieldbook", headers=headers).json()
    pts = body["points"]
    assert body["total_count"] == len(pts)
    assert body["outer_points"] + body["internal_points"] == len(pts)
    assert body["outer_points"] == sum(1 for p in pts if p["boundary_class"] == "outer")
    assert body["junction_points"] == 2
    assert body["total_vertices"] + body["interpolated_points"] == len(pts)
    outer_perimeter = sum(float(p["distance_to_next"]) for p in pts if p["boundary_class"] == "outer")
    assert abs(float(body["total_perimeter_meters"]) - outer_perimeter) < 0.1


def test_the_surveyors_remark_edit_still_works(client, book):
    headers, calc = book
    r = client.patch(f"/api/calculations/{calc.id}/fieldbook/1", headers=headers,
                     json={"remarks": "stone pillar here", "is_verified": True})
    assert r.status_code == 200, r.text
    # the note is added AFTER the generated text, so the units a point separates are never lost to a field note
    assert r.json()["remarks"] == "outer: Block-1; stone pillar here" and r.json()["is_verified"] is True
    # the generated classification is untouched by a remark edit
    assert r.json()["boundary_class"] == "outer" and r.json()["point_label"] == "O1"


def test_exports_are_served_with_the_new_columns(client, book):
    headers, calc = book
    r = client.get(f"/api/calculations/{calc.id}/fieldbook?format=csv", headers=headers)
    assert r.status_code == 200
    text = r.content.decode("utf-8")
    assert "TEST_NEW_CODE_LOADED" not in text
    assert text.splitlines()[1].startswith("O1,vertex,outer")
    g = client.get(f"/api/calculations/{calc.id}/fieldbook?format=geojson", headers=headers).json()
    assert g["features"][0]["properties"]["point"] == "O1"


def test_list_carries_the_lines_outer_closed_internal_open(client, book):
    headers, calc = book
    body = client.get(f"/api/calculations/{calc.id}/fieldbook", headers=headers).json()
    lines = {ln["id"]: ln for ln in body["lines"]}
    assert lines["O-1"]["kind"] == "outer" and lines["O-1"]["closed"] is True
    internal = [ln for ln in lines.values() if ln["kind"] == "internal"]
    assert internal and all(ln["closed"] is False for ln in internal)
    # the outer ring is exactly the outer points, in order; a line's length is reported
    outer_labels = [p["point_label"] for p in body["points"] if p["boundary_class"] == "outer"]
    assert lines["O-1"]["labels"] == outer_labels and lines["O-1"]["length_m"] > 0
    # each point reports the line it is on
    assert all(p["line_id"] and p["lines"] for p in body["points"])
