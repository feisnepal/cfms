"""Sampling design branch coverage (H4.2).

`update_sampling_design` takes the design's optimistic-lock version before
editing it (`check_and_bump` on the `sampling` domain). No test seeded a real
`SamplingDesign` row through the API, so that guard never ran.
"""
from __future__ import annotations

import uuid

from app.models.calculation import Calculation
from app.models.sampling import SamplingDesign


def _user(client):
    email = f"sampling-{uuid.uuid4().hex[:10]}@example.com"
    client.post("/api/auth/register", json={
        "email": email, "password": "TestPass123!", "full_name": "Samp",
    })
    r = client.post("/api/auth/login", json={
        "email": email, "password": "TestPass123!",
    })
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _design(db, user_id):
    calc = Calculation(user_id=user_id, forest_name="Sampling CF")
    db.add(calc)
    db.flush()
    d = SamplingDesign(
        calculation_id=calc.id, sampling_type="systematic", grid_spacing_meters=100,
    )
    db.add(d)
    db.commit()
    return d


def test_update_takes_the_optimistic_lock_and_bumps(client, db):
    from app.models.user import User

    headers = _user(client)
    user = db.query(User).order_by(User.created_at.desc()).first()
    design = _design(db, user.id)
    design_id = str(design.id)

    resp = client.put(
        f"/api/sampling/{design_id}",
        json={"version": 0, "notes": "revised methodology"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["notes"] == "revised methodology"
    assert body["version"] == 1, "the design's version was bumped by check_and_bump"


def test_update_with_a_stale_version_is_a_409(client, db):
    from app.models.user import User

    headers = _user(client)
    user = db.query(User).order_by(User.created_at.desc()).first()
    design = _design(db, user.id)
    design_id = str(design.id)

    # Take the lock once so the current version moves to 1.
    client.put(
        f"/api/sampling/{design_id}",
        json={"version": 0, "notes": "first"},
        headers=headers,
    )
    # Now retry with the stale version 0 -> 409.
    resp = client.put(
        f"/api/sampling/{design_id}",
        json={"version": 0, "notes": "stale"},
        headers=headers,
    )
    assert resp.status_code == 409, resp.text


def test_get_points_cache_miss_records_a_derived_write(client, db):
    from sqlalchemy import text

    from app.models.user import User

    headers = _user(client)
    user = db.query(User).order_by(User.created_at.desc()).first()
    design = _design(db, user.id)
    design_id = str(design.id)
    assert design.points_data is None, "precondition: no cached points"

    # Seed a real MultiPoint geometry so the cache-miss compute loop runs.
    db.execute(text(
        "UPDATE sampling_designs SET points_geometry = "
        "ST_SetSRID(ST_GeomFromText('MULTIPOINT((81.0 28.0),(81.1 28.05))'), 4326) "
        "WHERE id = CAST(:i AS uuid)"),
        {"i": design_id})
    db.commit()

    resp = client.get(
        f"/api/sampling/{design_id}/points", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["points"]) == 2

    refreshed = db.query(SamplingDesign).filter(
        SamplingDesign.id == design.id).first()
    assert refreshed.points_data, "the computed points were cached on the design"
