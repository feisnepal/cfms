"""Per-block zone classification for Sustainable Forest Management (P1).

``SUSTAINABLE_FOREST_MANAGEMENT_PLAN.md`` §3.2 / §5 P1.

For a block geometry: its dominant ``rasters.slope_regulation`` band (1-4 =
< 19° / 19-31° / 31-45° / > 45°), the LRMP physiography zone that covers most of
it, mean altitude, and — folding those together — one ``sfm_zone`` bucket
(``LOWLAND_SAL`` | ``HILL`` | ``TEMPERATE`` | ``HIGH_MOUNTAIN``) plus an
``inner_terai`` label flag (D1: inside the seven inner-terai districts AND on a
Chure/Dun/Bhabar physiography — never changes a prescription, only narration).

Everything is computed **fresh** from PostGIS per block — the per-unit arrays in
``result_data`` go stale and shadow ``forest_blocks`` (see
[[result-data-units-stale-trap]]). The forest-level ``whole_physiography_*`` in
``result_data`` is safe, but this module does not need it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.sustainable_fm.sfm_config import SfmParams

logger = logging.getLogger(__name__)

SFM_ZONES = ("LOWLAND_SAL", "HILL", "TEMPERATE", "HIGH_MOUNTAIN")

# LRMP "physiography Zone" strings → sfm_zone bucket.
_LOWLAND = {
    "Terai or Madhesh",
    "Bhawar",
    "Chure Hillslopes",
    "Dun",
    "Inner River Valley",
}
_HILL = {"Middle Mountain", "Mahabharat"}
_HIGH = {"High Mountain"}

# Inner-Terai physiography subset (D1) — valley / low-hill land, not the outer
# plain, not the Mahabharat. Combined with the seven-district gate.
_INNER_TERAI_PHYS = {"Chure Hillslopes", "Dun", "Inner River Valley", "Bhawar"}

# Only this table is ever queried; a param that names anything else is ignored
# (the value is validated on write, but the query still must not interpolate
# arbitrary identifiers).
_ALLOWED_SLOPE_TABLES = {"rasters.slope_regulation"}


@dataclass(frozen=True)
class ZoneResult:
    sfm_zone: str
    inner_terai: bool
    dom_phys: str
    slope_band: int
    slope_band_area_pct: dict[int, float]  # {1:..,2:..,3:..,4:..}, ~sums to 100
    mean_altitude_m: Optional[float]


# ─────────────────────────────────────────────────────────────────────────────
# PostGIS reads
# ─────────────────────────────────────────────────────────────────────────────
def dominant_slope_band(
    geom_wkt: str, db: Session, params: SfmParams
) -> tuple[int, dict[int, float]]:
    """Dominant ``slope_regulation`` band (1-4) + per-band area %.

    Same ``ST_ValueCount(ST_Clip(...))`` pattern as ``analyze_slope_geometry``.
    An empty result (raster absent, or the block outside coverage) → band 1.
    """
    table = params.slope_regulation_table
    if table not in _ALLOWED_SLOPE_TABLES:
        table = "rasters.slope_regulation"
    query = text(
        f"""
        SELECT (pvc).value AS band, SUM((pvc).count) AS px
        FROM (
            SELECT ST_ValueCount(ST_Clip(rast, ST_GeomFromText(:wkt, 4326))) AS pvc
            FROM {table}
            WHERE ST_Intersects(rast, ST_GeomFromText(:wkt, 4326))
        ) s
        WHERE (pvc).value BETWEEN 1 AND 4
        GROUP BY (pvc).value
        """  # noqa: S608 -- table is constrained to _ALLOWED_SLOPE_TABLES above
    )
    try:
        # SAVEPOINT so a missing raster (test DB) rolls back just this query
        # instead of poisoning the caller's transaction.
        with db.begin_nested():
            rows = db.execute(query, {"wkt": geom_wkt}).fetchall()
    except (
        Exception
    ):  # noqa: BLE001 -- slope_regulation optional (test DB / no coverage)
        logger.debug("dominant_slope_band: %s unavailable", table, exc_info=True)
        rows = []
    pct = {b: 0.0 for b in (1, 2, 3, 4)}
    if not rows:
        pct[1] = 100.0
        return 1, pct
    total = sum(float(r.px) for r in rows) or 1.0
    for r in rows:
        pct[int(r.band)] = round(float(r.px) / total * 100.0, 2)
    return max(pct, key=lambda k: pct[k]), pct


def physiography_pct(geom_wkt: str, db: Session) -> dict[str, float]:
    """LRMP physiography zone → % of the block's area it covers (UTM-projected).

    ``{}`` when ``admin.physiography`` is absent (test DB) or nothing intersects.
    """
    query = text(
        """
        WITH g AS (SELECT ST_GeomFromText(:wkt, 4326) AS geom),
        u AS (
            SELECT CASE WHEN ST_X(ST_Centroid(geom)) > 84 THEN 32645 ELSE 32644 END AS srid
            FROM g
        ),
        tot AS (SELECT ST_Area(ST_Transform(g.geom, u.srid)) AS a FROM g, u),
        ix AS (
            SELECT p."physiography Zone" AS zone,
                   ST_Area(ST_Transform(ST_Intersection(p.geom, g.geom), u.srid)) AS a
            FROM admin.physiography p, g, u
            WHERE ST_Intersects(p.geom, g.geom)
              AND p."physiography Zone" IS NOT NULL
        )
        SELECT zone, SUM(a) / NULLIF((SELECT a FROM tot), 0) * 100 AS pct
        FROM ix WHERE a > 0 GROUP BY zone
        """
    )
    try:
        with db.begin_nested():
            rows = db.execute(query, {"wkt": geom_wkt}).fetchall()
        return {r.zone: round(float(r.pct), 2) for r in rows if r.pct is not None}
    except Exception:  # noqa: BLE001 -- admin.physiography optional (test DB)
        logger.debug("physiography_pct: admin.physiography unavailable", exc_info=True)
        return {}


def mean_altitude_m(geom_wkt: str, db: Session) -> Optional[float]:
    """Mean DEM elevation over the block, metres. ``None`` when ``rasters.dem``
    is absent or the block is outside coverage. Mirrors ``analyze_dem``'s clip."""
    query = text(
        """
        WITH clip AS (
            SELECT ST_Clip(rast, ST_GeomFromText(:wkt, 4326)) AS rast
            FROM rasters.dem
            WHERE ST_Intersects(rast, ST_GeomFromText(:wkt, 4326))
            LIMIT 1
        ),
        px AS (SELECT (ST_PixelAsPolygons(rast)).val AS z FROM clip)
        SELECT AVG(z) FROM px WHERE z > -32000 AND z >= 0 AND z <= 9000
        """
    )
    try:
        with db.begin_nested():
            v = db.execute(query, {"wkt": geom_wkt}).scalar()
        return round(float(v), 1) if v is not None else None
    except Exception:  # noqa: BLE001 -- rasters.dem optional (test DB)
        logger.debug("mean_altitude_m: rasters.dem unavailable", exc_info=True)
        return None


