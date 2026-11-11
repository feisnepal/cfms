"""Union, Mode A (`union_fusion`, RS-10.3/P10) -- pixel-level fusion of the
SQL-queryable classified rasters into ONE composite code per pixel,
vectorized in a single pass. Canopy is NOT part of this pixel stack -- see
the module docstring note below -- and is attached per final piece
afterward, the same zonal step Mode B (`union_zonal`) already uses.

**Slope is always included and is the GATE** (owner decision, 2026-10-01):
a pixel enters the composite only if slope has a valid value there. Every
other SQL-fusable source -- aspect, forest type, NASA quality, forest
health, land cover, DEM contour band -- is OPTIONAL (RS-10.3b, owner
question 2026-10-01: "Can user select some of the raster instead select
all raster?"). Fusing fewer attributes means far fewer distinct
combinations, which means fewer, larger, more usable pieces and a much
faster `dominant_composite` re-derivation pass -- this is not just a
convenience, it directly answers the performance/fragmentation problem
RS-10.3's own build note found on a real forest (132s/1226 pieces fusing
all 6 optional sources, vs 13.3s/129 pieces after floor+bug fixes; fusing
fewer sources narrows this further still).

Composite packing is MIXED-RADIX (not a uniform base), because the pixel
raster storing the composite must stay within PostGIS's `32BSI` (signed
32-bit) pixel type -- a uniform base-100 encoding (first draft of this
module) overflowed it immediately (max value ~4.08e9, int32 max is
~2.15e9). Each slot gets exactly the radix its own real value range needs,
built from ONLY the selected optional sources, slope always first/outer:

    composite = slope, then for each SELECTED optional source in
    _OPTIONAL_SOURCES order: composite = composite * radix + packed_value

With all 6 selected this is (aspect, forest_type, nasa_quality,
forest_health, landcover, dem in that order) -- the plan's secondary
order, matching `union_zonal`'s RS-10.2 column order. With a subset
selected, the unselected slots are simply absent from the chain (not
zeroed-out placeholders), so selecting fewer sources also shrinks the
composite range, not just the combination count.

Per-slot value, before packing (0 always means "missing at this pixel",
never a real code -- see each source's own comment in `_OPTIONAL_SOURCES`
below for why 0 was free to reuse as that sentinel):

* slope   -- raw 1-4 directly. Never 0: a pixel with no valid slope value
  does not enter the composite AT ALL (the gate) -- there is no "missing
  slope" row in the output.
* aspect  -- raw 0-8 directly. 0 is already "flat / no dominant direction"
  in `rasters.aspect`'s own convention (`aspect_vectorize.py`), the same
  value this module reuses as "missing".
* forest_type -- raw 1-26 directly (26 = "Unclassified", a REAL code that
  competes, RS-9.5 -- not reused as a sentinel). 0 = no DB coverage at this
  pixel.
* nasa_quality -- raw+1 (1-4). NASA's raw 0 is real ground truth (D41) and
  must not collide with "missing", so it is shifted up by one before
  packing; unpacking subtracts 1 back, and unpacked 0 means missing.
* forest_health -- raw 0-5 directly. 0 is already true sensor NoData in
  this source (RS-9.8's `nodata_codes=(0,)` fix), the same value this
  module reuses as "missing".
* landcover -- raw/10 (0-10; ESA's raw codes are 0,10,20,...,100). 0 is
  already NoData in this source, consistent with the others above.
* dem_band -- the per-forest contour band (1-N, `band_table_for`/RS-9.3),
  computed by the CALLER once and passed in -- never 0 here either except
  "outside the DEM's valid range" (`DEM_VALID_PREDICATE`).

Canopy is excluded from the pixel stack entirely (not an optional slot)
because its data source is structurally different from the other 6:
`canopy_vectorize.py` reads a GeoTIFF directly via `rasterio`/`numpy`, not
a PostGIS raster table this module's `ST_MapAlgebraExpr` chain can touch.
Loading that TIF into PostGIS would be new infrastructure, out of scope
for this phase -- so a Union(fusion) piece's canopy class is attached via
the SAME per-piece `canopy_dominant_class(wkt, db)` zonal call Mode B
already uses, run once per final (post-fusion, post-sliver-absorb) piece,
regardless of which optional sources were selected for the pixel fusion
itself. This means canopy boundaries never create a new edge in fusion
mode's own geometry the way a SELECTED pixel-fused source's boundaries do
-- a real, owner-facing distinction (see RASTER_SOURCES_TRACKER.md
RS-10.3's build note and the frontend's own explanatory copy for this
source).
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

from shapely.geometry import shape
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.calculation import Calculation
from app.services.geom_generalize import meters_to_deg

logger = logging.getLogger(__name__)

# 10 m common grid (plan §P10 Mode A step 1) -- the two native-10 m sources
# (NDVI health, ESA land cover) lose nothing; the four native-30 m sources
# (slope, aspect, NASA quality, FRTC) are nearest-neighbor upsampled, never
# interpolated (these are categorical codes).
_PIXEL_DEG = meters_to_deg(10.0)

# Same generalization tail every other carve source uses (smoothing then
# simplify then re-clip last) -- this module's output tiles the same way.
_SMOOTH_M = 15.0
_SIMPLIFY_DEG = 0.00009
# RS-10.3 build note: 500 m2 (0.05 ha) produced 1226 pieces on a 316 ha test
# forest -- unusably fragmented (union_zonal gives 21 for the same forest)
# and made the per-piece dominant_composite re-derivation pass take over two
# minutes. Raised to 2500 m2 (0.25 ha): smaller than MMU's 1 ha default
# (fusion is meant to be finer-grained than a single-source carve), but not
# so small that every real combination gets its own tiny piece.
DEFAULT_SLIVER_M2 = 2500.0

# Every OPTIONAL source this module can fuse, in a fixed order (the plan's
# secondary order / RS-10.2's column order) -- (key, table, radix, cte
# alias, SQL transform of [rast2.val] into that source's 0..radix-1 packed
# slot value). Slope is NOT here: it is always included and is handled
# separately as the chain's starting term (the gate).
_OPTIONAL_SOURCES: tuple[tuple[str, str, int, str, str], ...] = (
    ("aspect", "rasters.aspect", 9, "aspect", "COALESCE([rast2.val], 0)"),
    ("forest_type", "rasters.forest_type", 27, "forest_type", "COALESCE([rast2.val], 0)"),
    ("nasa_quality", "rasters.nasa_forest_2020", 5, "nasa", "COALESCE([rast2.val] + 1, 0)"),
    ("forest_health", "rasters.nepal_forest_health", 6, "health", "COALESCE([rast2.val], 0)"),
    ("landcover", "rasters.esa_world_cover", 11, "landcover", "COALESCE([rast2.val] / 10, 0)"),
    ("dem", "rasters.dem", 6, "dem_band", "COALESCE([rast2.val], 0)"),
)
ALL_OPTIONAL_SOURCE_KEYS: frozenset[str] = frozenset(k for k, *_ in _OPTIONAL_SOURCES)

_SLOPE_TABLE = "rasters.slope_regulation"


def _unpack_key(entry: str) -> str:
    """The `unpack_composite` dict key for one optional source -- `dem`'s
    is `dem_band` (matching `union_zonal`'s own `dominant_contour_band`
    naming one level up), every other source's matches its own key."""
    return "dem_band" if entry == "dem" else entry


