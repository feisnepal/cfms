"""Auto-Block, canopy source (SLOPE_COMPARTMENT_AND_STRATIFIED_SAMPLING_PLAN
follow-on). Carve compartments along canopy-height structure breaks
(canopy_height5m.tif, binned 1-4 = non-forest/regeneration/pole/tree, the
same classification already used by `analysis.py::_canopy_from_rasterio`) —
same preview/commit engine as `test_auto_block_slope.py`, only the
piece-fetch source differs (a flat file, not a DB raster).

Uses a synthetic GeoTIFF written by the fixture itself (`CANOPY_TIF_PATH`
monkeypatched to it) rather than the real multi-GB Nepal-wide file: 20x20
grid, left half value 1 (class 1, non-forest), right half value 10 (class 3,
pole), plus one isolated value-3 (class 2, regeneration) sliver cell —
mirrors test_auto_block_slope.py's slope_raster fixture shape.
"""

from __future__ import annotations

import re
import uuid

import numpy as np
import pytest
import rasterio
from geoalchemy2.shape import from_shape, to_shape
from rasterio.crs import CRS
from rasterio.transform import from_origin
from shapely.geometry import Polygon, mapping, shape
from sqlalchemy import text

# EPSG:4326 as a WKT string — CRS.from_epsg(4326)/crs="EPSG:4326" hits
# proj.db (this machine's PostgreSQL 18 proj.db is an incompatible layout
# version, a known environment quirk — see soil_erosion.py's _WGS84_WKT for
# the same workaround); CRS.from_wkt does not need the database.
_WGS84_WKT = (
    'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
    'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]'
)

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.user import User, UserRole
from app.services import auto_block_service as svc
from app.services.canopy_vectorize import canopy_class_pieces

_BBOX = Polygon([(84.0, 27.0), (84.002, 27.0), (84.002, 27.002), (84.0, 27.002)])

# 20x20 grid: cols 0..9 -> 1 (class 1, non-forest), cols 10..19 -> 10
# (class 3, pole), one isolated value-3 (class 2, regen) sliver cell.
_GRID = np.zeros((20, 20), dtype="uint8")
_GRID[:, :10] = 1
_GRID[:, 10:] = 10
_GRID[4, 4] = 3


@pytest.fixture()
def canopy_tif(tmp_path, monkeypatch):
    path = tmp_path / "synthetic_canopy.tif"
    transform = from_origin(84.0, 27.002, 0.0001, 0.0001)
    with rasterio.open(
        path, "w", driver="GTiff", height=20, width=20, count=1,
        dtype="uint8", crs=CRS.from_wkt(_WGS84_WKT), transform=transform, nodata=0,
    ) as dst:
        dst.write(_GRID, 1)
    monkeypatch.setattr("app.services.analysis.CANOPY_TIF_PATH", str(path))
    yield path


# Grid WITH a wide no-data strip (cols 8-13 = 0, ~1.5 ha) — the "river"
# crossing the forest: cols 0-7 -> 1 (non-forest), strip -> 0 (no-data),
# cols 14-19 -> 10 (pole). Above the 1 ha default, so it must be carved as
# its own class-0 "no-data" piece, not absorbed into either neighbour.
_GRID_WITH_NODATA = np.zeros((20, 20), dtype="uint8")
_GRID_WITH_NODATA[:, :8] = 1
_GRID_WITH_NODATA[:, 14:] = 10


@pytest.fixture()
def canopy_tif_nodata(tmp_path, monkeypatch):
    path = tmp_path / "synthetic_canopy_nodata.tif"
    transform = from_origin(84.0, 27.002, 0.0001, 0.0001)
    with rasterio.open(
        path, "w", driver="GTiff", height=20, width=20, count=1,
        dtype="uint8", crs=CRS.from_wkt(_WGS84_WKT), transform=transform, nodata=0,
    ) as dst:
        dst.write(_GRID_WITH_NODATA, 1)
    monkeypatch.setattr("app.services.analysis.CANOPY_TIF_PATH", str(path))
    yield path


