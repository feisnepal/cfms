"""End-to-end read-side audit: the household read endpoints log who saw what.

H8.7 / S2-68 audited the WRITE side of household records (caste classification,
precise coordinates). This covers the READ side -- list, detail, summary,
export -- so there is a record of who has seen the sensitive fields, logged
after the ownership check (a refused request is not recorded as an access).

These tests drive the actual HTTP endpoints so the `record_household_access`
calls inside them genuinely execute, and verify a matching audit row is written
for each read.
"""
from __future__ import annotations

import uuid

from sqlalchemy import text

from app.models.user import User


def _user_id(db):
    return str(db.query(User).filter(User.email == "testuser@example.com").first().id)


def _make_calc(db, user_id, name="My Forest"):
    calc_id = uuid.uuid4()
    db.execute(text(
        "INSERT INTO calculations (id, user_id, forest_name, status) "
        "VALUES (:id, :uid, :fn, 'PROCESSING')"
    ), {"id": calc_id, "uid": user_id, "fn": name})
    db.commit()
    return calc_id


def _make_household(db, calc_id, user_id, house_no=1):
    hh_id = uuid.uuid4()
    db.execute(text(
        "INSERT INTO household_information (id, calculation_id, house_no, "
        "surname, female_count, male_count, created_by, version) "
        "VALUES (:id, :cid, :hn, :s, 2, 3, :uid, 0)"
    ), {"id": hh_id, "cid": calc_id, "hn": house_no, "s": "Shrestha", "uid": user_id})
    db.commit()
    return hh_id


def _count_logs(db, calc_id, hh_id=None):
    if hh_id is not None:
        return db.execute(text(
            "SELECT COUNT(*) FROM household_access_log "
            "WHERE calculation_id = :c OR household_id = :h"
        ), {"c": calc_id, "h": hh_id}).scalar()
    return db.execute(text(
        "SELECT COUNT(*) FROM household_access_log WHERE calculation_id = :c"
    ), {"c": calc_id}).scalar()


def test_read_endpoints_record_an_audit_row(client, db, auth_headers):
    user_id = _user_id(db)
    calc_id = _make_calc(db, user_id)
    _make_household(db, calc_id, user_id)

    assert _count_logs(db, calc_id) == 0

    resp_list = client.get(
        f"/api/household/calculations/{calc_id}/households", headers=auth_headers)
    assert resp_list.status_code == 200
    assert len(resp_list.json()) == 1

    resp_detail = client.get(
        f"/api/household/households/{calc_id}", headers=auth_headers)
    assert resp_detail.status_code == 404  # a calc id is not a household id

    resp_export = client.get(
        f"/api/household/calculations/{calc_id}/export", headers=auth_headers)
    assert resp_export.status_code == 200

    # list + export logged; the refused detail was not.
    assert _count_logs(db, calc_id) == 2


def test_detail_and_summary_log_an_audit_row(client, db, auth_headers):
    user_id = _user_id(db)
    calc_id = _make_calc(db, user_id)
    hh_id = _make_household(db, calc_id, user_id)

    resp_detail = client.get(
        f"/api/household/households/{hh_id}", headers=auth_headers)
    assert resp_detail.status_code == 200, resp_detail.text
    assert resp_detail.json()["total_population"] == 5

    resp_summary = client.get(
        f"/api/household/calculations/{calc_id}/summary", headers=auth_headers)
    assert resp_summary.status_code == 200
    assert resp_summary.json()["total_households"] == 1

    assert _count_logs(db, calc_id, hh_id) == 2