def _selected_sources(sources: Iterable[str] | None) -> tuple[tuple[str, str, int, str, str], ...]:
    """Resolve a caller's optional ``sources`` (any subset of
    `ALL_OPTIONAL_SOURCE_KEYS`, or ``None`` for "all of them", the default/
    backward-compatible behaviour) into the ordered subset of
    `_OPTIONAL_SOURCES` to actually fuse. Unknown keys are ignored rather
    than raising -- a stale frontend selection should degrade, not break a
    preview."""
    if sources is None:
        return _OPTIONAL_SOURCES
    wanted = set(sources) & ALL_OPTIONAL_SOURCE_KEYS
    return tuple(e for e in _OPTIONAL_SOURCES if e[0] in wanted)


def _boundary_wkt(calc: Calculation, db: Session) -> str | None:
    return db.execute(
        text("SELECT ST_AsText(boundary_geom) FROM calculations WHERE id = :cid"),
        {"cid": str(calc.id)},
    ).scalar()


def _resample_cte(alias: str, table: str, extra_select: str | None = None) -> str:
    """One source's ``<alias>_u`` (unioned raw tiles, clipped to scope) and
    ``<alias>_rs`` (resampled onto the shared ``ref`` grid) CTE pair.
    ``extra_select`` lets a caller swap in a reclassified/remapped
    expression instead of the raw ``rast`` before resampling (DEM's band
    reclass needs this -- doing it BEFORE resample, not after, keeps
    nearest-neighbor semantics exact)."""
    select_expr = extra_select if extra_select is not None else f"{alias}_u.rast"
    return (
        f"{alias}_u AS ("
        f"  SELECT ST_Union(ST_Clip(r.rast, b.geom)) AS rast"
        f"  FROM {table} r, b WHERE ST_Intersects(r.rast, b.geom)"
        f"),"
        f"{alias}_rs AS ("
        f"  SELECT ST_Resample({select_expr}, ref.rast, 'NearestNeighbor') AS rast"
        f"  FROM {alias}_u, ref"
        f")"
    )


