"""Per-layer raster coverage probe (RS-0.4).

The probe exists so that "this raster is not available for this forest" is a cheap
answer instead of a failed vectorize. The behaviour that matters, and that these
tests pin, is the difference between the two ways it can be False:

* the raster table is **not installed** on this deployment, versus
* the table is installed but the forest **falls outside** its extent.

Those need different fixes, and the pre-existing gates (``prereq_check.
_has_raster_coverage`` and ``raster_zonal.coverage_available``) could only ever
test ``rasters.dem`` -- so the second case was invisible.

Synthetic raster tables are created per test rather than relying on the national
rasters being imported, so the suite does not depend on the deployment's data.
The four shipping layers are asserted at the catalog level instead, which needs
no data at all.
"""

from __future__ import annotations

import uuid

import pytest
from geoalchemy2.shape import from_shape
from shapely.geometry import Polygon
from sqlalchemy import text

from app.models.calculation import Calculation
from app.models.user import User
from app.services import raster_coverage as rc
from app.services.tile_service import TileService

# The forest the synthetic rasters will cover.
_FOREST = Polygon([(84.0, 27.0), (84.002, 27.0), (84.002, 27.002), (84.0, 27.002)])
_FOREST_WKT = _FOREST.wkt

# A raster nowhere near the forest: the "installed but does not cover" case.
_FAR = Polygon([(1.0, 1.0), (1.002, 1.0), (1.002, 1.002), (1.0, 1.002)])

# The four layers RS-2 onward carve from, per the plan.
SHIPPING = {
    "nasa_forest_2020": "rasters.nasa_forest_2020",
    "forest_health": "rasters.nepal_forest_health",
    "landcover": "rasters.esa_world_cover",
    "dem": "rasters.dem",
}


def _make_raster_table(db, table, extent, tiles=1):
    """Create ``table`` holding ``tiles`` raster rows covering ``extent``."""
    minx, miny, maxx, maxy = extent.bounds
    db.execute(text("CREATE SCHEMA IF NOT EXISTS rasters"))
    db.execute(text(f"DROP TABLE IF EXISTS {table}"))
    db.execute(text(f"CREATE TABLE {table} (rid serial PRIMARY KEY, rast raster)"))
    for _ in range(tiles):
        db.execute(
            text(
                f"INSERT INTO {table} (rast) VALUES ("
                f"  ST_AddBand(ST_MakeEmptyRaster(20, 20, {minx}, {maxy},"
                f"    0.0001, -0.0001, 0, 0, 4326), '8BUI'::text, 1, 1))"
            )
        )
    db.commit()


@pytest.fixture()
def probe_tables(db, monkeypatch):
    """Two synthetic layers: one covering the forest, one far away from it.

    Registered into the live catalog so the probe resolves them exactly the way
    it resolves a real layer, and torn down afterwards.
    """
    _make_raster_table(db, "rasters.ssot_cover", _FOREST, tiles=3)
    _make_raster_table(db, "rasters.ssot_far", _FAR, tiles=1)
    db.execute(text("DROP TABLE IF EXISTS rasters.ssot_absent"))
    db.commit()

    monkeypatch.setitem(TileService.RASTER_TABLES, "ssot_cover", "rasters.ssot_cover")
    monkeypatch.setitem(TileService.RASTER_TABLES, "ssot_far", "rasters.ssot_far")
    monkeypatch.setitem(TileService.RASTER_TABLES, "ssot_absent", "rasters.ssot_absent")
    yield
    for t in ("rasters.ssot_cover", "rasters.ssot_far"):
        db.execute(text(f"DROP TABLE IF EXISTS {t}"))
    db.commit()


# --------------------------------------------------------------------------
# The catalog itself
# --------------------------------------------------------------------------


def test_the_four_shipping_layers_resolve_to_their_tables():
    """No data needed: the carve sources must be addressable by the probe."""
    for layer, table in SHIPPING.items():
        assert rc.raster_table_for(layer) == table


def test_the_four_shipping_layers_are_distinct_tables():
    """Guards against two sources silently pointing at one another's raster."""
    assert len(set(SHIPPING.values())) == len(SHIPPING)


def test_an_unknown_layer_is_rejected_by_name():
    with pytest.raises(rc.UnknownRasterLayer):
        rc.raster_table_for("not-a-real-layer")


