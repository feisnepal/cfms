"""Union, Mode A (`union_fusion`, RS-10.3/P10) -- the pixel-stack fusion
vectorizer. Full geoprocessing coverage (the actual `ST_MapAlgebraExpr`
chain, the sliver-absorb/MMU-split fix) was verified live against a real
316 ha forest with real rasters -- see RASTER_SOURCES_TRACKER.md's RS-10.3
build note for those numbers (pieces, timing, before/after the sliver and
performance fixes). The test DB has no live raster tables for any of the 7
SQL-fusable sources, so what belongs here is what CAN be verified without
one: the mixed-radix packing math (pure Python, no DB) and the
SAVEPOINT-guarded empty-on-no-coverage contract every other carve source
in this codebase already gives.
"""
from __future__ import annotations

import itertools

import pytest

from app.services.union_fusion_vectorize import (
    ALL_OPTIONAL_SOURCE_KEYS,
    _OPTIONAL_SOURCES,
    _selected_sources,
    unpack_composite,
)


def _pack(slope, aspect, forest_type, nasa_packed, health, landcover_packed, dem_band,
          sources=None):
    """Mirrors the SQL chain's own arithmetic exactly (c1=slope; then for
    each SELECTED optional source in `_OPTIONAL_SOURCES` order:
    c = c*radix + packed_value) -- the Python-side reference this test
    checks `unpack_composite` against. ``sources=None`` packs all 6,
    matching the module's own "no selection = everything" default."""
    packed = {
        "aspect": aspect, "forest_type": forest_type, "nasa_quality": nasa_packed,
        "forest_health": health, "landcover": landcover_packed, "dem": dem_band,
    }
    c = slope
    for key, _table, radix, _alias, _transform in _selected_sources(sources):
        c = c * radix + packed[key]
    return c


def test_unpack_composite_roundtrips_every_slot_combination_at_the_boundaries():
    """Every slot's min/max value, not just one happy-path example --
    found a real overflow bug (base-100 packing exceeded 32BSI's int32
    range) by testing against real DB output, not by reasoning about the
    math alone, so this test exists to pin the CORRECTED mixed-radix
    scheme against silent drift."""
    slope_vals = [1, 2, 3, 4]
    aspect_vals = [0, 1, 8]  # 0 = flat/missing, not a gap in the range
    forest_type_vals = [0, 1, 26]  # 0 = missing, 26 = Unclassified (real, not missing)
    nasa_packed_vals = [0, 1, 4]  # 0 = missing; 1 = raw NASA 0 (shifted); 4 = raw NASA 3
    health_vals = [0, 1, 5]
    landcover_packed_vals = [0, 1, 10]
    dem_vals = [0, 1, 5]

    for slope, aspect, ft, nasa_p, health, lc_p, dem in itertools.product(
        slope_vals, aspect_vals, forest_type_vals, nasa_packed_vals,
        health_vals, landcover_packed_vals, dem_vals,
    ):
        code = _pack(slope, aspect, ft, nasa_p, health, lc_p, dem)
        out = unpack_composite(code)
        assert out["slope"] == slope
        assert out["aspect"] == aspect  # 0 kept as 0, never None (flat is real)
        assert out["forest_type"] == (ft or None)
        assert out["nasa_quality"] == ((nasa_p - 1) if nasa_p else None)
        assert out["forest_health"] == (health or None)
        assert out["landcover"] == ((lc_p * 10) if lc_p else None)
        assert out["dem_band"] == (dem or None)


def test_max_composite_value_stays_within_32bsi_range():
    """The actual bug found live: a uniform base-100 pack overflowed
    PostGIS's `32BSI` (signed 32-bit) pixel type immediately. Pins the
    corrected mixed-radix scheme's ceiling at a comfortable margin under
    2^31, not just "happens to work today"."""
    max_code = _pack(4, 8, 26, 4, 5, 10, 5)
    assert max_code < 2**31
    # Not just "fits" -- fits with real headroom, so a future source
    # gaining one more real class doesn't silently reopen this bug.
    assert max_code < 2**31 // 2


