"""ND-3 — whole-forest USDA soil texture % distribution (area-weighted zonal).

Fixture: a synthetic 4x2, 3-band (clay/sand/silt) 32BF raster over a small
bbox. Five pixels are clay-heavy (50/30/20 -> "Clay") and three are sand-heavy
(5/80/15 -> "Loamy Sand"), so the zonal result must be an area-weighted
distribution summing to 100 with "Clay" dominant — not just the centroid class.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.services.analysis import analyze_soil_texture_zonal

# raster footprint: 85.5000..85.508984 lon, 27.397508..27.402 lat, 0.002246° cells
_BBOX_WKT = (
    "POLYGON((85.5 27.397, 85.510 27.397, 85.510 27.403, 85.5 27.403, 85.5 27.397))"
)
_CLAY = "ARRAY[ARRAY[50,50,50,50],ARRAY[50,5,5,5]]::double precision[][]"
_SAND = "ARRAY[ARRAY[30,30,30,30],ARRAY[30,80,80,80]]::double precision[][]"
_SILT = "ARRAY[ARRAY[20,20,20,20],ARRAY[20,15,15,15]]::double precision[][]"


def _build_band(rast_sql: str, band: int, arr: str) -> str:
    return f"ST_SetValues({rast_sql}, {band}, 1, 1, {arr})"


@pytest.fixture()
def soil_raster(db):
    db.execute(text("CREATE SCHEMA IF NOT EXISTS rasters"))
    db.execute(
        text(
            "CREATE TABLE IF NOT EXISTS rasters.soilgrids_isric "
            "(rid serial PRIMARY KEY, rast raster)"
        )
    )
    db.execute(text("DELETE FROM rasters.soilgrids_isric"))
    # three 32BF bands (clay/sand/silt) — ST_SetValues only writes existing bands,
    # so each band must be added before it can be filled
    rast = "ST_MakeEmptyRaster(4, 2, 85.5, 27.402, 0.002246, -0.002246, 0, 0, 4326)"
    for _ in range(3):
        rast = f"ST_AddBand({rast}, '32BF'::text, 0, -3.4e38)"
    rast = _build_band(rast, 1, _CLAY)
    rast = _build_band(rast, 2, _SAND)
    rast = _build_band(rast, 3, _SILT)
    db.execute(text(f"INSERT INTO rasters.soilgrids_isric (rast) SELECT {rast}"))
    db.commit()
    yield
    db.execute(text("DROP TABLE IF EXISTS rasters.soilgrids_isric"))
    db.commit()


def test_zonal_percentages_sum_to_100_with_expected_split(db, soil_raster):
    rec = analyze_soil_texture_zonal(_BBOX_WKT, db)

    pct = rec["soil_percentages"]
    assert abs(sum(pct.values()) - 100.0) <= 0.05
    assert pct == {"Clay": 62.5, "Loamy Sand": 37.5}
    assert rec["soil_dominant_type"] == "Clay"


def test_zonal_returns_empty_without_raster_table(db):
    db.execute(text("DROP TABLE IF EXISTS rasters.soilgrids_isric"))
    db.commit()

    assert analyze_soil_texture_zonal(_BBOX_WKT, db) == {}

    # the failed query must not leave the shared transaction aborted
    assert db.execute(text("SELECT 1")).scalar() == 1


def test_cache_version_bumped_for_soil_texture():
    from app.services.operational_plan.data_collector import OP_DATA_CACHE_VERSION

    assert OP_DATA_CACHE_VERSION >= 30
