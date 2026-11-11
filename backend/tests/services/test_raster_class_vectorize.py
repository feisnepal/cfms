"""P1 generic class vectorizer — `app/services/raster_class_vectorize.py`.

Covers the decisions in `RASTER_SOURCES_IMPLEMENTATION_PLAN.md` P1 that are
cheap to get wrong and expensive to discover on a 900 ha forest:

  * RS-1.3  the spec table (labels, anonymous codes, floors, groups)
  * RS-1.4  the geometry pipeline itself, against a synthetic 20x20 grid
  * RS-1.5  the continuous (DEM) mean +/- SD band table
  * RS-1.6  the per-compartment `scope_wkt` clip, and that it clips in SQL
  * RS-2.5  NASA class 0 is NON-FOREST: carved and labelled, never dropped
  * RS-3.7  ESA 10 + 20 group into one class as a remap, not a filter

The spec-level tests need no database at all — they are the reason this module
can be trusted for the four new sources before migration `105` exists.
"""

from __future__ import annotations

import uuid
from dataclasses import replace

import pytest
from geoalchemy2.shape import from_shape
from shapely.geometry import Polygon
from sqlalchemy import text

from app.models.calculation import Calculation
from app.models.user import User, UserRole
from app.services.raster_class_vectorize import (
    ASPECT_CLASSES,
    DEM_ELEVATION,
    ESA_LANDCOVER,
    FRTC_BLOCKED_REASON,
    NASA_QUALITY,
    NDVI_HEALTH,
    SLOPE_CLASSES,
    SPECS_BY_KEY,
    RasterClassSpec,
    band_table_for,
    class_pieces,
    dominant_code,
    effective_floor_ha,
    reclass_expression,
    reclass_pieces,
)

# A 20x20 grid over 0.002 deg (~222 m), left half one class, right half another,
# plus one isolated cell that must be dropped as a sliver. Same shape as the
# slope/aspect fixtures so the pipeline's numbers are comparable.
_W, _H = 20, 20
_X0, _Y0 = 84.0, 27.0
_PIX = 0.0001
_BBOX = Polygon(
    [(_X0, _Y0), (_X0 + _PIX * _W, _Y0), (_X0 + _PIX * _W, _Y0 + _PIX * _H), (_X0, _Y0 + _PIX * _H)]
)


def _grid(left: int, right: int) -> str:
    g = [[right if c >= 11 else left for c in range(1, _W + 1)] for _ in range(_H)]
    g[4][4] = right  # isolated single cell inside the left half -> sliver
    return _array(g)


def _array(g) -> str:
    body = ",".join("ARRAY[" + ",".join(str(v) for v in row) + "]" for row in g)
    return f"ARRAY[{body}]::double precision[][]"


def _make_calc(db, boundary=_BBOX):
    user = User(
        email=f"rcv{uuid.uuid4().hex[:8]}@test.com",
        full_name="Raster Class Vectorize",
        role=UserRole.USER,
        hashed_password="not-a-real-hash",
    )
    db.add(user)
    db.flush()
    calc = Calculation(
        id=str(uuid.uuid4()),
        user_id=user.id,
        uploaded_filename="rcv-test.csv",
        is_draft=False,
        structure_locked=False,
    )
    db.add(calc)
    db.flush()
    if boundary is not None:
        calc.boundary_geom = from_shape(boundary, srid=4326)
        db.flush()
    return calc


