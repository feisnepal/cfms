"""Hazard tiles for the workspace Analysis maps: the pixel mapping, the class/colour parity with the print map, and the
"cache only, never compute" rule."""
import io
import math

import numpy as np
import pytest
from PIL import Image

from app.core import semantic_palettes as sp
from app.services.operational_plan import hazard_tiles as ht
from app.services.operational_plan import soil_erosion as se
from app.services.operational_plan.thematic_map_spec import BUILTIN_THEMEMAP_SPECS

BREAKS = [5.0, 10.0, 20.0, 40.0, 80.0]
BOUNDS = (85.0, 27.0, 85.04, 27.04)  # 4 x 4 cells of 0.01 degree


def _surface(values, inside=None, bounds=BOUNDS):
    h, w = values.shape
    colours = sp.sample_ramp(BUILTIN_THEMEMAP_SPECS["soil__annual_loss"].palette or "reds", len(BREAKS) + 1)
    return ht.surface_from_array(
        "soil", values, bounds=bounds, inside=np.ones((h, w), bool) if inside is None else inside,
        cell_area_ha=np.full((h, w), 10.0), breaks=BREAKS, colours=colours,
        labels_ne=[f"ne{i}" for i in range(6)], labels_en=[f"en{i}" for i in range(6)],
        params_hash="abc", cell_m=1000.0,
    )


def _tile_for(lon, lat, z):
    n = 2 ** z
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
    return x, y


def _decode(png):
    return np.array(Image.open(io.BytesIO(png)).convert("RGBA"))


def _rgb(hexcol):
    return tuple(int(hexcol[i:i + 2], 16) for i in (1, 3, 5))


def test_classes_use_the_print_maps_own_classifier_and_palette():
    values = np.array([[1.0, 5.0, 12.0, 45.0]] * 4)  # classes 0, 1, 2, 4  (an edge belongs to the HIGHER class)
    s = _surface(values)
    assert list(s.cls[0]) == [0, 1, 2, 4]
    assert list(s.cls[0]) == list(se.classify_severity(values, BREAKS)[0])
    assert s.colours == sp.sample_ramp("reds", 6)


def test_a_tile_pixel_gets_its_cells_colour():
    values = np.array([[1.0, 5.0, 12.0, 45.0]] * 4)
    s = _surface(values)
    z = 14
    # centre of the cell in column 2 (lon 85.025), middle of the grid vertically
    lon, lat = 85.025, 27.02
    x, y = _tile_for(lon, lat, z)
    img = _decode(ht.render_tile(s, z, x, y))
    # find the pixel that holds (lon, lat)
    n = 2 ** z
    px = int(((lon + 180.0) / 360.0 * n - x) * ht.TILE_SIZE)
    latr = math.radians(lat)
    py = int(((1.0 - math.asinh(math.tan(latr)) / math.pi) / 2.0 * n - y) * ht.TILE_SIZE)
    r, g, b, a = img[py, px]
    assert (r, g, b) == _rgb(s.colours[2]) and a == ht.DEFAULT_ALPHA


def test_outside_the_forest_and_outside_the_grid_is_transparent():
    values = np.full((4, 4), 50.0)
    inside = np.zeros((4, 4), bool)
    inside[1:3, 1:3] = True  # only the middle four cells are forest
    s = _surface(values, inside)
    z = 14
    x, y = _tile_for(85.005, 27.035, z)  # a corner cell: not forest
    img = _decode(ht.render_tile(s, z, x, y))
    n = 2 ** z
    px = int(((85.005 + 180.0) / 360.0 * n - x) * ht.TILE_SIZE)
    py = int(((1.0 - math.asinh(math.tan(math.radians(27.035))) / math.pi) / 2.0 * n - y) * ht.TILE_SIZE)
    assert img[py, px][3] == 0
    far_x, far_y = _tile_for(86.5, 28.5, z)
    assert not _decode(ht.render_tile(s, z, far_x, far_y))[..., 3].any()


def test_every_part_of_a_multi_part_forest_is_drawn():
    values = np.full((4, 4), 50.0)
    inside = np.zeros((4, 4), bool)
    inside[0, 0] = True
    inside[3, 3] = True  # two separate parts
    s = _surface(values, inside)
    assert int((s.cls >= 0).sum()) == 2