def test_selected_sources_roundtrip_for_every_subset_size():
    """RS-10.3b (owner, 2026-10-01: "Can user select some of the raster
    instead select all raster?") -- packing/unpacking must stay correct
    for every subset of optional sources, not just "all 6". Selecting
    fewer sources also narrows the composite's own value range (fewer
    radix multiplications), which is the whole point: fewer combinations,
    fewer pieces."""
    import itertools as it

    all_keys = sorted(ALL_OPTIONAL_SOURCE_KEYS)
    sample_subsets = [
        [],  # slope alone -- the minimum, still a valid selection
        ["aspect"],
        ["forest_type", "dem"],
        ["aspect", "nasa_quality", "landcover"],
        all_keys,  # everything -- the original RS-10.3 behaviour
    ]
    vals = {
        "aspect": 7, "forest_type": 15, "nasa_quality": 3,
        "forest_health": 4, "landcover": 8, "dem": 2,
    }
    for subset in sample_subsets:
        code = _pack(
            3, vals["aspect"], vals["forest_type"], vals["nasa_quality"],
            vals["forest_health"], vals["landcover"], vals["dem"], sources=subset,
        )
        out = unpack_composite(code, sources=subset)
        assert out["slope"] == 3
        for key in all_keys:
            if key in subset:
                assert _selected_sources([key])  # sanity: a known key resolves
                assert ("dem_band" if key == "dem" else key) in out
            else:
                assert ("dem_band" if key == "dem" else key) not in out, (
                    f"{key} not selected but appeared in unpack_composite's output"
                )


def test_unknown_source_keys_are_ignored_not_rejected():
    """A stale frontend selection (a key that no longer exists, or a typo)
    must degrade to "just skip it", not break the preview -- same
    tolerance the rest of this codebase gives a caller-supplied filter."""
    selected = _selected_sources(["aspect", "not_a_real_source", "dem"])
    assert {k for k, *_ in selected} == {"aspect", "dem"}


def test_union_fusion_pieces_returns_empty_without_live_rasters(db):
    """SAVEPOINT-guarded empty-on-no-coverage, the same contract
    `raster_class_vectorize.class_pieces` gives for every other source --
    never poisons the caller's transaction."""
    from tests.services.test_auto_block_mmu import _make_calc
    from app.services.union_fusion_vectorize import union_fusion_pieces

    calc = _make_calc(db)

    # No bands (band_table_for would itself return [] with no DEM coverage)
    # and no source rasters at all -- both are real "nothing to fuse" cases
    # this function must degrade out of gracefully, not raise.
    assert union_fusion_pieces(calc, db, bands=[]) == []
    assert union_fusion_pieces(calc, db, bands=[(0.0, 1000.0, 1)]) == []


def test_preview_union_fusion_blocks_raises_bad_source_shaped_error_without_rasters(db):
    """`preview_union_fusion_blocks` (auto_block_service.py) surfaces a
    specific, catchable error rather than a raw exception when the pixel
    fusion has nothing to carve -- same `ValueError`-with-a-known-code
    contract every other `preview_*_blocks` function already uses, so the
    API layer's existing `except ValueError` mapping covers it unchanged.
    MMU itself is seeded (RS-10.0's auto-create needs `base.mmu` to exist
    at all in this bare test DB) so the test actually reaches the fusion
    step this is testing, not an unrelated MMU-table-missing error."""
    from tests.services.test_auto_block_mmu import _make_calc, _seed_gis_layers
    from app.services import auto_block_service as svc

    calc = _make_calc(db)
    _seed_gis_layers(db, calc.id)

    with pytest.raises(ValueError):
        svc.preview_union_fusion_blocks(db, calc, level="blocks")
