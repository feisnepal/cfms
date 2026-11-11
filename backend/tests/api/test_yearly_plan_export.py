"""The single exporter (YEARLY_ACTIVITIES_WORKSPACE_PLAN §5.7): the same table from either screen is
identical, reproduces the legacy derivations, and agrees with the operational plan's numbers."""

from __future__ import annotations

import csv
import io
import json
import uuid

import pytest

from app.models.calculation import Calculation
from app.models.user import User, UserRole
from app.models.yearly_activities import (
    ActivityDrawnFeature,
    ActivitySpatialAssignment,
    ActivityYearDetail,
    PotentialActivity,
    ProposedYearlyActivity,
)
from app.services.operational_plan.data_collector import _collect_yearly_activities_data

BASE = "/api/yearly-activities"


def _login(client, db, role=None):
    email = f"exp-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "TestPass123!", "full_name": "Export Tester"},
    )
    if role is not None:
        user = db.query(User).filter(User.email == email).first()
        user.role = role
        db.commit()
    resp = client.post(
        "/api/auth/login", json={"email": email, "password": "TestPass123!"}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}, db.query(
        User
    ).filter(User.email == email).first()


def _calc(db, user, name="Export Forest"):
    calc = Calculation(user_id=user.id, uploaded_filename="e.csv", forest_name=name)
    db.add(calc)
    db.commit()
    return calc


def _line(
    db,
    calc,
    name,
    program,
    unit,
    *,
    requires_map,
    years,
    quantity=1,
    budget=0,
    whole_forest=False,
):
    """``years`` = {year: (quantity, budget)}; every other year is an explicit 0 / 0."""
    master = PotentialActivity(
        progarms=program,
        activities=name,
        unit=unit,
        requires_map=requires_map,
        display_order=0,
    )
    db.add(master)
    db.flush()
    line = ProposedYearlyActivity(
        calculation_id=calc.id,
        potential_activity_id=master.id,
        default_quantity=quantity,
        default_yearly_budget=budget,
        assign_to_all_blocks=whole_forest,
    )
    db.add(line)
    db.flush()
    for y in range(1, 11):
        q, b = years.get(y, (0, 0))
        db.add(
            ActivityYearDetail(
                proposed_activity_id=line.id, year_number=y, quantity=q, yearly_budget=b
            )
        )
    db.commit()
    return line


def _parse(body: str):
    return list(csv.reader(io.StringIO(body.lstrip("﻿"))))


def _get(client, headers, calc, kind, **params):
    path = "yearly-plan" if kind == "plan" else "activity-features"
    return client.get(
        f"{BASE}/calculations/{calc.id}/{path}/export", headers=headers, params=params
    )


def test_the_plan_csv_reproduces_the_legacy_derivations_and_the_location_rules(
    client, db
):
    headers, user = _login(client, db)
    calc = _calc(db, user)
    placed = _line(
        db,
        calc,
        "Nursery construction",
        "Forest development",
        "वटा",
        requires_map=True,
        years={1: (2, 60000), 2: (2, 60000), 3: (2, 60000)},
    )
    db.add(
        ActivityDrawnFeature(
            proposed_activity_id=placed.id,
            calculation_id=calc.id,
            feature_type="point",
            geometry="SRID=4326;POINT(85 27)",
            properties={"name": "Ward 3 nursery", "years": [1]},
        )
    )
    _line(
        db,
        calc,
        "Office running cost",
        "Administration",
        "पटक",
        requires_map=False,
        years={y: (0.5, 1200) for y in range(1, 11)},
    )
    _line(
        db,
        calc,
        "Boundary patrol",
        "Protection",
        "पटक",
        requires_map=True,
        whole_forest=True,
        years={1: (4, 0), 2: (0, 300)},
    )  # voluntary in year 1, funded-only in year 2

    resp = _get(client, headers, calc, "plan")

    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/csv")
    assert "_YearlyActivity_Plan_" in resp.headers["content-disposition"]
    assert resp.content.startswith(
        "﻿".encode("utf-8")
    )  # BOM: Excel reads the Devanagari
    table = _parse(resp.text)
    assert table[0][:4] == ["S.No", "Activity", "Programme", "Unit"]
    by_name = {row[1]: row for row in table[1:]}

    nursery = by_name["Nursery construction"]
    assert nursery[4] == "Y1:2, Y2:2, Y3:2"  # only the years above 0
    assert nursery[5] == "Y1:60000, Y2:60000, Y3:60000"
    assert nursery[6] == "180000"  # the ten-year sum
    assert nursery[7:9] == [
        "places",
        "Drawn on the map",
    ]  # a place is drawn but lies in no unit: still not "no specific location"
    assert nursery[9] == "Ward 3 nursery"

    office = by_name["Office running cost"]
    assert office[4].startswith(
        "Y1:0.5, Y2:0.5"
    )  # NOT rounded to 1 (the legacy Math.round)
    assert office[7:9] == [
        "",
        "",
    ]  # an activity that needs no map has no location (D26)
    assert office[9] == "None"

    patrol = by_name["Boundary patrol"]
    assert (
        patrol[4] == "Y1:4" and patrol[5] == "Y2:300"
    )  # each list keeps only its own years > 0
    assert patrol[7:9] == ["all", "All Blocks"]  # applies to the whole forest


def test_the_rows_are_in_a_fixed_order_programme_then_activity(client, db):
    headers, user = _login(client, db)
    calc = _calc(db, user)
    for name, program in (
        ("Zeta", "B program"),
        ("Alpha", "B program"),
        ("Mid", "A program"),
    ):
        _line(db, calc, name, program, "पटक", requires_map=False, years={1: (1, 10)})
    rows = _parse(_get(client, headers, calc, "plan").text)[1:]
    assert [r[1] for r in rows] == ["Mid", "Alpha", "Zeta"]
    assert [r[0] for r in rows] == ["1", "2", "3"]


