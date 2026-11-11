"""Proposed corrections for refused values: which row, which class it belongs to, a repeatable random replacement, applied only on request."""
import json
from unittest.mock import MagicMock

import pandas as pd
import pytest

from app.services.field_inventory_validator import FieldInventoryValidator
from app.services.upload.corrections import apply_corrections, belongs_to, propose_corrections, propose_value, usual_range
from app.services.upload.rules import RULES

pytestmark = pytest.mark.usefixtures("forget_forests")  # committed forests / rows are purged before and after each test: see conftest (test order is random)


@pytest.mark.parametrize("key, lo, hi", [
    ("regen_dbh", 1.0, 3.9), ("sapling_dbh", 4.0, 9.9), ("pole_dbh", 10.0, 29.9),  # a class excludes its upper edge
    ("tree_dbh", 30.0, 100.0),  # the usual range, not up to the 200 cm hard stop
    ("pole_height", 5.0, 25.0), ("tree_height", 7.0, 50.0),
])
def test_a_proposal_stays_inside_the_usual_range_of_its_own_class(key, lo, hi):
    assert usual_range(RULES[key]) == pytest.approx((lo, hi))
    for row in range(2, 60):
        v = propose_value(RULES[key], f"{key}_col", row, 999.0)
        assert lo - 1e-9 <= v <= hi + 1e-9, (key, row, v)
        assert round(v, 1) == pytest.approx(v)  # recorded to a tenth


def test_the_same_row_always_gets_the_same_proposal_and_other_rows_differ():
    rule = RULES["pole_dbh"]
    assert propose_value(rule, "pole_dbh_cm", 4, 50.0) == propose_value(rule, "pole_dbh_cm", 4, 50.0)
    assert len({propose_value(rule, "pole_dbh_cm", r, 50.0) for r in range(2, 40)}) > 5  # it is a spread, not one constant


def test_a_count_is_never_invented():
    assert propose_value(RULES["regen_count"], "regen_count", 3, 0) is None


@pytest.mark.parametrize("key, value, stand", [("pole_dbh", 50.0, "tree"), ("tree_dbh", 12.0, "pole"), ("tree_dbh", 5.0, "sapling"), ("pole_dbh", 31.0, "tree")])
def test_it_says_which_class_the_value_really_belongs_to(key, value, stand):
    assert belongs_to(RULES[key], value) == stand


def test_a_value_in_no_class_or_not_a_dbh_has_no_destination():
    assert belongs_to(RULES["tree_dbh"], 450.0) is None and belongs_to(RULES["pole_height"], 80.0) is None


def test_proposals_name_the_row_the_old_value_and_the_new_one():
    out = propose_corrections(RULES["pole_dbh"], "pole_dbh_cm", pd.Series([15.0, 18.0, 50.0, 22.0, 31.5]))
    assert [(p["row"], p["old"], p["belongs_to"]) for p in out] == [(4, 50.0, "tree"), (6, 31.5, "tree")]
    assert all(10.0 <= p["new"] < 30.0 for p in out) and out[0]["range"] == "10 to under 30 cm"


# ── applying them ──────────────────────────────────────────────────────────────────────────────────────────────────────

COLS = {"pole_dbh": "pole_dbh_cm", "tree_height": "tree_height_m"}


def _df():
    return pd.DataFrame({"pole_dbh_cm": [15.0, 50.0, 22.0], "tree_height_m": [18.0, 20.0, 80.0]})


def test_an_accepted_correction_replaces_only_a_refused_value():
    df = _df()
    out, applied, ignored = apply_corrections(df, [{"row": 3, "column": "pole_dbh_cm", "value": 21.5}], COLS)
    assert out["pole_dbh_cm"].tolist() == [15.0, 21.5, 22.0] and applied == [{"row": 3, "column": "pole_dbh_cm", "old": 50.0, "new": 21.5}] and ignored == []
    assert df["pole_dbh_cm"].tolist() == [15.0, 50.0, 22.0]  # the input frame is not modified


def test_a_valid_measurement_is_never_rewritten():
    out, applied, ignored = apply_corrections(_df(), [{"row": 2, "column": "pole_dbh_cm", "value": 12.0}], COLS)  # 15.0 is fine
    assert applied == [] and out["pole_dbh_cm"].tolist() == [15.0, 50.0, 22.0] and "not refused" in ignored[0]["reason"]


