"""Which coordinate system is a table in, and what the user's choice does (owner plan step C2). The Nepal outline is a coarse copy: see _nepal_outline_wkt."""
import numpy as np
import pandas as pd
import pytest
from pyproj import Transformer
from shapely import wkt
from shapely.geometry import Point
from shapely.prepared import prep

from app.services.upload import coordinates as co
from tests.services._nepal_outline_wkt import NEPAL_WKT

pytestmark = pytest.mark.usefixtures("forget_forests")  # committed forests / rows are purged before and after each test: see conftest (test order is random)

_OUTLINE = prep(wkt.loads(NEPAL_WKT))
_T44 = Transformer.from_crs(4326, 32644, always_xy=True)
_T45 = Transformer.from_crs(4326, 32645, always_xy=True)


@pytest.fixture(autouse=True)
def coarse_nepal(monkeypatch):
    monkeypatch.setattr(co, "inside_nepal_flags", lambda db, lons, lats: [bool(np.isfinite(a) and np.isfinite(b) and _OUTLINE.intersects(Point(a, b))) for a, b in zip(lons, lats)])


def _utm(zone, lons, lats):
    return _T44.transform(lons, lats) if zone == 44 else _T45.transform(lons, lats)


def test_degrees_are_suggested_as_degrees():
    r = co.detect_systems(None, [84.1, 84.2], [28.2, 28.3])
    assert r["suggested_epsg"] == 4326 and not r["ambiguous"] and r["candidates"][0]["inside_fraction"] == 1.0


def test_utm_in_zone_45_is_recognised_as_zone_45():
    x, y = _utm(45, [85.30, 85.31], [27.70, 27.71])
    r = co.detect_systems(None, list(x), list(y))
    assert r["suggested_epsg"] == 32645 and [c["epsg"] for c in r["candidates"]][0] == 32645


def test_utm_in_zone_44_is_recognised_as_zone_44():
    x, y = _utm(44, [81.60, 81.61], [28.10, 28.11])
    assert co.detect_systems(None, list(x), list(y))["suggested_epsg"] == 32644


def test_easting_alone_cannot_decide_but_the_shape_of_nepal_does():
    # the same easting (500 000) at two different northings: only one zone lands in Nepal each time
    assert co.detect_systems(None, [500000, 500100], [3000000, 3000100])["suggested_epsg"] == 32645
    r = co.detect_systems(None, [500000, 500100], [3100000, 3100100])  # 81E,28N is India and 87E,28N is Tibet: neither fits
    assert r["suggested_epsg"] is None and r["none_fit"] is True and not r["ambiguous"]


def test_a_genuinely_ambiguous_point_asks_the_user():
    r = co.detect_systems(None, [583653], [3086415])  # 81.85E 27.9N and 87.85E 27.9N are both in Nepal
    assert r["ambiguous"] is True and r["suggested_epsg"] is None


def test_the_forest_boundary_breaks_a_tie():
    near_81 = (81.7, 27.8, 82.0, 28.0)
    r = co.detect_systems(None, [583653], [3086415], reference_bbox=near_81)
    assert r["suggested_epsg"] == 32644
    near_87 = (87.7, 27.8, 88.0, 28.0)
    assert co.detect_systems(None, [583653], [3086415], reference_bbox=near_87)["suggested_epsg"] == 32645


def test_the_outline_alone_picks_the_right_zone_across_nepal():
    """Measured with the real outline on 2026-10-13: 99.9% right, 0.1% asks the user, 0.0% wrong over 5 434 points. Re-checked here on the coarse copy."""
    lons, lats = np.meshgrid(np.arange(80.1, 88.2, 0.25), np.arange(26.4, 30.4, 0.25))
    right = ambiguous = wrong = total = 0
    for lo, la in zip(lons.ravel(), lats.ravel()):
        if not _OUTLINE.contains(Point(lo, la)):
            continue
        true = 32644 if lo < 84 else 32645
        x, y = _utm(44 if true == 32644 else 45, lo, la)
        r = co.detect_systems(None, [x], [y])
        total += 1
        if r["suggested_epsg"] == true:
            right += 1
        elif r["ambiguous"]:
            ambiguous += 1
        else:
            wrong += 1
    assert total > 200 and wrong / total <= 0.005 and right / total >= 0.97, (total, right, ambiguous, wrong)