def test_the_same_saved_data_gives_the_same_bytes_every_time(client, db):
    headers, user = _login(client, db)
    calc = _calc(db, user)
    _line(db, calc, "A", "P", "पटक", requires_map=False, years={1: (1, 10), 2: (1, 20)})
    a = _get(client, headers, calc, "plan").content
    b = _get(client, headers, calc, "plan").content
    assert a == b  # one builder: nothing depends on which screen asked


def test_the_nepali_headers_are_used_for_lang_ne(client, db):
    headers, user = _login(client, db)
    calc = _calc(db, user)
    _line(db, calc, "A", "P", "पटक", requires_map=False, years={1: (1, 10)})
    table = _parse(_get(client, headers, calc, "plan", lang="ne").text)
    assert table[0][1] == "कार्य" and table[0][6].startswith(
        "कुल बजेट"
    )  # the two legacy English headers too
    assert (
        _parse(_get(client, headers, calc, "features", lang="ne").text)[0][3] == "नाम"
    )


def test_the_csv_total_equals_the_operational_plans_total(client, db):
    headers, user = _login(client, db)
    calc = _calc(db, user)
    _line(
        db,
        calc,
        "A",
        "P",
        "पटक",
        requires_map=False,
        years={1: (1, 1500), 2: (1, 2500)},
    )
    _line(
        db,
        calc,
        "B",
        "P",
        "पटक",
        requires_map=False,
        years={y: (1, 100) for y in range(1, 11)},
    )
    rows = _parse(_get(client, headers, calc, "plan").text)[1:]
    op = _collect_yearly_activities_data(db, str(calc.id))
    assert sum(float(r[6]) for r in rows) == op["total_ten_year_budget"] == 5000.0


def test_the_features_csv_has_one_row_per_live_place_with_measured_length_and_area(
    client, db
):
    headers, user = _login(client, db)
    calc = _calc(db, user)
    line = _line(
        db,
        calc,
        "Plantation",
        "Forest development",
        "हेक्टर",
        requires_map=True,
        years={1: (2, 100)},
    )
    line_b = _line(
        db,
        calc,
        "Fire line",
        "Protection",
        "कि.मि.",
        requires_map=True,
        years={1: (1, 100)},
    )
    db.add_all(
        [
            ActivityDrawnFeature(
                proposed_activity_id=line.id,
                calculation_id=calc.id,
                feature_type="polygon",
                geometry="SRID=4326;POLYGON((85 27,85.001 27,85.001 27.001,85 27.001,85 27))",
                properties={
                    "name": "Block A planting",
                    "years": [1],
                    "geo_area_ha": 1.05,
                },
            ),
            ActivityDrawnFeature(
                proposed_activity_id=line_b.id,
                calculation_id=calc.id,
                feature_type="line",
                geometry="SRID=4326;LINESTRING(85 27,85.01 27)",
                properties={"name": "North line", "years": [1], "geo_length_km": 0.99},
            ),
        ]
    )
    db.commit()
    deleted = ActivityDrawnFeature(
        proposed_activity_id=line.id,
        calculation_id=calc.id,
        feature_type="point",
        geometry="SRID=4326;POINT(85 27)",
        properties={"name": "gone"},
    )
    db.add(deleted)
    db.commit()
    from datetime import datetime, timezone

    deleted.deleted_at = datetime.now(timezone.utc)
    db.commit()

    table = _parse(_get(client, headers, calc, "features").text)

    assert table[0][3:5] == ["Name", "Geometry"]
    names = {row[3]: row for row in table[1:]}
    assert set(names) == {
        "Block A planting",
        "North line",
    }  # the soft-deleted place is not exported
    assert (
        names["Block A planting"][4] == "Area"
        and names["Block A planting"][10] == "1.05"
    )
    assert names["North line"][4] == "Line" and names["North line"][9] == "0.99"
    assert names["North line"][6] == "Y1"


def test_a_spatial_assignment_to_all_blocks_prints_the_legacy_all_value(client, db):
    headers, user = _login(client, db)
    calc = _calc(db, user)
    line = _line(
        db,
        calc,
        "Grazing control",
        "Protection",
        "हेक्टर",
        requires_map=True,
        years={1: (1, 10)},
    )
    db.add(
        ActivitySpatialAssignment(
            proposed_activity_id=line.id, assignment_type="all_blocks"
        )
    )
    db.commit()
    row = _parse(_get(client, headers, calc, "plan").text)[1]
    assert row[7:9] == ["all", "All Blocks"]


def test_a_cell_with_a_quote_or_a_comma_survives(client, db):
    headers, user = _login(client, db)
    calc = _calc(db, user)
    _line(
        db,
        calc,
        'Path "Ridge", east',
        "P, Q",
        "पटक",
        requires_map=False,
        years={1: (1, 10)},
    )
    row = _parse(_get(client, headers, calc, "plan").text)[1]
    assert row[1] == 'Path "Ridge", east' and row[2] == "P, Q"


@pytest.mark.parametrize("role", [UserRole.USER, UserRole.SUPER_ADMIN])
def test_the_exports_are_owner_only(client, db, role):
    _h, owner = _login(client, db)
    calc = _calc(db, owner)
    intruder, _ = _login(client, db, role=role)
    assert _get(client, intruder, calc, "plan").status_code == 404
    assert _get(client, intruder, calc, "features").status_code == 404


def test_only_csv_is_available_for_now(client, db):
    headers, user = _login(client, db)
    calc = _calc(db, user)
    assert _get(client, headers, calc, "plan", format="xlsx").status_code == 400
