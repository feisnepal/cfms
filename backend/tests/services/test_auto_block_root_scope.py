"""FS-4a.6 root variant: the whole-forest Auto-create now resolves its shell
from the virtual root -- ``forest_area_geom`` (boundary minus private land, D8)
-- instead of the raw boundary, and skips the boundary-tiled coverage remainder
when that shell is smaller (the scope-aware invariant is FS-3.1's own work).

The slope source is used (same synthetic raster as ``test_auto_block_slope``: a
20x20 grid, cols 1..10 band 1, cols 11..20 band 3) so the mechanism is covered
for the raster sources too; the clip seam is shared by every source.
"""

from __future__ import annotations

import uuid

import pytest
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import Polygon, mapping, shape
from shapely.ops import unary_union
from sqlalchemy import text

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.user import User, UserRole
from app.services import auto_block_service as svc

_GRID = [[3 if c >= 11 else 1 for c in range(1, 21)] for _r in range(1, 21)]
_ARR = (
    "ARRAY["
    + ",".join("ARRAY[" + ",".join(str(v) for v in row) + "]" for row in _GRID)
    + "]::double precision[][]"
)
_BBOX = Polygon([(84.0, 27.0), (84.002, 27.0), (84.002, 27.002), (84.0, 27.002)])
# A private-land spine down the middle: band 1 and band 3 both still exist on
# either side of it, so the carve keeps both pieces.
_PRIVATE = Polygon(
    [(84.001, 27.0), (84.0015, 27.0), (84.0015, 27.002), (84.001, 27.002)]
)
_FOREST_AREA = _BBOX.difference(_PRIVATE)


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


def _owner(client, db):
    email = f"roots-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "TestPass123!", "full_name": "Root Scope"},
    )
    r = client.post(
        "/api/auth/login", json={"email": email, "password": "TestPass123!"}
    )
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return headers, db.query(User).filter(User.email == email).first()


def _calc(db, user=None, result_data=None):
    if user is None:
        user = User(
            email=f"rootsvc{uuid.uuid4().hex[:8]}@test.com",
            full_name="Root Scope Service Tester",
            role=UserRole.USER,
            hashed_password="not-a-real-hash",
        )
        db.add(user)
        db.flush()
    calc = Calculation(
        id=str(uuid.uuid4()),
        user_id=user.id,
        uploaded_filename="root-scope.csv",
        is_draft=False,
        result_data=result_data or {},
    )
    db.add(calc)
    db.flush()
    calc.boundary_geom = from_shape(_BBOX, srid=4326)
    db.commit()
    return calc


def _rows(db, calc):
    return (
        db.query(ForestBlock)
        .filter(ForestBlock.calculation_id == calc.id)
        .all()
    )


# ---------------------------------------------------------------------------
# resolve_root_scope
# ---------------------------------------------------------------------------
def test_resolve_root_scope_is_the_boundary_when_clean(db):
    calc = _calc(db)
    scope, excluded = svc.resolve_root_scope(db, calc)
    assert excluded is False
    assert scope.difference(_BBOX).area < 1e-12
    assert _BBOX.difference(scope).area < 1e-12


def test_resolve_root_scope_punches_private_land(db):
    calc = _calc(
        db,
        result_data={
            "sub_areas": [{"category": "private_land", "geometry": mapping(_PRIVATE)}]
        },
    )
    scope, excluded = svc.resolve_root_scope(db, calc)
    assert excluded is True
    assert scope.area < _BBOX.area
    assert scope.intersection(_PRIVATE).area < 1e-12
    assert abs(scope.area - _FOREST_AREA.area) < 1e-9


def test_resolve_root_scope_no_boundary_raises(db):
    user = User(
        email=f"nobnd{uuid.uuid4().hex[:8]}@test.com",
        full_name="No Boundary",
        role=UserRole.USER,
        hashed_password="not-a-real-hash",
    )
    db.add(user)
    db.flush()
    calc = Calculation(
        id=str(uuid.uuid4()),
        user_id=user.id,
        uploaded_filename="noboundary.csv",
        is_draft=False,
    )
    db.add(calc)
    db.commit()
    with pytest.raises(ValueError, match="no_boundary"):
        svc.resolve_root_scope(db, calc)


# ---------------------------------------------------------------------------
# endpoint preview: pieces stay inside the shell, boundary_ha is the shell
# ---------------------------------------------------------------------------
def test_root_preview_keeps_pieces_off_private_land(client, db, slope_raster):
    headers, user = _owner(client, db)
    calc = _calc(
        db,
        user,
        result_data={
            "sub_areas": [{"category": "private_land", "geometry": mapping(_PRIVATE)}]
        },
    )

    r = client.post(
        f"/api/v1/calculations/{calc.id}/auto-blocks/preview",
        headers=headers,
        json={"level": "blocks", "source": "slope"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    feats = body["pieces"]["features"]
    assert len(feats) == 2  # band 1 and band 3 both survive either side of the spine
    shell = shape(_FOREST_AREA)
    for f in feats:
        g = Polygon(f["geometry"]["coordinates"][0])
        assert g.difference(shell.buffer(1e-9)).area < 1e-12
        assert g.intersection(_PRIVATE).area < 1e-12
    assert body["meta"]["boundary_ha"] < svc._area_m2(_BBOX) / 10000.0
    # the carve covers the whole shell -- no gap and nothing on private land
    total = unary_union([shape(f["geometry"]) for f in feats])
    assert abs(total.area - shell.area) < 1e-9


def test_root_commit_keeps_blocks_off_private_land_and_skips_the_remainder(
    client, db, slope_raster
):
    headers, user = _owner(client, db)
    calc = _calc(
        db,
        user,
        result_data={
            "sub_areas": [{"category": "private_land", "geometry": mapping(_PRIVATE)}]
        },
    )

    prev = client.post(
        f"/api/v1/calculations/{calc.id}/auto-blocks/preview",
        headers=headers,
        json={"level": "blocks", "source": "slope"},
    ).json()
    blocks = [
        {"index": f["properties"]["index"], "geometry": f["geometry"]}
        for f in prev["pieces"]["features"]
    ]
    done = client.post(
        f"/api/v1/calculations/{calc.id}/auto-blocks/commit",
        headers=headers,
        json={"level": "blocks", "blocks": blocks},
    )
    assert done.status_code == 200, done.text
    body = done.json()
    # FS-4a.6: excluded -> the boundary-tiled remainder is NOT minted over private land
    assert body["invariant"]["remainder_added"] is False
    rows = _rows(db, calc)
    assert len(rows) == 2
    for row in rows:
        g = to_shape(row.geometry)
        assert g.intersection(_PRIVATE).area < 1e-9
        assert g.difference(_FOREST_AREA.buffer(1e-9)).area < 1e-12
    union = unary_union([to_shape(r.geometry) for r in rows])
    assert abs(union.area - _FOREST_AREA.area) < 1e-6
    # no block was minted where private land is
    vacant = _FOREST_AREA.difference(union)
    assert vacant.area < 1e-6