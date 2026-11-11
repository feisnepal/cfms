"""Typing a sample plot's coordinates: WGS84 latitude / longitude or UTM easting / northing, refused kindly when wrong or outside the forest."""
import json
import uuid

import pytest
from shapely import wkt as shp_wkt
from shapely.geometry import box
from sqlalchemy import text

from app.models.calculation import Calculation
from app.models.sampling import SamplingDesign
from app.services import sample_plot_coordinates as sc
from app.services import sampling as svc
from tests.services.test_sampling_stratified import _setup_two_equal_blocks, _user  # noqa: F401
from tests.test_sampling_add_units import _body, _headers, _round_one  # noqa: F401


@pytest.fixture(autouse=True)
def _stub_guideline_lookup(monkeypatch):
    monkeypatch.setattr(
        svc, "get_sample_count_from_guideline",
        lambda db, block_area_hectares, intensity_percent, plot_size_sqm: max(1, round(block_area_hectares * intensity_percent / 0.05)),
    )


# ── the arithmetic ──────────────────────────────────────────────────────────────────────────────


def test_the_zone_is_the_plots_own_and_changes_at_84_degrees_east():
    assert [sc.utm_zone_for(x) for x in (80.1, 83.99, 84.0, 84.01, 88.1)] == [44, 44, 45, 45, 45]


def test_utm_and_wgs84_are_the_same_place():
    zone, e, n = sc.to_utm(83.5, 27.5)
    lon, lat = sc.from_utm(zone, e, n)
    assert (zone, round(lon, 6), round(lat, 6)) == (44, 83.5, 27.5)


def test_one_typed_value_changes_only_its_own_axis():
    r = sc.resolve_new_location(83.5, 27.5, latitude=27.51)
    assert (r.longitude, r.latitude, r.system, r.typed) == (83.5, 27.51, "wgs84", True)
    zone, e, n = sc.to_utm(83.5, 27.5)
    r = sc.resolve_new_location(83.5, 27.5, utm_easting=e + 50)
    assert r.system == "utm" and r.zone == 44 and r.northing == pytest.approx(n, abs=0.01) and r.easting == pytest.approx(e + 50)
    assert r.latitude == pytest.approx(27.5, abs=1e-4) and r.longitude > 83.5  # 50 m east


def test_a_dragged_position_is_not_a_typed_value():
    assert sc.resolve_new_location(83.5, 27.5, longitude=83.51, latitude=27.51).typed is False


def test_a_utm_value_is_read_in_the_plots_own_zone_even_just_across_the_line():
    # a plot in zone 45 (east of 84): its UTM is read in zone 45, so a value typed there lands where the row says
    zone, e, n = sc.to_utm(84.002, 27.5)
    assert zone == 45
    r = sc.resolve_new_location(84.002, 27.5, utm_northing=n + 100)
    assert r.zone == 45 and r.longitude == pytest.approx(84.002, abs=1e-3)  # 100 m north: the longitude barely moves (grid convergence)


@pytest.mark.parametrize(
    "kwargs, code",
    [
        ({}, "coordinate_none"),
        ({"latitude": 27.5, "utm_easting": 500000}, "coordinate_both"),
        ({"latitude": 95}, "coordinate_lat_range"),
        ({"longitude": 200}, "coordinate_lon_range"),
        ({"utm_easting": 2_000_000}, "coordinate_easting_range"),
        ({"utm_northing": -5}, "coordinate_northing_range"),
        ({"latitude": float("nan")}, "coordinate_not_a_number"),
        ({"latitude": "abc"}, "coordinate_not_a_number"),
    ],
)
def test_unusable_input_is_named(kwargs, code):
    with pytest.raises(sc.CoordinateError) as e:
        sc.resolve_new_location(83.5, 27.5, **kwargs)
    assert e.value.code == code


# ── through the endpoint ────────────────────────────────────────────────────────────────────────


def _design_with_plots(client, db):
    calc = _setup_two_equal_blocks(db)
    h = _headers(client, db, calc)
    design_id = _round_one(client, h, calc, {"Block-1": 2.0, "Block-2": 0})
    return calc, h, design_id


def _plot(db, design_id, number):
    pts = db.execute(text("SELECT ST_X(g.geom), ST_Y(g.geom) FROM sampling_designs d, LATERAL ST_Dump(d.points_geometry) g WHERE d.id = :i ORDER BY (g.path)[1] OFFSET :o LIMIT 1"),
                     {"i": design_id, "o": number - 1}).first()
    return float(pts[0]), float(pts[1])


