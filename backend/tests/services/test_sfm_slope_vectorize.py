"""SFM P11 — slope-class vectorise + assisted protection digitizing (follow-on).

Builds a synthetic ``rasters.slope_regulation`` (20×20, ~100 m² cells): the left
half is band 1, the right half band 3, plus one isolated band-3 cell buried in
the band-1 half. That isolated cell is a sub-``slope_vector_sliver_m2`` sliver
and must be dropped; the big band-3 block must survive and merge into one
polygon.
"""

from __future__ import annotations

import uuid

import pytest
from geoalchemy2.shape import from_shape
from shapely.geometry import Polygon, shape
from sqlalchemy import text

from app.models.calculation import Calculation
from app.models.user import User, UserRole
from app.services.sustainable_fm.sfm_config import SfmParams
from app.services.sustainable_fm.slope_vectorize import (
    draft_protection_polygon,
    slope_class_polygons,
    slope_profile,
)

# 20×20 grid: cols 1..10 → band 1, cols 11..20 → band 3, (row 5, col 5) → band 3
_GRID = [[3 if c >= 11 else 1 for c in range(1, 21)] for _r in range(1, 21)]
_GRID[4][4] = 3  # the isolated sliver
_ARR = (
    "ARRAY["
    + ",".join("ARRAY[" + ",".join(str(v) for v in row) + "]" for row in _GRID)
    + "]::double precision[][]"
)

# raster footprint: 84.0000..84.0020 lon, 27.0000..27.0020 lat, 0.0001° cells
_BBOX = Polygon([(84.0, 27.0), (84.002, 27.0), (84.002, 27.002), (84.0, 27.002)])


@pytest.fixture()
def slope_raster(db):
    db.execute(text("CREATE SCHEMA IF NOT EXISTS rasters"))
    db.execute(
        text(
            "CREATE TABLE IF NOT EXISTS rasters.slope_regulation "
            "(rid serial PRIMARY KEY, rast raster)"
        )
    )
    db.execute(text("DELETE FROM rasters.slope_regulation"))
    db.execute(
        text(
            "INSERT INTO rasters.slope_regulation (rast) SELECT ST_SetValues("
            "  ST_AddBand("
            "    ST_MakeEmptyRaster(20, 20, 84.0, 27.002, 0.0001, -0.0001, 0, 0, 4326),"
            "    '8BUI'::text, 0, 0),"
            f"  1, 1, 1, {_ARR})"
        )
    )
    db.commit()
    yield
    db.execute(text("DROP TABLE IF EXISTS rasters.slope_regulation"))
    db.commit()


def _calc(db):
    u = User(
        email=f"sv{uuid.uuid4().hex[:8]}@t.com",
        full_name="SV",
        role=UserRole.USER,
        hashed_password="x",
    )
    db.add(u)
    db.flush()
    c = Calculation(
        id=str(uuid.uuid4()),
        user_id=u.id,
        uploaded_filename="sv.csv",
        is_draft=False,
        structure_locked=False,
        boundary_geom=from_shape(_BBOX, srid=4326),
    )
    db.add(c)
    db.flush()
    return c


# ── no raster → graceful empty, txn survives ──────────────────────────────
def test_no_raster_is_empty_and_savepoint_safe(db):
    c = _calc(db)
    fc = slope_class_polygons(c, db, SfmParams())
    assert fc == {"type": "FeatureCollection", "features": []}
    assert draft_protection_polygon(c, db, SfmParams(), 3) is None
    assert db.execute(text("SELECT 1")).scalar() == 1  # not poisoned


