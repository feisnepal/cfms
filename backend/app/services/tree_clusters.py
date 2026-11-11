"""
U05 — server-side tree clustering for `inventory_trees`.

`cluster_inventory_trees(db, calc_id, zoom, x, y)` -> {features, hasMore}

Decisions frozen in the plan (U05):
- Grid bucketing runs in EPSG:3857 METRES via `st_transform(location::geometry, 3857)`.
- Spatial filter uses the SAME 3857 functional GiST index `idx_tree_3857`.
- z<18: capped cluster groups (per-cell cap 500, total response cap 500 with ORDER BY cnt DESC LIMIT 500).
  A cell with exactly one tree in it is emitted as an individual (styled) point,
  not a "1"-labelled bubble — the QGIS point-cluster minimum-cluster-size idea.
- DENSITY_MIN_ZOOM <= z < 18: if the whole tile holds <= INDIVIDUAL_CAP trees it is returned as
  individuals instead of clusters (count-based, so a small forest is readable earlier and a dense
  one still clusters). The frontend (`StemMappingClusters.tsx`) requests tiles from MIN_VISIBLE_ZOOM.
- z>=18: individual rows, cap 2000 (decimated) + hasMore flag.
- Every individual carries `tree_group` (felling/mother/seedling/other, from `remark`) and
  `prime_species_code` (1..21 or null, `core/prime_species.py`) -- what the map needs to pick
  a SHAPE and a species COLOUR without re-implementing the matching rules in the browser.
- Single-tile API: client passes (z,x,y); the bbox is ALWAYS derived server-side
  (never accepted from the client) so the cache key is unambiguous.
- Cache: cachetools.TTLCache(512, ttl=60) guarded by threading.Lock; key=(cid, geom_epoch, x, y, z).
  The geometry epoch is the single freshness mechanism — no invalidate() by design.
"""

from __future__ import annotations

import threading

from cachetools import TTLCache
from sqlalchemy.orm import Session
from sqlalchemy import text

from ..core.prime_species import prime_species_code, tree_group
from .webmercator import bbox_for_tile

CAP_CLUSTER = 500      # per-cell cap at z<ZOOM_INDIVIDUALS (a hot cell returns ONE capped cluster)
TOTAL_CAP = 500        # total clusters per tile response (z<ZOOM_INDIVIDUALS)
INDIVIDUAL_CAP = 2000  # z>=ZOOM_INDIVIDUALS individual features per tile (decimated)
ZOOM_INDIVIDUALS = 18  # zoom >= this returns individual rows — matches the frontend's
                       # MIN_VISIBLE_ZOOM (StemMappingClusters.tsx): the layer is hidden
                       # entirely below z18, so by the time a request is even sent, it
                       # should be individual trees, not a cluster bubble.
DENSITY_MIN_ZOOM = 16  # between this and ZOOM_INDIVIDUALS a tile whose trees all fit under
                       # INDIVIDUAL_CAP is returned as individuals, not cluster bubbles: a small
                       # forest is readable (species colour, mother/felling shape) two zooms
                       # earlier, while a dense tile still clusters. Count-based, so the switch
                       # follows the data, not a fixed zoom.
CLUSTER_CELL_PX = 64   # cluster grid cell, in SCREEN pixels, at the query's zoom —
                       # matches the ~60-80px default every marker-cluster library uses
                       # (Leaflet.markercluster, Supercluster) so nearby points actually
                       # merge into one bubble on screen. NOT 1px (see below).

# (cache_id, geom_epoch, x, y, z) -> serialized response. Per-process only.
_TILE_CACHE: TTLCache = TTLCache(maxsize=512, ttl=60)
_CACHE_LOCK = threading.Lock()


def _geom_epoch(db: Session, calc_id) -> int:
    """Authoritative geometry epoch for a calculation (compare-and-set clock, U02/A.5)."""
    row = db.execute(
        text("SELECT geometry_version FROM calculations WHERE id = :cid"),
        {"cid": calc_id},
    ).first()
    return int(row[0]) if row and row[0] is not None else 0


def _respond(features, has_more):
    return {"features": features, "hasMore": has_more}


def _stem_props(species, remark) -> dict:
    """Map-styling keys for one tree: species colour code and shape group."""
    return {
        "remark": remark,
        "tree_group": tree_group(remark),
        "prime_species_code": prime_species_code(species),
    }


