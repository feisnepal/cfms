"""Auto-Block, aspect source (SLOPE_COMPARTMENT_AND_STRATIFIED_SAMPLING_PLAN
follow-on). Carve compartments along compass-direction breaks
(rasters.aspect, 1-8 = N/NE/E/SE/S/SW/W/NW) — same preview/commit engine as
`test_auto_block_slope.py` / `test_auto_block_mmu.py`, only the piece-fetch
source differs.

Raster fixture mirrors `test_auto_block_slope.py::slope_raster`: a 20x20
grid, left half aspect code 1 (N), right half aspect code 5 (S), plus one
isolated sliver cell (must be dropped).
"""

from __future__ import annotations

import re
import uuid

import pytest
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import Polygon, shape
from sqlalchemy import text

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.user import User, UserRole
from app.services import auto_block_service as svc

# 20x20 grid: cols 1..10 -> code 1 (N), cols 11..20 -> code 5 (S), one
# isolated code-5 sliver cell buried in the N half.
_GRID = [[5 if c >= 11 else 1 for c in range(1, 21)] for _r in range(1, 21)]
_GRID[4][4] = 5
_ARR = (
    "ARRAY["
    + ",".join("ARRAY[" + ",".join(str(v) for v in row) + "]" for row in _GRID)
    + "]::double precision[][]"
)

_BBOX = Polygon([(84.0, 27.0), (84.002, 27.0), (84.002, 27.002), (84.0, 27.002)])


@pytest.fixture()
def aspect_raster(db):
    db.execute(text("CREATE SCHEMA IF NOT EXISTS rasters"))
    db.execute(
        text(
            "CREATE TABLE IF NOT EXISTS rasters.aspect "
            "(rid serial PRIMARY KEY, rast raster)"
        )
    )
    db.execute(text("DELETE FROM rasters.aspect"))
    db.execute(
        text(
            "INSERT INTO rasters.aspect (rast) SELECT ST_SetValues("
            "  ST_AddBand("
            "    ST_MakeEmptyRaster(20, 20, 84.0, 27.002, 0.0001, -0.0001, 0, 0, 4326),"
            "    '8BUI'::text, 0, 0),"
            f"  1, 1, 1, {_ARR})"
        )
    )
    db.commit()
    yield
    db.execute(text("DROP TABLE IF EXISTS rasters.aspect"))
    db.commit()


def _make_user(db):
    user = User(
        email=f"aspectblk{uuid.uuid4().hex[:8]}@test.com",
        full_name="Aspect Block Tester",
        role=UserRole.USER,
        hashed_password="not-a-real-hash",
    )
    db.add(user)
    db.flush()
    return user


def _make_calc(db, boundary=_BBOX):
    user = _make_user(db)
    calc = Calculation(
        id=str(uuid.uuid4()),
        user_id=user.id,
        uploaded_filename="aspect-block-test.csv",
        is_draft=False,
        structure_locked=False,
    )
    db.add(calc)
    db.flush()
    if boundary is not None:
        calc.boundary_geom = from_shape(boundary, srid=4326)
        db.flush()
    return calc


def test_preview_no_boundary_raises(db):
    calc = _make_calc(db, boundary=None)
    with pytest.raises(ValueError, match="no_boundary"):
        svc.preview_aspect_blocks(db, calc, level="blocks")


def test_preview_no_raster_raises_no_aspect_coverage(db):
    calc = _make_calc(db)
    with pytest.raises(ValueError, match="no_aspect_coverage"):
        svc.preview_aspect_blocks(db, calc, level="blocks")
    assert db.execute(text("SELECT 1")).scalar() == 1


def test_preview_carves_along_aspect_and_drops_sliver(db, aspect_raster):
    calc = _make_calc(db)
    res = svc.preview_aspect_blocks(db, calc, level="blocks")
    m = res["meta"]
    feats = res["pieces"]["features"]

    assert m["source_layer"] == "rasters.aspect"
    assert m["level"] == "blocks"
    assert len(feats) == 2
    assert abs(m["pieces_ha"] - m["boundary_ha"]) < 0.05
    assert all(f["properties"]["name"].startswith("B") for f in feats)
    codes = {f["properties"]["aspect_code"] for f in feats}
    assert codes == {1, 5}
    labels = {f["properties"]["aspect_label"] for f in feats}
    assert labels == {"N", "S"}


def test_preview_compartments_level_naming(db, aspect_raster):
    calc = _make_calc(db)
    res = svc.preview_aspect_blocks(db, calc, level="compartments")
    feats = res["pieces"]["features"]
    # A compartment is named C1, C2, C3 - never C-1 or Compartment-1.
    names = [f["properties"]["name"] for f in feats]
    assert names and len(set(names)) == len(names)
    assert all(re.fullmatch(r"C\d+", n) for n in names), names
    assert all(f["properties"]["block_name"] == f["properties"]["name"] for f in feats)
    assert res["meta"]["level"] == "compartments"