def _install(db, table, arr, pixel_type="8BUI", nodata=255):
    """Create + fill a single-band raster table under the `rasters` schema.

    ``nodata=255`` by default, and it is applied with ``ST_SetBandNoDataValue``
    rather than passed to ``ST_AddBand``, because on this PostGIS 3.6 / GDAL
    build **``ST_AddBand`` ignores its nodata argument entirely**: every type
    (``8BUI``, ``16BSI``, ``32BSI``) comes back with NoData = 0. Since
    ``ST_DumpAsPolygons`` drops NoData pixels, a band left at the default loses
    its class 0 -- for NASA that is 83% of the world's pixels. The live tables
    have NoData NULL, so the class survives; an import that trusted
    ``ST_AddBand`` would silently drop it. See the plan's P2 import note.
    """
    db.execute(text("CREATE SCHEMA IF NOT EXISTS rasters"))
    db.execute(text(f"DROP TABLE IF EXISTS {table}"))
    db.execute(text(f"CREATE TABLE {table} (rid serial PRIMARY KEY, rast raster)"))
    db.execute(
        text(
            f"INSERT INTO {table} (rast) SELECT ST_SetBandNoDataValue(ST_SetValues("
            f"  ST_AddBand("
            f"    ST_MakeEmptyRaster({_W}, {_H}, {_X0}, {_Y0 + _PIX * _H}, {_PIX}, -{_PIX}, 0, 0, 4326),"
            f"    '{pixel_type}'::text, 0, 0),"
            f"  1, 1, 1, {arr}), 1, {int(nodata)})"
        )
    )
    db.commit()


@pytest.fixture()
def nasa_raster(db):
    """Left half class 2, right half class 1, one sliver cell of class 3.

    Class 0 is absent on purpose — the NASA class-0 tests use a second fixture so
    that "class 0 was dropped" and "class 0 was never drawn" cannot be confused.
    """
    _install(db, "rasters.nasa_forest_2020", _grid(2, 1))
    yield
    db.execute(text("DROP TABLE IF EXISTS rasters.nasa_forest_2020"))
    db.commit()


@pytest.fixture()
def nasa_with_zero(db):
    """Right half is class 0 (non-forest) instead of a forest class."""
    _install(db, "rasters.nasa_forest_2020", _grid(2, 0))
    yield
    db.execute(text("DROP TABLE IF EXISTS rasters.nasa_forest_2020"))
    db.commit()


@pytest.fixture()
def esa_raster(db):
    """Left half code 10 (tree cover), right half code 20 (deciduous forest).

    With the P3.7 group both halves are the same class, so a correct engine
    returns ONE merged piece covering the whole box.
    """
    _install(db, "rasters.esa_world_cover", _grid(10, 20))
    yield
    db.execute(text("DROP TABLE IF EXISTS rasters.esa_world_cover"))
    db.commit()


@pytest.fixture()
def health_with_zero(db):
    """Right half is code 0 (NoData for forest health) — the anonymous case."""
    _install(db, "rasters.nepal_forest_health", _grid(3, 0))
    yield
    db.execute(text("DROP TABLE IF EXISTS rasters.nepal_forest_health"))
    db.commit()


@pytest.fixture()
def dem_raster(db):
    """A 200..600 m ramp: every cell is a distinct elevation, no nodata."""
    g = [[200 + r * 20 for c in range(1, _W + 1)] for r in range(_H)]
    _install(db, "rasters.dem", _array(g), pixel_type="32BF")
    yield
    db.execute(text("DROP TABLE IF EXISTS rasters.dem"))
    db.commit()


# ---------------------------------------------------------------- RS-1.3 spec


def test_specs_are_registered_under_unique_keys():
    keys = list(SPECS_BY_KEY)
    assert len(keys) == len(set(keys))
    for spec in (NASA_QUALITY, NDVI_HEALTH, ESA_LANDCOVER, DEM_ELEVATION, SLOPE_CLASSES, ASPECT_CLASSES):
        assert SPECS_BY_KEY[spec.key] is spec
        assert spec.table.startswith("rasters.")


def _minimal_spec(**over) -> RasterClassSpec:
    """A spec built with the same shape the real ones use, so the allow-list
    check is reached instead of an argparse-style TypeError."""
    kw = dict(
        key="evil",
        table="rasters.aspect",
        pixel_m=30.0,
        value_range=(1, 4),
        anonymous_codes=(),
        smoothing_m=22.0,
        simplify_deg=0.00013,
        default_sliver_m2=1000.0,
        label_fn=lambda code: f"Class {code}",
    )
    kw.update(over)
    return RasterClassSpec(**kw)