def _combine_expr(prev_alias: str, next_alias: str, radix: int, next_transform: str) -> str:
    """Chain one more source into the running composite, multiplying the
    running total by exactly THAT source's own radix (mixed-radix, not a
    uniform base -- see module docstring; a uniform base-100 pack
    overflowed `32BSI`). ``next_transform`` turns ``[rast2.val]`` into
    that source's packed slot value (0..radix-1) -- the 0-missing/NULL
    distinction is handled by ``COALESCE`` inside ``next_transform``
    itself, not here."""
    return (
        f"ST_MapAlgebraExpr("
        f"{prev_alias}.rast, 1, {next_alias}_rs.rast, 1,"
        f"'CASE WHEN [rast1.val] IS NULL THEN NULL "
        f"ELSE [rast1.val]*{radix} + ({next_transform}) END'::text,"
        f"'32BSI'::text, 'FIRST'::text, '[rast1.val]'::text, NULL::text, NULL::double precision"
        f")"
    )


def _composite_cte_block(
    bands: list[tuple[float, float, int]],
    selected: tuple[tuple[str, str, int, str, str], ...],
) -> str:
    """The shared chain of CTEs (``ref`` through ``composite``) both
    ``union_fusion_pieces`` and ``dominant_composite`` need -- factored out
    so the two can never drift apart on how the composite is built. Only
    emits CTEs for sources actually in ``selected`` (plus slope,
    unconditionally) -- an unselected source costs nothing, not even the
    resample."""
    needs_dem = any(key == "dem" for key, *_ in selected)
    dem_block = ""
    if needs_dem:
        dem_case = " ".join(
            f"WHEN [rast.val] >= {lo} AND [rast.val] < {hi} THEN {code}"
            for lo, hi, code in bands
        )
        dem_reclass_expr = (
            "ST_MapAlgebraExpr(dem_u.rast, 1, '32BSI'::text,"
            f"'CASE WHEN [rast.val] IS NULL OR [rast.val] <= -32000 "
            f"OR [rast.val] < 0 OR [rast.val] > 9000 THEN NULL "
            f"{dem_case} ELSE NULL END'::text, NULL::double precision)"
        )
        dem_block = f""",
        dem_u AS (
            SELECT ST_Union(ST_Clip(r.rast, b.geom)) AS rast
            FROM rasters.dem r, b WHERE ST_Intersects(r.rast, b.geom)
        ),
        dem_band_rs AS (
            SELECT ST_Resample({dem_reclass_expr}, ref.rast, 'NearestNeighbor') AS rast
            FROM dem_u, ref
        )"""

    optional_ctes = ",".join(
        _resample_cte(alias, table)
        for key, table, _radix, alias, _transform in selected
        if key != "dem"
    )
    optional_ctes_sql = ("," + optional_ctes) if optional_ctes else ""

    chain = "c1"
    chain_ctes = []
    for i, (key, _table, radix, alias, transform) in enumerate(selected, start=2):
        rs_alias = "dem_band" if key == "dem" else alias
        next_chain = f"c{i}"
        chain_ctes.append(
            f"{next_chain} AS (SELECT {_combine_expr(chain, rs_alias, radix, transform)} AS rast "
            f"FROM {chain}, {rs_alias}_rs)"
        )
        chain = next_chain
    chain_sql = ("," + ",".join(chain_ctes)) if chain_ctes else ""
    composite_select = f"SELECT rast FROM {chain}" if chain != "c1" else "SELECT rast FROM c1"

    return f"""
        ref AS (
            SELECT ST_AddBand(
                ST_MakeEmptyRaster(
                    GREATEST(1, CEIL((ST_XMax(geom) - ST_XMin(geom)) / :px))::int,
                    GREATEST(1, CEIL((ST_YMax(geom) - ST_YMin(geom)) / :px))::int,
                    ST_XMin(geom), ST_YMax(geom), :px, -:px, 0, 0, 4326
                ), '32BSI'::text, 0, -1
            ) AS rast
            FROM b
        ),
        {_resample_cte("slope", _SLOPE_TABLE)}
        {optional_ctes_sql}
        {dem_block},
        c1 AS (
            SELECT ST_MapAlgebraExpr(
                slope_rs.rast, 1, '32BSI'::text,
                'CASE WHEN [rast.val] IS NULL OR [rast.val] NOT IN (1,2,3,4) THEN NULL ELSE [rast.val] END'::text,
                NULL::double precision
            ) AS rast
            FROM slope_rs
        )
        {chain_sql},
        composite AS ({composite_select})
    """