def test_preview_desired_n_merges_across_directions(db, aspect_raster):
    calc = _make_calc(db)
    res = svc.preview_aspect_blocks(db, calc, level="blocks", desired_n=1)
    assert res["meta"]["piece_count"] == 1
    assert abs(res["meta"]["pieces_ha"] - res["meta"]["boundary_ha"]) < 0.05


def test_preview_all_pieces_single_part(db, aspect_raster):
    calc = _make_calc(db)
    res = svc.preview_aspect_blocks(db, calc, level="blocks")
    for f in res["pieces"]["features"]:
        g = shape(f["geometry"])
        assert g.geom_type == "Polygon", f"expected single-part Polygon, got {g.geom_type}"


def test_commit_after_aspect_preview_persists_dominant_aspect(db, aspect_raster):
    calc = _make_calc(db)
    res = svc.preview_aspect_blocks(db, calc, level="blocks")
    payload = [
        {
            "index": f["properties"]["index"],
            "name": f["properties"]["name"],
            "block_name": f["properties"]["block_name"],
            "natural_name": f["properties"]["natural_name"],
            "dominant_aspect": f["properties"]["aspect_code"],
            "geometry": f["geometry"],
        }
        for f in res["pieces"]["features"]
    ]
    created = svc.commit_blocks(db, calc, payload, level="blocks")
    assert len(created) == 2
    assert {c["dominant_aspect"] for c in created} == {1, 5}
    rows = db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).all()
    assert {r.dominant_aspect for r in rows} == {1, 5}
    assert all(r.dominant_slope_band is None for r in rows)
    assert all(r.dominant_canopy_class is None for r in rows)
    assert all(to_shape(r.geometry).geom_type == "Polygon" for r in rows)


# ---------------------------------------------------------------------------
# API wiring
# ---------------------------------------------------------------------------
def _owner(client, db):
    email = f"aspectapi-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "TestPass123!", "full_name": "Aspect API"},
    )
    r = client.post(
        "/api/auth/login", json={"email": email, "password": "TestPass123!"}
    )
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return headers, db.query(User).filter(User.email == email).first()


def test_api_preview_source_aspect(client, db, aspect_raster):
    headers, user = _owner(client, db)
    calc = _make_calc(db)
    calc.user_id = user.id
    db.commit()

    resp = client.post(
        f"/api/v1/calculations/{calc.id}/auto-blocks/preview",
        headers=headers,
        json={"level": "blocks", "source": "aspect"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["meta"]["source_layer"] == "rasters.aspect"
    assert len(body["pieces"]["features"]) == 2


def test_compartment_tree_surfaces_dominant_aspect_after_commit(client, db, aspect_raster):
    headers, user = _owner(client, db)
    calc = _make_calc(db)
    calc.user_id = user.id
    db.commit()

    preview = client.post(
        f"/api/v1/calculations/{calc.id}/auto-blocks/preview",
        headers=headers,
        json={"level": "compartments", "source": "aspect"},
    ).json()
    blocks = [
        {
            "index": f["properties"]["index"],
            "name": f["properties"]["name"],
            "block_name": f["properties"]["block_name"],
            "natural_name": f["properties"]["natural_name"],
            "dominant_aspect": f["properties"]["aspect_code"],
            "geometry": f["geometry"],
        }
        for f in preview["pieces"]["features"]
    ]
    commit = client.post(
        f"/api/v1/calculations/{calc.id}/auto-blocks/commit",
        headers=headers,
        json={"level": "compartments", "blocks": blocks, "source": "aspect"},
    )
    assert commit.status_code == 200, commit.text

    # RS-2.16 (P2.5): a commit only creates a TRIAL layer now -- promote it
    # before a builtin-layer read (compartment-tree) will surface it.
    layers = client.get(
        f"/api/v1/calculations/{calc.id}/auto-block-layers", headers=headers,
    ).json()["layers"]
    layer_id = next(l["id"] for l in layers if l["source"] == "aspect")
    promote = client.post(
        f"/api/v1/calculations/{calc.id}/auto-block-layers/{layer_id}/promote",
        headers=headers, json={"as_level": "compartments"},
    )
    assert promote.status_code == 200, promote.text

    tree = client.get(
        f"/api/compartments/calculations/{calc.id}/compartment-tree",
        headers=headers,
    ).json()
    nodes = tree["blocks"]
    assert len(nodes) == 2
    assert {n["dominant_aspect"] for n in nodes} == {1, 5}