def test_legend_lists_only_present_classes_with_area_and_share():
    values = np.array([[1.0, 1.0, 12.0, 12.0]] * 4)
    lg = ht.legend(_surface(values))
    assert [r["index"] for r in lg["classes"]] == [0, 2]
    assert lg["classes"][0]["area_ha"] == 80.0 and lg["classes"][0]["share_pct"] == 50.0
    assert lg["total_ha"] == 160.0 and lg["state"] == "ready"


def test_unknown_layer_is_rejected():
    with pytest.raises(ValueError):
        ht.load_surface(None, "00000000-0000-0000-0000-000000000000", "nope")


def test_tile_route_never_computes_and_says_not_computed(client, auth_headers, db, monkeypatch):
    import uuid

    from sqlalchemy import text

    from app.models.user import User

    called = []
    monkeypatch.setattr(se, "compute_soil_loss", lambda *a, **k: called.append(1))
    uid = str(db.query(User).filter(User.email == "testuser@example.com").first().id)
    cid = uuid.uuid4()
    db.execute(text("INSERT INTO calculations (id, user_id, forest_name, status) VALUES (:i,:u,'F','PROCESSING')"), {"i": cid, "u": uid})
    db.commit()
    r = client.get(f"/api/calculations/{cid}/hazard-tiles/soil/12/1/1.png", headers=auth_headers)
    assert r.status_code == 200 and r.headers["x-hazard-state"] == "not-computed"
    assert not _decode(r.content)[..., 3].any()
    assert called == []
    for key in ("soil", "lsi", "fs", "prone"):
        r = client.get(f"/api/calculations/{cid}/hazard-tiles/{key}/12/1/1.png", headers=auth_headers)
        assert r.status_code == 200 and r.headers["x-hazard-state"] == "not-computed", key
        lg = client.get(f"/api/calculations/{cid}/hazard-legend/{key}", headers=auth_headers).json()
        assert lg["state"] == "not_computed", key
    assert client.get(f"/api/calculations/{cid}/hazard-tiles/bogus/12/1/1.png", headers=auth_headers).status_code == 404


def test_tile_route_requires_credentials(client):
    r = client.get("/api/calculations/00000000-0000-0000-0000-000000000001/hazard-tiles/soil/12/1/1.png")
    assert r.status_code in (401, 403)


def test_a_cached_but_empty_surface_is_no_data_not_not_computed():
    """E.g. the factor of safety switched off: the grid is cached and all NaN."""
    s = _surface(np.full((4, 4), np.nan))
    assert ht.legend(s) == {"state": "no_data", "key": "soil"}


def test_layer_keys_cover_the_four_maps():
    assert ht.LAYER_KEYS == ("soil", "lsi", "fs", "prone")


# ── per-unit summaries ────────────────────────────────────────────────────────────────────────────────────────────
def _units():
    from shapely.geometry import box

    # BOUNDS is 85.00–85.04 x 27.00–27.04 (4x4 cells of 0.01): the left half and the right half
    return [
        {"name": "Left", "geometry": box(85.0, 27.0, 85.02, 27.04)},
        {"name": "Right", "geometry": box(85.02, 27.0, 85.04, 27.04)},
    ]


def test_soil_unit_summary_is_area_weighted_mean_and_severe_share():
    values = np.array([[1.0, 1.0, 50.0, 100.0]] * 4)  # classes 0, 0, 4, 5
    s = _surface(values)
    out = ht.unit_summary(s, _units())
    assert out["Left"]["mean"] == 1.0 and out["Left"]["severe_pct"] == 0.0
    assert out["Right"]["mean"] == 75.0 and out["Right"]["severe_pct"] == 100.0
    assert out["Left"]["area_ha"] == 80.0


def test_a_unit_with_no_valid_cell_is_left_out():
    inside = np.zeros((4, 4), bool)
    inside[:, 2:] = True  # only the right half is forest
    out = ht.unit_summary(_surface(np.full((4, 4), 50.0), inside), _units())
    assert "Left" not in out and "Right" in out