def _individual_feature(r) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [round(float(r.lng), 7), round(float(r.lat), 7)]},
        "properties": {
            "id": r[0] if isinstance(r[0], str) else str(r[0]),
            "species": r.species,
            "dbh_cm": float(r.dia_cm) if r.dia_cm is not None else 0,
            "height_m": float(r.height_m) if r.height_m is not None else 0,
            "volume_m3": float(r.tree_volume) if r.tree_volume is not None else 0,
            "block_id": str(r.block_id) if r.block_id else None,
            "block_name": r.block_name,
            "dbh_class": r.dbh_class,
            **_stem_props(r.species, r.remark),
        },
    }


_INDIVIDUALS_SQL = f"""
    SELECT it.id AS id, st_y(location::geometry) AS lat, st_x(location::geometry) AS lng,
           it.species, it.dia_cm, it.height_m, it.tree_volume, it.block_id, it.block_name,
           it.dbh_class, it.remark
    FROM inventory_trees it
    JOIN inventory_calculations ic ON ic.id = it.inventory_calculation_id
    WHERE ic.calculation_id = :cid
      AND st_transform(location::geometry, 3857) &&
          st_transform(st_setsrid(st_makeenvelope(:w,:s,:e,:n,4326),4326)::geometry, 3857)
    ORDER BY it.id
    LIMIT {INDIVIDUAL_CAP + 1}
"""


