"""U05 — tree-cluster service integration tests.

Seeds a fresh DB calculation + a cluster of trees into the test DB, then
exercises the spatial behaviour (3857 bucketing, capped totals, hasMore, cache)
for real — no mocks on the geometry path.
"""
import uuid

import pytest
from sqlalchemy import text

from app.models.inventory import InventoryCalculation, InventoryTree
from app.models.user import User, UserRole
from app.services.tree_clusters import (
    INDIVIDUAL_CAP,
    TOTAL_CAP,
    ZOOM_INDIVIDUALS,
    _CACHE_LOCK,
    _TILE_CACHE,
    cluster_inventory_trees,
    invalidate_all,
)
from app.services.webmercator import tile_xy

DENSE = 60           # trees packed into one small area (a single cluster cell)
CENT_LNG, CENT_LAT = 85.06, 27.43
LONE_LNG, LONE_LAT = 85.20, 27.43  # far enough from the dense lattice to land in its own cell/tile


@pytest.fixture(autouse=True)
def _clean_cache():
    invalidate_all()
    yield
    invalidate_all()


@pytest.fixture()
def calc(db):
    # The conftest's create_all tolerates the Geography GiST index and can skip
    # inventory_trees entirely. Build it via raw DDL matching the model so the
    # cluster service's spatial SQL runs for real.
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS public.inventory_trees (
            id UUID PRIMARY KEY,
            inventory_calculation_id UUID REFERENCES public.inventory_calculations(id) ON DELETE CASCADE NOT NULL,
            species VARCHAR(255) NOT NULL,
            dia_cm FLOAT NOT NULL,
            height_m FLOAT,
            tree_volume FLOAT,
            block_id UUID,
            block_name VARCHAR(255),
            location geography(POINT, 4326)
        )
    """))
    db.commit()
    cid = uuid.uuid4()
    user = User(
        email=f"cluster{uuid.uuid4().hex[:8]}@test.com",
        full_name="Cluster Tester",
        role=UserRole.USER,
        hashed_password="not-a-real-hash",
    )
    db.add(user)
    db.flush()
    # The service filters `inventory_calculations.calculation_id = :cid`, which
    # is a FK to `calculations.id`. Create a calculation and link it.
    from app.models.calculation import Calculation
    calc_id_core = str(uuid.uuid4())
    db.add(Calculation(
        id=calc_id_core,
        user_id=user.id,
        uploaded_filename="cluster-core.csv",
        is_draft=False,
    ))
    db.flush()
    calc = InventoryCalculation(
        id=cid,
        calculation_id=calc_id_core,
        user_id=user.id,
        uploaded_filename="cluster-test.csv",
        status="processing",
        grid_spacing_meters=20.0,
        total_trees=DENSE,
    )
    db.add(calc)
    db.flush()
    for i in range(DENSE):
        d = (i % 12) * 0.0001  # ~11 m lattice, all within one low-zoom cell
        db.execute(text(
            "INSERT INTO public.inventory_trees "
            "(id, inventory_calculation_id, species, dia_cm, location) "
            "VALUES (:id, :icid, :sp, :dia, :loc)"
        ), {
            "id": str(uuid.uuid4()),
            "icid": str(calc.id),
            "sp": "A",
            "dia": 10.0 + i,
            "loc": f"POINT({CENT_LNG + d} {CENT_LAT + d})",
        })
    # One isolated tree, geographically distinct from the dense lattice — the
    # singleton-cell case (a cell/tile with exactly one tree in it).
    db.execute(text(
        "INSERT INTO public.inventory_trees "
        "(id, inventory_calculation_id, species, dia_cm, height_m, tree_volume, location) "
        "VALUES (:id, :icid, :sp, :dia, :h, :vol, :loc)"
    ), {
        "id": str(uuid.uuid4()),
        "icid": str(calc.id),
        "sp": "Sal",
        "dia": 42.5,
        "h": 18.0,
        "vol": 1.234,
        "loc": f"POINT({LONE_LNG} {LONE_LAT})",
    })
    db.commit()
    return calc_id_core
    return str(cid)


def test_returns_both_keys(db, calc):
    z = 8
    r = cluster_inventory_trees(db, calc, z, *tile_xy(CENT_LNG, CENT_LAT, z))
    assert set(r.keys()) == {"features", "hasMore"}


def test_zoom_below_individuals_groups_into_clusters(db, calc):
    z = 8
    r = cluster_inventory_trees(db, calc, z, *tile_xy(CENT_LNG, CENT_LAT, z))
    assert len(r["features"]) >= 1
    cluster = next(f for f in r["features"])
    assert cluster["geometry"]["type"] == "Point"
    assert cluster["properties"]["point_count"] > 1


def test_zoom_below_individuals_total_response_cap(db, calc):
    r = cluster_inventory_trees(db, calc, 8, *tile_xy(CENT_LNG, CENT_LAT, 8))
    assert len(r["features"]) <= TOTAL_CAP


def test_zoom_at_individuals_is_capped_stream(db, calc):
    z = ZOOM_INDIVIDUALS          # 18
    r = cluster_inventory_trees(db, calc, z, *tile_xy(CENT_LNG, CENT_LAT, z))
    assert len(r["features"]) <= INDIVIDUAL_CAP
    for f in r["features"]:
        assert f["geometry"]["type"] == "Point"


def test_singleton_cell_renders_as_individual_point_not_a_bubble(db, calc):
    # z=12 (< ZOOM_INDIVIDUALS) is still the "clustered" branch, but the lone
    # tree's cell only ever has one tree in it, so it should come back shaped
    # like an individual tree feature (dbh_cm etc.), not a point_count bubble.
    z = 12
    r = cluster_inventory_trees(db, calc, z, *tile_xy(LONE_LNG, LONE_LAT, z))
    lone = [f for f in r["features"] if f["properties"].get("dbh_cm") == 42.5]
    assert len(lone) == 1
    props = lone[0]["properties"]
    assert "point_count" not in props
    assert props["species"] == "Sal"
    assert props["height_m"] == 18.0
    assert props["volume_m3"] == 1.234


def test_cache_hit_no_growth_within_same_tile(db, calc):
    z = 10
    x, y = tile_xy(CENT_LNG, CENT_LAT, z)
    cluster_inventory_trees(db, calc, z, x, y)
    with _CACHE_LOCK:
        before = dict(_TILE_CACHE)
    cluster_inventory_trees(db, calc, z, x, y)
    with _CACHE_LOCK:
        assert list(dict(_TILE_CACHE).keys()) == list(before.keys())


def test_distinct_tiles_distinct_keys(db, calc):
    z = 12
    x1, y1 = tile_xy(CENT_LNG - 0.05, CENT_LAT, z)
    x2, y2 = tile_xy(CENT_LNG + 0.02, CENT_LAT, z)
    cluster_inventory_trees(db, calc, z, x1, y1)
    cluster_inventory_trees(db, calc, z, x2, y2)
    with _CACHE_LOCK:
        tile_keys = {(x, y, z) for (_c, _e, x, y, z) in _TILE_CACHE.keys()}
    assert (x1, y1, z) in tile_keys
    assert (x2, y2, z) in tile_keys


def test_invalidate_all_clears_cache(db, calc):
    cluster_inventory_trees(db, calc, 12, *tile_xy(CENT_LNG, CENT_LAT, 12))
    with _CACHE_LOCK:
        assert len(_TILE_CACHE) >= 1
    invalidate_all()
    with _CACHE_LOCK:
        assert len(_TILE_CACHE) == 0

# ---- Stem Mapping styling: shape group, prime species colour code, density switch ----

def _add_tree(db, calc_id, species, remark, lng, lat, dia=25.0):
    icid = db.execute(
        text("SELECT id FROM inventory_calculations WHERE calculation_id = :c"), {"c": calc_id}
    ).scalar()
    db.execute(text(
        "INSERT INTO public.inventory_trees (id, inventory_calculation_id, species, dia_cm, remark, location) "
        "VALUES (:id, :icid, :sp, :dia, :rm, :loc)"
    ), {"id": str(uuid.uuid4()), "icid": str(icid), "sp": species, "dia": dia, "rm": remark,
        "loc": f"POINT({lng} {lat})"})
    db.commit()


def test_individuals_carry_tree_group_and_prime_species_code(db, calc):
    mx, my = 85.40, 27.60
    _add_tree(db, calc, "Shorea robusta", "Felling Tree", mx, my)
    _add_tree(db, calc, "Albizia lebbeck", "Mother Tree", mx + 0.00005, my)
    _add_tree(db, calc, "Castanopsis indica", None, mx + 0.0001, my)
    z = ZOOM_INDIVIDUALS
    feats = cluster_inventory_trees(db, calc, z, *tile_xy(mx, my, z))["features"]
    by = {f["properties"]["species"]: f["properties"] for f in feats}
    assert (by["Shorea robusta"]["tree_group"], by["Shorea robusta"]["prime_species_code"]) == ("felling", 18)
    assert (by["Albizia lebbeck"]["tree_group"], by["Albizia lebbeck"]["prime_species_code"]) == ("mother", 4)
    assert (by["Castanopsis indica"]["tree_group"], by["Castanopsis indica"]["prime_species_code"]) == ("other", None)
    assert by["Shorea robusta"]["remark"] == "Felling Tree"


def test_lone_tree_in_cluster_branch_also_carries_styling_keys(db, calc):
    z = 12
    r = cluster_inventory_trees(db, calc, z, *tile_xy(LONE_LNG, LONE_LAT, z))
    props = next(f["properties"] for f in r["features"] if f["properties"].get("dbh_cm") == 42.5)
    assert {"tree_group", "prime_species_code", "remark"} <= set(props)


def _tile_centre(z, lng, lat):
    from app.services.webmercator import bbox_for_tile
    x, y = tile_xy(lng, lat, z)
    w, so, e, n = bbox_for_tile(x, y, z)
    return x, y, (w + e) / 2, (so + n) / 2


def test_density_switch_small_tile_is_individuals_two_zooms_early(db, calc):
    from app.services.tree_clusters import DENSITY_MIN_ZOOM
    z = DENSITY_MIN_ZOOM                       # 16: below ZOOM_INDIVIDUALS, but the tile is small
    x, y, cx, cy = _tile_centre(z, 85.40, 27.60)
    for k in range(5):
        _add_tree(db, calc, "Shorea robusta", "Felling Tree", cx + k * 0.00003, cy)
    feats = cluster_inventory_trees(db, calc, z, x, y)["features"]
    assert len(feats) == 5
    assert all("point_count" not in f["properties"] for f in feats)
    # one zoom below the density floor the same trees are clustered
    zb = DENSITY_MIN_ZOOM - 1
    xb, yb = tile_xy(cx, cy, zb)
    below = cluster_inventory_trees(db, calc, zb, xb, yb)["features"]
    assert any("point_count" in f["properties"] for f in below)


def test_density_switch_dense_tile_still_clusters(db, calc):
    from app.services.tree_clusters import DENSITY_MIN_ZOOM
    z = DENSITY_MIN_ZOOM
    x, y, cx, cy = _tile_centre(z, 85.40, 27.60)
    icid = db.execute(
        text("SELECT id FROM inventory_calculations WHERE calculation_id = :c"), {"c": calc}
    ).scalar()
    db.execute(text(
        "INSERT INTO public.inventory_trees (id, inventory_calculation_id, species, dia_cm, location) "
        "SELECT gen_random_uuid(), :icid, 'A', 20, "
        "ST_SetSRID(ST_MakePoint(:lng + (g % 50) * 0.00002, :lat + (g / 50) * 0.00002), 4326)::geography "
        "FROM generate_series(1, :n) g"
    ), {"icid": str(icid), "lng": cx, "lat": cy, "n": INDIVIDUAL_CAP + 100})
    db.commit()
    feats = cluster_inventory_trees(db, calc, z, x, y)["features"]
    assert any("point_count" in f["properties"] for f in feats)
