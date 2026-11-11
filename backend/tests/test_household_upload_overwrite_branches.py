"""Coverage for the household bulk-import overwrite branch (H4.2).

`upload_household_data` upserts by `house_no`; when a record matches an
existing household it takes the optimistic lock with no expected version (a
deliberate bulk overwrite) and updates in place. That branch never ran in a
test, so the `check_and_bump(..., None)` overwrite path was uncovered.
"""
from __future__ import annotations

import uuid

from app.models.calculation import Calculation
from app.models.household_information import HouseholdInformation


def _owner(client, db):
    from app.models.user import User

    email = f"hh-{uuid.uuid4().hex[:10]}@example.com"
    client.post("/api/auth/register", json={
        "email": email, "password": "TestPass123!", "full_name": "HH Tester",
    })
    resp = client.post("/api/auth/login", json={
        "email": email, "password": "TestPass123!",
    })
    assert resp.status_code == 200, resp.text
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    user = db.query(User).filter(User.email == email).first()
    return headers, user


def _csv_bytes():
    header_ne = "घर नंवर,थर,महिला संख्या,पुरूष संख्या\n"
    header_en = "house_no,surname,female_count,male_count\n"
    data = "1234,Existing,2,3\n"
    return (header_ne + header_en + data).encode("utf-8-sig")


def test_upload_overwrites_existing_house_no(client, db):
    headers, user = _owner(client, db)
    c = Calculation(user_id=user.id, forest_name=f"HH CF {uuid.uuid4().hex[:6]}")
    db.add(c)
    db.flush()
    db.add(HouseholdInformation(
        calculation_id=c.id, house_no=1234, surname="Old",
        female_count=1, male_count=1, created_by=user.id,
    ))
    db.commit()

    resp = client.post(
        f"/api/household/calculations/{c.id}/upload",
        headers=headers,
        files={"file": ("hh.csv", _csv_bytes(), "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    updated = body.get("records_updated", 0)
    import_total = body.get("records_imported", 0)
    assert updated == 1, f"expected one overwrite, got updated={updated} total={import_total}"

    rec = db.query(HouseholdInformation).filter(
        HouseholdInformation.calculation_id == c.id).one()
    assert rec.house_no == 1234
    # The surname column came only from the CSV, so the record was overwritten.
    assert rec.surname == "Existing"