def _make_user(db):
    user = User(
        email=f"canopyblk{uuid.uuid4().hex[:8]}@test.com",
        full_name="Canopy Block Tester",
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
        uploaded_filename="canopy-block-test.csv",
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
        svc.preview_canopy_blocks(db, calc, level="blocks")


def test_preview_missing_tif_raises_no_canopy_coverage(db, monkeypatch):
    monkeypatch.setattr(
        "app.services.analysis.CANOPY_TIF_PATH", r"D:\does-not-exist.tif"
    )
    calc = _make_calc(db)
    with pytest.raises(ValueError, match="no_canopy_coverage"):
        svc.preview_canopy_blocks(db, calc, level="blocks")
    assert db.execute(text("SELECT 1")).scalar() == 1


def test_class_pieces_respects_a_scope_instead_of_the_whole_boundary(db, canopy_tif):
    """RS-1.8: the scope is the raster WINDOW, not just a later Python clip.

    Squeezing the right half of the TIF (values 10 m -> class 3 "pole") must
    return only class-3 pieces, all inside that half. A scope applied only
    after vectorizing the whole TIF would still hand back the left half's
    class-1 "non-forest" piece, so this fails against the unscoped read.
    """
    calc = _make_calc(db)
    right = Polygon(
        [(84.0010, 27.0), (84.002, 27.0), (84.002, 27.002), (84.0010, 27.002)]
    )
    pieces = canopy_class_pieces(calc, db, scope_geojson=mapping(right))

    assert pieces, "the scoped half returned nothing"
    assert {cls for cls, _ in pieces} == {3}
    for _cls, geom in pieces:
        assert geom.difference(right).area == pytest.approx(0.0, abs=1e-12)


def test_preview_carves_along_canopy_class_and_drops_sliver(db, canopy_tif):
    calc = _make_calc(db)
    res = svc.preview_canopy_blocks(db, calc, level="blocks")
    m = res["meta"]
    feats = res["pieces"]["features"]

    assert m["source_layer"] == "canopy_height5m.tif"
    assert m["level"] == "blocks"
    assert len(feats) == 2
    assert abs(m["pieces_ha"] - m["boundary_ha"]) < 0.05
    assert all(f["properties"]["name"].startswith("B") for f in feats)
    classes = {f["properties"]["canopy_class"] for f in feats}
    assert classes == {1, 3}
    labels = {f["properties"]["canopy_class_label"] for f in feats}
    assert labels == {"non-forest", "pole"}


def test_preview_compartments_level_naming(db, canopy_tif):
    calc = _make_calc(db)
    res = svc.preview_canopy_blocks(db, calc, level="compartments")
    feats = res["pieces"]["features"]
    # A compartment is named C1, C2, C3 - never C-1 or Compartment-1.
    names = [f["properties"]["name"] for f in feats]
    assert names and len(set(names)) == len(names)
    assert all(re.fullmatch(r"C\d+", n) for n in names), names
    assert all(f["properties"]["block_name"] == f["properties"]["name"] for f in feats)
    assert res["meta"]["level"] == "compartments"


def test_preview_desired_n_merges_across_classes(db, canopy_tif):
    calc = _make_calc(db)
    res = svc.preview_canopy_blocks(db, calc, level="blocks", desired_n=1)
    assert res["meta"]["piece_count"] == 1
    assert abs(res["meta"]["pieces_ha"] - res["meta"]["boundary_ha"]) < 0.05


def test_preview_all_pieces_single_part(db, canopy_tif):
    calc = _make_calc(db)
    res = svc.preview_canopy_blocks(db, calc, level="blocks")
    for f in res["pieces"]["features"]:
        g = shape(f["geometry"])
        assert g.geom_type == "Polygon", f"expected single-part Polygon, got {g.geom_type}"


def _labels_of(feats):
    return {f["properties"]["canopy_class_label"] for f in feats}


def test_preview_carves_large_nodata_patch_as_own_piece(db, canopy_tif_nodata):
    """A no-data strip (river) at/above the 1 ha threshold becomes its own
    class-0 "no-data" block — it is NOT absorbed into a neighbouring forest
    block, and the full boundary is still tiled."""
    calc = _make_calc(db)
    res = svc.preview_canopy_blocks(db, calc, level="blocks")
    feats = res["pieces"]["features"]

    assert res["meta"]["nodata_min_m2"] == 10000.0
    assert res["meta"]["nodata_seed_pieces"] == 1
    classes = {f["properties"]["canopy_class"] for f in feats}
    assert classes == {1, 3, None}
    assert _labels_of(feats) == {"non-forest", "pole", "no-data"}
    assert abs(res["meta"]["pieces_ha"] - res["meta"]["boundary_ha"]) < 0.05


def test_preview_absorbs_nodata_patch_below_threshold(db, canopy_tif_nodata):
    """Raise the threshold above the strip: the same no-data area must NOT
    become its own piece — the coverage-gap absorb folds it into a
    neighbouring forest block and the boundary is still tiled."""
    calc = _make_calc(db)
    res = svc.preview_canopy_blocks(db, calc, level="blocks", nodata_min_m2=1e9)
    feats = res["pieces"]["features"]

    assert res["meta"]["nodata_seed_pieces"] == 0
    classes = {f["properties"]["canopy_class"] for f in feats}
    assert classes == {1, 3}
    assert "no-data" not in _labels_of(feats)
    assert abs(res["meta"]["pieces_ha"] - res["meta"]["boundary_ha"]) < 0.05


def test_commit_persists_nodata_block_with_null_class(db, canopy_tif_nodata):
    calc = _make_calc(db)
    res = svc.preview_canopy_blocks(db, calc, level="blocks")
    payload = [
        {
            "index": f["properties"]["index"],
            "name": f["properties"]["name"],
            "block_name": f["properties"]["block_name"],
            "natural_name": f["properties"]["natural_name"],
            "dominant_canopy_class": f["properties"]["canopy_class"],
            "geometry": f["geometry"],
        }
        for f in res["pieces"]["features"]
    ]
    created = svc.commit_blocks(db, calc, payload, level="blocks")
    assert len(created) == 3
    rows = db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).all()
    assert {r.dominant_canopy_class for r in rows} == {1, 3, None}