def test_fs_and_prone_and_lsi_summaries():
    # fs: classes 0 unstable, 1 marginal, 2 stable are made from breaks [1.0, 1.5]
    fs_vals = np.array([[0.5, 1.2, 2.0, 2.0]] * 4)
    s = _surface(fs_vals)
    s.key = "fs"
    s.cls = se.classify_severity(fs_vals, [1.0, 1.5]).astype("int16")
    out = ht.unit_summary(s, _units())
    assert out["Left"]["unstable_pct"] == 50.0 and out["Left"]["unsafe_pct"] == 100.0
    assert out["Right"]["unsafe_pct"] == 0.0

    lsi = _surface(np.array([[0, 0, 4, 4]] * 4, dtype=float))
    lsi.key = "lsi"
    lsi.cls = np.array([[0, 0, 4, 4]] * 4, dtype="int16")
    lsi.labels_en = ["Very low (LSI 1.8–2.4)", "Low", "Moderate", "High", "Very high (LSI 2.9–3.3)", ""]
    o = ht.unit_summary(lsi, _units())
    assert o["Left"]["dominant"]["label_en"] == "Very low" and o["Right"]["dominant"]["index"] == 4
    assert o["Right"]["high_pct"] == 100.0 and o["Left"]["high_pct"] == 0.0

    pr = _surface(np.array([[0, 1, 1, 1]] * 4, dtype=float))
    pr.key = "prone"
    pr.cls = np.array([[0, 1, 1, 1]] * 4, dtype="int16")
    p = ht.unit_summary(pr, _units())
    assert p["Left"]["high_pct"] == 50.0 and p["Right"]["high_pct"] == 100.0


def test_hazard_units_route_reports_missing_layers_and_never_computes(client, auth_headers, db):
    import uuid

    from sqlalchemy import text

    from app.models.user import User

    uid = str(db.query(User).filter(User.email == "testuser@example.com").first().id)
    cid = uuid.uuid4()
    db.execute(text("INSERT INTO calculations (id, user_id, forest_name, status) VALUES (:i,:u,'F','PROCESSING')"), {"i": cid, "u": uid})
    db.commit()
    got = client.get(f"/api/calculations/{cid}/hazard-units", headers=auth_headers)
    assert got.status_code == 200
    assert got.json()["layers"] == {} and sorted(got.json()["missing"]) == ["fs", "lsi", "prone", "soil"]


# ── the user-group view ───────────────────────────────────────────────────────────────────────────────────────────
class _Grid:
    def __init__(self, cf, ug):
        self.cf_mask, self.ug_mask = cf, ug


def test_the_user_group_view_uses_the_user_group_mask_and_refuses_without_one():
    cf = np.zeros((4, 4), bool)
    cf[:2] = True
    ug = np.zeros((4, 4), bool)
    ug[:, 2:] = True
    assert (ht._inside_mask(_Grid(cf, ug), "forest") == cf).all()
    assert (ht._inside_mask(_Grid(cf, ug), "user_group") == ug).all()
    with pytest.raises(ht.NoUserGroup):
        ht._inside_mask(_Grid(cf, None), "user_group")
    with pytest.raises(ht.NoUserGroup):
        ht._inside_mask(_Grid(cf, np.zeros((4, 4), bool)), "user_group")


def test_an_unknown_area_is_rejected():
    with pytest.raises(ValueError):
        ht.load_surface(None, "00000000-0000-0000-0000-000000000000", "soil", "elsewhere")


def test_area_query_is_validated_by_the_routes(client, auth_headers, db):
    import uuid

    from sqlalchemy import text

    from app.models.user import User

    uid = str(db.query(User).filter(User.email == "testuser@example.com").first().id)
    cid = uuid.uuid4()
    db.execute(text("INSERT INTO calculations (id, user_id, forest_name, status) VALUES (:i,:u,'F','PROCESSING')"), {"i": cid, "u": uid})
    db.commit()
    ok = client.get(f"/api/calculations/{cid}/hazard-legend/soil?area=user_group", headers=auth_headers)
    assert ok.status_code == 200 and ok.json()["state"] in ("not_computed", "no_user_group")
    assert client.get(f"/api/calculations/{cid}/hazard-legend/soil?area=moon", headers=auth_headers).status_code == 422