def _in_seven_districts(geom_wkt: str, db: Session, params: SfmParams) -> bool:
    """True when the block intersects a ward of one of the seven inner-terai
    districts (D1). SAVEPOINT-guarded — ``admin.ward`` is optional on a
    migrations-only DB."""
    query = text(
        """
        SELECT EXISTS(
            SELECT 1 FROM admin.ward w
            WHERE w.district = ANY(:d)
              AND ST_Intersects(w.geom, ST_GeomFromText(:wkt, 4326))
        )
        """
    )
    try:
        with db.begin_nested():
            return bool(
                db.execute(
                    query,
                    {"d": list(params.inner_terai_districts), "wkt": geom_wkt},
                ).scalar()
            )
    except Exception:  # noqa: BLE001 -- admin.ward optional (test DB)
        logger.debug("_in_seven_districts: admin.ward unavailable", exc_info=True)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Classification
# ─────────────────────────────────────────────────────────────────────────────
def classify_zone(
    geom_wkt: str,
    physio_pct: dict[str, float],
    slope_band: int,
    slope_band_area_pct: dict[int, float],
    mean_alt_m: Optional[float],
    db: Session,
    params: SfmParams,
) -> ZoneResult:
    """Fold physiography + altitude into one ``sfm_zone`` + the ``inner_terai``
    flag. The caller supplies the slope band / altitude (already read once) so
    this does no raster work — only the optional ``admin.ward`` gate."""
    dom_phys = max(physio_pct, key=lambda k: physio_pct[k]) if physio_pct else ""

    if dom_phys in _HIGH:
        zone = "HIGH_MOUNTAIN"
    elif dom_phys in _HILL:
        zone = (
            "TEMPERATE"
            if mean_alt_m is not None and 1800.0 <= mean_alt_m <= 3000.0
            else "HILL"
        )
    elif dom_phys in _LOWLAND:
        zone = "LOWLAND_SAL"
    else:
        zone = "HILL"  # unknown physiography → conservative hill default

    inner_terai = dom_phys in _INNER_TERAI_PHYS and _in_seven_districts(
        geom_wkt, db, params
    )

    return ZoneResult(
        sfm_zone=zone,
        inner_terai=inner_terai,
        dom_phys=dom_phys,
        slope_band=slope_band,
        slope_band_area_pct=dict(slope_band_area_pct),
        mean_altitude_m=mean_alt_m,
    )


