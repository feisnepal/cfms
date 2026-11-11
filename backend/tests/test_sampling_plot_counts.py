"""A typed number of plots per polygon: placed exactly, any number allowed (fewer than 5 included) as long as it amounts to at least the
stratum's legal minimum intensity and at most 5 %, with the system suggesting at least 5 and showing what an intensity amounts to.

Fixture forest (``test_sampling_stratified``): Block-1 (production, floor 2 %) and Block-2 (orientation Conservation, floor 1 %), each
recorded as 100 ha. One 500 m2 plot is therefore 0.05 % of a block: the legal range is 40-100 plots in Block-1 and 20-100 in Block-2.
"""
import uuid

import pytest
from shapely import wkt as shp_wkt
from shapely.geometry import box

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.sampling import SamplingDesign
from app.services import sampling as svc
from tests.services.test_sampling_stratified import _setup_two_equal_blocks, _user  # noqa: F401  (fixture helpers)
from tests.test_sampling_add_units import _body, _headers, _preview_info, _round_one  # noqa: F401


@pytest.fixture(autouse=True)
def _stub_guideline_lookup(monkeypatch):
    monkeypatch.setattr(
        svc, "get_sample_count_from_guideline",
        lambda db, block_area_hectares, intensity_percent, plot_size_sqm: max(1, round(block_area_hectares * intensity_percent / 0.05)),
    )


def _create(client, h, calc, per_block, plots):
    return client.post(f"/api/calculations/{calc.id}/sampling/create", json=_body(per_block, per_block_plots=plots), headers=h)


def _plots_by_unit(db, design_id):
    db.expire_all()
    d = db.query(SamplingDesign).filter(SamplingDesign.id == design_id).one()
    out = {}
    for a in d.points_block_assignment or []:
        out[a["block_name"]] = out.get(a["block_name"], 0) + 1
    return out


def _small_forest(db):
    """One 9 ha production block (about 300 m square): 2 % of it is 0.18 ha = 3.6 plots, so 4 plots is legal and the usual minimum of 5
    is above it."""
    u = _user(db)
    boundary = box(83.480, 27.495, 83.48304, 27.4977)
    calc = Calculation(id=uuid.uuid4(), user_id=u.id, forest_name="Small Forest", boundary_geom=shp_wkt.dumps(boundary), is_draft=True, result_data={})
    db.add(calc)
    db.add(ForestBlock(
        id=uuid.uuid4(), calculation_id=calc.id, name="Small-1", block_name="Small-1", compartment_code=None,
        geometry=shp_wkt.dumps(boundary), area_hectares=9.0, index=0, is_compartment=False, division_level=1,
    ))
    db.commit()
    return calc


# ── the engine ──────────────────────────────────────────────────────────────────────────────────


def test_a_typed_count_is_placed_exactly(client, db):
    calc = _setup_two_equal_blocks(db)
    h = _headers(client, db, calc)
    r = _create(client, h, calc, {"Block-1": 2.0, "Block-2": 0}, {"Block-1": 50})
    assert r.status_code == 200, r.text
    assert _plots_by_unit(db, r.json()["sampling_design_id"]) == {"Block-1": 50}  # not the 40 the intensity gives


def test_fewer_than_five_plots_are_allowed_when_the_legal_minimum_is_met(client, db):
    calc = _small_forest(db)
    h = _headers(client, db, calc)
    r = _create(client, h, calc, {"Small-1": 2.0}, {"Small-1": 4})
    assert r.status_code == 200, r.text
    assert _plots_by_unit(db, r.json()["sampling_design_id"]) == {"Small-1": 4}  # the "at least 5" minimum did not override the user


def test_the_same_unit_without_a_typed_count_still_gets_the_usual_minimum_of_five(client, db, monkeypatch):
    # the intensity arithmetic gives 3 here; the usual per-unit minimum raises it to 5
    monkeypatch.setattr(svc, "get_sample_count_from_guideline", lambda db, block_area_hectares, intensity_percent, plot_size_sqm: 3)
    calc = _small_forest(db)
    h = _headers(client, db, calc)
    r = _create(client, h, calc, {"Small-1": 2.0}, None)
    assert r.status_code == 200, r.text
    assert _plots_by_unit(db, r.json()["sampling_design_id"]) == {"Small-1": 5}


def test_a_count_below_the_legal_minimum_is_refused_by_name(client, db):
    calc = _setup_two_equal_blocks(db)
    h = _headers(client, db, calc)
    r = _create(client, h, calc, {"Block-1": 2.0, "Block-2": 0}, {"Block-1": 10})  # 10 plots = 0.5 % < 2 %
    assert r.status_code == 400
    assert "Block-1" in r.text and "2.0" in r.text and "0.5" in r.text
    assert db.query(SamplingDesign).filter(SamplingDesign.calculation_id == calc.id).count() == 0


def test_a_count_above_the_usual_ceiling_is_allowed_not_refused(client, db):
    """Owner 2026-10-08: intensity may be raised; the screen warns (above the usual 5 %), the server does not stop it."""
    calc = _setup_two_equal_blocks(db)
    h = _headers(client, db, calc)
    r = _create(client, h, calc, {"Block-1": 2.0, "Block-2": 0}, {"Block-1": 110})  # 5.5 % of the 100 ha block
    assert r.status_code == 200, r.text
    assert _plots_by_unit(db, r.json()["sampling_design_id"]) == {"Block-1": 110}