def test_a_typed_latitude_moves_the_plot_and_reports_both_systems(client, db):
    calc, h, design_id = _design_with_plots(client, db)
    lon0, lat0 = _plot(db, design_id, 1)
    r = client.patch(f"/api/sampling/{design_id}/points/1", json={"latitude": lat0 + 0.0001}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["latitude"] == pytest.approx(lat0 + 0.0001, abs=1e-9) and body["longitude"] == pytest.approx(lon0, abs=1e-9)
    assert body["utm_zone"] == 44 and body["utm_easting"] > 0 and body["utm_northing"] > 0
    assert _plot(db, design_id, 1)[1] == pytest.approx(lat0 + 0.0001, abs=1e-9)
    assert body["block_name"] == "Block-1"  # the polygon it belongs to is worked out again


def test_a_typed_utm_easting_moves_the_plot_east_by_that_much(client, db):
    calc, h, design_id = _design_with_plots(client, db)
    lon0, lat0 = _plot(db, design_id, 2)
    zone, e0, n0 = sc.to_utm(lon0, lat0)
    r = client.patch(f"/api/sampling/{design_id}/points/2", json={"utm_easting": e0 + 25.0}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["utm_easting"] == pytest.approx(e0 + 25.0, abs=0.01)
    assert r.json()["utm_northing"] == pytest.approx(n0, abs=0.01)
    assert _plot(db, design_id, 2)[0] > lon0


def test_a_value_outside_the_forest_is_refused_with_a_friendly_message_and_nothing_changes(client, db):
    calc, h, design_id = _design_with_plots(client, db)
    before = _plot(db, design_id, 1)
    r = client.patch(f"/api/sampling/{design_id}/points/1", json={"latitude": 20.0}, headers=h)
    assert r.status_code == 400
    msg = r.json()["detail"]["message"]
    assert "outside the forest boundary" in msg and "not saved" in msg and "lat 20.000000" in msg
    assert r.json()["detail"]["message_np"]  # the Nepali message is there too
    assert _plot(db, design_id, 1) == before


def test_unusable_input_gets_a_clear_400_not_a_crash(client, db):
    calc, h, design_id = _design_with_plots(client, db)
    assert client.patch(f"/api/sampling/{design_id}/points/1", json={"latitude": 95}, headers=h).status_code == 400
    r = client.patch(f"/api/sampling/{design_id}/points/1", json={"latitude": 27.5, "utm_easting": 500000}, headers=h)
    assert r.status_code == 400 and "not both" in r.json()["detail"]["message"]
    assert client.patch(f"/api/sampling/{design_id}/points/1", json={}, headers=h).status_code == 400


def test_a_dragged_position_still_works_and_keeps_its_short_refusal(client, db):
    calc, h, design_id = _design_with_plots(client, db)
    lon0, lat0 = _plot(db, design_id, 1)
    assert client.patch(f"/api/sampling/{design_id}/points/1", json={"longitude": lon0, "latitude": lat0 + 0.0001}, headers=h).status_code == 200
    r = client.patch(f"/api/sampling/{design_id}/points/1", json={"longitude": 10.0, "latitude": 10.0}, headers=h)
    assert r.status_code == 400 and "typed" not in r.json()["detail"]["message"]


def test_plots_cannot_be_moved_once_field_inventory_exists(client, db):
    from app.models.field_inventory import FieldInventoryCalculation

    calc, h, design_id = _design_with_plots(client, db)
    lon0, lat0 = _plot(db, design_id, 1)
    db.add(FieldInventoryCalculation(calculation_id=calc.id, user_id=calc.user_id, uploaded_filename="f.csv", status="completed"))
    db.commit()
    assert client.patch(f"/api/sampling/{design_id}/points/1", json={"latitude": lat0 + 0.0001}, headers=h).status_code == 409


def test_a_forest_that_crosses_the_zone_line_says_so_when_a_typed_utm_value_misses(client, db):
    """Boundary 83.99-84.01 E: plots are in zone 44 and zone 45. A UTM value typed far off is refused, with the zone advice."""
    u = _user(db)
    boundary = box(83.990, 27.495, 84.010, 27.505)
    calc = Calculation(id=uuid.uuid4(), user_id=u.id, forest_name="Two Zones", boundary_geom=shp_wkt.dumps(boundary), is_draft=True, result_data={})
    db.add(calc)
    db.commit()
    design = SamplingDesign(calculation_id=calc.id, sampling_type="systematic", total_points=1)
    db.add(design)
    db.commit()
    db.execute(
        text("UPDATE sampling_designs SET points_geometry = ST_GeomFromText('MULTIPOINT(83.995 27.5)', 4326), "
             "points_block_assignment = CAST(:a AS jsonb) WHERE id = :i"),
        {"i": design.id, "a": json.dumps([{"point_index": 0, "block_number": 1, "block_name": "B"}])},
    )
    db.commit()
    h = _headers(client, db, calc)
    r = client.patch(f"/api/sampling/{design.id}/points/1", json={"utm_easting": 100_500.0}, headers=h)  # ~ 400 km west: outside
    assert r.status_code == 400
    assert "crosses two UTM zones" in r.json()["detail"]["message"] and "UTM Zone column" in r.json()["detail"]["message"]
    r1 = client.patch(f"/api/sampling/{design.id}/points/1", json={"utm_northing": 10_000_000.0 - 1}, headers=h)
    assert r1.status_code == 400 and "UTM 44N" in r1.json()["detail"]["message"]  # the zone it was read in is named