def test_swapped_degrees_are_degrees_with_the_columns_the_wrong_way_round():
    r = co.detect_systems(None, [28.2, 28.3], [84.1, 84.2])
    assert r["dominant"] == "swapped" and r["suggested_epsg"] == 4326


def test_strays_and_missing_rows_come_back_by_row():
    r = co.detect_systems(None, pd.Series([84.1, None, 94.1, 84.3]), pd.Series([28.2, 28.2, 28.2, 28.4]))
    assert r["missing_rows"] == [3] and r["strays"] == [(4, "outside_nepal")] and r["suggested_epsg"] == 4326


def test_nothing_is_offered_for_swapped_utm_the_user_names_the_system():
    r = co.detect_systems(None, [3_065_000, 3_066_000], [350_000, 351_000])
    assert r["candidates"] == [] and r["suggested_epsg"] is None


def test_the_chosen_zone_is_applied_to_the_coordinate_columns():
    x, y = _utm(45, [85.30, 85.31], [27.70, 27.71])
    df = pd.DataFrame({"longitude": list(x) + [85.5], "latitude": list(y) + [27.9], "plot": [1, 2, 3]})
    out, findings = co.apply_chosen_system(None, df, 32645)
    assert out["longitude"].round(2).tolist() == [85.30, 85.31, 85.5] and out["plot"].tolist() == [1, 2, 3]  # the degree row is left alone
    assert [f.code for f in findings] == ["coordinates.utm_converted"]


def test_degrees_or_no_choice_change_nothing():
    df = pd.DataFrame({"longitude": [84.1], "latitude": [28.2]})
    for epsg in (None, 4326):
        out, findings = co.apply_chosen_system(None, df, epsg)
        assert out is df and findings == []


def test_a_wrong_zone_is_named_with_its_rows_and_the_better_system():
    x, y = _utm(45, [85.30, 85.31], [27.70, 27.71])
    df = pd.DataFrame({"longitude": list(x), "latitude": list(y)})
    out, findings = co.apply_chosen_system(None, df, 32644)  # the user said zone 44; the numbers are zone 45
    by = {f.code: f for f in findings}
    assert by["coordinates.system_mismatch"].where["rows"] == [2, 3]
    assert "UTM zone 45N" in by["coordinates.system_mismatch"].fix_en


# ── the endpoint ────────────────────────────────────────────────────────────────────────────────────────────────────────

def _post(client, auth_headers, name, content):
    return client.post("/api/uploads/coordinate-system", files={"file": (name, content, "text/csv")}, headers=auth_headers)


def test_endpoint_reads_a_typed_table_and_suggests_the_system(client, auth_headers):
    x, y = _utm(45, [85.30, 85.31, 85.32], [27.70, 27.71, 27.72])
    csv = "Plot No,Easting,Lon,Lat\n" + "\n".join(f"{i + 1},0,{a:.1f},{b:.1f}" for i, (a, b) in enumerate(zip(x, y)))
    r = _post(client, auth_headers, "plots.csv", csv)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["has_coordinates"] and body["lon_column"] == "Lon" and body["lat_column"] == "Lat"
    assert body["suggested_epsg"] == 32645 and body["labels"]["32645"] == "UTM zone 45N"