def union_fusion_pieces(
    calc: Calculation,
    db: Session,
    bands: list[tuple[float, float, int]],
    sliver_m2: float | None = None,
    scope_wkt: str | None = None,
    sources: Iterable[str] | None = None,
) -> list[tuple[int, Any]]:
    """One ``(composite_code, shapely_geom)`` per contiguous same-composite
    region -- the pixel fusion itself (canopy attached separately, see
    module docstring). ``sources`` (RS-10.3b): which OPTIONAL attributes to
    fuse alongside the always-included slope gate -- any subset of
    `ALL_OPTIONAL_SOURCE_KEYS`, or ``None`` for all of them (the default).
    Fewer sources means fewer distinct combinations, so fewer/larger
    pieces and a faster `dominant_composite` pass later -- this is the
    owner's own "make it more usable" lever, not just a filter.

    ``bands`` is the per-forest DEM band table
    (`band_table_for(calc, db, DEM_ELEVATION, boundary_wkt, n_bands=...)`,
    computed ONCE by the caller so Mode A and Mode B never disagree on what
    "High" means -- RS-10.2's correction #3, which governs this module
    equally) -- only read if ``dem`` is among the selected sources. Empty
    list on no coverage or any failure -- SAVEPOINT-guarded, never poisons
    the caller's transaction, same contract as
    `raster_class_vectorize.class_pieces`.
    """
    boundary = _boundary_wkt(calc, db) if scope_wkt is None else None
    if not scope_wkt and not boundary:
        return []
    selected = _selected_sources(sources)
    if any(key == "dem" for key, *_ in selected) and not bands:
        return []

    sql = f"""
        WITH b AS (SELECT ST_GeomFromText(COALESCE(:scope_wkt, :boundary_wkt), 4326) AS geom),
        {_composite_cte_block(bands, selected)},
        px AS (
            SELECT (ST_DumpAsPolygons(rast, 1)).* FROM composite
        ),
        merged AS (
            SELECT val::int AS code, ST_Union(geom) AS geom FROM px GROUP BY val
        ),
        parts AS (
            SELECT code, (ST_Dump(geom)).geom AS geom FROM merged
        ),
        kept AS (
            SELECT code, geom FROM parts
            WHERE ST_Area(geom::geography) >= :sliver
        )
        SELECT code,
               ST_AsGeoJSON(
                 ST_Intersection(
                   ST_SimplifyPreserveTopology(
                     ST_Buffer(ST_Buffer(geom, :smooth, 'join=round'), -:smooth, 'join=round'),
                     :tol
                   ),
                   (SELECT geom FROM b)
                 )
               ) AS gj
        FROM kept
    """
    try:
        with db.begin_nested():
            rows = db.execute(
                text(sql),
                {
                    "scope_wkt": scope_wkt,
                    "boundary_wkt": boundary,
                    "px": _PIXEL_DEG,
                    "sliver": float(sliver_m2 if sliver_m2 is not None else DEFAULT_SLIVER_M2),
                    "smooth": meters_to_deg(_SMOOTH_M),
                    "tol": _SIMPLIFY_DEG,
                },
            ).fetchall()
    except Exception:  # noqa: BLE001 -- any source raster optional/missing -> empty
        logger.debug("union_fusion: pixel fusion unavailable", exc_info=True)
        return []

    out: list[tuple[int, Any]] = []
    for r in rows:
        if not r.gj:
            continue
        geom = shape(__import__("json").loads(r.gj))
        if geom.is_empty:
            continue
        out.append((int(r.code), geom))
    return out