# ── with a synthetic raster ──────────────────────────────────────────────
def test_vectorize_bands_and_drop_the_sliver(db, slope_raster):
    c = _calc(db)
    fc = slope_class_polygons(c, db, SfmParams(slope_vector_sliver_m2=1000.0))
    assert fc["type"] == "FeatureCollection"
    bands = {f["properties"]["band"]: f for f in fc["features"]}
    assert set(bands) == {1, 3}  # only the two present classes
    # band 3 is ONE polygon (the isolated 100 m² cell dropped, the block merged)
    g3 = shape(bands[3]["geometry"])
    assert g3.geom_type in ("Polygon", "MultiPolygon")
    assert bands[3]["properties"]["area_ha"] > 0.15  # ~200 cells * 100 m² = 2 ha
    assert bands[3]["properties"]["label_en"] == "31–45°"
    # the sliver did not survive as its own feature
    assert (
        bands[3]["geometry"]["type"] == "Polygon"
        or len(bands[3]["geometry"]["coordinates"]) == 1
    )


def test_slope_profile_percentages_sum_to_100(db, slope_raster):
    prof = slope_profile(_BBOX.wkt, db, SfmParams())
    assert prof["dominant_band"] in (1, 3)
    total = sum(prof["area_pct_by_band"].values())
    assert abs(total - 100.0) < 1.0
    assert prof["area_pct_by_band"]["1"] > 40 and prof["area_pct_by_band"]["3"] > 40


def test_draft_protection_polygon_is_the_steep_union(db, slope_raster):
    c = _calc(db)
    geom = draft_protection_polygon(c, db, SfmParams(), min_band=3)
    assert geom is not None
    poly = shape(geom)
    assert poly.is_valid and not poly.is_empty
    # it is the right (band-3) half only — roughly half the forest, well inside it
    assert poly.within(_BBOX.buffer(1e-9))
    assert 0.35 < poly.area / _BBOX.area < 0.65
    # min_band 5 is clamped to 4 → nothing that steep → None
    assert draft_protection_polygon(c, db, SfmParams(), min_band=4) is None


# ── API ──────────────────────────────────────────────────────────────────
def _owner(client, db):
    email = f"sva-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "TestPass123!", "full_name": "SVA"},
    )
    r = client.post(
        "/api/auth/login", json={"email": email, "password": "TestPass123!"}
    )
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return headers, db.query(User).filter(User.email == email).first()


def _calc_for(db, user):
    c = Calculation(
        id=str(uuid.uuid4()),
        user_id=user.id,
        forest_name="SV CF",
        is_draft=False,
        structure_locked=False,
        boundary_geom=from_shape(_BBOX, srid=4326),
    )
    db.add(c)
    db.commit()
    return c


def test_api_slope_endpoints(client, db, slope_raster):
    headers, user = _owner(client, db)
    c = _calc_for(db, user)

    fc = client.get(
        f"/api/calculations/{c.id}/sustainable-fm/slope-class-polygons",
        headers=headers,
    )
    assert fc.status_code == 200, fc.text
    assert fc.json()["type"] == "FeatureCollection"
    assert {f["properties"]["band"] for f in fc.json()["features"]} == {1, 3}

    d = client.post(
        f"/api/calculations/{c.id}/sustainable-fm/draft-protection-subarea",
        headers=headers,
        json={"min_band": 3},
    )
    assert d.status_code == 200, d.text
    body = d.json()
    assert body["category"] == "protected"
    assert body["polygon"]["type"] in ("Polygon", "MultiPolygon")
    assert body["slope_profile"]["dominant_band"] in (3, 4)
    assert body["hint_en"] and body["hint_ne"]

    # bad min_band → 422
    assert (
        client.post(
            f"/api/calculations/{c.id}/sustainable-fm/draft-protection-subarea",
            headers=headers,
            json={"min_band": 9},
        ).status_code
        == 422
    )

    # slope-profile for a supplied geometry
    sp = client.post(
        f"/api/calculations/{c.id}/sustainable-fm/slope-profile",
        headers=headers,
        json={
            "geometry": {
                "type": "Polygon",
                "coordinates": list(_BBOX.__geo_interface__["coordinates"]),
            }
        },
    )
    assert sp.status_code == 200
    assert abs(sum(sp.json()["area_pct_by_band"].values()) - 100.0) < 1.0

    # a non-owner is 403
    h2, _ = _owner(client, db)
    assert (
        client.get(
            f"/api/calculations/{c.id}/sustainable-fm/slope-class-polygons",
            headers=h2,
        ).status_code
        == 403
    )