def test_zero_plots_leaves_the_polygon_out(client, db):
    calc = _setup_two_equal_blocks(db)
    h = _headers(client, db, calc)
    r = _create(client, h, calc, {"Block-1": 2.0, "Block-2": 1.0}, {"Block-1": 45, "Block-2": 0})
    assert r.status_code == 200, r.text
    assert _plots_by_unit(db, r.json()["sampling_design_id"]) == {"Block-1": 45}


def test_the_preview_matches_what_is_created(client, db):
    calc = _setup_two_equal_blocks(db)
    h = _headers(client, db, calc)
    p = client.post(f"/api/calculations/{calc.id}/sampling/preview", json=_body({"Block-1": 2.0, "Block-2": 0}, per_block_plots={"Block-1": 60}), headers=h)
    assert p.status_code == 200, p.text
    assert p.json()["total_points"] == 60


# ── a later round ───────────────────────────────────────────────────────────────────────────────


def test_a_later_round_can_use_a_typed_count_too(client, db):
    calc = _setup_two_equal_blocks(db)
    h = _headers(client, db, calc)
    design_id = _round_one(client, h, calc, {"Block-1": 2.0, "Block-2": 0})
    body = _body({"Block-1": 0, "Block-2": 1.0}, per_block_plots={"Block-2": 25})
    prev = client.post(f"/api/calculations/{calc.id}/sampling/preview?add_to_design={design_id}", json=body, headers=h)
    assert prev.status_code == 200, prev.text
    assert prev.json()["total_points"] == 25
    added = client.post(f"/api/calculations/{calc.id}/sampling/{design_id}/add-units", json={**body, "preview": _preview_info(prev.json())}, headers=h)
    assert added.status_code == 200, added.text
    assert _plots_by_unit(db, design_id)["Block-2"] == 25


def test_a_later_round_with_only_a_count_ticks_the_polygon_and_holds_the_others_at_zero(client, db):
    calc = _setup_two_equal_blocks(db)
    h = _headers(client, db, calc)
    design_id = _round_one(client, h, calc, {"Block-1": 2.0, "Block-2": 0})
    body = _body({}, per_block_plots={"Block-2": 30})  # no intensity at all, just a count
    prev = client.post(f"/api/calculations/{calc.id}/sampling/preview?add_to_design={design_id}", json=body, headers=h)
    assert prev.status_code == 200, prev.text
    assert {f["properties"]["block_name"] for f in prev.json()["sampling_points_geojson"]["features"]} == {"Block-2"}


# ── the suggestion ──────────────────────────────────────────────────────────────────────────────


def test_the_suggestion_shows_what_an_intensity_amounts_to_and_never_suggests_fewer_than_five(client, db):
    calc = _setup_two_equal_blocks(db)
    h = _headers(client, db, calc)
    r = client.post(f"/api/calculations/{calc.id}/sampling/suggested-counts",
                    json={"method": "manual", "intensities": {"Block-1": 2.0, "Block-2": 0.0}}, headers=h)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["minimum_suggested"] == 5
    b1, b2 = d["units"]["Block-1"], d["units"]["Block-2"]
    assert (b1["computed"], b1["suggested"], b1["raised_to_minimum"]) == (40, 40, False)
    assert (b1["min_plots_legal"], b1["max_plots_legal"]) == (40, 100)  # 2 % .. 5 % of 100 ha in 500 m2 plots
    assert (b2["suggested"], b2["computed"]) == (0, 0)  # excluded at 0 %


def test_a_small_polygon_is_suggested_five_even_though_its_intensity_gives_fewer(client, db):
    calc = _small_forest(db)
    h = _headers(client, db, calc)
    d = client.post(f"/api/calculations/{calc.id}/sampling/suggested-counts", json={"method": "manual", "intensities": {"Small-1": 2.0}}, headers=h).json()
    u = d["units"]["Small-1"]
    assert u["computed"] < 5 and u["suggested"] == 5 and u["raised_to_minimum"] is True
    assert u["min_plots_legal"] <= 4 <= u["max_plots_legal"]  # four plots is a legal choice for it


def test_someone_elses_forest_is_refused(client, db):
    calc, other = _setup_two_equal_blocks(db), _setup_two_equal_blocks(db)
    r = client.post(f"/api/calculations/{calc.id}/sampling/suggested-counts", json={}, headers=_headers(client, db, other))
    assert r.status_code == 404


def test_the_preview_unit_layer_carries_the_workspace_name_and_the_sampling_key(client, db):
    """The map shows a unit's NAME (as the workspace attribute table does); plots are filed under code-or-name, so the layer
    carries both and the screen can translate one into the other."""
    from app.api.sampling import _preview_forest_blocks_layer
    from app.models.forest_block import ForestBlock

    calc = _setup_two_equal_blocks(db)
    block = db.query(ForestBlock).filter_by(calculation_id=calc.id, name="Block-1").one()
    block.compartment_code = "CODE-1"
    db.commit()
    props = {f["properties"]["name"]: f["properties"] for f in _preview_forest_blocks_layer(db, calc.id)["features"]}
    assert props["Block-1"]["unit_key"] == "CODE-1"      # what the plots are filed under
    assert props["Block-2"]["unit_key"] == "Block-2"     # no code: the name