def test_a_replacement_that_is_itself_refused_is_not_applied():
    _, applied, ignored = apply_corrections(_df(), [{"row": 3, "column": "pole_dbh_cm", "value": 45.0}], COLS)
    assert applied == [] and "still refused" in ignored[0]["reason"]


@pytest.mark.parametrize("bad", [{"row": 99, "column": "pole_dbh_cm", "value": 20}, {"row": 3, "column": "nope", "value": 20}, {"row": "x", "column": "pole_dbh_cm", "value": 20}, {"row": 3}])
def test_nonsense_corrections_are_ignored(bad):
    out, applied, ignored = apply_corrections(_df(), [bad], COLS)
    assert applied == [] and len(ignored) == 1 and out["pole_dbh_cm"].tolist() == [15.0, 50.0, 22.0]


# ── the validator report and the real endpoint ────────────────────────────────────────────────────────────────────────

def test_the_validator_report_carries_the_proposals():
    v = FieldInventoryValidator(MagicMock())
    df = pd.DataFrame({"block_name": ["B1"] * 3, "sample_plot_number": [1, 2, 3], "longitude": [84.1] * 3, "latitude": [28.2] * 3,
                       "pole_species_scientific": ["Shorea robusta"] * 3, "pole_dbh_cm": [15.0, 50.0, 22.0], "pole_height_m": [9.0, 10.0, 80.0]})
    cols = v._detect_columns(df)["columns"]
    v.errors, v.warnings, v.proposals = [], [], []
    v._validate_dbh_ranges(df, cols)
    v._validate_heights(df, cols)
    assert sorted((p["column"], p["row"], p["measure"]) for p in v.proposals) == [("pole_dbh_cm", 3, "dbh"), ("pole_height_m", 4, "height")]


def _csv(pole_dbh):
    rows = "\n".join(f"B1,{i + 1},84.1,28.2,Shorea robusta,{d},9.5" for i, d in enumerate(pole_dbh))
    return "block_name,sample_plot_number,longitude,latitude,pole_species_scientific,pole_dbh_cm,pole_height_m\n" + rows


def test_upload_refuses_proposes_then_accepts_the_corrections(client, auth_headers, db):
    import uuid

    from app.models.calculation import Calculation
    from app.models.user import User

    owner = db.query(User).filter(User.email == "testuser@example.com").first()
    mapping = json.dumps({"block_name": "block_name", "sample_plot_number": "sample_plot_number", "longitude": "longitude", "latitude": "latitude"})

    def upload(**extra):
        from sqlalchemy import text

        c = Calculation(id=uuid.uuid4(), user_id=owner.id, forest_name="E test forest")
        db.add(c)
        db.commit()
        # the validator needs a boundary to check the plots against: a small square around them
        db.execute(text("UPDATE calculations SET boundary_geom = ST_Multi(ST_GeomFromText('POLYGON((84.05 28.15, 84.15 28.15, 84.15 28.25, 84.05 28.25, 84.05 28.15))', 4326)) WHERE id = :i"), {"i": str(c.id)})
        db.commit()
        return client.post("/api/field-inventory/upload", files={"file": ("fi.csv", _csv([15.0, 50.0, 22.0]), "text/csv")},
                           data={"mapping": mapping, "calculation_id": str(c.id), **extra}, headers=auth_headers).json()

    refused = upload()
    assert refused["summary"]["ready_for_processing"] is False and "field_inventory_id" not in refused  # nothing was stored
    f = next(x for x in refused["findings"] if x["code"] == "field_inventory.corrections_proposed")
    assert f["where"]["rows"] == [3] and f["auto_fix"] == "replace_random_in_class"
    prop = f["where"]["proposals"][0]
    assert (prop["row"], prop["column"], prop["old"], prop["belongs_to"]) == (3, "pole_dbh_cm", 50.0, "tree") and 10.0 <= prop["new"] < 30.0

    accepted = upload(corrections=json.dumps([{"row": prop["row"], "column": prop["column"], "value": prop["new"]}]))
    assert accepted["summary"]["ready_for_processing"] is True and accepted.get("field_inventory_id")
    codes = [x["code"] for x in accepted["findings"]]
    assert "field_inventory.corrections_applied" in codes and "field_inventory.corrections_proposed" not in codes

    sneaky = upload(corrections=json.dumps([{"row": 2, "column": "pole_dbh_cm", "value": 12.0}]))  # row 2 (15.0) is valid: must not be rewritten
    assert sneaky["summary"]["ready_for_processing"] is False
    assert "field_inventory.corrections_applied" not in [x["code"] for x in sneaky["findings"]]