# ── factor layers and household dots ──────────────────────────────────────────────────────────────────────────────
def test_the_factor_layers_of_the_original_tab_are_all_served():
    assert len(ht.FACTOR_KEYS) == 14
    assert len([k for k in ht.FACTOR_KEYS if k.startswith("f_soil_")]) == 4
    assert len([k for k in ht.FACTOR_KEYS if k.startswith("f_lsi_")]) == 10
    assert set(ht.TILE_KEYS) == set(ht.LAYER_KEYS) | set(ht.FACTOR_KEYS)
    # band positions: soil file = loss, R, K, LS, C ...; LSI file = lsi, class, then the ten factors in order
    assert [v[0] for v in ht.SOIL_FACTORS.values()] == [2, 3, 4, 5]
    assert [v[0] for v in ht.LSI_FACTORS.values()] == list(range(3, 13))


def test_factor_specs_exist_so_labels_and_palettes_can_be_taken_from_them():
    from app.services.operational_plan.thematic_map_spec import BUILTIN_THEMEMAP_SPECS as SPECS

    for _, spec_key in list(ht.LSI_FACTORS.values()):
        assert spec_key in SPECS
    for _, _, spec_key in ht.SOIL_FACTORS.values():
        assert spec_key in SPECS


def test_factor_and_household_routes_never_compute(client, auth_headers, db, monkeypatch):
    import uuid

    from sqlalchemy import text

    from app.models.user import User
    from app.services.operational_plan import household_vulnerability as hvm

    called = []
    monkeypatch.setattr(hvm, "compute_household_vulnerability", lambda *a, **k: called.append(1))
    uid = str(db.query(User).filter(User.email == "testuser@example.com").first().id)
    cid = uuid.uuid4()
    db.execute(text("INSERT INTO calculations (id, user_id, forest_name, status) VALUES (:i,:u,'F','PROCESSING')"), {"i": cid, "u": uid})
    db.commit()
    for key in ("f_soil_r", "f_lsi_slope"):
        r = client.get(f"/api/calculations/{cid}/hazard-tiles/{key}/12/1/1.png", headers=auth_headers)
        assert r.status_code == 200 and r.headers["x-hazard-state"] == "not-computed", key
        assert client.get(f"/api/calculations/{cid}/hazard-legend/{key}", headers=auth_headers).json()["state"] == "not_computed"
    for kind in ("households", "settlements"):
        got = client.get(f"/api/calculations/{cid}/hazard-households/{kind}", headers=auth_headers).json()
        assert got["state"] == "not_computed", kind  # the grids are not cached: no household computation is started
    assert called == []
    assert client.get(f"/api/calculations/{cid}/hazard-households/people", headers=auth_headers).status_code == 404
    ug = client.get(f"/api/calculations/{cid}/hazard-households/households?area=user_group", headers=auth_headers).json()
    assert ug["state"] == "no_user_group"


def test_household_points_carry_no_identifiers(monkeypatch):
    from types import SimpleNamespace

    from app.services.operational_plan import hazard_households as hh

    res = SimpleNamespace(
        households=[{"longitude": 85.0, "latitude": 27.0, "score": 0.3, "priority": True, "house_no": "12", "caste": "x", "surname": "y"}],
        settlement_rollup=[{"_lon": 85.0, "_lat": 27.0, "mean_score": 0.3, "tole": "Tole", "n_households": 4, "n_priority": 1}],
        summary={"basis": "households"},
    )
    monkeypatch.setattr(hh, "_grids_cached", lambda *a, **k: True)
    monkeypatch.setattr(hh, "_result", lambda *a, **k: res)
    monkeypatch.setattr(hh, "_signature", lambda *a, **k: "sig")
    one = hh.points(None, "00000000-0000-0000-0000-000000000001", "households")
    assert one["state"] == "ready" and one["count"] == 1 and one["n_priority"] == 1
    assert set(one["features"][0]["properties"]) == {"score", "priority"}  # never a house number, name or caste
    st = hh.points(None, "00000000-0000-0000-0000-000000000001", "settlements")
    assert st["features"][0]["properties"]["name"] == "Tole" and st["features"][0]["properties"]["n"] == 4