def cluster_inventory_trees(db: Session, calc_id, zoom: int, x: int, y: int) -> dict:
    """Return {features, hasMore} for a single tile (z,x,y)."""
    epoch = _geom_epoch(db, calc_id)
    key = (str(calc_id), epoch, x, y, zoom)

    with _CACHE_LOCK:
        if (cached := _TILE_CACHE.get(key)) is not None:
            return cached

    w, s, e, n = bbox_for_tile(x, y, zoom)

    features: list = []
    has_more = False

    # Density switch: in [DENSITY_MIN_ZOOM, ZOOM_INDIVIDUALS) a tile that fits under the
    # individual cap is shown tree by tree; only a denser tile falls through to clusters.
    density_rows = None
    if DENSITY_MIN_ZOOM <= zoom < ZOOM_INDIVIDUALS:
        probe = db.execute(
            text(_INDIVIDUALS_SQL),
            {"cid": str(calc_id), "w": w, "s": s, "e": e, "n": n},
        ).fetchall()
        if len(probe) <= INDIVIDUAL_CAP:
            density_rows = probe

    if density_rows is not None:
        out = _respond([_individual_feature(r) for r in density_rows], False)
    elif zoom < ZOOM_INDIVIDUALS:
        # cell_m used to be 156543.03392 / 2**zoom -- the raw Web-Mercator
        # metres-per-PIXEL value, i.e. a 1px-wide grid cell. That's not
        # clustering, it's just quantizing to the pixel grid: on a dense
        # inventory (e.g. 14k trees in under 1km^2) a single 256x256px tile
        # already had >500 distinct occupied 1px cells by z13-16, so almost
        # every tile hit TOTAL_CAP -- hundreds of overlapping bubbles, most
        # of the forest silently dropped (hasMore never shown), thousands of
        # DOM markers across a multi-tile viewport. Scaling by CLUSTER_CELL_PX
        # makes the cell a real ~64px cluster radius, like every other
        # point-cluster renderer (QGIS included) uses.
        cell_m = CLUSTER_CELL_PX * 156543.03392 / (2.0 ** zoom)
        # z<ZOOM_INDIVIDUALS clustered buckets in EPSG:3857 metres; both operands in 3857 so the
        # functional GiST index (idx_tree_3857) is used. Total cap via ORDER BY cnt DESC LIMIT.
        cluster_sql = f"""
            WITH scoped AS (
                SELECT location::geometry AS loc, it.id AS id, it.species AS species,
                       it.dia_cm AS dia_cm, it.height_m AS height_m, it.tree_volume AS tree_volume,
                       it.block_id AS block_id, it.block_name AS block_name, it.dbh_class AS dbh_class,
                       it.remark AS remark
                FROM inventory_trees it
                JOIN inventory_calculations ic ON ic.id = it.inventory_calculation_id
                WHERE ic.calculation_id = :cid
                  AND st_transform(location::geometry, 3857) &&
                      st_transform(st_setsrid(st_makeenvelope(:w,:s,:e,:n,4326),4326)::geometry, 3857)
            ),
            bucketed AS (
                SELECT
                    floor(st_x(st_transform(loc::geometry,3857)) / :cell)::bigint AS cx,
                    floor(st_y(st_transform(loc::geometry,3857)) / :cell)::bigint AS cy,
                    count(*) AS cnt,
                    st_centroid(st_collect(loc)) AS ctr,
                    -- Only meaningful when cnt=1 (then it's *the* tree's own
                    -- attributes); max() over a bigger cell is a cheap, single-pass
                    -- aggregate that happens to be junk we never read for cnt>1.
                    max(id::text) AS sample_id,
                    max(species) AS sample_species,
                    max(dia_cm) AS sample_dia_cm,
                    max(height_m) AS sample_height_m,
                    max(tree_volume) AS sample_volume_m3,
                    max(block_id::text) AS sample_block_id,
                    max(block_name) AS sample_block_name,
                    max(dbh_class) AS sample_dbh_class,
                    max(remark) AS sample_remark
                FROM scoped
                GROUP BY cx, cy
            )
            SELECT cnt AS point_count,
                   st_y(ctr::geometry) AS lat,
                   st_x(ctr::geometry) AS lng,
                   sample_id, sample_species, sample_dia_cm, sample_height_m,
                   sample_volume_m3, sample_block_id, sample_block_name, sample_dbh_class,
                   sample_remark
            FROM bucketed
            ORDER BY cnt DESC
            LIMIT :cap
        """
        rows = db.execute(
            text(cluster_sql),
            {
                "cid": str(calc_id),
                "w": w, "s": s, "e": e, "n": n,
                "cell": cell_m,
                "cap": TOTAL_CAP,
            },
        ).fetchall()

        # Detect total-response cap exceeded: if we returned TOTAL_CAP rows the tile may
        # have more clusters → flag hasMore. Per-cell cap 500 (zoom_hint) handled below.
        if len(rows) >= TOTAL_CAP:
            has_more = True

        features = []
        for r in rows:
            point_count = int(r.point_count)
            if point_count == 1:
                # A lone tree in this cell — render it as an actual tree (same
                # shape as the z>=ZOOM_INDIVIDUALS branch below), not a "1" bubble.
                features.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [round(float(r.lng), 7), round(float(r.lat), 7)]},
                    "properties": {
                        "id": r.sample_id,
                        "species": r.sample_species,
                        "dbh_cm": float(r.sample_dia_cm) if r.sample_dia_cm is not None else 0,
                        "height_m": float(r.sample_height_m) if r.sample_height_m is not None else 0,
                        "volume_m3": float(r.sample_volume_m3) if r.sample_volume_m3 is not None else 0,
                        "block_id": r.sample_block_id,
                        "block_name": r.sample_block_name,
                        "dbh_class": r.sample_dbh_class,
                        **_stem_props(r.sample_species, r.sample_remark),
                    },
                })
                continue
            zoom_hint = point_count >= CAP_CLUSTER
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [round(float(r.lng), 7), round(float(r.lat), 7)]},
                "properties": {
                    "point_count": min(point_count, CAP_CLUSTER),
                    "actual_count": point_count,
                    "zoom_hint": zoom_hint,
                },
            })
        out = _respond(features, has_more)
    else:
        # z>=18: individual rows, capped 2000; decimate if a tile exceeds it.
        rows = db.execute(
            text(_INDIVIDUALS_SQL),
            {"cid": str(calc_id), "w": w, "s": s, "e": e, "n": n},
        ).fetchall()

        truncated = len(rows) > INDIVIDUAL_CAP
        rows = rows[:INDIVIDUAL_CAP]
        has_more = truncated
        features = [_individual_feature(r) for r in rows]
        out = _respond(features, has_more)

    with _CACHE_LOCK:
        _TILE_CACHE[key] = out
    return out


def invalidate_all():  # test helper only — removes the whole local cache.
    """Clear the in-process tile cache (tests only; productions relies on epoch key)."""
    with _CACHE_LOCK:
        _TILE_CACHE.clear()