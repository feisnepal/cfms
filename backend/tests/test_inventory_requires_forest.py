"""A tree inventory must belong to a forest the caller may use (work package FD, FD-5).

Owner's rule, 2026-09-21: deleting a forest deletes all of its data, so no data may exist without a
forest. The upload endpoints therefore answer 422 without one (a clear, bilingual message rather than a
database error), 404 for a forest that does not exist and 403 for someone else's forest.
"""

import uuid

from app.models.calculation import Calculation

_CSV = (
    "file",
    (
        "t.csv",
        b"species,dia_cm,height_m,longitude,latitude\nSal,20,10,84.0,28.0\n",
        "text/csv",
    ),
)


def _login(client, db, prefix):
    from app.models.user import User

    email = f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "TestPass123!", "full_name": "Inv Tester"},
    )
    resp = client.post(
        "/api/auth/login", json={"email": email, "password": "TestPass123!"}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}, db.query(
        User
    ).filter(User.email == email).first()


def _detail(resp):
    return resp.json().get("detail", {})


def test_upload_without_a_forest_is_refused_with_a_bilingual_message(client, db):
    headers, _ = _login(client, db, "nf")
    resp = client.post("/api/inventory/upload", headers=headers, files=[_CSV])
    assert resp.status_code == 422, resp.text
    assert _detail(resp)["code"] == "inventory.forest_required"
    assert _detail(resp)["message"] and _detail(resp)["message_np"]


def test_upload_to_a_forest_that_does_not_exist_is_404(client, db):
    headers, _ = _login(client, db, "nx")
    resp = client.post(
        "/api/inventory/upload",
        headers=headers,
        files=[_CSV],
        data={"calculation_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 404, resp.text
    assert _detail(resp)["code"] == "inventory.forest_not_found"


def test_upload_to_someone_elses_forest_is_403(client, db):
    _, owner = _login(client, db, "own")
    other_headers, _ = _login(client, db, "oth")
    forest = Calculation(user_id=owner.id, forest_name=f"Owned {uuid.uuid4().hex[:6]}")
    db.add(forest)
    db.commit()
    resp = client.post(
        "/api/inventory/upload",
        headers=other_headers,
        files=[_CSV],
        data={"calculation_id": str(forest.id)},
    )
    assert resp.status_code == 403, resp.text
    assert _detail(resp)["code"] == "inventory.forest_not_yours"


def test_the_confirm_mapping_endpoint_also_requires_a_forest(client, db):
    headers, _ = _login(client, db, "cm")
    resp = client.post(
        "/api/inventory/confirm-mapping",
        headers=headers,
        files=[_CSV],
        data={"mapping": "{}"},
    )
    assert resp.status_code == 422, resp.text
    assert _detail(resp)["code"] == "inventory.forest_required"