def dominant_composite(
    geom_wkt: str,
    db: Session,
    bands: list[tuple[float, float, int]],
    sources: Iterable[str] | None = None,
) -> int | None:
    """Majority COMPOSITE value inside one geometry -- re-derives a final
    OUTPUT piece's true combination after the shared sliver-absorb/merge
    tail (which operates on bare geometry, the same as every other source
    in this codebase) may have altered it from the raw piece it started
    as. Mirrors `dominant_class`/`dominant_band`'s own role and SQL shape
    (ST_ValueCount + tie-break sort) -- but voting on the COMPOSITE INTEGER
    as a whole, never on the individual slots, which is what makes this
    safe: each composite value that exists in the raster came from one
    real pixel's real combination, so majority-voting the integer can only
    ever return a combination that genuinely exists on the ground -- the
    same guarantee the plan's "whole-tuple, never per-attribute" sliver
    rule was written to protect, reached here by re-deriving from pixels
    instead of inheriting a neighbor's value. ``sources`` MUST be the same
    selection `union_fusion_pieces` was called with, or the composite
    values won't mean the same thing. ``None`` on no coverage or any
    failure (SAVEPOINT-guarded)."""
    selected = _selected_sources(sources)
    if not geom_wkt or (any(key == "dem" for key, *_ in selected) and not bands):
        return None
    try:
        with db.begin_nested():
            row = db.execute(
                text(f"""
                    WITH b AS (SELECT ST_GeomFromText(:wkt, 4326) AS geom),
                    {_composite_cte_block(bands, selected)},
                    px AS (
                        SELECT (ST_ValueCount(ST_Clip(composite.rast, b.geom))).*
                        FROM composite, b
                    )
                    SELECT value FROM px
                    WHERE value IS NOT NULL AND value != -1
                    GROUP BY value
                    ORDER BY SUM(count) DESC, value ASC
                    LIMIT 1
                """),
                {"wkt": geom_wkt, "px": _PIXEL_DEG},
            ).first()
    except Exception:  # noqa: BLE001 -- raster optional / no coverage -> None
        logger.debug("union_fusion: dominant_composite failed", exc_info=True)
        return None
    return int(row.value) if row is not None else None


def unpack_composite(code: int, sources: Iterable[str] | None = None) -> dict[str, int | None]:
    """Reverse ``union_fusion_pieces``'s mixed-radix packing (module
    docstring). ``sources`` MUST be the same selection the composite was
    PACKED with, or this decodes garbage -- always pass the layer's own
    stored selection through, never assume "all of them". Every value is
    ``None`` where the packed slot was 0 (missing) -- except ``aspect``,
    where packed 0 is kept as 0 (flat/no-dominant is itself a real, if
    unclassified, answer, the same convention `aspect_vectorize.py`
    already uses elsewhere). A source NOT in ``sources`` is simply absent
    from the returned dict (not ``None`` -- that would claim "we checked
    and it's missing", which is a different, false statement from
    "we never fused this attribute at all")."""
    selected = _selected_sources(sources)
    remaining = int(code)
    values: dict[str, int] = {}
    for key, _table, radix, _alias, _transform in reversed(selected):
        values[key] = remaining % radix
        remaining //= radix
    slope = remaining

    out: dict[str, int | None] = {"slope": slope or None}
    for key, _table, _radix, _alias, _transform in selected:
        v = values[key]
        if key == "aspect":
            out["aspect"] = v  # 0 kept as 0, never None (flat is real)
        elif key == "nasa_quality":
            out["nasa_quality"] = (v - 1) if v else None
        elif key == "landcover":
            out["landcover"] = (v * 10) if v else None
        elif key == "dem":
            out["dem_band"] = v or None
        else:
            out[key] = v or None
    return out


__all__ = [
    "union_fusion_pieces",
    "unpack_composite",
    "dominant_composite",
    "DEFAULT_SLIVER_M2",
    "ALL_OPTIONAL_SOURCE_KEYS",
]
