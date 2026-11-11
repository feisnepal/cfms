"""Generic class/band vectorizer for the raster-carve sources.

One engine for every PostGIS-backed carve source. This is the port of
``aspect_vectorize.aspect_class_pieces`` and ``sustainable_fm.slope_vectorize.
slope_class_pieces`` into a single spec-driven pair of functions, and the place
rule 19 of the plan is honoured: **the clip polygon is per-compartment when a
scope is supplied, and the whole forest only when it is not.**

The generalization tail (buffer round-trip -> simplify -> re-clip LAST) is
copied byte-for-byte from the reference implementation and is deliberately NOT
improved here. ``ST_SimplifyPreserveTopology`` gives no containment guarantee,
so clipping before it leaves a piece bulging past the true boundary -- the
reference documents this at ``aspect_vectorize.py:99-103`` and
``sustainable_fm/slope_vectorize.py:201-216``, and the two sources' 23
existing tests are the regression net for it.

Two independent failures this module must not reintroduce:

* **Never exclude a class from the *geometry*, only from the *label*.** A gap in
  the carve is not silently absorbed into something sensible: it is either a
  hole in a piece or, worse, a "Remainder Block/Compartment" invented by
  ``block_area_invariant_service``. Every class in ``value_range`` is carved;
  ``anonymous_codes`` get geometry and **no** label.
* **Never read slope/aspect out of the DEM.** ``rasters.slope_regulation`` and
  ``rasters.aspect`` are the prepared class rasters. ``ST_Slope`` on the DEM is
  not used anywhere in this module.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from shapely.geometry import shape
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.calculation import Calculation
from app.services.geom_generalize import meters_to_deg

logger = logging.getLogger(__name__)

# Every table this module will interpolate into SQL. A spec naming anything
# else is rejected before a query is built -- a table name is the one thing here
# that cannot be parameterised, so it is constrained rather than escaped.
_ALLOWED_TABLES: frozenset[str] = frozenset(
    {
        "rasters.slope_regulation",
        "rasters.aspect",
        "rasters.nasa_forest_2020",
        "rasters.nepal_forest_health",
        "rasters.esa_world_cover",
        "rasters.dem",
        # RS-9.5 (P9, owner directive 2026-10-01): RS-4.1a resolved -- the
        # owner's legend is authoritative (class 26 = the raster's own
        # "Non forest", shown in this app as "Unclassified", see
        # core.forest_types). FRTC_BLOCKED_REASON below is now historical.
        "rasters.forest_type",
    }
)

# The DEM's NoData sentinel is -32768 and is NOT registered in the raster
# metadata, so ST_SummaryStats on rasters.dem averages -21,470 m on a real
# boundary. Never use it. (Plan rule 14, verified 2026-09-29.)
DEM_VALID_PREDICATE = "z > -32000 AND z >= 0 AND z <= 9000"

# Floor policy. D38: a flat 5 ha floor throws away 80-99% of a ~30 m class
# mosaic -- measured 1-11 compartments for a 926 ha forest and none at all for
# a 4.4 ha one. So the floor is area-aware, and is never allowed to exceed the
# area it is filtering.
MIN_FLOOR_HA = 1.0
MAX_FLOOR_HA = 50.0
DEFAULT_TARGET_PIECES = 30


@dataclass(frozen=True)
class RasterClassSpec:
    """Everything the engine needs to carve one source, in one place.

    ``default_sliver_m2`` and ``default_floor_ha`` are **defaults only** (plan
    rule 11): the sliver must stay a caller argument, because
    ``slope_class_pieces`` reads it from per-calculation
    ``SfmParams.slope_vector_sliver_m2`` and a spec that owned it would silently
    drop per-forest SFM configuration.
    """

    key: str
    table: str
    pixel_m: float
    value_range: tuple[int, int]
    anonymous_codes: tuple[int, ...]
    smoothing_m: float
    simplify_deg: float
    default_sliver_m2: float
    label_fn: Callable[[int], str]
    # -- D38 additions ---------------------------------------------------
    # Area-aware floor. `target_pieces` is how many compartments a large forest
    # should end up with; the effective floor is derived from it per forest.
    target_pieces: int = DEFAULT_TARGET_PIECES
    min_floor_ha: float = MIN_FLOOR_HA
    max_floor_ha: float = MAX_FLOOR_HA
    # Codes to group into one class before carving (P3.7: ESA 10 + 20 = Forest).
    # Applied as `GROUP` specs are resolved; empty for every other source.
    group_codes: dict[int, int] = field(default_factory=dict)
    # The exact code set to carve, when `value_range` is too wide to enumerate
    # honestly (ESA is 10..100 in steps of 10, not 0..100). None means "every
    # code in value_range", which is what the already-shipping sources use.
    codes: tuple[int, ...] | None = None
    # Owner report 2026-10-01 ("raster data covers all expected extent... I
    # have checked it in QGIS") -- a SUBSET of `anonymous_codes` that are
    # true sensor/no-coverage gaps rather than real ground information, and
    # must be excluded from the dominant-class VOTE, not merely left
    # unlabelled. `anonymous_codes` alone only controls the label
    # (`.label()` returns None); `dominant_class` still counted an anonymous
    # code's raw pixels alongside real classes, so a piece that was genuinely
    # 45% real-class-3 / 42% NoData reported "no classification" because
    # NoData happened to have the plurality -- even though real data existed
    # and the raster's true coverage was fine, confirmed directly against
    # raw ST_ValueCount on the live raster. Whether an anonymous code belongs
    # here is a PER-SOURCE decision, not automatic: NASA's anonymous code 0
    # is real ground truth ("non-forest", D41) and must keep competing for
    # dominance -- only a code that means "we have no reading here" belongs
    # in `nodata_codes`. Empty tuple (default) preserves every already
    # owner-tested source's existing behaviour unchanged.
    nodata_codes: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if self.table not in _ALLOWED_TABLES:
            raise ValueError(f"table not in module allow-list: {self.table}")

    @property
    def smoothing_deg(self) -> float:
        return meters_to_deg(self.smoothing_m)

    def label(self, code: int) -> str | None:
        """``None`` for an anonymous code -- geometry without a label."""
        if code in self.anonymous_codes:
            return None
        return self.label_fn(code)


def effective_floor_ha(spec: RasterClassSpec, forest_area_m2: float) -> float:
    """The D38 floor: area-aware, and never so high that a forest yields nothing.

    ``area / target_pieces`` gives a large forest a proportionally larger floor
    (so a 926 ha forest yields compartments rather than 10 of them), clamped to
    the spec's bounds. If even the clamped floor would swallow the whole forest,
    the floor becomes the whole area -- one piece -- because a source that
    returns nothing is indistinguishable from a broken one, whereas one piece
    surfaces the honest ``DIVISION_TOO_FEW`` error (plan rule 17).
    """
    area_ha = float(forest_area_m2 or 0.0) / 10_000.0
    if area_ha <= 0:
        return spec.min_floor_ha
    floor = area_ha / max(int(spec.target_pieces), 1)
    floor = max(spec.min_floor_ha, min(floor, spec.max_floor_ha))
    if floor >= area_ha:
        return area_ha
    return floor


# --------------------------------------------------------------------------
# The four shippable specs (RS-1.3). Labels come from the single vocabularies in
# app/core/forest_types.py -- RS-0.5's whole point was that a source used to
# carry a private label dict that disagreed with the map beside it.
# --------------------------------------------------------------------------
def _vocab_label(
    table_attr: str, *, zero: str
) -> Callable[[int], str]:
    """A label function bound to ONE vocabulary table.

    Deliberately not shared between sources. Health and NASA both use small
    integers for unrelated things -- 1 is "Stressed" in one and "Primary Forest"
    in the other -- so a single "look it up in whichever table has this code"
    function silently renames half the classes, which is the exact defect
    RS-0.5 removed from ``raster_zonal``. Each spec therefore names its own
    table, and a code missing from it falls through to ``Class <n>`` rather than
    borrowing another source's name.

    ``zero`` is what code 0 means for this source, which differs per source and
    is the one thing a generic fallback cannot know.
    """
    def label(code: int) -> str:
        import app.core.forest_types as ft

        if code == 0:
            return zero
        table = getattr(ft, table_attr)
        entry = table.get(code)
        return entry.name_en if entry is not None else f"Class {code}"

    return label


#: NASA 2020 forest quality. 3 classes (1-3); code 0 is **non-forest** and is
#: carved as geometry but never claims a class (anonymous_codes, rule 9).
#: Carve-and-anonymous, per RS-2.5 (measured 0-share is 1-48% of a real forest
#: and 100% of the two 4.4 ha ones, so "exclude" was disqualified), and mandated
#: by the RS-2.3 storage bounds: `dominant_nasa_quality` is 1-3, so code 0 can
#: never be a persisted class either.
NASA_QUALITY = RasterClassSpec(
    key="nasa_quality",
    table="rasters.nasa_forest_2020",
    pixel_m=27.0,
    value_range=(0, 3),
    anonymous_codes=(0,),
    smoothing_m=22.0,
    simplify_deg=0.00013,
    default_sliver_m2=1000.0,
    # Code 0 is real, mappable ground (grassland, bare, urban) that simply is
    # not forest. Measured it is 1-48% of a real forest and 100% of a 4.4 ha
    # one, so calling it NoData would be both a lie and a hole in the map.
    label_fn=_vocab_label("NASA_FOREST_QUALITY", zero="Non-forest"),
    target_pieces=30,
    codes=(0, 1, 2, 3),
)

#: NDVI stored as a 5-class forest-health map. 0 is NoData: carved, never
#: labelled.
NDVI_HEALTH = RasterClassSpec(
    key="forest_health",
    table="rasters.nepal_forest_health",
    pixel_m=10.0,
    value_range=(0, 5),
    anonymous_codes=(0,),
    # 2026-10-01 (owner report, confirmed against raw ST_ValueCount on the
    # live raster): unlike NASA's 0, NDVI's 0 is a TRUE sensor/no-reading
    # gap, not a real ground class -- it must not win the dominant-class
    # vote over a real class 1-5 just because it happens to have more raw
    # pixels in a merged piece. See `RasterClassSpec.nodata_codes`.
    nodata_codes=(0,),
    smoothing_m=12.0,
    simplify_deg=0.00008,
    default_sliver_m2=1000.0,
    # Code 1 is "Stressed" here and "Primary Forest" for NASA; the label is
    # bound to this table alone so the two can never be confused.
    label_fn=_vocab_label("FOREST_HEALTH_CLASSES", zero="NoData"),
    target_pieces=40,
    codes=(0, 1, 2, 3, 4, 5),
)

#: ESA WorldCover 2021. Grouped 10 + 20 -> "Forest" (P3.7): grouping, not
#: filtering, per plan rule 9. The code set is enumerated because ESA is
#: 10..100 in steps of 10, not a contiguous 0..100.
ESA_LANDCOVER = RasterClassSpec(
    key="esa_landcover",
    table="rasters.esa_world_cover",
    pixel_m=10.0,
    value_range=(0, 100),
    anonymous_codes=(0,),
    # 2026-10-01 (same audit that found NDVI's bug): ESA's own legend
    # (ESA_WORLD_COVER in forest_types.py) has no entry for 0 -- unlike
    # NASA's 0, which is defined ground truth (D41). It is sensor/encoding
    # NoData and must not win the dominant-class vote over a real class
    # just because it has more raw pixels in a merged piece.
    nodata_codes=(0,),
    smoothing_m=12.0,
    simplify_deg=0.00008,
    default_sliver_m2=1000.0,
    label_fn=_vocab_label("ESA_WORLD_COVER", zero="NoData"),
    target_pieces=40,
    codes=(0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100),
    group_codes={10: 10, 20: 10},
)

#: DEM, continuous. Carved through `reclass_pieces` with a band table computed
#: one level UP (plan rule 16): cuts come from the parent or the forest
#: boundary, never from a compartment, because per-compartment mean +/- SD makes
#: "High" mean a different altitude in every compartment.
DEM_ELEVATION = RasterClassSpec(
    key="dem_zones",
    table="rasters.dem",
    pixel_m=30.0,
    value_range=(0, 9000),
    anonymous_codes=(),
    smoothing_m=22.0,
    simplify_deg=0.00013,
    default_sliver_m2=1000.0,
    label_fn=lambda code: {1: "Low", 2: "Mid", 3: "High"}.get(code, f"Zone {code}"),
    target_pieces=20,
)

#: The two already-shipping sources, so RS-1.2 can repoint them onto this
#: engine without changing behaviour. `target_pieces` is deliberately unused for
#: them: they keep their tuned 5 ha floor (plan rule 10).
SLOPE_CLASSES = RasterClassSpec(
    key="slope",
    table="rasters.slope_regulation",
    pixel_m=30.0,
    value_range=(1, 4),
    anonymous_codes=(),
    smoothing_m=22.0,
    simplify_deg=0.00013,
    default_sliver_m2=1000.0,
    label_fn=lambda code: {
        1: "Gentle",
        2: "Moderate",
        3: "Steep",
        4: "Very Steep",
    }.get(code, f"Class {code}"),
    target_pieces=1,
    min_floor_ha=5.0,
    max_floor_ha=5.0,
)

ASPECT_CLASSES = RasterClassSpec(
    key="aspect",
    table="rasters.aspect",
    pixel_m=30.0,
    value_range=(1, 8),
    anonymous_codes=(),
    smoothing_m=22.0,
    simplify_deg=0.00013,
    default_sliver_m2=1000.0,
    label_fn=lambda code: {
        1: "N",
        2: "NE",
        3: "E",
        4: "SE",
        5: "S",
        6: "SW",
        7: "W",
        8: "NW",
    }.get(code, f"Class {code}"),
    target_pieces=1,
    min_floor_ha=5.0,
    max_floor_ha=5.0,
)

#: FRTC 2015 forest type, 26 classes. Code 26 ("Unclassified" in this app,
#: "Non forest" in the raster's own legend) is anonymous (RS-9.5, RS-4.1a
#: resolved 2026-10-01): carved as geometry so tiling stays exact, but never
#: claimed as one of the 25 named types -- the same treatment NASA 2020 code 0
#: gets, decided independently from FRTC's own 78%-of-raster distribution
#: (test_frtc_legend.py), not inherited from NASA's rule (D50).
FRTC_FOREST_TYPE = RasterClassSpec(
    key="forest_type",
    table="rasters.forest_type",
    pixel_m=30.0,
    value_range=(1, 26),
    anonymous_codes=(26,),
    smoothing_m=22.0,
    simplify_deg=0.00013,
    default_sliver_m2=1000.0,
    # `zero=` is inert here (FRTC's raw values are 1-26, never 0) -- kept only
    # because `_vocab_label` requires it; `.label()` never calls label_fn for
    # 26 anyway, since it is in `anonymous_codes` above.
    label_fn=_vocab_label("FRTC_FOREST_TYPES", zero="Unclassified"),
    target_pieces=30,
    codes=tuple(range(1, 27)),
)

SPECS_BY_KEY: dict[str, RasterClassSpec] = {
    s.key: s
    for s in (
        NASA_QUALITY, NDVI_HEALTH, ESA_LANDCOVER, DEM_ELEVATION,
        SLOPE_CLASSES, ASPECT_CLASSES, FRTC_FOREST_TYPE,
    )
}

#: Historical (RS-1.3 asked for a FRTC spec "marked blocked" pending RS-0.2/
#: RS-4.1a; both are resolved as of 2026-10-01, RS-9.5). Kept only because
#: existing code/tests may still reference the name; no longer enforced --
#: `FRTC_FOREST_TYPE` above is registered in `SPECS_BY_KEY` and
#: `rasters.forest_type` is in the module allow-list.
FRTC_BLOCKED_REASON = (
    "HISTORICAL — resolved 2026-10-01 (RS-9.5). rasters.forest_type (FRTC) "
    "was blocked on data (RS-0.2) and then on the class-26 contradiction "
    "(RS-4.1a); the owner's legend is authoritative and 26 is carved as an "
    "anonymous class, shown as 'Unclassified'."
)


# --------------------------------------------------------------------------
# Fetch helpers
# --------------------------------------------------------------------------
def _boundary_wkt(calc: Calculation, db: Session) -> str | None:
    return db.execute(
        text("SELECT ST_AsText(boundary_geom) FROM calculations WHERE id = :cid"),
        {"cid": str(calc.id)},
    ).scalar()


def _clip_cte() -> str:
    """The rule-19 clip polygon.

    ``COALESCE(:scope_wkt, :boundary_wkt)`` is the whole point: with no scope the
    query is exactly the whole-forest fetch the reference implementations do
    today, and with a scope the fetch is compartment-sized **in SQL**, instead of
    vectorising the entire forest per compartment and discarding it in Python.
    """
    return (
        "b AS (SELECT ST_GeomFromText("
        "COALESCE(:scope_wkt, :boundary_wkt), 4326) AS geom)"
    )


def _carve_sql(spec: RasterClassSpec, raster_expr: str, codes: list[int]) -> str:
    """`px -> merged -> parts -> kept -> smooth -> simplify -> re-clip last`.

    ``raster_expr`` is the raster handed to ``ST_DumpAsPolygons``: the clipped
    table cell for a class raster, or a reclassed copy for a continuous one.
    Either way the band column it yields is named ``val`` -- ``ST_Reclass``
    renumbers the values, not the column -- so the two paths share this SQL
    verbatim and only the fetch differs.
    """
    if not codes:
        raise ValueError(f"{spec.key}: no codes to carve")
    in_list = ", ".join(str(c) for c in sorted(codes))
    # P3.7 grouping is a remap, never a filter: ESA 20 (Deciduous forest) folds
    # into 10 (Tree cover) so the map shows one "Forest" class. Rule 9 is the
    # reason this cannot be a WHERE clause -- excluding a code leaves a gap, and
    # a gap becomes a hole in a piece or an invented "Remainder" unit.
    if spec.group_codes:
        when_parts = " ".join(
            f"WHEN {raw} THEN {target}"
            for raw, target in sorted(spec.group_codes.items())
            if raw != target
        )
        code_expr = f"(CASE val::int {when_parts} ELSE val::int END)"
    else:
        code_expr = "val::int"
    return f"""
        WITH {_clip_cte()},
        px AS (
            SELECT (ST_DumpAsPolygons({raster_expr}, 1)).*
            FROM {spec.table} r, b
            WHERE ST_Intersects(r.rast, b.geom)
        ),
        mapped AS (
            SELECT {code_expr} AS code, geom FROM px
            WHERE {code_expr} IN ({in_list})
        ),
        merged AS (
            SELECT code, ST_Union(geom) AS geom FROM mapped GROUP BY code
        ),
        parts AS (
            SELECT code, (ST_Dump(geom)).geom AS geom FROM merged
        ),
        kept AS (
            SELECT code, geom FROM parts
            WHERE ST_Area(geom::geography) >= :sliver
        )
        SELECT code,
               -- Re-clip to the boundary as the ABSOLUTE LAST step, AFTER
               -- simplify: ST_SimplifyPreserveTopology gives no containment
               -- guarantee, so clipping before it leaves a piece bulging a few
               -- metres past the true forest boundary.
               ST_AsGeoJSON(
                 ST_Intersection(
                   ST_SimplifyPreserveTopology(
                     ST_Buffer(ST_Buffer(geom, :smooth, 'join=round'),
                               -:smooth, 'join=round'),
                     :tol
                   ),
                   (SELECT geom FROM b)
                 )
               ) AS gj
        FROM kept
    """  # noqa: S608 -- table constrained by RasterClassSpec.__post_init__


def _codes_for(spec: RasterClassSpec, value_filter: tuple[int, ...] | None) -> list[int]:
    lo, hi = spec.value_range
    base = list(spec.codes) if spec.codes is not None else list(range(lo, hi + 1))
    if value_filter is None:
        return base
    wanted = [c for c in value_filter if c in base]
    if not wanted:
        raise ValueError(
            f"{spec.key}: value_filter {value_filter} excludes every code in {base}"
        )
    return wanted


def _rows_to_pieces(rows: Any) -> list[tuple[int, Any]]:
    out: list[tuple[int, Any]] = []
    for r in rows:
        if not r.gj:
            continue
        geom = shape(json.loads(r.gj))
        if geom.is_empty:
            continue
        out.append((int(r.code), geom))
    return out


def class_pieces(
    calc: Calculation,
    db: Session,
    spec: RasterClassSpec,
    sliver_m2: float | None = None,
    value_filter: tuple[int, ...] | None = None,
    scope_wkt: str | None = None,
) -> list[tuple[int, Any]]:
    """One ``(class_code, shapely_geom)`` per contiguous same-class region inside
    ``scope_wkt`` (or the forest boundary when no scope is given).

    Every code in the spec's range is carved, including ``anonymous_codes`` --
    they get geometry and no label. SAVEPOINT-guarded: a missing or
    non-covering raster returns ``[]`` and never poisons the transaction.
    """
    boundary = _boundary_wkt(calc, db) if scope_wkt is None else None
    if not scope_wkt and not boundary:
        return []
    codes = _codes_for(spec, value_filter)
    q = text(_carve_sql(spec, "ST_Clip(r.rast, b.geom)", codes))
    try:
        with db.begin_nested():
            rows = db.execute(
                q,
                {
                    "scope_wkt": scope_wkt,
                    "boundary_wkt": boundary,
                    "sliver": float(sliver_m2 if sliver_m2 is not None else spec.default_sliver_m2),
                    "tol": spec.simplify_deg,
                    "smooth": spec.smoothing_deg,
                },
            ).fetchall()
    except Exception:  # noqa: BLE001 -- raster optional / no coverage -> empty
        logger.debug("%s: %s unavailable", spec.key, spec.table, exc_info=True)
        return []
    return _rows_to_pieces(rows)


def _code_in_filter(spec: RasterClassSpec) -> tuple[str, list[int]]:
    """``(sql_fragment, codes)`` for "is this a real class of this spec" in a
    raw ``ST_ValueCount`` result, where no CASE remap has happened yet.

    Uses the enumerated ``codes`` set when the spec has one, not the numeric
    ``value_range``: ESA's range is ``0..100`` but only 10..100 in steps of 10
    exists, and a value filter over a range the raster never uses is a lie about
    what the source can produce.
    """
    codes = list(spec.codes) if spec.codes is not None else list(
        range(spec.value_range[0], spec.value_range[1] + 1)
    )
    return "value IN (" + ", ".join(str(c) for c in sorted(codes)) + ")", codes


#: Why a dominant class came back the way it did. `dominant_code` used to
#: return a bare `None` for the first three of these, so "this compartment is
#: mostly non-forest" and "the raster never covered it" and "the query blew up"
#: were one indistinguishable blank cell in the attribute table (RS-2.14).
DOMINANT_OK = "ok"
DOMINANT_ANONYMOUS = "anonymous"
DOMINANT_NO_COVERAGE = "no_coverage"
DOMINANT_FAILED = "failed"
DOMINANT_NO_GEOMETRY = "no_geometry"


@dataclass(frozen=True)
class DominantClass:
    """A dominant-class answer that can explain itself.

    ``code`` is what may be persisted: ``None`` whenever the dominant code is an
    ``anonymous_code`` (a real, mappable class that is simply not a *class* this
    vocabulary reports). ``raw_code`` keeps that dominant code including the
    anonymous ones, so a caller can show "Non-forest (0)" instead of a blank.
    ``reason`` is which of the outcomes above produced this.
    """

    code: int | None
    raw_code: int | None
    reason: str


def classify_dominant(raw: int | None, spec: RasterClassSpec) -> DominantClass:
    """Turn one raw dominant code into the answer, with its reason.

    Pure, so the decision that RS-2.14 is really about -- code 0 is a real class
    that is not *reported* as one, and is nothing like "no coverage" -- is
    testable without a raster, a PostGIS version, or a geometry.
    """
    if raw is None:
        return DominantClass(None, None, DOMINANT_NO_COVERAGE)
    # Report the GROUPED code, matching what the carve produced: a compartment
    # dominated by ESA 20 belongs to the same "Forest" class as one dominated by
    # 10, and returning 20 would put a code on the map that no feature carries.
    code = spec.group_codes.get(raw, raw)
    if code in spec.anonymous_codes:
        return DominantClass(None, raw, DOMINANT_ANONYMOUS)
    return DominantClass(code, raw, DOMINANT_OK)


def dominant_class(geom_wkt: str, db: Session, spec: RasterClassSpec) -> DominantClass:
    """Majority class inside one geometry, with the reason it is what it is.

    2026-10-01 (owner report, confirmed against the live raster): a plain
    "most pixels wins" vote lets a TRUE no-data code (`spec.nodata_codes`)
    beat a real class whenever NoData happens to have the plurality in one
    merged piece -- even on a forest with excellent overall raster coverage,
    because sliver-absorption groups many small raw pieces (some NoData-
    heavy, some data-heavy) into one, and whichever has more raw pixels wins
    for the WHOLE merged piece. When `spec.nodata_codes` is non-empty, the
    real classes compete among themselves FIRST; a no-data code only wins
    when the piece truly has no real classification at all. Sources with no
    `nodata_codes` (NASA/ESA/FRTC, whose anonymous codes are real ground
    information by their own owner decisions) are completely unaffected --
    this fetches every row either way and the Python-side preference is a
    no-op when the exclusion set is empty.
    """
    if not geom_wkt:
        return DominantClass(None, None, DOMINANT_NO_GEOMETRY)
    in_filter, _ = _code_in_filter(spec)
    try:
        with db.begin_nested():
            rows = db.execute(
                text(
                    f"""
                    WITH g AS (SELECT ST_GeomFromText(:wkt, 4326) AS geom),
                    px AS (
                      SELECT (ST_ValueCount(ST_Clip(rast, g.geom))).*
                      FROM {spec.table}, g
                      WHERE ST_Intersects(rast, g.geom)
                    )
                    SELECT value FROM px
                    WHERE {in_filter}
                    GROUP BY value
                    -- The secondary sort is load-bearing: without it an exact tie
                    -- between two classes resolves arbitrarily, so the same
                    -- compartment could be classified differently on two runs.
                    ORDER BY SUM(count) DESC, value ASC
                    """
                ),  # noqa: S608 -- table constrained by RasterClassSpec
                {"wkt": geom_wkt},
            ).fetchall()
    except Exception:  # noqa: BLE001 -- raster optional / no coverage -> None
        logger.debug("%s dominant_code failed", spec.key, exc_info=True)
        return DominantClass(None, None, DOMINANT_FAILED)
    if not rows:
        return classify_dominant(None, spec)
    if spec.nodata_codes:
        real = next((r for r in rows if int(r.value) not in spec.nodata_codes), None)
        if real is not None:
            return classify_dominant(int(real.value), spec)
    return classify_dominant(int(rows[0].value), spec)


def dominant_code(geom_wkt: str, db: Session, spec: RasterClassSpec) -> int | None:
    """Majority class inside one geometry, or ``None``.

    Thin wrapper over :func:`dominant_class` for callers that only need the
    persistable code and are happy to treat every absence as one thing.
    """
    return dominant_class(geom_wkt, db, spec).code


# --------------------------------------------------------------------------
# Continuous path (DEM)
# --------------------------------------------------------------------------
def band_table_for(
    calc: Calculation,
    db: Session,
    spec: RasterClassSpec,
    stats_wkt: str | None = None,
    *,
    target_pieces: int | None = None,
    n_bands: int = 3,
) -> list[tuple[float, float, int]]:
    """``n_bands`` EQUAL-ELEVATION-INTERVAL cuts -> ``[(lo_cut, hi_cut, code), ...]``.

    RS-9.3 (owner directive, 2026-10-01): "divide by contour line, a fixed
    number of bands" -- replaces the original mean +/- SD scheme (P3.5,
    cancelled by D51) with cuts spaced evenly across the observed elevation
    RANGE (``[zmin, zmax]``), not the pixel-count distribution. At 30 m DEM
    resolution the vectorized boundary between two adjacent bands traces that
    elevation's isoline at pixel granularity -- a real contour, stepped to the
    raster grid, not a synthetic percentile edge. Equal-interval bands also
    sidestep D51's actual objection to the old scheme (percentile-of-pixel-
    count bands straddle ridges/drainage because area, not elevation, decided
    the cut) -- an equal-elevation cut is a real, fixed altitude everywhere it
    is drawn, which is what "contour" means.

    ``stats_wkt`` is the polygon the statistics are computed over, and per plan
    rule 16 that is the **parent** (divide) or the **forest boundary**
    (auto-create) -- never the compartment being carved, so "band 2" means the
    same altitude range everywhere in one forest.

    Returns ``[]`` when the raster does not cover ``stats_wkt``. A flat
    forest (``zmax <= zmin``) is a real case (a plateau), not an error: it
    yields a single band, so the caller gets one zone instead of N identical
    ones.
    """
    polygon = stats_wkt or _boundary_wkt(calc, db)
    if not polygon:
        return []
    try:
        with db.begin_nested():
            row = db.execute(
                text(
                    f"""
                    WITH g AS (SELECT ST_GeomFromText(:wkt, 4326) AS geom),
                    clip AS (
                        SELECT ST_Clip(rast, g.geom) AS rast
                        FROM {spec.table}, g
                        WHERE ST_Intersects(rast, g.geom)
                        LIMIT 1
                    ),
                    px AS (SELECT (ST_PixelAsPolygons(rast)).val AS z FROM clip)
                    SELECT MIN(z), MAX(z), COUNT(*)
                    FROM px WHERE {DEM_VALID_PREDICATE}
                    """
                ),  # noqa: S608 -- table constrained by RasterClassSpec
                {"wkt": polygon},
            ).first()
    except Exception:  # noqa: BLE001 -- raster optional / no coverage
        logger.debug("%s: band_table_for failed", spec.key, exc_info=True)
        return []
    if not row or not row[2]:
        return []

    zmin, zmax = float(row[0]), float(row[1])
    n = max(1, int(n_bands))
    if zmax <= zmin or n == 1:
        return [(zmin - 1.0, zmax + 1.0, 1)]

    step = (zmax - zmin) / n
    bands: list[tuple[float, float, int]] = []
    lo = zmin - 1.0
    for i in range(n):
        hi = (zmin + step * (i + 1)) if i < n - 1 else zmax + 1.0
        bands.append((lo, hi, i + 1))
        lo = hi
    return bands


def dominant_band(
    geom_wkt: str, db: Session, spec: RasterClassSpec, bands: list[tuple[float, float, int]]
) -> DominantClass:
    """Majority BAND inside one geometry, for a continuous-raster spec.

    `dominant_class`/`dominant_code` cannot be reused here: they match a
    piece's raw pixel VALUES against `spec.value_range` (elevations 0-9000
    for DEM), which answers "what is the modal altitude", not "which band
    does this piece belong to". This re-reclassifies the piece's own clip
    against the SAME ``bands`` the preview carved with (bands are per-forest,
    computed by `band_table_for` -- never assume a caller's fixed table) and
    majority-votes the resulting band codes, mirroring `dominant_class`'s own
    SQL shape (``ST_ValueCount`` + the tie-breaking sort).
    """
    if not geom_wkt:
        return DominantClass(None, None, DOMINANT_NO_GEOMETRY)
    if not bands:
        return DominantClass(None, None, DOMINANT_FAILED)
    codes = [code for _lo, _hi, code in bands]
    in_list = ", ".join(str(c) for c in sorted(codes))
    expr = f"ST_Reclass(ST_Clip(rast, g.geom), '{reclass_expression(bands)}', '16BUI')"
    try:
        with db.begin_nested():
            row = db.execute(
                text(
                    f"""
                    WITH g AS (SELECT ST_GeomFromText(:wkt, 4326) AS geom),
                    px AS (
                      SELECT (ST_ValueCount({expr})).*
                      FROM {spec.table} rast, g
                      WHERE ST_Intersects(rast, g.geom)
                    )
                    SELECT value FROM px
                    WHERE value IN ({in_list})
                    GROUP BY value
                    ORDER BY SUM(count) DESC, value ASC
                    LIMIT 1
                    """
                ),  # noqa: S608 -- table constrained by RasterClassSpec; codes are ints from `bands`
                {"wkt": geom_wkt},
            ).first()
    except Exception:  # noqa: BLE001 -- raster optional / no coverage -> failed
        logger.debug("%s dominant_band failed", spec.key, exc_info=True)
        return DominantClass(None, None, DOMINANT_FAILED)
    if not row:
        return DominantClass(None, None, DOMINANT_NO_COVERAGE)
    code = int(row.value)
    return DominantClass(code, code, DOMINANT_OK)


def reclass_expression(bands: list[tuple[float, float, int]]) -> str:
    """``ST_Reclass`` 3-arg expression for this PostGIS (plan rule 15).

    The documented 5-arg form does not exist in 3.6.2 and ``'16BF'`` is
    rejected, so the pixel type is the third argument. The DEM's NoData sentinel
    needs the double-negative row ``'-32768--1:0'``.
    """
    rows = [f"{lo:g}-{hi:g}:{code}" for lo, hi, code in bands]
    return ",".join(["-32768--1:0", *rows])


def reclass_pieces(
    calc: Calculation,
    db: Session,
    spec: RasterClassSpec,
    bands: list[tuple[float, float, int]],
    sliver_m2: float | None = None,
    scope_wkt: str | None = None,
) -> list[tuple[int, Any]]:
    """``class_pieces`` for a continuous raster: same tail, different fetch.

    Only the piece fetch differs from ``class_pieces`` -- an ``ST_Reclass`` step
    turns the continuous values into the three band codes, and everything
    downstream (union, dump, sliver, smooth, simplify, re-clip last) is shared.
    That is the split ``auto_block_service.py:729-732`` already describes for
    the four categorical sources.
    """
    if not bands:
        return []
    boundary = _boundary_wkt(calc, db) if scope_wkt is None else None
    if not scope_wkt and not boundary:
        return []
    codes = [code for _lo, _hi, code in bands]
    expr = (
        f"ST_Reclass(ST_Clip(r.rast, b.geom), '{reclass_expression(bands)}', '16BUI')"
    )
    q = text(_carve_sql(spec, expr, codes))
    try:
        with db.begin_nested():
            rows = db.execute(
                q,
                {
                    "scope_wkt": scope_wkt,
                    "boundary_wkt": boundary,
                    "sliver": float(sliver_m2 if sliver_m2 is not None else spec.default_sliver_m2),
                    "tol": spec.simplify_deg,
                    "smooth": spec.smoothing_deg,
                },
            ).fetchall()
    except Exception:  # noqa: BLE001 -- raster optional / no coverage -> empty
        logger.debug("%s: reclass_pieces failed", spec.key, exc_info=True)
        return []
    return _rows_to_pieces(rows)


__all__ = [
    "ASPECT_CLASSES",
    "DEM_ELEVATION",
    "ESA_LANDCOVER",
    "FRTC_BLOCKED_REASON",
    "FRTC_FOREST_TYPE",
    "NASA_QUALITY",
    "NDVI_HEALTH",
    "SLOPE_CLASSES",
    "SPECS_BY_KEY",
    "RasterClassSpec",
    "band_table_for",
    "class_pieces",
    "dominant_band",
    "dominant_code",
    "effective_floor_ha",
    "reclass_expression",
    "reclass_pieces",
]
