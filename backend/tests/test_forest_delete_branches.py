"""The calculation-delete endpoint's permission branches run (H4.2).

The owner's rule (2026-08-27): a calculation may only be deleted by its owner
while the map is in `draft`, or by a super admin regardless. A non-owner gets
403 and a submitted map gets 409. A deletable draft is deleted **together with all
of its data -- nothing is archived**: the owner's rule of 2026-09-21 replaced the
2026-08-27 "archive, never destroy" rule. Each of those branches lives in
`forests.delete_calculation`.
"""
from __future__ import annotations

import uuid

from app.models.calculation import Calculation, MapLifecycleStatus


def _token(client, db, prefix):
    from app.models.user import User

    email = f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"
    client.post("/api/auth/register", json={
        "email": email, "password": "TestPass123!", "full_name": "Delete Tester",
    })
    resp = client.post("/api/auth/login", json={
        "email": email, "password": "TestPass123!",
    })
    assert resp.status_code == 200, resp.text
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    user = db.query(User).filter(User.email == email).first()
    return headers, user


def _calc(db, user_id, lifecycle="draft"):
    c = Calculation(user_id=user_id, forest_name=f"Delete CF {uuid.uuid4().hex[:6]}")
    c.map_lifecycle_status = lifecycle
    db.add(c)
    db.commit()
    return c


def test_a_non_owner_cannot_delete(client, db):
    owner_headers, owner = _token(client, db, "owner")
    other_headers, _other = _token(client, db, "other")
    c = _calc(db, owner.id)

    resp = client.delete(
        f"/api/forests/calculations/{c.id}", headers=other_headers)
    assert resp.status_code == 403, resp.text


def test_a_submitted_map_is_not_deletable_by_its_owner(client, db):
    headers, owner = _token(client, db, "sub")
    c = _calc(db, owner.id, lifecycle=MapLifecycleStatus.SUBMITTED.value)

    resp = client.delete(f"/api/forests/calculations/{c.id}", headers=headers)
    assert resp.status_code == 409, resp.text
    assert "SUBMITTED_NOT_DELETABLE" in resp.text


def test_an_owner_deletes_their_draft_and_nothing_is_archived(client, db):
    from sqlalchemy import text

    headers, owner = _token(client, db, "del")
    c = _calc(db, owner.id)
    cid = str(c.id)

    resp = client.delete(f"/api/forests/calculations/{cid}", headers=headers)
    assert resp.status_code == 204, resp.text

    gone = db.execute(text(
        "SELECT count(*) FROM calculations WHERE id = :c"), {"c": cid}).scalar()
    assert gone == 0
    # nothing is archived: the archive table itself was dropped (migration 093, owner's rule 2026-09-21)
    assert db.execute(text("SELECT to_regclass('public.deleted_calculations')")).scalar() is None
