"""Sampling in rounds: one row per polygon for ANY forest, a later round that appends plots to the forest's one design, and removing
one polygon's plots so it can be sampled again.

Fixture forest (``test_sampling_stratified``): Block-1 (production by default) and Block-2 (orientation Conservation), side by side.
"""
import pytest

from app.models.forest_block import ForestBlock
from app.models.sampling import SamplingDesign
from app.models.user import User
from app.services import sampling as svc
from app.services import sampling_unit_plan as plan_svc
from app.services.sustainable_fm.stratum_spec import classify_calc_units, stratum_and_source

from tests.services.test_sampling_stratified import _counts_by_block, _setup_two_equal_blocks  # noqa: F401  (fixture helper)


@pytest.fixture(autouse=True)
def _stub_guideline_lookup(monkeypatch):
    # same stand-in the stratified tests use: the DoF lookup table does not exist in the test DB
    monkeypatch.setattr(
        svc, "get_sample_count_from_guideline",
        lambda db, block_area_hectares, intensity_percent, plot_size_sqm: max(1, round(block_area_hectares * intensity_percent / 0.05)),
    )


def _headers(client, db, calc):
    email = db.query(User).filter(User.id == calc.user_id).one().email
    r = client.post("/api/auth/login", json={"email": email, "password": "TestPass123!"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _body(per_block, **extra):
    return {
        "sampling_method": "guideline_2061", "productive_intensity": "2.0", "plot_size_sqm": 500, "plot_shape": "circular",
        "filter_tree_cover": False, "filter_slope": False, "boundary_buffer_meters": 0.0, "per_block_intensity": per_block, **extra,
    }


def _round_one(client, headers, calc, per_block):
    r = client.post(f"/api/calculations/{calc.id}/sampling/create", json=_body(per_block), headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["sampling_design_id"]


def _preview_info(p):
    keys = ("preview_token", "total_points", "total_blocks", "forest_area_hectares", "requested_intensity_percent",
            "actual_intensity_per_hectare", "plot_area_sqm", "total_sampled_area_hectares", "sampling_percentage", "blocks_info",
            "sampling_points_geojson", "area_basis")
    return {k: p[k] for k in keys if k in p}


# ── the per-polygon plan, with no forest type and no plots ───────────────────────────────────


def test_the_plan_lists_every_polygon_with_the_stratum_and_the_reason(db):
    calc = _setup_two_equal_blocks(db)
    plan = plan_svc.unit_plan(db, calc)
    by = {u["name"]: u for u in plan["units"]}
    assert plan["design_id"] is None and set(by) == {"Block-1", "Block-2"}
    assert (by["Block-1"]["stratum"], by["Block-1"]["stratum_source"], by["Block-1"]["floor_pct"], by["Block-1"]["plot_size_sqm"]) == ("production", "default", 2.0, 500)
    assert (by["Block-2"]["stratum"], by["Block-2"]["stratum_source"], by["Block-2"]["floor_pct"]) == ("conservation", "user", 1.0)
    assert all(u["sampled_plots"] == 0 for u in plan["units"])


def test_a_steep_polygon_is_proposed_as_conservation_and_the_engine_enforces_the_same(db):
    calc = _setup_two_equal_blocks(db)
    b1 = db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id, ForestBlock.name == "Block-1").one()
    b1.dominant_slope_band = 4
    db.commit()
    by = {u["name"]: u for u in plan_svc.unit_plan(db, calc)["units"]}
    assert (by["Block-1"]["stratum"], by["Block-1"]["stratum_source"]) == ("conservation", "slope")
    from geoalchemy2.shape import to_shape

    units = [(i + 1, to_shape(b.geometry).wkt, b.block_name, 100.0)
             for i, b in enumerate(db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).order_by(ForestBlock.index))]
    assert classify_calc_units(db, calc.id, units)["Block-1"] == "conservation"  # the screen and the 400 "below the floor" agree


def test_the_users_own_choice_beats_the_slope_proposal():
    assert stratum_and_source("u", None, None, "Production", None, 4, None) == ("production", "user")
    assert stratum_and_source("u", None, None, None, "Protection", 4, None) == ("protection", "sfm")
    assert stratum_and_source("u", None, "protection", "Production", None, 1, None) == ("protection", "working_circle")
    assert stratum_and_source("u", None, None, None, None, None, None) == ("production", "default")


# ── rounds ──────────────────────────────────────────────────────────────────────────────────────


def test_a_later_round_appends_plots_for_the_new_polygon_and_leaves_the_old_ones_alone(client, db):
    calc = _setup_two_equal_blocks(db)
    h = _headers(client, db, calc)
    design_id = _round_one(client, h, calc, {"Block-1": 2.0, "Block-2": 0})  # only Block-1 ticked
    d = db.query(SamplingDesign).filter(SamplingDesign.id == design_id).one()
    first_plots = len(d.points_block_assignment)
    assert {a["block_name"] for a in d.points_block_assignment} == {"Block-1"}
    before = db.execute(__import__("sqlalchemy").text("SELECT ST_AsText(points_geometry) FROM sampling_designs WHERE id=:i"), {"i": design_id}).scalar()

    plan = client.get(f"/api/calculations/{calc.id}/sampling/unit-plan", headers=h).json()
    by = {u["name"]: u for u in plan["units"]}
    assert by["Block-1"]["sampled_plots"] == first_plots and by["Block-2"]["sampled_plots"] == 0 and plan["design_id"] == design_id

    # round two: Block-2 ticked (the screen holds Block-1 at 0)
    p = client.post(f"/api/calculations/{calc.id}/sampling/preview?add_to_design={design_id}", json=_body({"Block-1": 0, "Block-2": 2.0}), headers=h)
    assert p.status_code == 200, p.text
    prev = p.json()
    assert {f["properties"]["block_name"] for f in prev["sampling_points_geojson"]["features"]} == {"Block-2"}
    added = client.post(f"/api/calculations/{calc.id}/sampling/{design_id}/add-units",
                        json=_body({"Block-1": 0, "Block-2": 2.0}, preview=_preview_info(prev)), headers=h)
    assert added.status_code == 200, added.text
    assert added.json()["added"] == len(prev["sampling_points_geojson"]["features"]) and added.json()["units"] == ["Block-2"]

    db.expire_all()
    d = db.query(SamplingDesign).filter(SamplingDesign.id == design_id).one()
    idx = [a["point_index"] for a in d.points_block_assignment]
    assert idx == list(range(len(idx))) and d.total_points == len(idx)  # numbered 1..N with no gap, new plots after the old
    assert [a["block_name"] for a in d.points_block_assignment][:first_plots] == ["Block-1"] * first_plots
    after = db.execute(__import__("sqlalchemy").text("SELECT ST_AsText(points_geometry) FROM sampling_designs WHERE id=:i"), {"i": design_id}).scalar()
    assert after.replace("MULTIPOINT(", "").startswith(before.replace("MULTIPOINT(", "").rstrip(")"))  # the first plots did not move
    assert db.query(SamplingDesign).filter(SamplingDesign.calculation_id == calc.id).count() == 1  # still ONE design
    assert {b["block_name"]: b["samples_generated"] > 0 for b in d.result_data["blocks_info"]} == {"Block-1": True, "Block-2": True}


def test_a_polygon_that_already_has_plots_cannot_be_sampled_again(client, db):
    calc = _setup_two_equal_blocks(db)
    h = _headers(client, db, calc)
    design_id = _round_one(client, h, calc, {"Block-1": 2.0, "Block-2": 0})
    r = client.post(f"/api/calculations/{calc.id}/sampling/preview?add_to_design={design_id}", json=_body({"Block-1": 2.0, "Block-2": 2.0}), headers=h)
    assert r.status_code == 409 and "Block-1" in r.json()["detail"]["message"]
    r = client.post(f"/api/calculations/{calc.id}/sampling/preview?add_to_design={design_id}", json=_body({"Block-1": 0, "Block-2": 0}), headers=h)
    assert r.status_code == 400  # nothing ticked
    # without the add flag the one-design rule still holds
    assert client.post(f"/api/calculations/{calc.id}/sampling/preview", json=_body({"Block-2": 2.0}), headers=h).status_code == 400


def test_removing_a_polygons_plots_frees_it_and_renumbers_the_rest(client, db):
    calc = _setup_two_equal_blocks(db)
    h = _headers(client, db, calc)
    design_id = _round_one(client, h, calc, {"Block-1": 2.0, "Block-2": 2.0})
    d = db.query(SamplingDesign).filter(SamplingDesign.id == design_id).one()
    n1 = sum(1 for a in d.points_block_assignment if a["block_name"] == "Block-1")
    total = d.total_points
    assert n1 > 0 and total > n1
    r = client.delete(f"/api/sampling/{design_id}/units/Block-1/points", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["removed"] == n1
    db.expire_all()
    d = db.query(SamplingDesign).filter(SamplingDesign.id == design_id).one()
    assert d.total_points == total - n1 and {a["block_name"] for a in d.points_block_assignment} == {"Block-2"}
    assert [a["point_index"] for a in d.points_block_assignment] == list(range(total - n1))
    by = {u["name"]: u for u in client.get(f"/api/calculations/{calc.id}/sampling/unit-plan", headers=h).json()["units"]}
    assert by["Block-1"]["sampled_plots"] == 0  # free to be sampled again
    assert client.delete(f"/api/sampling/{design_id}/units/Block-1/points", headers=h).status_code == 404  # nothing left to remove


def test_the_last_plots_of_a_design_are_not_removed_this_way(client, db):
    calc = _setup_two_equal_blocks(db)
    h = _headers(client, db, calc)
    design_id = _round_one(client, h, calc, {"Block-1": 2.0, "Block-2": 0})
    assert client.delete(f"/api/sampling/{design_id}/units/Block-1/points", headers=h).status_code == 400


def test_plots_cannot_be_added_or_removed_once_field_inventory_exists(client, db):
    from app.models.field_inventory import FieldInventoryCalculation

    calc = _setup_two_equal_blocks(db)
    h = _headers(client, db, calc)
    design_id = _round_one(client, h, calc, {"Block-1": 2.0, "Block-2": 2.0})
    db.add(FieldInventoryCalculation(calculation_id=calc.id, user_id=calc.user_id, uploaded_filename="f.csv", status="completed"))
    db.commit()
    assert client.get(f"/api/calculations/{calc.id}/sampling/unit-plan", headers=h).json()["field_data_exists"] is True
    assert client.delete(f"/api/sampling/{design_id}/units/Block-1/points", headers=h).status_code == 409
    r = client.post(f"/api/calculations/{calc.id}/sampling/{design_id}/add-units", json=_body({"Block-2": 2.0}), headers=h)
    assert r.status_code == 409


def test_someone_elses_forest_is_refused(client, db):
    calc = _setup_two_equal_blocks(db)
    other = _setup_two_equal_blocks(db)
    h = _headers(client, db, other)
    assert client.get(f"/api/calculations/{calc.id}/sampling/unit-plan", headers=h).status_code == 404


def test_the_unit_plan_carries_the_workspace_name_beside_the_sampling_key(client, db):
    """Plots are filed under code-or-name; the screen shows the unit's Name as the attribute table does."""
    from app.models.forest_block import ForestBlock

    calc = _setup_two_equal_blocks(db)
    block = db.query(ForestBlock).filter_by(calculation_id=calc.id, name="Block-1").one()
    block.compartment_code = "CODE-1"
    db.commit()
    h = _headers(client, db, calc)
    units = client.get(f"/api/calculations/{calc.id}/sampling/unit-plan", headers=h).json()["units"]
    by_display = {u["display_name"]: u["name"] for u in units}
    assert by_display == {"Block-1": "CODE-1", "Block-2": "Block-2"}
