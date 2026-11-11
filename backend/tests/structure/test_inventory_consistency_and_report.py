"""Field inventory vs the forest's units: the consistency check and the per-sub-unit report.

Forest F3: block B1 divided into SB1 (x 0-5) and SB2 (x 5-10), block B2 (x 10-20) undivided. The inventory belongs to the three
undivided units SB1, SB2 and B2.
"""

from __future__ import annotations

import uuid

import pytest
from geoalchemy2.shape import from_shape
from shapely.geometry import Point

from . import fixtures

from app.models.calculation import Calculation
from app.models.field_inventory import FieldInventoryBlockSummary, FieldInventoryCalculation, FieldInventorySamplePlot
from app.models.forest_block import ForestBlock
from app.services import field_inventory_consistency as fic
from app.services import field_inventory_unit_report as rep


def _inventory(db, forest, plots: dict, summaries: dict | None = None):
    """plots: {unit name: [(x, y), ...]} in the fixtures' frame (units of 0.001 degree); summaries: {unit name: plot count} (default: the plot count)."""
    calc = db.query(Calculation).filter(Calculation.id == forest.calc_id).one()
    fi = FieldInventoryCalculation(
        calculation_id=calc.id, user_id=calc.user_id, uploaded_filename="t.csv", status="completed",
    )
    db.add(fi)
    db.flush()
    n = 0
    for unit, pts in plots.items():
        for (x, y) in pts:
            n += 1
            db.add(FieldInventorySamplePlot(
                field_inventory_calculation_id=fi.id, block_name=unit, sample_plot_number=n,
                location=from_shape(Point(fixtures.X0 + x / 1000, fixtures.Y0 + y / 1000), srid=4326),  # the fixtures' 0.001-degree frame
            ))
    for unit, count in (summaries if summaries is not None else {u: len(p) for u, p in plots.items()}).items():
        db.add(FieldInventoryBlockSummary(field_inventory_calculation_id=fi.id, block_name=unit, total_sample_plots=count))
    db.flush()
    return fi


def _by_code(db, forest):
    return {(f.code, f.unit) for f in fic.check(db, forest.calc_id)}


GOOD = {"SB1": [(1, 5), (2, 5)], "SB2": [(6, 5)], "B2": [(15, 5)]}


def test_a_consistent_inventory_has_no_findings(make_forest, db):
    f = make_forest("F3")
    _inventory(db, f, GOOD)
    assert fic.check(db, f.calc_id) == []


def test_a_forest_without_inventory_has_nothing_to_check(make_forest, db):
    assert fic.check(db, make_forest("F3").calc_id) == []


def test_a_unit_without_plots_is_a_warning_not_an_error(make_forest, db):
    f = make_forest("F3")
    _inventory(db, f, {"SB1": [(1, 5)], "SB2": [(6, 5)]})  # B2 not sampled
    found = fic.check(db, f.calc_id)
    assert [(x.code, x.unit, x.severity) for x in found] == [(fic.UNIT_WITHOUT_PLOTS, "B2", fic.WARNING)]
    assert not fic.has_errors(found)


def test_plots_left_on_a_divided_unit_are_reported(make_forest, db):
    """The case after dividing a unit: its plots now belong to the children, but the inventory still names the parent."""
    f = make_forest("F3")
    _inventory(db, f, {"B1": [(1, 5), (6, 5)], "B2": [(15, 5)]})
    codes = _by_code(db, f)
    assert (fic.PLOT_IN_DIVIDED_UNIT, "B1") in codes and (fic.SUMMARY_UNIT_DIVIDED, "B1") in codes
    assert fic.has_errors(fic.check(db, f.calc_id))


def test_a_plot_outside_its_unit_is_reported(make_forest, db):
    f = make_forest("F3")
    _inventory(db, f, {**GOOD, "B2": [(15, 5), (2, 5)]})  # the second B2 plot lies in SB1
    found = {(x.code, x.unit): x for x in fic.check(db, f.calc_id)}
    assert found[(fic.PLOT_OUTSIDE_UNIT, "B2")].count == 1