def test_spec_rejects_a_table_outside_the_allowlist():
    with pytest.raises(ValueError, match="allow-list"):
        _minimal_spec(table="public.users")


def test_nasa_class_zero_is_carved_anonymous_not_excluded():
    """RS-2.5 (decision recorded): class 0 is mappable non-forest ground, so it
    is carved as geometry (rule 9 — excluding it would punch a hole in the
    forest) but it is *anonymous*: no label, and never a dominant code, and it
    is not excluded. See the D41 evidence: measured 0-share is 1-48% inside real
    boundaries (100% on the two smallest), so exclude was disqualified."""
    # carved, not excluded -> it is in the carved code set
    assert 0 in NASA_QUALITY.codes
    # ...but anonymous: geometry without a class name or a dominant code
    assert 0 in NASA_QUALITY.anonymous_codes
    assert NASA_QUALITY.label(0) is None
    assert NASA_QUALITY.label(3) == "Old Secondary Forest"


def test_ndvi_and_esa_class_zero_is_anonymous_no_data():
    for spec in (NDVI_HEALTH, ESA_LANDCOVER):
        assert 0 in spec.anonymous_codes, spec.key
        assert 0 in spec.codes, spec.key


def test_each_spec_has_its_own_label_vocabulary():
    """The bug RS-0.5 was created to kill: one shared label dict made a health
    class and a NASA class with the same integer report the same name."""
    assert NDVI_HEALTH.label(1) != NASA_QUALITY.label(1)
    assert NDVI_HEALTH.label(4) == "Healthy"
    assert ESA_LANDCOVER.label(10) == "Tree cover"


def test_esa_code_set_is_sparse_not_the_full_range():
    """ESA is 10..100 in steps of 10. Enumerating 0..100 would claim 91 classes
    the source cannot produce, and would let a band legend grow phantom rows."""
    assert ESA_LANDCOVER.codes == (0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100)
    assert ESA_LANDCOVER.group_codes == {10: 10, 20: 10}


def test_frtc_is_now_registered_rs_9_5():
    """RS-0.2 (the legend) and RS-4.1a (the class-26 contradiction) are both
    resolved (owner directive 2026-10-01) — FRTC is a usable source now, with
    26 carved as an anonymous class (never claimed as one of the 25 named
    types). `FRTC_BLOCKED_REASON` is kept only as a historical string."""
    assert "forest_type" in SPECS_BY_KEY
    spec = SPECS_BY_KEY["forest_type"]
    assert spec.anonymous_codes == (26,)
    assert spec.table == "rasters.forest_type"
    assert "FRTC" in FRTC_BLOCKED_REASON


# --------------------------------------------------- RS-1.4 geometry pipeline


def test_class_pieces_carves_both_classes_and_drops_the_sliver(db, nasa_raster):
    calc = _make_calc(db)
    pieces = class_pieces(calc, db, NASA_QUALITY)
    assert {code for code, _ in pieces} == {1, 2}
    # 400 cells, one of them an isolated island below the 1000 m2 sliver floor,
    # so 399 survive. Each cell is ~98 m2 at this latitude, so the single cell
    # is filtered on area BEFORE smoothing -- the sliver test is not an artefact
    # of the buffer round-trip.
    assert len(pieces) == 2
    total = sum(g.area for _, g in pieces)
    assert total == pytest.approx(_BBOX.area * 399 / 400, rel=1e-3)


def test_pixels_equal_to_the_band_nodata_are_not_carved(db, nasa_with_zero):
    """PostGIS drops NoData pixels inside ST_DumpAsPolygons, so a band that
    declares 0 as NoData cannot express a class 0 at all. This is why the live
    tables must keep NoData unset for NASA, and the reason migration 105 may not
    set it."""
    db.execute(text("DROP TABLE IF EXISTS rasters.nasa_forest_2020"))
    _install(db, "rasters.nasa_forest_2020", _grid(2, 0), nodata=0)
    try:
        calc = _make_calc(db)
        pieces = class_pieces(calc, db, NASA_QUALITY)
        assert {code for code, _ in pieces} == {2}
    finally:
        db.execute(text("DROP TABLE IF EXISTS rasters.nasa_forest_2020"))
        db.commit()