def test_endpoint_reads_degrees_typed_in_nepali_and_dms(client, auth_headers):
    csv = 'longitude,latitude\n८४.१,"27°41\'12""N"\n"84,2",२७.७\n'  # CSV quoting: a decimal comma and a DMS seconds mark must be quoted
    body = _post(client, auth_headers, "p.csv", csv).json()
    assert body["has_coordinates"] and body["dominant"] == "degrees" and body["suggested_epsg"] == 4326


def test_endpoint_says_so_when_there_are_no_coordinates_or_it_is_not_a_table(client, auth_headers):
    assert _post(client, auth_headers, "t.csv", "species,dbh\nSal,35\n").json()["reason"] == "no_coordinate_columns"
    assert _post(client, auth_headers, "x.kml", "<kml/>").json()["reason"] == "not_a_table"


def test_endpoint_needs_a_login(client):
    assert client.post("/api/uploads/coordinate-system", files={"file": ("p.csv", "a,b\n1,2\n", "text/csv")}).status_code in (401, 403)


def test_field_inventory_upload_applies_the_chosen_utm_zone(client, auth_headers, db):
    import uuid

    from app.models.calculation import Calculation
    from app.models.user import User

    owner = db.query(User).filter(User.email == "testuser@example.com").first()
    calc_ids = []

    def new_calc():
        c = Calculation(id=uuid.uuid4(), user_id=owner.id, forest_name="C2 test forest")
        db.add(c)
        db.commit()
        calc_ids.append(c.id)
        return str(c.id)

    x, y = _utm(45, [85.30, 85.31, 85.32], [27.70, 27.71, 27.72])
    rows = "\n".join(f"B1,{i + 1},{a:.1f},{b:.1f},Shorea robusta,22.0,10.5" for i, (a, b) in enumerate(zip(x, y)))
    csv = "block_name,sample_plot_number,longitude,latitude,pole_species_scientific,pole_dbh_cm,pole_height_m\n" + rows
    mapping = '{"block_name":"block_name","sample_plot_number":"sample_plot_number","longitude":"longitude","latitude":"latitude"}'

    def upload(**extra):
        return client.post("/api/field-inventory/upload", files={"file": ("fi.csv", csv, "text/csv")},
                           data={"mapping": mapping, "calculation_id": new_calc(), **extra}, headers=auth_headers)

    plain = upload().json()
    chosen = upload(crs_epsg="32645").json()
    plain_codes = {f["code"] for f in plain.get("findings", [])}
    chosen_codes = {f["code"] for f in chosen.get("findings", [])}
    assert "coordinates.looks_like_utm" in plain_codes  # without a choice the file is only flagged
    assert "coordinates.utm_converted" in chosen_codes and "coordinates.looks_like_utm" not in chosen_codes
    assert not any(e.get("type") in ("invalid_longitude", "invalid_latitude") for e in chosen.get("warnings", []))


def test_a_utm_sheet_headed_easting_northing_is_recognised_by_the_endpoint(client, auth_headers):
    x, y = _utm(45, [85.30, 85.31], [27.70, 27.71])
    csv = "Plot,Easting,Northing\n" + "\n".join(f"{i + 1},{a:.1f},{b:.1f}" for i, (a, b) in enumerate(zip(x, y)))
    body = _post(client, auth_headers, "utm.csv", csv).json()
    assert body["has_coordinates"] and body["lon_column"] == "Easting" and body["lat_column"] == "Northing" and body["suggested_epsg"] == 32645


def test_plain_longitude_latitude_beat_easting_northing_when_a_file_has_both():
    from app.services.upload.column_synonyms import coordinate_columns

    assert coordinate_columns(["Easting", "Northing", "Lon", "Lat"]) == ("Lon", "Lat")
    assert coordinate_columns(["X", "Y"]) == ("X", "Y")
    assert coordinate_columns(["species", "dbh"]) == (None, None)


# ── the stem-mapping quick boundary check ────────────────────────────────────────────────────────────────────────────────

