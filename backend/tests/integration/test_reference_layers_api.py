"""Reference-data layers round a forest (rivers, roads, wards ...): each layer's query runs on the real tables, is cut to the neighbourhood, and is read-only shared data."""
import dataclasses
import uuid

import pytest
from shapely import wkt as shp_wkt
from shapely.geometry import box
from sqlalchemy import text

from app.core import reference_layers as ref
from app.models.calculation import Calculation
from tests.integration.test_ntfp_design_api import _register


CX, CY = 83.405, 27.405          # where the stand-in features are, and where the test forests sit


def _wkt(g):
    return f"ST_GeomFromText('{g}', 4326)"


# The test database is built from migrations alone, so the national reference schemas (loaded data in cf_db) are not in it. A stand-in with the same schema, table and column
# names is made for every table that is missing and dropped again afterwards: the layer queries are checked against the real column names, on a few known features.
_STANDINS = {
    "river.river84": ('objectid int, shape geometry(MultiLineString,4326), length_meter int, "river name" text, "sub river system name" text',
                      ["(1, {g}, 900, 'Test Khola', 'Test system')".format(g=_wkt(f"MULTILINESTRING(({CX-0.01} {CY-0.003}, {CX+0.01} {CY+0.003}))"))]),
    "infrastructure.road": ("id int, geom geometry(MultiLineString,4326), name varchar, name_en varchar, highway varchar, surface varchar, width varchar, name_ne varchar, osm_id bigint",
                            ["(1, {g}, 'Test Road', NULL, 'track', 'dirt', '4', NULL, 1001)".format(g=_wkt(f"MULTILINESTRING(({CX-0.02} {CY}, {CX+0.02} {CY}))"))]),
    "admin.municipality": ("id int, geom geometry(MultiPolygon,4326), state_code int, district varchar, gapa_napa varchar, type_gn varchar, province varchar",
                           ["(1, {g}, 3, 'TESTDIST', 'Test Palika', 'Gaunpalika', 'Bagmati')".format(g=_wkt(f"MULTIPOLYGON((({CX-0.5} {CY-0.5}, {CX+0.5} {CY-0.5}, {CX+0.5} {CY+0.5}, {CX-0.5} {CY+0.5}, {CX-0.5} {CY-0.5})))"))]),
    "admin.ward": ("id int, geom geometry(MultiPolygon,4326), district varchar, municipality varchar, ward varchar, palika_type varchar",
                   ["(1, {g}, 'Testdist', 'Test Palika', '2', 'Gaunpalika')".format(g=_wkt(f"MULTIPOLYGON((({CX-0.05} {CY-0.05}, {CX+0.05} {CY-0.05}, {CX+0.05} {CY+0.05}, {CX-0.05} {CY+0.05}, {CX-0.05} {CY-0.05})))"))]),
    "admin.protected_area": ('id int, geom geometry(MultiPolygon,4326), "area sqm" bigint, description text, "protected area name" text',
                             ["(1, {g}, 5000000, 'a test area', 'Test Conservation Area')".format(g=_wkt(f"MULTIPOLYGON((({CX-0.1} {CY-0.1}, {CX+0.1} {CY-0.1}, {CX+0.1} {CY+0.1}, {CX-0.1} {CY+0.1}, {CX-0.1} {CY-0.1})))"))]),
    "admin.settlement": ("objectid int, shape geometry(Point,4326), vil_name varchar, asl int",
                         ["(1, {g}, 'Test Gaun', 700)".format(g=_wkt(f"POINT({CX} {CY})"))]),
    "buildings.building": ('objectid int, shape geometry(MultiPolygon,4326), "area sqm" int',
                           [("({i}, {g}, 40)".format(i=i + 1, g=_wkt(f"MULTIPOLYGON((({CX+i*0.0003} {CY} , {CX+i*0.0003+0.0001} {CY}, {CX+i*0.0003+0.0001} {CY+0.0001}, {CX+i*0.0003} {CY+0.0001}, {CX+i*0.0003} {CY})))")))
                            for i in range(8)]),
}


@pytest.fixture(scope="module", autouse=True)
def _reference_tables():
    from app.core.database import engine

    made = []
    with engine.begin() as conn:
        for table, (cols, rows) in _STANDINS.items():
            schema = table.split(".")[0]
            if conn.execute(text("SELECT to_regclass(:t)"), {"t": table}).scalar() is not None:
                continue                              # the real table is here (a developer's database): use it as it is
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
            conn.execute(text(f"CREATE TABLE {table} ({cols})"))
            geom_col = next(c.split()[0] for c in cols.split(", ") if "geometry(" in c)
            conn.execute(text(f"CREATE INDEX ON {table} USING gist ({geom_col})"))
            conn.execute(text(f"INSERT INTO {table} VALUES " + ", ".join(rows)))
            made.append(table)
    yield
    with engine.begin() as conn:
        for table in made:
            conn.execute(text(f"DROP TABLE IF EXISTS {table}"))


def _forest_around(db, user_id, layer, half_deg=0.002):
    """A tiny forest on top of the stand-in features, so every layer has something to return."""
    calc = Calculation(id=uuid.uuid4(), user_id=user_id, forest_name=f"Ref {layer.key}", is_draft=True, result_data={},
                       boundary_geom=shp_wkt.dumps(box(CX - half_deg, CY - half_deg, CX + half_deg, CY + half_deg)))
    db.add(calc)
    db.commit()
    return calc, (CX - half_deg, CY - half_deg, CX + half_deg, CY + half_deg)