def test_class_pieces_geometries_stay_inside_the_boundary(db, nasa_raster):
    """The re-clip is the last step; nothing may bulge past the boundary."""
    calc = _make_calc(db)
    for _code, geom in class_pieces(calc, db, NASA_QUALITY):
        assert geom.within(_BBOX.buffer(1e-12)), "piece escaped the forest boundary"


def test_class_pieces_covers_the_whole_boundary_with_no_remainder(db, esa_raster):
    """ESA 10 + 20 group to one class, so the box is tiled exactly: a filter
    instead of a remap would have left class 20's half unaccounted for."""
    calc = _make_calc(db)
    pieces = class_pieces(calc, db, ESA_LANDCOVER)
    assert [code for code, _ in pieces] == [10]
    assert sum(g.area for _, g in pieces) == pytest.approx(_BBOX.area, rel=1e-3)


def test_class_pieces_returns_empty_without_a_boundary(db, nasa_raster):
    assert class_pieces(_make_calc(db, boundary=None), db, NASA_QUALITY) == []


def test_class_pieces_degrades_to_empty_when_the_raster_is_missing(db):
    """SAVEPOINT-guarded: an absent raster is an empty result, not an exception
    and not a poisoned transaction."""
    calc = _make_calc(db)
    assert class_pieces(calc, db, NASA_QUALITY) == []
    # The session is still usable afterwards.
    assert db.execute(text("SELECT 1")).scalar() == 1


def test_nasa_non_forest_class_zero_is_carved_but_anonymous(db, nasa_with_zero):
    """RS-2.5 end-to-end. Excluding code 0 would leave a 100%-non-forest forest
    with no compartments at all, and a forest that is 48% non-forest with a hole
    where the grassland is. So it is carved as geometry — but anonymously: it
    reports no label and no dominant code, so it never claims a NASA class."""
    calc = _make_calc(db)
    pieces = class_pieces(calc, db, NASA_QUALITY)
    assert {code for code, _ in pieces} == {0, 2}
    # No remainder: the two classes tile the whole boundary.
    assert sum(g.area for _, g in pieces) == pytest.approx(_BBOX.area * 399 / 400, rel=1e-3)
    zero_piece = next(g for c, g in pieces if c == 0)
    assert zero_piece.area > 0
    # anonymous -> no name and no dominant code (carve-and-anonymous, not labelled)
    assert NASA_QUALITY.label(0) is None
    assert dominant_code(zero_piece.wkt, db, NASA_QUALITY) is None


def test_dominant_code_reports_the_majority_class(db, nasa_raster):
    calc = _make_calc(db)
    _code, geom = max(class_pieces(calc, db, NASA_QUALITY), key=lambda t: t[1].area)
    assert dominant_code(geom.wkt, db, NASA_QUALITY) in {1, 2}


def test_anonymous_class_is_carved_but_reports_no_dominant_code(db, health_with_zero):
    """Rule 9 vs the label rule, together: code 0 gets geometry (the land is
    real) but no class name, so the caller must get None rather than a
    fabricated 0."""
    calc = _make_calc(db)
    pieces = class_pieces(calc, db, NDVI_HEALTH)
    assert {code for code, _ in pieces} == {0, 3}
    _code, geom = max(pieces, key=lambda t: t[1].area)
    assert dominant_code(geom.wkt, db, NDVI_HEALTH) is None
    # ...and the 0-carved piece is still real area on the map.
    zero_piece = next(g for c, g in pieces if c == 0)
    assert zero_piece.area > 0
    assert zero_piece.within(_BBOX.buffer(1e-12))


def test_dominant_code_applies_the_group_remap(db, esa_raster):
    """Grouped code is what the map carries, so 20 must never come back raw."""
    calc = _make_calc(db)
    _code, geom = class_pieces(calc, db, ESA_LANDCOVER)[0]
    assert dominant_code(geom.wkt, db, ESA_LANDCOVER) == 10


