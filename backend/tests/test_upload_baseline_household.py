"""UP-0 characterization: what the household upload does TODAY with each wrong file (UPLOAD_EXPERIENCE_PLAN.md).

These tests pin the CURRENT behaviour, including the defects, so the later phases change it on purpose: when a phase fixes a defect it
inverts the matching assertion here and says so in the commit. Tests named ``..._today`` are known defects, not wanted behaviour.
"""
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


def _upload(client, forest, name: str, data: bytes):
    headers, c = forest
    return client.post(f"/api/household/calculations/{c.id}/upload", headers=headers, files={"file": (name, data, "application/octet-stream")})


def _count(db, c) -> int:
    db.expire_all()
    return db.query(HouseholdInformation).filter(HouseholdInformation.calculation_id == c.id).count()


def test_template_shaped_file_imports_every_row(client, db, forest):
    r = _upload(client, forest, "hh.csv", fx.household_csv([[1, "Sharma", 2, 3], [2, "Thapa", 1, 1]]))
    assert r.status_code == 200 and r.json()["records_imported"] == 2
    assert _count(db, forest[1]) == 2


def test_a_single_header_file_imports_every_row(client, db, forest):
    """Was: the first data row was eaten as if it were the English header row (UP-0 defect, confirmed). Fixed in UP-3.2."""
    r = _upload(client, forest, "hh.csv", fx.household_csv([[1, "Sharma", 2, 3], [2, "Thapa", 1, 1]], two_header_rows=False))
    body = r.json()
    assert r.status_code == 200 and body["total_rows"] == 2 and body["records_imported"] == 2
    db.expire_all()
    assert {h.house_no for h in db.query(HouseholdInformation).filter(HouseholdInformation.calculation_id == forest[1].id)} == {1, 2}


def test_invalid_rows_are_skipped_and_the_valid_ones_imported(client, db, forest):
    r = _upload(client, forest, "hh.csv", fx.household_csv([[1, "Sharma", 2, 3], [2, "Thapa", -1, 2], [3, "Rai", "two", 1], [4, "Gurung", 1, 1]]))
    body = r.json()
    assert r.status_code == 200
    assert (body["valid_rows"], body["invalid_rows"], body["records_imported"]) == (2, 2, 2)
    problems = {v["row_number"]: v["errors"] for v in body["validations"] if not v["is_valid"]}
    assert problems == {4: ["female_count cannot be negative"], 5: ["Invalid value for female_count"]}  # English only, no "how to fix"
    assert _count(db, forest[1]) == 2


def test_a_house_number_repeated_in_one_file_is_listed_and_the_rest_still_import(client, db, forest):
    """Was a 500 showing raw SQL with nothing imported (UP-0 finding); fixed in UP-1.4 per decision D1: good rows go in, the repeat is listed."""
    r = _upload(client, forest, "hh.csv", fx.household_csv([[3, "Rai", 1, 1], [4, "Gurung", 1, 1], [4, "Gurung", 1, 1]]))
    body = r.json()
    assert r.status_code == 200 and (body["valid_rows"], body["invalid_rows"], body["records_imported"]) == (2, 1, 2)
    bad = [v for v in body["validations"] if not v["is_valid"]]
    assert len(bad) == 1 and "House number 4 is repeated (also on row 4)" in bad[0]["errors"][0]  # says where, and what to do
    assert "Give each household its own house number" in bad[0]["errors"][0]
    assert _count(db, forest[1]) == 2


def _detail(r):
    return r.json()["detail"]


def test_an_empty_file_gets_a_plain_bilingual_finding(client, forest):
    """Was a 500 'list index out of range' (UP-0); coded since UP-2."""
    r = _upload(client, forest, "hh.csv", fx.empty_file())
    d = _detail(r)
    assert r.status_code == 400 and d["code"] == "file.empty" and "empty" in d["message"] and d["message_np"]
    assert "index out of range" not in str(d)


def test_a_header_only_file_says_there_are_no_data_rows_and_how_the_file_should_look(client, forest):
    r = _upload(client, forest, "hh.csv", fx.header_only_csv("घर नंवर,थर"))
    body = r.json()
    assert r.status_code == 200 and body["success"] is False and body["total_rows"] == 0
    f = body["findings"][0]
    assert f["code"] == "household.no_rows" and f["severity"] == "error" and "row 3" in f["fix_en"] and f["fix_ne"]


def test_non_utf8_csv_gets_the_encoding_finding_with_the_excel_steps(client, forest):
    r = _upload(client, forest, "hh.csv", fx.non_utf8_csv())
    d = _detail(r)
    assert r.status_code == 400 and d["code"] == "file.encoding" and "CSV UTF-8" in d["message"] and d["message_np"]


def test_a_workbook_renamed_to_csv_is_named_for_what_it_is(client, forest):
    """Was the misleading 'encoding error' (UP-0); now the real cause."""
    r = _upload(client, forest, "hh.csv", fx.csv_that_is_really_xlsx())
    d = _detail(r)
    assert r.status_code == 400 and d["code"] == "file.wrong_type" and "Excel workbook" in d["message"] and "UTF-8" not in d["message"]


def test_wrong_extension_is_refused_with_what_to_save_it_as(client, forest):
    r = _upload(client, forest, "hh.txt", fx.household_csv([[1, "A", 1, 1]]))
    d = _detail(r)
    assert r.status_code == 400 and d["code"] == "file.wrong_type" and ".txt" in d["message"] and "CSV" in d["message"]


def test_a_corrupt_workbook_is_a_plain_finding_not_a_library_error(client, forest):
    """Was a 500 'File is not a zip file' (UP-0)."""
    r = _upload(client, forest, "hh.xlsx", fx.corrupt_xlsx())
    d = _detail(r)
    assert r.status_code == 400 and d["code"] == "file.corrupt" and "password" in d["message"] and d["message_np"]
    assert "zip" not in str(d).lower()


def test_problem_rows_are_grouped_by_cause_with_the_rows_and_the_fix(client, db, forest):
    r = _upload(client, forest, "hh.csv", fx.household_csv([[1, "A", -1, 1], [2, "B", -1, 1], [3, "C", "x", 1], [4, "D", 1, 1]]))
    body = r.json()
    groups = {f["found"]: f for f in body["findings"] if f["code"] == "household.row_invalid"}
    neg = groups["female_count cannot be negative"]
    assert neg["where"]["rows"] == [3, 4] and "2 rows have a problem" in neg["title_en"] and "rows 3, 4" in neg["fix_en"] and neg["fix_ne"]
    assert groups["Invalid value for female_count"]["where"]["rows"] == [5]
    assert _count(db, forest[1]) == 1  # only the valid row went in
