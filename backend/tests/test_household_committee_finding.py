"""A committee sheet that cannot be read is reported, not swallowed (UP-0.5 / UP-3); the households still import."""
from __future__ import annotations

import uuid

import pytest

from app.models.calculation import Calculation
from app.models.household_information import HouseholdInformation
from tests import upload_fixtures as fx
from tests.test_household_upload_overwrite_branches import _owner


@pytest.fixture()
def forest(client, db):
    headers, user = _owner(client, db)
    c = Calculation(user_id=user.id, forest_name=f"HH CF {uuid.uuid4().hex[:6]}")
    db.add(c)
    db.commit()
    return headers, c


def test_unreadable_committee_sheet_is_a_finding_and_households_still_import(client, db, forest):
    headers, c = forest
    r = client.post(f"/api/household/calculations/{c.id}/upload", headers=headers,
                    files={"file": ("hh.xlsx", fx.household_xlsx_with_broken_committee(), "application/octet-stream")})
    assert r.status_code == 200
    body = r.json()
    assert body["records_imported"] == 1
    f = [x for x in body["findings"] if x["code"] == "household.committee_not_imported"]
    assert len(f) == 1 and "वन उपभोक्ता समिति" in f[0]["title_en"] and f[0]["fix_en"] and f[0]["fix_ne"] and f[0]["severity"] == "warning"
    db.expire_all()
    assert db.query(HouseholdInformation).filter(HouseholdInformation.calculation_id == c.id).count() == 1
