"""POST /uploads/classify — the endpoint that reads a dropped file's contents (UP-4.2a)."""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.usefixtures("forget_forests")


def _register(client):
    email = f"classify-{uuid.uuid4().hex[:8]}@example.com"
    client.post("/api/auth/register", json={
        "email": email, "password": "TestPass123!", "full_name": "Classify",
    })
    resp = client.post("/api/auth/login", json={"email": email, "password": "TestPass123!"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_a_tree_csv_dropped_for_households_is_identified_and_flagged(client):
    headers = _register(client)
    content = b"species,dbh_cm,longitude,latitude\nShorea robusta,30,85.1,27.1\n"
    resp = client.post(
        "/api/uploads/classify?expected=households",
        files={"file": ("data.csv", content, "text/csv")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["best"] == "trees"
    assert body["looks_like_other"] is True
    assert body["expected_label"]["en"] == "Households"
    assert "species" in body["columns"]


def test_a_household_sheet_is_identified(client):
    headers = _register(client)
    content = "Household Head,Ward,Members\nRam Bahadur,3,5\n".encode()
    resp = client.post(
        "/api/uploads/classify",
        files={"file": ("household data.csv", content, "text/csv")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["best"] == "households"


def test_an_unreadable_file_still_answers(client):
    headers = _register(client)
    resp = client.post(
        "/api/uploads/classify",
        files={"file": ("weird.gpkg", b"\x00\x01\x02", "application/octet-stream")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["best"] is None


def _forest(client, db, headers):
    """A forest whose boundary is a 0.1 x 0.1 degree box around (85.6, 27.4)."""
    from shapely import wkt as shp_wkt
    from shapely.geometry import box

    from app.models.calculation import Calculation, CalculationStatus
    from app.models.user import User

    user = db.query(User).filter(User.email == headers["_email"]).first()
    c = Calculation(
        id=uuid.uuid4(), user_id=user.id, forest_name="Overlap forest",
        boundary_geom=shp_wkt.dumps(box(85.55, 27.35, 85.65, 27.45)), status=CalculationStatus.PROCESSING, is_draft=True,
    )
    db.add(c)
    db.commit()
    return c


def _classify(client, headers, calc, csv: bytes):
    h = {"Authorization": headers["Authorization"]}
    return client.post(f"/api/uploads/classify?calculation_id={calc.id}", files={"file": ("plots.csv", csv, "text/csv")}, headers=h)


@pytest.fixture()
def owner(client):
    email = f"overlap-{uuid.uuid4().hex[:8]}@example.com"
    client.post("/api/auth/register", json={"email": email, "password": "TestPass123!", "full_name": "Overlap"})
    r = client.post("/api/auth/login", json={"email": email, "password": "TestPass123!"})
    return {"Authorization": f"Bearer {r.json()['access_token']}", "_email": email}


def test_a_plot_file_inside_the_forest_is_reported_inside(client, db, owner):
    calc = _forest(client, db, owner)
    r = _classify(client, owner, calc, b"plot_no,lat,lon\n1,27.40,85.60\n2,27.41,85.61\n")
    assert r.status_code == 200, r.text
    o = r.json()["forest_overlap"]
    assert o["status"] == "inside" and o["inside"] == 2 and o["outside"] == 0


def test_a_plot_file_from_another_forest_is_reported_outside_with_the_distance(client, db, owner):
    calc = _forest(client, db, owner)
    r = _classify(client, owner, calc, b"plot_no,lat,lon\n1,27.40,86.10\n2,27.41,86.11\n")
    o = r.json()["forest_overlap"]
    assert o["status"] == "outside" and o["inside"] == 0 and o["outside"] == 2 and o["distance_km"] > 30


def test_a_file_half_in_the_forest_is_partial(client, db, owner):
    calc = _forest(client, db, owner)
    o = _classify(client, owner, calc, b"plot_no,lat,lon\n1,27.40,85.60\n2,27.40,86.10\n").json()["forest_overlap"]
    assert o["status"] == "partial" and o["inside"] == 1 and o["outside"] == 1


def test_someone_elses_forest_cannot_be_probed(client, db, owner):
    calc = _forest(client, db, owner)
    from tests.integration.test_user_group_journey import _register as register_other

    other_headers, _uid = register_other(client)
    r = _classify(client, other_headers, calc, b"plot_no,lat,lon\n1,27.40,85.60\n")
    assert r.status_code == 403