def test_a_plot_on_the_edge_between_two_units_is_not_outside(make_forest, db):
    f = make_forest("F3")
    _inventory(db, f, {**GOOD, "SB1": [(1, 5), (5.01, 5)]})  # 0.00001 degree (~1 m) over the line into SB2
    assert fic.check(db, f.calc_id) == []


def test_names_the_forest_does_not_have_are_reported(make_forest, db):
    f = make_forest("F3")
    _inventory(db, f, {**GOOD, "Block-9": [(1, 1)]})
    codes = _by_code(db, f)
    assert (fic.PLOT_UNIT_MISSING, "Block-9") in codes and (fic.SUMMARY_UNIT_MISSING, "Block-9") in codes


def test_a_summary_whose_plot_count_disagrees_is_reported(make_forest, db):
    f = make_forest("F3")
    _inventory(db, f, GOOD, summaries={"SB1": 5, "SB2": 1, "B2": 1})  # SB1 has 2 plots stored, 5 counted
    assert (fic.PLOT_COUNT_MISMATCH, "SB1") in _by_code(db, f)


# ── the report ──────────────────────────────────────────────────────────────────────────────────


def _values(**units):
    base = {"total_sample_plots": 3, "regeneration_per_ha": 0, "sapling_per_ha": 0, "pole_per_ha": 0, "tree_per_ha": 0,
            "basal_area_m2_per_ha": 0.0, "mai_total_m3_per_ha": 0.0, "aah_total_m3_per_ha": 0.0}
    return {name: {**base, **vals} for name, vals in units.items()}


def test_a_divided_parent_is_the_area_weighted_roll_up_of_its_children(make_forest, db):
    f = make_forest("F3")
    r = rep.build(db, f.calc_id, values=_values(
        SB1={"total_growing_stock_m3_per_ha": 100.0, "forest_condition": "Good"},
        SB2={"total_growing_stock_m3_per_ha": 40.0, "forest_condition": "Weak"},
        B2={"total_growing_stock_m3_per_ha": 10.0},
    ))
    rows = {x["name"]: x for x in r["rows"]}
    assert [x["name"] for x in r["rows"]] == ["B1", "SB1", "SB2", "B2"]  # a parent, then its children
    assert [rows[n]["kind"] for n in ("B1", "SB1", "SB2", "B2")] == ["rollup", "unit", "unit", "unit"]
    # SB1 and SB2 are equal-area halves of B1, so B1 is the plain mean here
    assert rows["B1"]["growing_stock_m3_per_ha"] == pytest.approx(70.0, abs=0.1)
    assert rows["B1"]["forest_condition"] is None  # a condition is a unit's own, not an average
    assert rows["B1"]["growing_stock_m3"] == pytest.approx(rows["SB1"]["growing_stock_m3"] + rows["SB2"]["growing_stock_m3"], abs=0.2)
    assert r["leaf_count"] == 3 and r["state"] == "ready"
    total = r["total"]
    assert total["kind"] == "total" and total["growing_stock_m3"] == pytest.approx(
        sum(rows[n]["growing_stock_m3"] for n in ("SB1", "SB2", "B2")), abs=0.3)


def test_a_roll_up_from_only_some_children_says_how_much_it_covers(make_forest, db):
    f = make_forest("F3")
    r = rep.build(db, f.calc_id, values=_values(SB1={"total_growing_stock_m3_per_ha": 100.0}, B2={"total_growing_stock_m3_per_ha": 10.0}))
    b1 = next(x for x in r["rows"] if x["name"] == "B1")
    sb2 = next(x for x in r["rows"] if x["name"] == "SB2")
    assert sb2["has_data"] is False and sb2["growing_stock_m3_per_ha"] is None
    assert b1["growing_stock_m3_per_ha"] == pytest.approx(100.0, abs=0.1)  # only the child with data counts
    assert b1["covered_pct"] == pytest.approx(50.0, abs=1.0)