def test_a_table_name_outside_the_catalog_never_reaches_sql(db, probe_tables):
    """The service's own guard: a bare table name is not a layer key.

    A caller must pass a catalog *key*. Passing a table name straight through is
    the mistake this refuses -- without it, a caller-controlled string would be
    the thing interpolated into the coverage SQL.
    """
    with pytest.raises(rc.UnknownRasterLayer):
        # a real table, but not a catalog value (was rasters.slope, now deleted)
        rc.table_exists(db, "rasters.total_associations")
    with pytest.raises(rc.UnknownRasterLayer):
        rc.table_exists(db, "rasters.pg_class")


# --------------------------------------------------------------------------
# The two ways "covered" is False
# --------------------------------------------------------------------------


def test_a_raster_covering_the_forest_reports_covered(db, probe_tables):
    r = rc.raster_coverage(db, _FOREST_WKT, "ssot_cover")
    assert r["covered"] is True
    assert r["table_present"] is True
    assert r["tile_count"] == 3
    assert r["has_boundary"] is True
    assert r["layer"] == "ssot_cover"
    assert r["table"] == "rasters.ssot_cover"


def test_an_absent_table_reports_absent_rather_than_raising(db, probe_tables):
    """The headline behaviour: a missing raster is a value, not a 500."""
    r = rc.raster_coverage(db, _FOREST_WKT, "ssot_absent")
    assert r["table_present"] is False
    assert r["covered"] is False
    assert r["tile_count"] == 0


def test_an_installed_raster_that_misses_the_forest_is_distinguishable(
    db, probe_tables
):
    """The split the old dem-only gates could not express."""
    r = rc.raster_coverage(db, _FOREST_WKT, "ssot_far")
    assert r["table_present"] is True, "the raster IS installed"
    assert r["covered"] is False, "it just does not reach this forest"
    assert r["tile_count"] == 0


def test_a_missing_boundary_is_not_covered_and_not_an_error(db, probe_tables):
    """A diagnostic should answer "no boundary yet", not blow up."""
    r = rc.raster_coverage(db, None, "ssot_cover")
    assert r["has_boundary"] is False
    assert r["covered"] is False
    assert r["table_present"] is True, "still report what we do know"
    assert r["tile_count"] == 0


def test_known_layers_matches_the_catalog():
    assert set(rc.known_layers()) == set(TileService.RASTER_TABLES)


# --------------------------------------------------------------------------
# Over the wire
# --------------------------------------------------------------------------


@pytest.fixture()
def calc(client, db):
    email = f"rs04-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "TestPass123!", "full_name": "RS04"},
    )
    r = client.post(
        "/api/auth/login", json={"email": email, "password": "TestPass123!"}
    )
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    user = db.query(User).filter(User.email == email).first()

    row = Calculation(
        id=str(uuid.uuid4()),
        user_id=user.id,
        uploaded_filename="rs04.csv",
        is_draft=False,
        structure_locked=False,
        result_data={},
    )
    db.add(row)
    db.flush()
    row.boundary_geom = from_shape(_FOREST, srid=4326)
    db.commit()
    return headers, row


def test_the_endpoint_answers_for_a_covered_layer(client, db, calc, probe_tables):
    headers, row = calc
    r = client.get(
        f"/api/v1/calculations/{row.id}/raster-coverage/ssot_cover", headers=headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["covered"] is True
    assert r.json()["tile_count"] == 3


def test_the_endpoint_answers_for_an_absent_layer(client, db, calc, probe_tables):
    headers, row = calc
    r = client.get(
        f"/api/v1/calculations/{row.id}/raster-coverage/ssot_absent", headers=headers
    )
    assert r.status_code == 200, "an absent raster is an answer, not an error"
    assert r.json()["table_present"] is False
    assert r.json()["covered"] is False


def test_an_unknown_layer_is_a_bilingual_404(client, db, calc, probe_tables):
    headers, row = calc
    r = client.get(
        f"/api/v1/calculations/{row.id}/raster-coverage/not-a-real-layer",
        headers=headers,
    )
    assert r.status_code == 404
    detail = r.json()["detail"]
    assert detail["code"] == "rasters.unknown_layer"
    assert detail["layer"] == "not-a-real-layer"
    assert detail["message"] and detail["message_np"]
    assert "not-a-real-layer" in detail["message"]


def test_the_probe_requires_ownership(client, db, calc, probe_tables):
    """Same rule as every other calculation-scoped read (H2.4)."""
    _headers, row = calc
    email = f"rs04-other-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "TestPass123!", "full_name": "Other"},
    )
    login = client.post(
        "/api/auth/login", json={"email": email, "password": "TestPass123!"}
    )
    other = {"Authorization": f"Bearer {login.json()['access_token']}"}

    r = client.get(
        f"/api/v1/calculations/{row.id}/raster-coverage/ssot_cover", headers=other
    )
    assert r.status_code in (403, 404)