def classify_block(geom_wkt: str, db: Session, params: SfmParams) -> ZoneResult:
    """Convenience: read slope / physiography / altitude for a block and
    classify in one call. ``sfm_service`` (P2) uses this."""
    band, band_pct = dominant_slope_band(geom_wkt, db, params)
    physio = physiography_pct(geom_wkt, db)
    alt = mean_altitude_m(geom_wkt, db)
    return classify_zone(geom_wkt, physio, band, band_pct, alt, db, params)


def _normalise_band_pct(
    band: int, band_pct: Optional[dict[int, float]]
) -> dict[int, float]:
    """Fill / re-scale a (possibly partial) per-band % dict to sum 100.

    Keys may be ``int`` or numeric ``str`` (JSONB). The manual dominant band
    is kept (co-)dominant — deterministic tie-break: the manual band wins over
    an equal % on another band. An empty / all-zero input → ``{band: 100.0}``
    (bump a "bare dominant band" override).
    """
    pct: dict[int, float] = {b: 0.0 for b in (1, 2, 3, 4)}
    if band_pct:
        for k, v in band_pct.items():
            try:
                b = int(k)
            except (TypeError, ValueError):
                continue
            if b in pct:
                pct[b] = float(v) or 0.0
    total = sum(pct.values())
    if total <= 0:
        return {b: 0.0 for b in (1, 2, 3, 4)} | {band: 100.0}
    others = [v for b, v in pct.items() if b != band] or [0.0]
    pct[band] = max(pct[band], max(others))  # manual band stays dominant
    total = sum(pct.values())
    return {b: round(v / total * 100.0, 2) for b, v in pct.items()}


def classify_block_with_override(
    geom_wkt: str,
    db: Session,
    params: SfmParams,
    band: Optional[int],
    band_pct: Optional[dict[int, float]] = None,
) -> ZoneResult:
    """Classify a block with a *manual* dominant slope band / distribution.

    Identical to :func:`classify_block` except the slope read is replaced by
    the caller's ``band`` (scale 1-4 = <19° / 19-31° / 31-45° / >45°) — no
    slope-raster read happens here. ``band=None`` falls back to the raster path
    :func:`classify_block` (the per-block fallback used by the user variant).
    ``band_pct`` (optional, per-band %) normalises to sum-100; a bare band
    yields ``{band: 100.0}``. Physiography / altitude are still read fresh.
    """
    if band is None:
        return classify_block(geom_wkt, db, params)
    physio = physiography_pct(geom_wkt, db)
    alt = mean_altitude_m(geom_wkt, db)
    pct = _normalise_band_pct(band, band_pct)
    return classify_zone(geom_wkt, physio, band, pct, alt, db, params)


__all__ = [
    "SFM_ZONES",
    "ZoneResult",
    "dominant_slope_band",
    "physiography_pct",
    "mean_altitude_m",
    "classify_zone",
    "classify_block",
    "classify_block_with_override",
]