def test_no_inventory_means_not_computed(make_forest, db):
    assert rep.build(db, make_forest("F3").calc_id, values={})["state"] == "not_computed"


def test_the_workbook_has_the_rows_and_the_problems(make_forest, db):
    from io import BytesIO

    from openpyxl import load_workbook

    f = make_forest("F3")
    r = rep.build(db, f.calc_id, values=_values(SB1={"total_growing_stock_m3_per_ha": 100.0}, SB2={"total_growing_stock_m3_per_ha": 40.0},
                                                 B2={"total_growing_stock_m3_per_ha": 10.0}))
    wb = load_workbook(BytesIO(rep.to_xlsx(r, [{"severity": "warning", "code": "UNIT_WITHOUT_PLOTS", "unit": "X", "message": "m"}])))
    assert wb.sheetnames == ["Sub-unit report", "Problems"]
    ws = wb["Sub-unit report"]
    assert [c.value for c in ws[1]][:5] == ["Unit", "Row", "Parent", "Area (ha)", "Plots"]
    assert [ws.cell(row=i, column=1).value for i in range(2, 7)] == ["B1", "SB1", "SB2", "B2", "total"]
    assert ws.cell(row=2, column=2).value == "roll-up of sub-units"


# ── the endpoint ───────────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def owner_headers(client, db):
    from app.models.user import User, UserStatus
    from app.utils.auth import hash_password

    def _for(forest):
        user = db.query(User).filter(User.id == forest.user_id).first()
        user.hashed_password = hash_password("TestPass123!")
        user.status = UserStatus.ACTIVE
        db.commit()
        r = client.post("/api/v1/auth/login", json={"email": user.email, "password": "TestPass123!"})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    return _for


def _stub_values(monkeypatch):
    from app.services.operational_plan import thematic_overlay as to

    monkeypatch.setattr(to, "_load_unit_values", lambda db, cid: _values(
        SB1={"total_growing_stock_m3_per_ha": 100.0}, SB2={"total_growing_stock_m3_per_ha": 40.0}, B2={"total_growing_stock_m3_per_ha": 10.0}))


def test_the_endpoint_returns_the_report_and_the_problems(make_forest, db, client, owner_headers, monkeypatch):
    f = make_forest("F3")
    _inventory(db, f, {"SB1": [(1, 5)], "SB2": [(6, 5)]})  # B2 unsampled -> one warning
    db.commit()
    _stub_values(monkeypatch)
    r = client.get(f"/api/calculations/{f.calc_id}/field-inventory-report", headers=owner_headers(f))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["state"] == "ready" and [x["name"] for x in body["rows"]] == ["B1", "SB1", "SB2", "B2"]
    assert [(p["code"], p["unit"]) for p in body["problems"]] == [("UNIT_WITHOUT_PLOTS", "B2")] and body["has_errors"] is False


def test_the_endpoint_serves_the_workbook(make_forest, db, client, owner_headers, monkeypatch):
    f = make_forest("F3")
    _inventory(db, f, GOOD)
    db.commit()
    _stub_values(monkeypatch)
    r = client.get(f"/api/calculations/{f.calc_id}/field-inventory-report?format=xlsx", headers=owner_headers(f))
    assert r.status_code == 200 and r.content[:2] == b"PK"
    assert "SubUnitReport" in r.headers["content-disposition"]


def test_someone_elses_forest_is_refused(make_forest, db, client, owner_headers):
    mine, theirs = make_forest("F3"), make_forest("F1")
    r = client.get(f"/api/calculations/{theirs.calc_id}/field-inventory-report", headers=owner_headers(mine))
    assert r.status_code in (403, 404)
