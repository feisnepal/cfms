"""Owner decision D5: a household upload updates by house number and keeps the others; "replace the whole list" is a separate, explicit choice."""
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
    db.flush()
    for n in (1, 2, 3):
        db.add(HouseholdInformation(calculation_id=c.id, house_no=n, surname=f"Old{n}", female_count=1, male_count=1, created_by=user.id))
    db.commit()
    return headers, c


def _upload(client, forest, rows, **params):
    headers, c = forest
    return client.post(f"/api/household/calculations/{c.id}/upload", headers=headers, params=params,
                       files={"file": ("hh.csv", fx.household_csv(rows), "text/csv")})


def _house_nos(db, c):
    db.expire_all()
    return {h.house_no for h in db.query(HouseholdInformation).filter(HouseholdInformation.calculation_id == c.id)}


def test_by_default_the_others_are_kept(client, db, forest):
    r = _upload(client, forest, [[2, "New2", 3, 3]])
    assert r.status_code == 200 and r.json()["records_updated"] == 1 and r.json()["records_removed"] == 0
    assert _house_nos(db, forest[1]) == {1, 2, 3}


def test_replace_the_whole_list_removes_the_households_the_file_does_not_mention(client, db, forest):
    r = _upload(client, forest, [[2, "New2", 3, 3], [9, "Nine", 1, 1]], replace_all=True)
    body = r.json()
    assert r.status_code == 200 and (body["records_updated"], body["records_imported"], body["records_removed"]) == (1, 1, 2)
    assert _house_nos(db, forest[1]) == {2, 9}


def test_a_household_with_a_typo_in_the_file_is_not_deleted_by_replace(client, db, forest):
    """House 3 is in the file but its row has a negative count: the row is not imported, and the existing household 3 must NOT be removed."""
    r = _upload(client, forest, [[2, "New2", 3, 3], [3, "Typo", -1, 1]], replace_all=True)
    body = r.json()
    assert body["invalid_rows"] == 1 and body["records_removed"] == 1  # only house 1 went
    assert _house_nos(db, forest[1]) == {2, 3}


def test_a_file_with_no_readable_households_never_wipes_the_list(client, db, forest):
    headers, c = forest
    r = client.post(f"/api/household/calculations/{c.id}/upload", headers=headers, params={"replace_all": True},
                    files={"file": ("hh.csv", fx.header_only_csv("घर नंवर,थर"), "text/csv")})
    assert r.status_code == 200 and r.json()["records_removed"] == 0
    assert _house_nos(db, c) == {1, 2, 3}