def test_value_filter_narrows_the_carved_codes(db, nasa_raster):
    calc = _make_calc(db)
    pieces = class_pieces(calc, db, NASA_QUALITY, value_filter=(1,))
    assert {code for code, _ in pieces} == {1}


def test_value_filter_that_excludes_everything_is_an_error(db, nasa_raster):
    with pytest.raises(ValueError, match="excludes every code"):
        class_pieces(_make_calc(db), db, NASA_QUALITY, value_filter=(99,))


# ------------------------------------------------------------ RS-1.6 scope


def test_scope_wkt_clips_to_the_compartment_not_the_forest(db, nasa_raster):
    calc = _make_calc(db)
    half = Polygon(
        [
            (_X0, _Y0),
            (_X0 + _PIX * 10, _Y0),
            (_X0 + _PIX * 10, _Y0 + _PIX * _H),
            (_X0, _Y0 + _PIX * _H),
        ]
    )
    scoped = class_pieces(calc, db, NASA_QUALITY, scope_wkt=half.wkt)
    full = class_pieces(calc, db, NASA_QUALITY)
    assert sum(g.area for _, g in scoped) < sum(g.area for _, g in full)
    for _code, geom in scoped:
        assert geom.within(half.buffer(1e-12))


def test_scope_wkt_takes_precedence_over_the_boundary(db, nasa_raster):
    """Rule 19. A compartment must never be carved against the forest
    boundary when the caller passed its own geometry."""
    calc = _make_calc(db)
    tiny = Polygon([(_X0, _Y0), (_X0 + 0.0002, _Y0), (_X0 + 0.0002, _Y0 + 0.0002), (_X0, _Y0 + 0.0002)])
    scoped = class_pieces(calc, db, NASA_QUALITY, scope_wkt=tiny.wkt)
    for _code, geom in scoped:
        assert geom.within(tiny.buffer(1e-12))
        assert geom.intersection(_BBOX).area == pytest.approx(geom.area, rel=1e-6)


def test_an_invalid_scope_wkt_degrades_to_empty(db, nasa_raster):
    assert class_pieces(_make_calc(db), db, NASA_QUALITY, scope_wkt="not wkt") == []


# --------------------------------------------------- RS-1.5 continuous / DEM


def test_band_table_splits_the_observed_range_into_three_zones(db, dem_raster):
    calc = _make_calc(db)
    bands = band_table_for(calc, db, DEM_ELEVATION)
    assert len(bands) == 3
    codes = [c for _, _, c in bands]
    assert codes == [1, 2, 3]
    # Contiguous and tiling: each band starts where the previous one ended.
    for (a_lo, a_hi, _), (b_lo, b_hi, _) in zip(bands, bands[1:]):
        assert a_hi == pytest.approx(b_lo)
    # No degenerate (zero-width) band, and the ends bracket the data.
    assert all(lo < hi for lo, hi, _ in bands)


def test_band_table_clamps_cuts_into_the_observed_range(db, dem_raster):
    """A left-skewed distribution puts mean-SD below the minimum elevation.
    Without the clamp the first zone collapses and its terrain is lost."""
    calc = _make_calc(db)
    bands = band_table_for(calc, db, DEM_ELEVATION)
    with db.begin_nested():
        stats = db.execute(
            text("SELECT (ST_SummaryStats(rast, 1)).min AS mn, (ST_SummaryStats(rast, 1)).max AS mx "
                 "FROM rasters.dem")
        ).first()
    assert bands[0][0] <= float(stats.mn)
    assert bands[-1][1] > float(stats.mx)