def _url(calc, tail=""):
    return f"/api/calculations/{calc.id}/reference-layers{tail}"


def _coords(geom):
    def walk(c):
        if isinstance(c[0], (int, float)):
            yield c
        else:
            for x in c:
                yield from walk(x)
    return list(walk(geom["coordinates"]))


def test_the_catalogue_says_what_each_layer_is_and_where_it_comes_from(client, db):
    headers, uid = _register(client)
    calc, _ = _forest_around(db, uid, ref.LAYERS[0])
    got = client.get(_url(calc), headers=headers).json()["layers"]
    assert [l["key"] for l in got] == [l.key for l in ref.LAYERS] and len(got) == 7
    by = {l["key"]: l for l in got}
    assert by["roads"]["licence"] == "ODbL 1.0" and "OpenStreetMap" in by["roads"]["source"]
    assert by["rivers"]["licence"] is None and "not recorded" in by["rivers"]["licence_note"]       # an unknown licence is said to be unknown, never guessed
    assert all(l["label_en"] and l["label_ne"] and l["style"] and l["source"] for l in got)
    assert {l["geometry"] for l in got} == {"line", "polygon", "point"}


@pytest.mark.parametrize("key", [l.key for l in ref.LAYERS])
def test_every_layer_runs_on_the_real_table_and_returns_features_inside_the_neighbourhood(client, db, key):
    layer = ref.get(key)
    headers, uid = _register(client)
    calc, (x0, y0, x1, y1) = _forest_around(db, uid, layer)
    r = client.get(_url(calc, f"/{key}"), headers=headers, params={"buffer_m": 0})
    assert r.status_code == 200, r.text
    fc = r.json()
    assert fc["type"] == "FeatureCollection" and fc["key"] == key and fc["count"] == len(fc["features"]) >= 1 and fc["truncated"] is False
    for f in fc["features"]:
        assert f["type"] == "Feature" and f["properties"]["_ref"] == f["id"] and set(layer.properties) <= set(f["properties"])
    if layer.clip != ref.CLIP_NONE:     # a clipped layer lies inside the box (a little slack for the 5-decimal rounding)
        for f in fc["features"]:
            for x, y in [(c[0], c[1]) for c in _coords(f["geometry"])]:
                assert x0 - 1e-4 <= x <= x1 + 1e-4 and y0 - 1e-4 <= y <= y1 + 1e-4, (key, x, y)


def test_a_wider_buffer_reaches_further(client, db):
    layer = ref.get("roads")
    headers, uid = _register(client)
    calc, _ = _forest_around(db, uid, layer, half_deg=0.0005)
    narrow = client.get(_url(calc, "/roads"), headers=headers, params={"buffer_m": 0}).json()["count"]
    wide = client.get(_url(calc, "/roads"), headers=headers, params={"buffer_m": 3000}).json()
    assert wide["count"] >= narrow >= 1 and wide["buffer_m"] == 3000


def test_a_layer_is_cut_at_its_limit_and_says_so(client, db, monkeypatch):
    layer = ref.get("buildings")
    headers, uid = _register(client)
    calc, _ = _forest_around(db, uid, layer, half_deg=0.01)
    monkeypatch.setitem(ref.BY_KEY, "buildings", dataclasses.replace(layer, max_features=3))
    fc = client.get(_url(calc, "/buildings"), headers=headers, params={"buffer_m": 500}).json()
    assert fc["count"] == 3 and fc["truncated"] is True and fc["max_features"] == 3


def test_refusals(client, db):
    layer = ref.get("rivers")
    headers, uid = _register(client)
    calc, _ = _forest_around(db, uid, layer)
    assert client.get(_url(calc, "/no-such-layer"), headers=headers).status_code == 404
    assert client.get(_url(calc, "/rivers"), headers=headers, params={"buffer_m": 20000}).status_code == 422
    assert client.get(_url(calc, "/rivers"), headers=headers, params={"buffer_m": -5}).status_code == 422
    bare = Calculation(id=uuid.uuid4(), user_id=uid, forest_name="No boundary", is_draft=True, result_data={})
    db.add(bare)
    db.commit()
    r = client.get(_url(bare, "/rivers"), headers=headers)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "no_boundary"
    other, _ = _register(client)
    assert client.get(_url(calc), headers=other).status_code == 403
    assert client.get(_url(calc, "/rivers"), headers=other).status_code == 403


def test_the_list_is_one_definition_with_no_duplicate_keys_and_safe_identifiers():
    keys = [l.key for l in ref.LAYERS]
    assert len(keys) == len(set(keys))
    for l in ref.LAYERS:   # identifiers are put into SQL: only our own constants, with no statement-breaking characters
        assert ";" not in l.table and "--" not in l.table and l.geom_column.isidentifier()
        assert l.geometry in ("line", "polygon", "point") and l.clip in (ref.CLIP_POLYGON, ref.CLIP_LINE, ref.CLIP_NONE)
        assert l.max_features > 0 and l.style and l.source
