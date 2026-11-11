"""UP-3.2: the household reader finds the header row itself, understands English column names, and reports columns it does not understand."""
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


def _upload(client, forest, data: bytes, name: str = "hh.csv"):
    headers, c = forest
    return client.post(f"/api/household/calculations/{c.id}/upload", headers=headers, files={"file": (name, data, "text/csv")})


def _count(db, c) -> int:
    db.expire_all()
    return db.query(HouseholdInformation).filter(HouseholdInformation.calculation_id == c.id).count()


def test_a_title_row_above_the_header_is_skipped_and_the_user_is_told_where_the_header_was(client, db, forest):
    title = "सामुदायिक वन घरधुरी विवरण,,,\n,,,\n"
    data = (title + fx.household_csv([[1, "A", 1, 1], [2, "B", 1, 1]]).decode("utf-8-sig")).encode("utf-8-sig")
    body = _upload(client, forest, data).json()
    assert body["records_imported"] == 2 and body["total_rows"] == 2
    found = [x for x in body["findings"] if x["code"] == "household.header_row_found"]
    assert len(found) == 1 and "row 3" in found[0]["title_en"] and found[0]["severity"] == "info"


def test_english_only_column_names_are_understood(client, db, forest):
    data = "house_no,surname,female_count,male_count\n1,Sharma,2,3\n2,Thapa,1,1\n".encode("utf-8")
    body = _upload(client, forest, data).json()
    assert body["records_imported"] == 2 and body["invalid_rows"] == 0
    assert _count(db, forest[1]) == 2


def test_a_column_that_is_not_understood_is_reported_not_silently_dropped(client, db, forest):
    data = "house_no,surname,female_count,male_count,my_notes\n1,Sharma,2,3,checked\n".encode("utf-8")
    body = _upload(client, forest, data).json()
    assert body["records_imported"] == 1
    found = [x for x in body["findings"] if x["code"] == "household.headers_not_recognised"]
    assert len(found) == 1 and "my_notes" in found[0]["title_en"] and found[0]["severity"] == "warning" and found[0]["fix_ne"]


def test_the_template_layout_is_unchanged_and_needs_no_note(client, db, forest):
    body = _upload(client, forest, fx.household_csv([[1, "Sharma", 2, 3], [2, "Thapa", 1, 1]])).json()
    assert body["records_imported"] == 2 and body["findings"] == []  # nothing to say about a file that is exactly right


def test_a_sheet_with_no_household_column_names_says_what_it_saw_and_to_use_the_template(client, db, forest):
    body = _upload(client, forest, b"name,village,phone\nA,One,1\n").json()
    assert body["success"] is False and body["records_imported"] == 0
    f = body["findings"][0]
    assert f["code"] == "household.headers_not_found" and "name, village, phone" in f["title_en"] and "template" in f["fix_en"]
    assert _count(db, forest[1]) == 0


def test_the_spelling_nambar_with_ba_is_read_like_the_template_spelling(client, db, forest):
    """UP-4.X parity: the file Add data identifies as a household list (e2e fixture) must import on the household screen the same way."""
    data = ("घर नंबर,थर,महिला संख्या,पुरूष संख्या\nhouse_no,surname,female_count,male_count\n1,Sharma,2,3\n2,Thapa,1,1\n").encode("utf-8-sig")
    body = _upload(client, forest, data).json()
    assert body["records_imported"] == 2 and body["invalid_rows"] == 0 and body["findings"] == []