def test_reclass_expression_is_a_bare_band_list(db, dem_raster):
    """Returns the `old:new,...` list only -- no ST_Reclass wrapper and no
    NODATA= clause, so `reclass_pieces` can inject the nodata and the output
    pixel type. It does prepend one band that maps the source's NoData to 0, so
    a hole in the DEM does not get reclassified into a real zone."""
    calc = _make_calc(db)
    bands = band_table_for(calc, db, DEM_ELEVATION)
    expr = reclass_expression(bands)
    assert "ST_Reclass" not in expr
    assert "NODATA" not in expr
    entries = expr.split(",")
    assert len(entries) == len(bands) + 1
    assert entries[0].endswith(":0"), "the NoData band must come first and map to 0"
    for (_lo, _hi, code) in bands:
        assert any(e.endswith(f":{code}") for e in entries)


def test_reclass_pieces_carves_all_three_zones(db, dem_raster):
    """The real end-to-end check of the band table: whatever zones it produced,
    every one of them comes back as geometry and they tile the boundary."""
    calc = _make_calc(db)
    bands = band_table_for(calc, db, DEM_ELEVATION)
    pieces = reclass_pieces(calc, db, DEM_ELEVATION, bands)
    assert {code for code, _ in pieces} == {1, 2, 3}
    for _code, geom in pieces:
        assert geom.within(_BBOX.buffer(1e-12))
    # Smoothing at a DEM pixel scale loses a little area, but nothing like a
    # whole zone: the three pieces must still cover nearly the whole boundary.
    covered = sum(g.area for _, g in pieces)
    assert covered == pytest.approx(_BBOX.area, rel=0.02)


def test_dem_cuts_come_from_the_parent_not_the_compartment(db, dem_raster):
    """Rule 16. Passing an explicit stats geometry must change the bands; the
    default must be the forest boundary."""
    calc = _make_calc(db)
    default = band_table_for(calc, db, DEM_ELEVATION)
    west = Polygon([(_X0, _Y0), (_X0 + 0.001, _Y0), (_X0 + 0.001, _Y0 + 0.0005), (_X0, _Y0 + 0.0005)])
    scoped = band_table_for(calc, db, DEM_ELEVATION, stats_wkt=west.wkt)
    assert scoped != default


def test_band_table_degrades_to_empty_without_a_boundary(db):
    assert band_table_for(_make_calc(db, boundary=None), db, DEM_ELEVATION) == []


# ---------------------------------------------------------------- RS-1.x floor


def test_effective_floor_is_monotonic_and_positive():
    for spec in (NASA_QUALITY, NDVI_HEALTH, ESA_LANDCOVER, DEM_ELEVATION):
        small = effective_floor_ha(spec, 1_000.0)
        big = effective_floor_ha(spec, 10_000_000.0)
        assert small <= big, spec.key
        assert small > 0, spec.key


def test_existing_sources_keep_their_five_hectare_floor():
    """Rule 10/D38: the tuned 5 ha floor for slope/aspect/canopy is not a
    default to be re-derived, it is a decision."""
    for spec in (SLOPE_CLASSES, ASPECT_CLASSES):
        assert spec.min_floor_ha == 5.0 and spec.max_floor_ha == 5.0
        for area_ha in (6.0, 50.0, 926.8, 100_000.0):
            assert effective_floor_ha(spec, area_ha * 10_000) == 5.0, (spec.key, area_ha)


def test_a_forest_smaller_than_the_floor_collapses_to_one_piece_not_zero():
    """A 0.1 ha forest with a 5 ha floor would otherwise yield nothing, and a
    source that returns nothing is indistinguishable from a broken one. One
    piece surfaces the honest DIVISION_TOO_FEW error instead (rule 17)."""
    assert effective_floor_ha(SLOPE_CLASSES, 1_000.0) == pytest.approx(0.1)
    assert effective_floor_ha(SLOPE_CLASSES, 0.0) == 5.0


def test_a_tiny_forest_never_gets_a_zero_floor():
    for spec in (NASA_QUALITY, NDVI_HEALTH, ESA_LANDCOVER):
        assert effective_floor_ha(spec, 0.5) > 0, spec.key


def test_replacing_a_spec_revalidates_the_table():
    with pytest.raises(ValueError, match="allow-list"):
        replace(NASA_QUALITY, table="public.calculations")
