"""Regression coverage for the household Excel template download.

`download_household_template` embeds a hidden "CasteDB" sheet + a surname
auto-suggestion dropdown from `testData/households_information/caste_classification.csv`.
When that CSV is missing, `dropdown_start_row`/`dropdown_end_row` were only ever
assigned inside the `if os.path.exists(...)` branch — referencing them
afterwards crashed the whole download with
`UnboundLocalError: cannot access local variable 'dropdown_start_row' where it
is not associated with a value` (Python 3.11+ wording) even though the feature
this data drives (a caste-surname dropdown) is a convenience, not a hard
requirement of the template.
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

from app.models.calculation import Calculation


def _owner(client, db):
    from app.models.user import User

    email = f"hh-tpl-{uuid.uuid4().hex[:10]}@example.com"
    client.post("/api/auth/register", json={
        "email": email, "password": "TestPass123!", "full_name": "HH Template Tester",
    })
    resp = client.post("/api/auth/login", json={
        "email": email, "password": "TestPass123!",
    })
    assert resp.status_code == 200, resp.text
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    user = db.query(User).filter(User.email == email).first()
    return headers, user


def test_template_download_survives_missing_caste_csv(client, db):
    """The download must succeed (no surname dropdown) even when the CSV is gone."""
    headers, user = _owner(client, db)
    c = Calculation(user_id=user.id, forest_name=f"HH Tpl CF {uuid.uuid4().hex[:6]}")
    db.add(c)
    db.commit()

    # Simulate the CSV having moved/been deleted, without touching the real
    # file on disk: os.path.exists returns False for exactly this one path.
    with patch("app.api.household_info.os.path.exists", return_value=False):
        resp = client.post(
            f"/api/household/calculations/{c.id}/template",
            headers=headers,
            json={},
        )

    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert len(resp.content) > 0


def test_template_download_with_caste_csv_present(client, db):
    """Normal path: the CSV is there, template still downloads cleanly."""
    headers, user = _owner(client, db)
    c = Calculation(user_id=user.id, forest_name=f"HH Tpl CF {uuid.uuid4().hex[:6]}")
    db.add(c)
    db.commit()

    resp = client.post(
        f"/api/household/calculations/{c.id}/template",
        headers=headers,
        json={},
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.content) > 0