def test_utm_stem_points_are_converted_before_they_are_compared_with_the_boundary():
    x, y = _utm(45, [85.55, 85.56, 85.57], [27.40, 27.41, 27.42])
    pts = co.boundary_check_points(list(x), list(y), projection_epsg=32645)
    assert [(round(a, 3), round(b, 3), r) for a, b, r in pts] == [(85.55, 27.4, 1), (85.56, 27.41, 2), (85.57, 27.42, 3)]


def test_the_zone_is_found_when_the_user_chose_none_and_only_one_fits(db):
    x, y = _utm(45, [85.55, 85.56], [27.40, 27.41])
    pts = co.boundary_check_points(list(x), list(y))  # the coarse Nepal outline is patched in by the autouse fixture
    assert round(pts[0][0], 2) == 85.55


def test_degrees_pass_through_unchanged_and_blanks_are_dropped():
    pts = co.boundary_check_points([84.1, None, 84.3], [28.2, 28.2, 28.4])
    assert pts == [(84.1, 28.2, 1), (84.3, 28.4, 3)]  # the row numbers stay the spreadsheet's


def test_a_wrong_zone_choice_is_not_papered_over():
    x, y = _utm(45, [85.55], [27.40])
    lon, lat, _ = co.boundary_check_points(list(x), list(y), projection_epsg=32644)[0]
    assert lon < 84  # zone 44 puts a zone-45 easting far to the west: the boundary check then (correctly) reports it outside


# ── the stem-mapping validator's UTM zone (the old detector called almost everything zone 44) ───────────────────────────

def _validator():
    from unittest.mock import MagicMock

    from app.services.inventory_validator import InventoryValidator

    return InventoryValidator(MagicMock())


def test_the_old_detector_called_a_zone_45_file_zone_44_and_the_refinement_corrects_it():
    from app.services.validators.coordinate_detector import CoordinateDetector

    x, y = _utm(45, [85.55, 85.56, 85.57], [27.40, 27.41, 27.42])
    old = CoordinateDetector().detect_crs(list(x), list(y))
    assert old["epsg"] == 32644  # the weakness: a point at 85.56 E is not in zone 44
    fixed = _validator()._refine_utm_zone(old, list(x), list(y), None)
    assert fixed["epsg"] == 32645 and "inside Nepal" in fixed["method"] and fixed["name"].endswith("UTM zone 45N")


def test_the_zone_the_user_chose_wins_over_the_detector():
    x, y = _utm(45, [85.55, 85.56], [27.40, 27.41])
    from app.services.validators.coordinate_detector import CoordinateDetector

    old = CoordinateDetector().detect_crs(list(x), list(y))
    assert _validator()._refine_utm_zone(old, list(x), list(y), 32645)["epsg"] == 32645
    assert _validator()._refine_utm_zone({**old, "epsg": 32645}, list(x), list(y), 32644)["epsg"] == 32644  # the user's choice, even if it is the odd one


def test_a_genuine_tie_keeps_the_old_answer():
    old = {"epsg": 32644, "name": "WGS84 / UTM Zone 44N", "method": "UTM 44N bounds (Western Nepal)"}
    assert _validator()._refine_utm_zone(old, [583653.0], [3086415.0], None) == old  # both zones fit: the dialog asks the user, the validator does not guess


def test_degrees_and_unknown_are_left_alone():
    v = _validator()
    assert v._refine_utm_zone({"epsg": 4326}, [84.1], [28.2], 32645) == {"epsg": 4326}
    assert v._refine_utm_zone({"epsg": "UNKNOWN"}, [1.0], [2.0], None) == {"epsg": "UNKNOWN"}


def test_if_the_refinement_cannot_run_the_old_answer_stands(monkeypatch):
    old = {"epsg": 32644, "name": "WGS84 / UTM Zone 44N"}
    monkeypatch.setattr(co, "detect_systems", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no database")))
    assert _validator()._refine_utm_zone(old, [356841.9], [3031794.4], None) == old