def test_commit_after_canopy_preview_persists_dominant_canopy_class(db, canopy_tif):
    calc = _make_calc(db)
    res = svc.preview_canopy_blocks(db, calc, level="blocks")
    payload = [
        {
            "index": f["properties"]["index"],
            "name": f["properties"]["name"],
            "block_name": f["properties"]["block_name"],
            "natural_name": f["properties"]["natural_name"],
            "dominant_canopy_class": f["properties"]["canopy_class"],
            "geometry": f["geometry"],
        }
        for f in res["pieces"]["features"]
    ]
    created = svc.commit_blocks(db, calc, payload, level="blocks")
    assert len(created) == 2
    assert {c["dominant_canopy_class"] for c in created} == {1, 3}
    rows = db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id).all()
    assert {r.dominant_canopy_class for r in rows} == {1, 3}
    assert all(r.dominant_slope_band is None for r in rows)
    assert all(r.dominant_aspect is None for r in rows)
    assert all(to_shape(r.geometry).geom_type == "Polygon" for r in rows)


# ---------------------------------------------------------------------------
# API wiring
# ---------------------------------------------------------------------------
def _owner(client, db):
    email = f"canopyapi-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "TestPass123!", "full_name": "Canopy API"},
    )
    r = client.post(
        "/api/auth/login", json={"email": email, "password": "TestPass123!"}
    )
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return headers, db.query(User).filter(User.email == email).first()


def test_api_preview_source_canopy(client, db, canopy_tif):
    headers, user = _owner(client, db)
    calc = _make_calc(db)
    calc.user_id = user.id
    db.commit()

    resp = client.post(
        f"/api/v1/calculations/{calc.id}/auto-blocks/preview",
        headers=headers,
        json={"level": "blocks", "source": "canopy"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["meta"]["source_layer"] == "canopy_height5m.tif"
    assert len(body["pieces"]["features"]) == 2


def test_api_preview_canopy_nodata_threshold_routes_through(client, db, canopy_tif_nodata):
    headers, user = _owner(client, db)
    calc = _make_calc(db)
    calc.user_id = user.id
    db.commit()

    default = client.post(
        f"/api/v1/calculations/{calc.id}/auto-blocks/preview",
        headers=headers,
        json={"level": "blocks", "source": "canopy"},
    ).json()
    classes = {f["properties"]["canopy_class"] for f in default["pieces"]["features"]}
    assert classes == {1, 3, None}
    assert default["meta"]["nodata_min_m2"] == 10000.0

    absorbed = client.post(
        f"/api/v1/calculations/{calc.id}/auto-blocks/preview",
        headers=headers,
        json={"level": "blocks", "source": "canopy", "nodata_min_m2": 1e9},
    ).json()
    classes = {f["properties"]["canopy_class"] for f in absorbed["pieces"]["features"]}
    assert classes == {1, 3}


def test_compartment_tree_surfaces_dominant_canopy_class_after_commit(client, db, canopy_tif):
    headers, user = _owner(client, db)
    calc = _make_calc(db)
    calc.user_id = user.id
    db.commit()

    preview = client.post(
        f"/api/v1/calculations/{calc.id}/auto-blocks/preview",
        headers=headers,
        json={"level": "compartments", "source": "canopy"},
    ).json()
    blocks = [
        {
            "index": f["properties"]["index"],
            "name": f["properties"]["name"],
            "block_name": f["properties"]["block_name"],
            "natural_name": f["properties"]["natural_name"],
            "dominant_canopy_class": f["properties"]["canopy_class"],
            "geometry": f["geometry"],
        }
        for f in preview["pieces"]["features"]
    ]
    commit = client.post(
        f"/api/v1/calculations/{calc.id}/auto-blocks/commit",
        headers=headers,
        json={"level": "compartments", "blocks": blocks, "source": "canopy"},
    )
    assert commit.status_code == 200, commit.text

    # RS-2.16 (P2.5): a commit only creates a TRIAL layer now -- promote it
    # before a builtin-layer read (compartment-tree) will surface it.
    layers = client.get(
        f"/api/v1/calculations/{calc.id}/auto-block-layers", headers=headers,
    ).json()["layers"]
    layer_id = next(l["id"] for l in layers if l["source"] == "canopy")
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
    assert {n["dominant_canopy_class"] for n in nodes} == {1, 3}
