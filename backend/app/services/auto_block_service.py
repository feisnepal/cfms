"""Auto-block generation from the natural-feature MMU layer (`base.mmu`).

Two-stage workflow (preview → commit) for the "Automatic Block Creation from
Natural Feature Boundary (MMU)" plan:

- ``preview_mmu_blocks`` clips ``base.mmu`` tiles to the calculation's forest
  boundary entirely server-side (GiST pre-filter + per-tile ST_Intersection),
  dedupes tile overlaps, absorbs slivers (< ``MMU_SLIVER_AREA_M2``, default
  1 ha, overridable per request) into their
  largest touching neighbour, and returns a descending FeatureCollection with a
  serial (``Block-N`` / ``Compartment-N``), per-piece ``natural_name``
  (best-effort nearest named river/ridge), plus adjacency edges so the frontend
  can run the target-N merge live.
- ``commit_blocks`` persists the accepted serial + merged geometries as
  ``forest_blocks`` rows (with ``block_name`` / ``natural_name``), refusing
  (409 BLOCKS_EXIST) whenever any block/compartment already exists.

The 841k-tile MMU layer is NEVER loaded to the browser; only the ~dozens of
clipped pieces for the chosen forest are returned.
"""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from geoalchemy2.shape import from_shape
from shapely import make_valid
from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from shapely.ops import unary_union
from sqlalchemy import text
from sqlalchemy.orm.attributes import set_committed_value

from ..core.constants import MMU_SLIVER_AREA_M2, SQM_PER_HA
from ..core.naming_strategies import compartment_serial, block_serial
from ..models.forest_block import ForestBlock
from ..models.raster_layer import RasterLayer
from ..services.forest_units.operations.sampling_mutex import _check_sampling_mutex as sampling_mutex_check
from ..services.forest_units.operations.virtual_root import hole_protect_geom
from ..services.geometry_edit_service import bump_geometry_version
from ..utils.single_part_geometry import explode_and_filter_slivers

from app.core.dropped import report_dropped

logger = logging.getLogger(__name__)

# Overlap dedupe epsilon: two pieces whose intersection exceeds this area are
# considered genuinely overlapping (MMU tiles occasionally share a sliver).
OVERLAP_EPSILON_M2: float = 1.0

# Strict max distance (metres) from a block centroid for a natural-name label
# (user-confirmed: river84/ridge/settlement names ONLY within 50 m).
NATURAL_NAME_MAX_DISTANCE_M: float = 50.0

# Hole-fill threshold (m²): interior rings (voids) smaller than this are filled.
# Defaults to MMU sliver floor (1 ha) so tiny artifact holes disappear but
# legitimate clearings/lakes above 1 ha are preserved.
MMU_HOLE_FILL_AREA_M2: float = MMU_SLIVER_AREA_M2

_MMU_INTERSECT_SQL = text(
    """
    WITH calc AS (
        SELECT id, boundary_geom FROM calculations WHERE id = :calc_id
    ),
    tiles AS (
        SELECT mmu.mmuid, mmu.geom
        FROM base.mmu mmu
        CROSS JOIN calc c
        WHERE ST_Intersects(mmu.geom, c.boundary_geom)
    ),
    clipped AS (
        SELECT t.mmuid,
               (ST_Dump(ST_CollectionExtract(
                   ST_Intersection(t.geom, c.boundary_geom), 3
               ))).geom AS piece
        FROM tiles t CROSS JOIN calc c
    )
    SELECT ST_AsGeoJSON(piece) AS geojson
    FROM clipped
    """
)


def _as_shapely(geojson):
    if geojson is None:
        return None
    if isinstance(geojson, str):
        geojson = json.loads(geojson)
    try:
        return shape(geojson)
    except Exception:
        logger.exception(
            "geometry could not be parsed - it is treated as absent by the "
            "block generator"
        )
        return None


def _explode_multiparts(pieces: List[Any]) -> List[Any]:
    """Guarantee single-part blocks.

    Union/sliver-absorption can produce ``MultiPolygon``s (disjoint parts). A
    multipart block would render as one feature with several polygons, so
    clicking it selects "multiple blocks" and merging adjacent neighbours is
    impossible — the same serial would appear in several places (user report,
    Phase C review). Splitting every MultiPolygon into its parts makes each
    block one contiguous polygon.

    Delegates to ``explode_and_filter_slivers`` (the shared single-part
    invariant helper) rather than a narrow local ``isinstance(Polygon |
    MultiPolygon)`` check: ``_absorb_coverage_gaps`` unions a piece with a
    raw difference()/gap fragment, and ``make_valid`` on that union can come
    back as a ``GeometryCollection`` mixing the real polygon(s) with
    degenerate LineString/Point repair noise (see
    ``single_part_geometry._polygon_parts``'s docstring) — a type neither
    ``Polygon`` nor ``MultiPolygon`` matches. The old local version silently
    dropped such a piece *in its entirety*, including its real polygon
    content: found live on हिमाल forest (2026-09-13), where one
    gap-absorbing piece carrying ~192 ha of real coverage was a
    `GeometryCollection` and vanished here, leaving only ~30% of the
    boundary covered by the committed blocks and forcing a single crude
    remainder block to patch the "missing" 70% — the "no outer boundary,
    only inner polygons" symptom the user reported. ``min_area_m2=0.0`` here
    preserves this function's existing behaviour of not dropping by a sliver
    floor (that is `_absorb_slivers`'s job, already run before this step) —
    only genuinely zero-area repair noise is discarded.
    """
    return explode_and_filter_slivers(pieces, min_area_m2=0.0)


def _area_m2(geom) -> float:
    try:
        from ..utils.geometry_utils import calculate_area_geodesic_from_shapely

        sqm, _ = calculate_area_geodesic_from_shapely(geom)
        return float(sqm or 0.0)
    except Exception:
        logger.warning(
            "geodesic area failed - falling back to a planar approximation, "
            "which overstates the block area used for the 5 ha floor",
            exc_info=True,
        )
        return float(getattr(geom, "area", 0.0) or 0.0) * (111_320.0**2)


def _as_polygonal(geom: Any) -> Any:
    """Re-normalize the result of a ``.union()`` back to a bare
    ``Polygon``/``MultiPolygon`` (never a ``GeometryCollection``).

    ``make_valid`` on a union of two already-valid polygons can still come
    back as a ``GeometryCollection`` mixing the real polygon(s) with
    degenerate lower-dimension repair noise (see
    ``single_part_geometry._polygon_parts``'s docstring). Both
    ``_absorb_slivers`` and ``_absorb_coverage_gaps`` mutate a piece in place
    across loop iterations and pass it straight back into
    ``_shared_boundary_m`` on the next pass — a lingering
    ``GeometryCollection`` there degrades that comparison to "not adjacent"
    (``GeometryCollection.boundary`` is ``None``, not raised) instead of
    just at the very end where ``_explode_multiparts`` cleans it up anyway.
    Normalizing right after each union keeps every intermediate comparison
    correct, not just the final output.
    """
    parts = explode_and_filter_slivers([geom], min_area_m2=0.0)
    if not parts:
        return geom
    if len(parts) == 1:
        return parts[0]
    return unary_union(parts)


def _shared_boundary_m(a: Any, b: Any) -> float:
    """Length (approx metres) of the boundary two pieces share.

    ``GeometryCollection.boundary`` is ``None`` in Shapely (not an exception,
    not an empty geometry) — a real case here, since ``_absorb_coverage_gaps``
    can leave a piece as a ``GeometryCollection`` mid-loop (a union with a
    gap fragment that ``make_valid`` had to repair). Treated the same as "no
    shared edge" rather than raising, same graceful degrade as the
    except-block below (found live on हिमाल forest, 2026-09-13: fired ~78
    times in one preview, degrading adjacency for every pair touching that
    one piece).
    """
    try:
        if not a.intersects(b):
            return 0.0
        a_boundary = a.boundary
        b_boundary = b.boundary
        if a_boundary is None or b_boundary is None:
            return 0.0
        shared = a_boundary.intersection(b_boundary)
        if shared is None or shared.is_empty:
            return 0.0
        return float(shared.length * 111_320.0)
    except Exception:
        # 0.0 means "these two tiles share no edge", so a real neighbour
        # stops being a merge candidate and the tile is absorbed elsewhere.
        logger.exception(
            "shared-edge length failed - the two tiles are treated as not "
            "adjacent, which changes which blocks get merged"
        )
        return 0.0


def _hole_is_protected(hole_poly: Any, protect_geom: Any) -> bool:
    """G1 (FS-4a.12): does ``hole_poly`` materially coincide with excluded
    ground (private land ∪ protection units)? Mirrors
    ``geometry_edit_service._hole_is_protected`` — kept as its own tiny copy
    rather than a cross-module import, since the two files already duplicate
    ``_fill_holes`` itself (pieces-list vs single-geom shape) and reusing
    ONE unit's helper from the other would tie their load order together for
    no benefit."""
    if protect_geom is None or protect_geom.is_empty:
        return False
    try:
        inter = hole_poly.intersection(protect_geom)
    except Exception:  # noqa: BLE001 -- an unreadable protect_geom must not crash hole-fill
        logger.warning("[hole-fill] protect_geom overlap check failed", exc_info=True)
        return False
    if inter is None or inter.is_empty:
        return False
    hole_area = _area_m2(hole_poly)
    if hole_area <= 0:
        return False
    return (_area_m2(inter) / hole_area) >= 0.5


def _fill_holes(
    pieces: List[Any],
    hole_fill_area_m2: Optional[float] = None,
    protect_geom: Any = None,
) -> List[Any]:
    """Fill interior holes (voids) smaller than ``hole_fill_area_m2``.

    base.mmu tiles often contain thin artifact holes that look like lines at
    normal zoom but are actual polygon interiors. Filling holes below the
    sliver threshold (default 1 ha) removes these voids while preserving
    legitimate clearings/lakes.

    ``protect_geom`` (G1, FS-4a.12) — private land ∪ protection units
    (``operations.virtual_root.hole_protect_geom``). A hole that materially
    overlaps it is kept regardless of size — it is deliberately excluded
    ground, not an MMU rendering artifact, and every caller below passes it
    so a private plot under the sliver threshold is never silently
    re-absorbed into an auto-generated block.
    """
    if hole_fill_area_m2 is None:
        hole_fill_area_m2 = MMU_HOLE_FILL_AREA_M2

    filled: List[Any] = []
    for p in pieces:
        if p is None or p.is_empty:
            continue
        p = make_valid(p)
        if isinstance(p, Polygon):
            if p.interiors:
                # Filter interiors: keep only those larger than threshold
                kept_interiors = []
                for interior in p.interiors:
                    hole_poly = Polygon(interior)
                    if _area_m2(hole_poly) >= hole_fill_area_m2 or _hole_is_protected(
                        hole_poly, protect_geom
                    ):
                        kept_interiors.append(interior)
                if kept_interiors:
                    filled.append(Polygon(p.exterior, kept_interiors))
                else:
                    filled.append(Polygon(p.exterior))
            else:
                filled.append(p)
        elif isinstance(p, MultiPolygon):
            new_parts = []
            for part in p.geoms:
                if isinstance(part, Polygon):
                    if part.interiors:
                        kept_interiors = []
                        for interior in part.interiors:
                            hole_poly = Polygon(interior)
                            if _area_m2(hole_poly) >= hole_fill_area_m2 or _hole_is_protected(
                                hole_poly, protect_geom
                            ):
                                kept_interiors.append(interior)
                        if kept_interiors:
                            new_parts.append(Polygon(part.exterior, kept_interiors))
                        else:
                            new_parts.append(Polygon(part.exterior))
                    else:
                        new_parts.append(part)
                else:
                    new_parts.append(part)
            if new_parts:
                filled.append(
                    MultiPolygon(new_parts) if len(new_parts) > 1 else new_parts[0]
                )
        else:
            filled.append(p)
    return filled


def _dedupe_overlaps(pieces: List[Any]) -> List[Any]:
    """Remove genuine overlaps between MMU tiles (keep the larger piece)."""
    cleaned: List[Any] = []
    for p in pieces:
        if p is None or p.is_empty:
            continue
        p = make_valid(p)
        if not isinstance(p, (Polygon, MultiPolygon)):
            continue
        for i, other in enumerate(cleaned):
            if other is None or other.is_empty:
                continue
            try:
                inter = p.intersection(other)
                if inter.is_empty or _area_m2(inter) <= OVERLAP_EPSILON_M2:
                    continue
            except Exception:
                report_dropped(
                    logger,
                    "overlap test",
                    "the pair is treated as not overlapping, so an overlap may "
                    "survive into the generated blocks",
                )
                continue
            # Keep the larger polygon; carve the overlap out of the smaller.
            if _area_m2(p) >= _area_m2(other):
                other = make_valid(other.difference(p))
                cleaned[i] = other if not other.is_empty else None
            else:
                p = make_valid(p.difference(other))
                if p.is_empty:
                    break
        if p is not None and not p.is_empty:
            cleaned.append(p)
    return [c for c in cleaned if c is not None and not c.is_empty]


def _absorb_slivers(
    pieces: List[Any],
    sliver_area_m2: Optional[float] = None,
    force_absorb_orphans: bool = False,
) -> Tuple[List[Any], int]:
    """Drop pieces < sliver floor, absorbing their area into the largest
    touching neighbour (coverage preserved). Returns (kept, absorbed_count).
    The floor defaults to the SSOT constant ``MMU_SLIVER_AREA_M2`` (1 ha) but
    can be overridden per request at auto-block creation time.

    If ``force_absorb_orphans=True``, pieces below the floor that have no
    touching neighbour (orphans) are forcibly merged into the largest
    remaining piece by area."""
    if sliver_area_m2 is None:
        sliver_area_m2 = MMU_SLIVER_AREA_M2
    absorbed = 0
    result = [p for p in pieces if p is not None and not p.is_empty]
    changed = True
    while changed:
        changed = False
        i = 0
        while i < len(result):
            if _area_m2(result[i]) >= sliver_area_m2:
                i += 1
                continue
            sliver = result[i]
            best_idx = -1
            best_shared = 0.0
            for j in range(len(result)):
                if i == j:
                    continue
                shared = _shared_boundary_m(sliver, result[j])
                if shared > best_shared:
                    best_shared = shared
                    best_idx = j
            if best_idx >= 0:
                result[best_idx] = _as_polygonal(make_valid(result[best_idx].union(sliver)))
                result.pop(i)
                absorbed += 1
                changed = True
            elif force_absorb_orphans and len(result) > 1:
                # No touching neighbour — merge into the largest piece by area
                best_area = -1.0
                for j in range(len(result)):
                    if i == j:
                        continue
                    area = _area_m2(result[j])
                    if area > best_area:
                        best_area = area
                        best_idx = j
                if best_idx >= 0:
                    result[best_idx] = _as_polygonal(make_valid(result[best_idx].union(sliver)))
                    result.pop(i)
                    absorbed += 1
                    changed = True
                else:
                    i += 1  # truly isolated (only piece left)
            else:
                i += 1  # orphan sliver — keep as-is (do not delete area)
    return result, absorbed


def _absorb_coverage_gaps(pieces: List[Any], boundary_geom: Any) -> List[Any]:
    """Merge any residual gap between the union of ``pieces`` and
    ``boundary_geom`` into whichever piece shares the most boundary with
    that gap fragment.

    A raster-derived source that generalizes its polygon boundaries (see
    ``app/services/geom_generalize.py``) smooths each classified region
    independently, which can leave a tiny sliver of uncovered area exactly
    where an internal class-to-class seam meets the forest boundary — each
    side of the seam rounds its own corner there on its own, and neither
    knows about the other. ``_absorb_slivers`` cannot catch this: a
    coverage GAP is not one of the pieces in the list, it is the area no
    piece covers at all.

    Left unabsorbed, this is exactly what ``commit_blocks``'s own coverage
    invariant (``editing.py``'s ``REMAINDER_COMPARTMENT_ADDED`` /
    ``REMAINDER_BLOCK_ADDED``) would silently patch with an extra block at
    commit time — meaning the committed set would differ from what preview
    showed the user. Closing it here, before the preview response is built,
    keeps preview and commit piece counts identical. A no-op for a source
    whose pieces already exactly tile the boundary (MMU, or slope/aspect/
    canopy with generalization disabled)."""
    if boundary_geom is None or not pieces:
        return pieces
    try:
        covered = unary_union([p for p in pieces if p is not None and not p.is_empty])
        gap = make_valid(boundary_geom).difference(covered)
    except Exception:
        logger.exception(
            "coverage-gap computation failed - any residual gap is left for "
            "commit's own remainder-block invariant to patch instead"
        )
        return pieces
    if gap is None or gap.is_empty:
        return pieces

    for frag in _explode_multiparts([gap]):
        if frag is None or frag.is_empty:
            continue
        # Ignore genuinely negligible floating-point slivers (sub-cm2) —
        # merging those would be pure noise, not a real gap.
        if _area_m2(frag) < 0.01:
            continue
        best_idx = -1
        best_shared = 0.0
        for j, p in enumerate(pieces):
            shared = _shared_boundary_m(frag, p)
            if shared > best_shared:
                best_shared = shared
                best_idx = j
        if best_idx >= 0:
            pieces[best_idx] = _as_polygonal(make_valid(pieces[best_idx].union(frag)))
        # else: an orphan gap fragment touching no piece at all (should not
        # happen for a gap strictly inside the boundary) — left for
        # commit's own invariant, same graceful fallback as above.
    return pieces


def _nearest_natural_names(
    db, lons: List[float], lats: List[float], calc_id: str
) -> List[Optional[str]]:
    """Nearest named river84/ridge/settlement within NATURAL_NAME_MAX_DISTANCE_M.

    Single batched query: candidates for the whole boundary are prefiltered by
    the envelope GiST index (once, cheap), then a per-centroid LATERAL KNN with
    a strict geodesic ST_DWithin distance cut.  Returns one name (or None) per
    (lon, lat), in input order.
    """
    if not lons:
        return []
    try:
        # SAVEPOINT: a missing/erroring reference table (river.ridge etc. -
        # optional, best-effort labelling) must roll back only this query, not
        # poison the caller's transaction. Without this, a failed statement
        # left the session in Postgres's "current transaction is aborted"
        # state, so every query AFTER this best-effort one (including the
        # caller's own db.commit() in commit_blocks) failed too.
        with db.begin_nested():
            rows = db.execute(
                text(
                    """
                WITH named AS MATERIALIZED (
                    SELECT name, g FROM (
                        SELECT ridge_name AS name, geom AS g FROM river.ridge
                         WHERE ridge_name IS NOT NULL AND btrim(ridge_name) <> ''
                           AND geom && (SELECT ST_Expand(ST_Envelope(boundary_geom), 0.01) FROM calculations WHERE id = :calc_id)
                        UNION ALL
                        SELECT "river name" AS name, shape AS g FROM river.river84
                         WHERE "river name" IS NOT NULL AND btrim("river name") <> ''
                           AND shape && (SELECT ST_Expand(ST_Envelope(boundary_geom), 0.01) FROM calculations WHERE id = :calc_id)
                        UNION ALL
                        SELECT river_name AS name, geom AS g FROM river.river_line
                         WHERE river_name IS NOT NULL AND btrim(river_name) <> ''
                           AND geom && (SELECT ST_Expand(ST_Envelope(boundary_geom), 0.01) FROM calculations WHERE id = :calc_id)
                        UNION ALL
                        SELECT vil_name AS name, shape AS g FROM admin.settlement
                         WHERE vil_name IS NOT NULL AND btrim(vil_name) <> ''
                           AND shape && (SELECT ST_Expand(ST_Envelope(boundary_geom), 0.01) FROM calculations WHERE id = :calc_id)
                    ) n
                    WHERE name IS NOT NULL
                ),
                pts AS (
                    SELECT unnest(:lons) AS lon, unnest(:lats) AS lat
                )
                SELECT cand.name
                FROM pts
                LEFT JOIN LATERAL (
                    SELECT name
                    FROM named
                    WHERE ST_DWithin(g::geography, ST_SetSRID(ST_MakePoint(pts.lon, pts.lat), 4326)::geography, :maxdist)
                    ORDER BY g <-> ST_SetSRID(ST_MakePoint(pts.lon, pts.lat), 4326)
                    LIMIT 1
                ) cand ON true
                """
                ),
                {
                    "calc_id": str(calc_id),
                    "lons": lons,
                    "lats": lats,
                    "maxdist": NATURAL_NAME_MAX_DISTANCE_M,
                },
            ).fetchall()
        return [str(r[0]) if r and r[0] else None for r in rows]
    except Exception as e:  # best-effort — never fail the whole preview for a label
        logger.warning("[auto_block] natural-name batch failed: %s", e)
        return [None] * len(lons)


def _adjacency_edges(pieces: List[Any]) -> List[Dict[str, Any]]:
    """Shared-edge graph (index pairs + approx shared metres) for the merge UI."""
    edges: List[Dict[str, Any]] = []
    for i in range(len(pieces)):
        for j in range(i + 1, len(pieces)):
            shared = _shared_boundary_m(pieces[i], pieces[j])
            if shared > 1.0:
                edges.append({"a": i, "b": j, "shared_m": round(shared, 1)})
    return edges


def _boundary_shape(db, calc, scope: Optional[Any] = None):
    """The polygon a preview must tile: the forest boundary, or — when dividing a
    selected feature — that feature's ``scope`` (see :func:`resolve_divide_scope`)."""
    if scope is not None:
        return scope
    boundary_row = db.execute(
        text("SELECT ST_AsGeoJSON(boundary_geom) FROM calculations WHERE id = :calc_id"),
        {"calc_id": str(calc.id)},
    ).fetchone()
    return shape(json.loads(boundary_row[0]))


def _clip_to_scope(pieces: List[Any], scope: Optional[Any]) -> List[Any]:
    """Clip freshly fetched pieces to the feature being divided. A no-op without a
    scope, so the whole-forest path is untouched. Every source is fetched for the
    whole forest and clipped here — one seam, source-agnostic."""
    if scope is None:
        return pieces
    kept: List[Any] = []
    for p in pieces:
        if p is None or p.is_empty:
            continue
        clipped = _as_polygonal(make_valid(p).intersection(scope))
        if clipped is not None and not clipped.is_empty and _area_m2(clipped) >= OVERLAP_EPSILON_M2:
            kept.append(clipped)
    if not kept:
        raise ValueError("no_coverage_in_feature")
    return kept


def _serial(level: str, i: int) -> str:
    """Serial of the i-th proposed unit: blocks ``Block-N``, compartments ``C<N>``
    (``naming_strategies.compartment_serial``) - the same format every other path uses."""
    return compartment_serial(i) if level == "compartments" else block_serial(i)


def _merge_plan(pieces: List[Any], edges: List[Dict[str, Any]], n: int) -> List[Any]:
    """Server-side largest-anchor merge: keep the N largest as anchors; every
    smaller piece merges into the adjacent anchor with the longest shared
    boundary. Returns exactly N merged polygons (parity with the client)."""
    if n <= 0 or n >= len(pieces):
        return [p for p in pieces]
    by_area = sorted(range(len(pieces)), key=lambda i: -_area_m2(pieces[i]))
    anchors = set(by_area[:n])
    remaining = by_area[n:]
    groups: Dict[int, List[int]] = {a: [a] for a in anchors}
    for piece_idx in remaining:
        best_anchor = -1
        best_shared = 0.0
        for e in edges:
            if e["a"] == piece_idx and e["b"] in anchors:
                cand, shared = e["b"], e["shared_m"]
            elif e["b"] == piece_idx and e["a"] in anchors:
                cand, shared = e["a"], e["shared_m"]
            else:
                continue
            if shared > best_shared:
                best_shared = shared
                best_anchor = cand
        if best_anchor >= 0:
            groups[best_anchor].append(piece_idx)
        else:
            # no direct anchor neighbour — fold into the smallest anchor
            smallest = min(anchors, key=lambda a: _area_m2(pieces[a]))
            groups[smallest].append(piece_idx)
    merged = []
    for a in anchors:
        poly = unary_union([pieces[x] for x in groups[a]])
        merged.append(make_valid(poly))
    return merged


def _applied_floor_ha(sliver_area_m2) -> float:
    """The minimum-piece-size actually in force for a preview, in hectares (RS-2.9).

    **The floor and the sliver are TWO knobs, not one** (corrected D45). There is
    a SQL-side *carve* filter and a separate Python-side *absorb* floor:

    - the carve filter is `ST_Area >= sliver_area_m2` inside `class_pieces`, and
      `_fill_holes` / `_absorb_slivers` / `_absorb_coverage_gaps` use the same
      value as the smallest piece worth keeping;
    - the **area-aware absorb floor** is computed on top of it by `effective_floor_ha`
      with the forest's area, for the raster sources, because a fixed hectare floor
      yields wildly different piece counts across forests.

    An earlier version of this docstring claimed one knob and cited
    `467 -> 96`, which conflated the two. **Both numbers are live measurements**
    from D45: with a 0.1 ha carve filter and no area-aware floor, NASA returned
    **467** pieces across the 14 live boundaries; with the area-aware floor
    applied it returns **111**, and **106** after the sliver absorb. Neither is
    "the" answer -- they are three different stages.

    The figure has to be derived from the value in force rather than stated as a
    constant: `"minimize_floor_ha": 5.0` was hardcoded in all five previews from
    before the raster sources existed, so no preview ever applied a 5 ha floor,
    and the API and the designer (`AutoBlockDesigner.tsx` interpolates this
    number into a tooltip and a button label) both advertised a filter that was
    not running.

    Every caller resolves `sliver_area_m2` from its own default before building
    the meta, so the value handed in is the one the engine used.
    """
    return round(float(sliver_area_m2) / SQM_PER_HA, 2)


#: Preview property name -> the `dominant_*` column it is stored in.
#:
#: The previews emit **bare** keys (`slope_band`, `aspect_code`, `canopy_class`,
#: `nasa_quality`) because that is what the source registry calls them, while
#: `commit_blocks` writes them into `dominant_*` columns. The two halves of the
#: service therefore disagreed on the name, and only the frontend bridged it: it
#: renames the key when it builds the payload (`AutoBlockDesigner.tsx:378-381`).
#: Every test that exercised commit→persist also did the rename by hand, which
#: is why the mismatch survived -- the workaround was encoded instead of the
#: contract (RS-2.10). Any other caller handing preview output straight to commit
#: persisted NULL for **every** block, with no error.
#:
#: `aspect_code` is the one that cannot be derived by stripping the `dominant_`
#: prefix, which is why this is an explicit table rather than a convention.
_PREVIEW_CLASS_KEYS = {
    "dominant_slope_band": "slope_band",
    "dominant_aspect": "aspect_code",
    "dominant_canopy_class": "canopy_class",
    "dominant_nasa_quality": "nasa_quality",
    # The raw NASA class, 0 included. The preview key and the column name are the
    # same, so this self-map is documentation rather than translation: it says
    # "this one is already spelled the same on both sides" and keeps the RS-2.10
    # guards (which are keyed on the map) honest about the new column (RS-2.14).
    "dominant_nasa_code": "dominant_nasa_code",
    "dominant_health_class": "health_class",
    "dominant_landcover": "landcover",
    # RS-2.19's `dominant_elevation_zone` is computed post-hoc in
    # `commit_blocks` (`assign_relative_elevation_zones`) for every source, so
    # it has no preview-side key here -- unlike the others, nothing ever
    # sends it as a commit payload property.
    "dominant_forest_type": "forest_type",
    "dominant_contour_band": "contour_band",
}


def _dominant_class(req, field):
    """Read a dominant class off a commit payload.

    Accepts either spelling: the `dominant_*` column name (what the frontend
    sends) or the bare key its own preview emitted (what a service-level
    preview→commit hand-off sends). The `dominant_*` name wins when both are
    present, so this can only ever add a value the caller meant to supply -- it
    cannot override an explicit one.
    """
    val = req.get(field)
    if val is None:
        val = req.get(_PREVIEW_CLASS_KEYS.get(field, ""))
    return val


def preview_mmu_blocks(
    db,
    calc,
    level: str = "blocks",
    desired_n: Optional[int] = None,
    sliver_area_m2: Optional[float] = None,
    force_absorb_orphans: bool = False,
    scope: Optional[Any] = None,
) -> Dict[str, Any]:
    """Stage 1 — clip `base.mmu` to the forest boundary (server-side only).

    Returns {meta, pieces} where pieces is a descending FeatureCollection with
    serial ``name``/``block_name`` and best-effort ``natural_name`` per piece.
    ``sliver_area_m2`` overrides the SSOT 1-ha floor per request (optional).
    ``force_absorb_orphans`` merges sub-threshold pieces even if they have no
    touching neighbour (into the largest remaining piece by area)."""
    if calc.boundary_geom is None:
        raise ValueError("no_boundary")
    if sliver_area_m2 is None:
        sliver_area_m2 = MMU_SLIVER_AREA_M2


    rows = db.execute(_MMU_INTERSECT_SQL, {"calc_id": str(calc.id)}).fetchall()
    pieces = [_as_shapely(r.geojson) for r in rows]
    pieces = _clip_to_scope(pieces, scope)
    pieces = _fill_holes(pieces, sliver_area_m2, protect_geom=hole_protect_geom(db, calc))
    pieces = _dedupe_overlaps(pieces)
    pieces, absorbed = _absorb_slivers(pieces, sliver_area_m2, force_absorb_orphans)
    boundary_shape = _boundary_shape(db, calc, scope)
    pieces = _absorb_coverage_gaps(pieces, boundary_shape)
    # Single-part guarantee (user report, Phase C): union/sliver absorption can
    # leave MultiPolygons; each disjoint part becomes its own block so no serial
    # is ever split across separate polygons.
    pieces = _explode_multiparts(pieces)
    pieces = [make_valid(p) for p in pieces if p is not None and not p.is_empty]
    pieces.sort(key=lambda p: -_area_m2(p))

    # Re-absorb AFTER the single-part explode. Force-merging an isolated orphan
    # unions it into a *disjoint* MultiPolygon, which `_explode_multiparts`
    # above would split straight back into the sub-floor island the user asked
    # to merge — so sub-threshold pieces still surfaced in the preview (and,
    # via commit's own explode, in the attribute table): "increasing or
    # decreasing the minimum area works partially but not fully". Running the
    # floor absorb as the LAST geometry step guarantees no sub-floor piece
    # survives on its own; an intentionally force-merged orphan stays one
    # multi-part block (folded area, single serial) rather than a separate row.
    pieces, _reabsorbed = _absorb_slivers(pieces, sliver_area_m2, force_absorb_orphans)
    absorbed += _reabsorbed
    pieces = [make_valid(p) for p in pieces if p is not None and not p.is_empty]
    pieces.sort(key=lambda p: -_area_m2(p))

    total_ha = sum(_area_m2(p) for p in pieces) / SQM_PER_HA
    boundary_ha = _area_m2(boundary_shape) / SQM_PER_HA

    edges = _adjacency_edges(pieces)

    if desired_n is not None:
        merged = _merge_plan(pieces, edges, desired_n)
        merged.sort(key=lambda p: -_area_m2(p))
        pieces = merged

    features = []
    centroids = []
    for p in pieces:
        try:
            centroid = p.representative_point() if not p.is_empty else p.centroid
        except Exception:
            logger.exception(
                "representative point failed - the block will be generated "
                "without a centroid, so it cannot be labelled on the map"
            )
            centroid = None
        centroids.append(centroid)

    valid = [(i, c) for i, c in enumerate(centroids) if c is not None]
    names = _nearest_natural_names(
        db, [c.x for _, c in valid], [c.y for _, c in valid], str(calc.id)
    )
    name_map = {i: nm for (i, _), nm in zip(valid, names)}

    for i, p in enumerate(pieces, start=1):
        props = {"index": i, "name": _serial(level, i), "block_name": _serial(level, i)}
        props["natural_name"] = name_map.get(i - 1)
        props["area_hectares"] = round(_area_m2(p) / SQM_PER_HA, 4)
        features.append(
            {"type": "Feature", "properties": props, "geometry": p.__geo_interface__}
        )

    meta = {
        "source_layer": "base.mmu",
        "basis": "rivers & ridges",
        "level": level,
        "boundary_ha": round(boundary_ha, 2),
        "pieces_ha": round(total_ha, 2),
        "slivers_absorbed": absorbed,
        "piece_count": len(features),
        # Derived from the floor in force, not a hardcoded 5 ha: this is the
        # count the "minimize" button jumps to, so it has to agree with the
        # floor reported directly above it (RS-2.9). Guarded against a zero or
        # negative floor, and clamped to at least 1 so a sub-floor forest still
        # has a target instead of dividing by nothing.
        "minimize_n": max(1, int(total_ha // _applied_floor_ha(sliver_area_m2)))
        if _applied_floor_ha(sliver_area_m2) > 0
        else 1,
        "adjacency_edge_count": len(edges),
        "sliver_area_m2": sliver_area_m2,
        "minimize_floor_ha": _applied_floor_ha(sliver_area_m2),
    }

    return {
        "meta": meta,
        "pieces": {"type": "FeatureCollection", "features": features},
        "edges": edges,
    }


def preview_slope_blocks(
    db,
    calc,
    level: str = "blocks",
    desired_n: Optional[int] = None,
    sliver_area_m2: Optional[float] = None,
    force_absorb_orphans: bool = False,
    scope: Optional[Any] = None,
) -> Dict[str, Any]:
    """Stage 1, slope-class source — carve the forest boundary along
    slope-class breaks (< 19° / 19-31° / 31-45° / > 45°, कार्यविधि §15.2)
    instead of `base.mmu`.

    Shares every post-fetch step with `preview_mmu_blocks` (hole-fill, overlap
    dedupe, sliver-absorb, single-part explode, adjacency + optional
    server-side merge, serial naming, best-effort natural-name join) — only
    the initial piece fetch differs, so this is source-agnostic downstream.
    `sliver_area_m2` overrides the SfmParams slope-vectorization floor
    (default ~1000 m², distinct from MMU's 1 ha floor - slope terrain
    naturally carves into smaller contiguous zones than river/ridge tiles).
    ``force_absorb_orphans`` merges sub-threshold pieces even if they have no
    touching neighbour (into the largest remaining piece by area)."""
    if calc.boundary_geom is None:
        raise ValueError("no_boundary")

    from app.services.sustainable_fm.sfm_config import resolve_params
    from app.services.sustainable_fm.slope_vectorize import (
        BAND_LABELS,
        slope_class_pieces,
        slope_profile,
    )

    params = resolve_params(db, calc.id)
    if sliver_area_m2 is None:
        sliver_area_m2 = float(params.slope_vector_sliver_m2 or 1000.0)


    # Rule 19: the scope goes into the fetch, not only into the Python clip
    # below. Without it a divide re-vectorized the WHOLE forest once per
    # compartment and threw most of it away — `_clip_to_scope` then made that
    # look correct. `_clip_to_scope` stays as the correctness net (D28).
    banded = slope_class_pieces(
        calc, db, params, scope_wkt=scope.wkt if scope is not None else None
    )
    if not banded:
        raise ValueError("no_slope_coverage")
    pieces = [geom for _band, geom in banded]
    pieces = _clip_to_scope(pieces, scope)

    pieces = _fill_holes(pieces, sliver_area_m2, protect_geom=hole_protect_geom(db, calc))
    pieces = _dedupe_overlaps(pieces)
    pieces, absorbed = _absorb_slivers(pieces, sliver_area_m2, force_absorb_orphans)
    boundary_shape = _boundary_shape(db, calc, scope)
    pieces = _absorb_coverage_gaps(pieces, boundary_shape)
    pieces = _explode_multiparts(pieces)
    pieces = [make_valid(p) for p in pieces if p is not None and not p.is_empty]
    pieces.sort(key=lambda p: -_area_m2(p))

    # Re-absorb AFTER the single-part explode. Force-merging an isolated orphan
    # unions it into a *disjoint* MultiPolygon, which `_explode_multiparts`
    # above would split straight back into the sub-floor island the user asked
    # to merge — so sub-threshold pieces still surfaced in the preview (and,
    # via commit's own explode, in the attribute table): "increasing or
    # decreasing the minimum area works partially but not fully". Running the
    # floor absorb as the LAST geometry step guarantees no sub-floor piece
    # survives on its own; an intentionally force-merged orphan stays one
    # multi-part block (folded area, single serial) rather than a separate row.
    pieces, _reabsorbed = _absorb_slivers(pieces, sliver_area_m2, force_absorb_orphans)
    absorbed += _reabsorbed
    pieces = [make_valid(p) for p in pieces if p is not None and not p.is_empty]
    pieces.sort(key=lambda p: -_area_m2(p))

    total_ha = sum(_area_m2(p) for p in pieces) / SQM_PER_HA
    boundary_ha = _area_m2(boundary_shape) / SQM_PER_HA

    edges = _adjacency_edges(pieces)

    if desired_n is not None:
        merged = _merge_plan(pieces, edges, desired_n)
        merged.sort(key=lambda p: -_area_m2(p))
        pieces = merged
        # Adjacency for the (now merged) piece set, for a further live re-merge.
        edges = _adjacency_edges(pieces)

    centroids = []
    for p in pieces:
        try:
            centroids.append(p.representative_point() if not p.is_empty else p.centroid)
        except Exception:
            logger.exception(
                "representative point failed - the block will be generated "
                "without a centroid, so it cannot be labelled on the map"
            )
            centroids.append(None)

    valid = [(i, c) for i, c in enumerate(centroids) if c is not None]
    names = _nearest_natural_names(
        db, [c.x for _, c in valid], [c.y for _, c in valid], str(calc.id)
    )
    name_map = {i: nm for (i, _), nm in zip(valid, names)}

    features = []
    for i, p in enumerate(pieces, start=1):
        # A dominant band per OUTPUT piece (not the input band) - sliver
        # absorption/merging can fold pieces of different origin bands
        # together, so the classification must be re-derived from the final
        # geometry rather than carried forward from the input piece.
        try:
            prof = slope_profile(p.wkt, db, params)
        except Exception:
            logger.exception(
                "slope_profile failed for a generated piece - it is labelled "
                "with no slope band rather than a guessed one"
            )
            prof = {"dominant_band": None}
        band = prof.get("dominant_band")
        label_ne, label_en = (
            BAND_LABELS.get(band, (None, None)) if band else (None, None)
        )
        props = {
            "index": i,
            "name": _serial(level, i),
            "block_name": _serial(level, i),
            "natural_name": name_map.get(i - 1),
            "slope_band": band,
            "slope_band_label_ne": label_ne,
            "slope_band_label_en": label_en,
            "area_hectares": round(_area_m2(p) / SQM_PER_HA, 4),
        }
        features.append(
            {"type": "Feature", "properties": props, "geometry": p.__geo_interface__}
        )

    meta = {
        "source_layer": "rasters.slope_regulation",
        "basis": "slope class (§15.2)",
        "level": level,
        "boundary_ha": round(boundary_ha, 2),
        "pieces_ha": round(total_ha, 2),
        "slivers_absorbed": absorbed,
        "piece_count": len(features),
        # Derived from the floor in force, not a hardcoded 5 ha: this is the
        # count the "minimize" button jumps to, so it has to agree with the
        # floor reported directly above it (RS-2.9). Guarded against a zero or
        # negative floor, and clamped to at least 1 so a sub-floor forest still
        # has a target instead of dividing by nothing.
        "minimize_n": max(1, int(total_ha // _applied_floor_ha(sliver_area_m2)))
        if _applied_floor_ha(sliver_area_m2) > 0
        else 1,
        "adjacency_edge_count": len(edges),
        "sliver_area_m2": sliver_area_m2,
        "minimize_floor_ha": _applied_floor_ha(sliver_area_m2),
    }

    return {
        "meta": meta,
        "pieces": {"type": "FeatureCollection", "features": features},
        "edges": edges,
    }


def preview_aspect_blocks(
    db,
    calc,
    level: str = "blocks",
    desired_n: Optional[int] = None,
    sliver_area_m2: Optional[float] = None,
    force_absorb_orphans: bool = False,
    scope: Optional[Any] = None,
) -> Dict[str, Any]:
    """Stage 1, aspect source — carve the forest boundary along
    compass-direction breaks (rasters.aspect, 1-8 = N/NE/E/SE/S/SW/W/NW,
    matching `analysis.py::analyze_aspect`'s scheme). Same shared pipeline as
    `preview_mmu_blocks`/`preview_slope_blocks` downstream of the piece fetch.
    ``force_absorb_orphans`` merges sub-threshold pieces even if they have no
    touching neighbour (into the largest remaining piece by area)."""
    if calc.boundary_geom is None:
        raise ValueError("no_boundary")

    from app.services.aspect_vectorize import (
        ASPECT_LABELS,
        aspect_class_pieces,
        aspect_dominant_code,
    )

    if sliver_area_m2 is None:
        sliver_area_m2 = 1000.0


    coded = aspect_class_pieces(
        calc, db, sliver_area_m2, scope_wkt=scope.wkt if scope is not None else None
    )
    if not coded:
        raise ValueError("no_aspect_coverage")
    pieces = [geom for _code, geom in coded]
    pieces = _clip_to_scope(pieces, scope)

    pieces = _fill_holes(pieces, sliver_area_m2, protect_geom=hole_protect_geom(db, calc))
    pieces = _dedupe_overlaps(pieces)
    pieces, absorbed = _absorb_slivers(pieces, sliver_area_m2, force_absorb_orphans)
    boundary_shape = _boundary_shape(db, calc, scope)
    pieces = _absorb_coverage_gaps(pieces, boundary_shape)
    pieces = _explode_multiparts(pieces)
    pieces = [make_valid(p) for p in pieces if p is not None and not p.is_empty]
    pieces.sort(key=lambda p: -_area_m2(p))

    # Re-absorb AFTER the single-part explode. Force-merging an isolated orphan
    # unions it into a *disjoint* MultiPolygon, which `_explode_multiparts`
    # above would split straight back into the sub-floor island the user asked
    # to merge — so sub-threshold pieces still surfaced in the preview (and,
    # via commit's own explode, in the attribute table): "increasing or
    # decreasing the minimum area works partially but not fully". Running the
    # floor absorb as the LAST geometry step guarantees no sub-floor piece
    # survives on its own; an intentionally force-merged orphan stays one
    # multi-part block (folded area, single serial) rather than a separate row.
    pieces, _reabsorbed = _absorb_slivers(pieces, sliver_area_m2, force_absorb_orphans)
    absorbed += _reabsorbed
    pieces = [make_valid(p) for p in pieces if p is not None and not p.is_empty]
    pieces.sort(key=lambda p: -_area_m2(p))

    total_ha = sum(_area_m2(p) for p in pieces) / SQM_PER_HA
    boundary_ha = _area_m2(boundary_shape) / SQM_PER_HA

    edges = _adjacency_edges(pieces)

    if desired_n is not None:
        merged = _merge_plan(pieces, edges, desired_n)
        merged.sort(key=lambda p: -_area_m2(p))
        pieces = merged
        edges = _adjacency_edges(pieces)

    centroids = []
    for p in pieces:
        try:
            centroids.append(p.representative_point() if not p.is_empty else p.centroid)
        except Exception:
            logger.exception(
                "representative point failed - the block will be generated "
                "without a centroid, so it cannot be labelled on the map"
            )
            centroids.append(None)

    valid = [(i, c) for i, c in enumerate(centroids) if c is not None]
    names = _nearest_natural_names(
        db, [c.x for _, c in valid], [c.y for _, c in valid], str(calc.id)
    )
    name_map = {i: nm for (i, _), nm in zip(valid, names)}

    features = []
    for i, p in enumerate(pieces, start=1):
        # Re-derive per OUTPUT piece (not the input code) - sliver-absorb /
        # merge can fold pieces of different origin directions together.
        try:
            code = aspect_dominant_code(p.wkt, db)
        except Exception:
            logger.exception(
                "aspect_dominant_code failed for a generated piece - it is "
                "labelled with no aspect rather than a guessed one"
            )
            code = None
        label = ASPECT_LABELS.get(code) if code else None
        props = {
            "index": i,
            "name": _serial(level, i),
            "block_name": _serial(level, i),
            "natural_name": name_map.get(i - 1),
            "aspect_code": code,
            "aspect_label": label,
            "area_hectares": round(_area_m2(p) / SQM_PER_HA, 4),
        }
        features.append(
            {"type": "Feature", "properties": props, "geometry": p.__geo_interface__}
        )

    meta = {
        "source_layer": "rasters.aspect",
        "basis": "aspect (compass direction)",
        "level": level,
        "boundary_ha": round(boundary_ha, 2),
        "pieces_ha": round(total_ha, 2),
        "slivers_absorbed": absorbed,
        "piece_count": len(features),
        # Derived from the floor in force, not a hardcoded 5 ha: this is the
        # count the "minimize" button jumps to, so it has to agree with the
        # floor reported directly above it (RS-2.9). Guarded against a zero or
        # negative floor, and clamped to at least 1 so a sub-floor forest still
        # has a target instead of dividing by nothing.
        "minimize_n": max(1, int(total_ha // _applied_floor_ha(sliver_area_m2)))
        if _applied_floor_ha(sliver_area_m2) > 0
        else 1,
        "adjacency_edge_count": len(edges),
        "sliver_area_m2": sliver_area_m2,
        "minimize_floor_ha": _applied_floor_ha(sliver_area_m2),
    }

    return {
        "meta": meta,
        "pieces": {"type": "FeatureCollection", "features": features},
        "edges": edges,
    }


def preview_canopy_blocks(
    db,
    calc,
    level: str = "blocks",
    desired_n: Optional[int] = None,
    sliver_area_m2: Optional[float] = None,
    nodata_min_m2: Optional[float] = None,
    force_absorb_orphans: bool = False,
    scope: Optional[Any] = None,
) -> Dict[str, Any]:
    """Stage 1, canopy source — carve the forest boundary along canopy-height
    structure breaks (`canopy_height5m.tif`, binned 1-4 = non-forest/
    regeneration/pole/tree — the same classification already established in
    `analysis.py::_canopy_from_rasterio`, plus class 0 = no-data). Same shared
    pipeline downstream of the piece fetch. Coverage is patchy (a spaceborne
    product) — a forest with no valid canopy pixels inside its boundary raises
    `no_canopy_coverage` (a real, expected gap, not an error).

    No-data regions at or above ``nodata_min_m2`` (default 1 ha — a river,
    sandbank, settlement or large sensor/cloud gap) are carved as their OWN
    pieces (class 0, label "no-data") rather than silently absorbed into a
    neighbouring forest block, so a real feature never inflates a forest
    block's area/class statistics. Smaller no-data patches are left as
    coverage gaps and absorbed as before.
    ``force_absorb_orphans`` merges sub-threshold pieces even if they have no
    touching neighbour (into the largest remaining piece by area)."""
    if calc.boundary_geom is None:
        raise ValueError("no_boundary")

    from app.services.canopy_vectorize import (
        CANOPY_CLASS_LABELS,
        _DEFAULT_NODATA_MIN_M2,
        canopy_class_pieces,
        canopy_dominant_class,
    )

    if sliver_area_m2 is None:
        sliver_area_m2 = 1000.0
    if nodata_min_m2 is None:
        nodata_min_m2 = _DEFAULT_NODATA_MIN_M2


    classed = canopy_class_pieces(
        calc,
        db,
        sliver_area_m2,
        nodata_min_m2,
        # rasterio, not PostGIS -> the scope arrives as GeoJSON (rule 19).
        scope_geojson=mapping(scope) if scope is not None else None,
    )
    if not classed:
        raise ValueError("no_canopy_coverage")
    pieces = [geom for _cls, geom in classed]
    pieces = _clip_to_scope(pieces, scope)
    nodata_seed_pieces = sum(1 for _cls, _ in classed if _cls == 0)

    pieces = _fill_holes(pieces, sliver_area_m2, protect_geom=hole_protect_geom(db, calc))
    pieces = _dedupe_overlaps(pieces)
    pieces, absorbed = _absorb_slivers(pieces, sliver_area_m2, force_absorb_orphans)
    boundary_shape = _boundary_shape(db, calc, scope)
    pieces = _absorb_coverage_gaps(pieces, boundary_shape)
    pieces = _explode_multiparts(pieces)
    pieces = [make_valid(p) for p in pieces if p is not None and not p.is_empty]
    pieces.sort(key=lambda p: -_area_m2(p))

    # Re-absorb AFTER the single-part explode. Force-merging an isolated orphan
    # unions it into a *disjoint* MultiPolygon, which `_explode_multiparts`
    # above would split straight back into the sub-floor island the user asked
    # to merge — so sub-threshold pieces still surfaced in the preview (and,
    # via commit's own explode, in the attribute table): "increasing or
    # decreasing the minimum area works partially but not fully". Running the
    # floor absorb as the LAST geometry step guarantees no sub-floor piece
    # survives on its own; an intentionally force-merged orphan stays one
    # multi-part block (folded area, single serial) rather than a separate row.
    pieces, _reabsorbed = _absorb_slivers(pieces, sliver_area_m2, force_absorb_orphans)
    absorbed += _reabsorbed
    pieces = [make_valid(p) for p in pieces if p is not None and not p.is_empty]
    pieces.sort(key=lambda p: -_area_m2(p))

    total_ha = sum(_area_m2(p) for p in pieces) / SQM_PER_HA
    boundary_ha = _area_m2(boundary_shape) / SQM_PER_HA

    edges = _adjacency_edges(pieces)

    if desired_n is not None:
        merged = _merge_plan(pieces, edges, desired_n)
        merged.sort(key=lambda p: -_area_m2(p))
        pieces = merged
        edges = _adjacency_edges(pieces)

    centroids = []
    for p in pieces:
        try:
            centroids.append(p.representative_point() if not p.is_empty else p.centroid)
        except Exception:
            logger.exception(
                "representative point failed - the block will be generated "
                "without a centroid, so it cannot be labelled on the map"
            )
            centroids.append(None)

    valid = [(i, c) for i, c in enumerate(centroids) if c is not None]
    names = _nearest_natural_names(
        db, [c.x for _, c in valid], [c.y for _, c in valid], str(calc.id)
    )
    name_map = {i: nm for (i, _), nm in zip(valid, names)}

    features = []
    for i, p in enumerate(pieces, start=1):
        # Re-derive per OUTPUT piece (not the input class) - sliver-absorb /
        # merge can fold pieces of different origin classes together.
        try:
            cls = canopy_dominant_class(p.wkt, db)
        except Exception:
            logger.exception(
                "canopy_dominant_class failed for a generated piece - it is "
                "labelled with no canopy class rather than a guessed one"
            )
            cls = None
        label = CANOPY_CLASS_LABELS.get(cls) if cls is not None else CANOPY_CLASS_LABELS.get(0)
        props = {
            "index": i,
            "name": _serial(level, i),
            "block_name": _serial(level, i),
            "natural_name": name_map.get(i - 1),
            "canopy_class": cls,
            "canopy_class_label": label,
            "area_hectares": round(_area_m2(p) / SQM_PER_HA, 4),
        }
        features.append(
            {"type": "Feature", "properties": props, "geometry": p.__geo_interface__}
        )

    meta = {
        "source_layer": "canopy_height5m.tif",
        "basis": "canopy height structure",
        "level": level,
        "boundary_ha": round(boundary_ha, 2),
        "pieces_ha": round(total_ha, 2),
        "slivers_absorbed": absorbed,
        "piece_count": len(features),
        "nodata_seed_pieces": nodata_seed_pieces,
        "nodata_min_m2": nodata_min_m2,
        # Derived from the floor in force, not a hardcoded 5 ha: this is the
        # count the "minimize" button jumps to, so it has to agree with the
        # floor reported directly above it (RS-2.9). Guarded against a zero or
        # negative floor, and clamped to at least 1 so a sub-floor forest still
        # has a target instead of dividing by nothing.
        "minimize_n": max(1, int(total_ha // _applied_floor_ha(sliver_area_m2)))
        if _applied_floor_ha(sliver_area_m2) > 0
        else 1,
        "adjacency_edge_count": len(edges),
        "sliver_area_m2": sliver_area_m2,
        "minimize_floor_ha": _applied_floor_ha(sliver_area_m2),
    }

    return {
        "meta": meta,
        "pieces": {"type": "FeatureCollection", "features": features},
        "edges": edges,
    }


def preview_nasa_quality_blocks(
    db,
    calc,
    level: str = "blocks",
    desired_n: Optional[int] = None,
    sliver_area_m2: Optional[float] = None,
    force_absorb_orphans: bool = False,
    scope: Optional[Any] = None,
) -> Dict[str, Any]:
    """Stage 1, NASA 2020 forest-quality source (`rasters.nasa_forest_2020`,
    code 1-3 = Primary / Young Secondary / Old Secondary). Carved through the
    generic `raster_class_vectorize` engine driven by the `NASA_QUALITY` spec,
    so every code the raster has (0-3) becomes geometry (rule 9); per OUTPUT
    piece the dominant code is re-derived from the final geometry (sliver-absorb
    / merge can fold pieces of different origin classes together).

    Code 0 (non-forest — grassland, bare, urban; the "absent forest" class the
    effective-area model already absorbs) is carved per the spec as **anonymous**
    geometry (RS-2.5): it still becomes single-part polygons so the pieces tile
    exactly, but a piece whose dominant code is 0 carries `nasa_quality: null` /
    label `null` — it never claims a NASA class, and it is not stored as one
    (`dominant_nasa_quality` is bound 1-3 in the RS-2.3 edit schema).
    """
    if calc.boundary_geom is None:
        raise ValueError("no_boundary")

    from app.core.forest_types import NASA_FOREST_QUALITY
    from app.services.raster_class_vectorize import (
        DOMINANT_FAILED,
        NASA_QUALITY,
        DominantClass,
        class_pieces,
        dominant_class,
        effective_floor_ha,
    )

    # RS-2.9 / D45: the floor is AREA-AWARE, not a fixed 5 ha. A fixed floor
    # was never actually applied -- the only size filter was the 0.1 ha
    # `default_sliver_m2`, over a hardcoded `"minimize_floor_ha": 5.0` the API
    # and the designer both reported. Measured over the 14 live boundaries, that
    # returned 467 pieces (the 926.8 ha forest alone: 126). `effective_floor_ha`
    # had been written, exported and unit-tested since RS-1.3 but called from
    # nothing outside its own tests, so its passing tests covered behaviour that
    # did not exist. It is now actually wired.
    #
    # The floor is a *minimum piece size*, so its only honest job is stopping
    # fragmentation (467 -> 96 across those boundaries). It cannot deliver a
    # compartment COUNT: it caps the count at `target_pieces` and sliver-absorb
    # lands far below that (436 ha yields 3 pieces against a 30 target). The
    # count therefore stays with the existing `desired_n` merge step.
    #
    # The floor is computed from the area actually being carved -- the scope's
    # own area when dividing one feature, not the whole forest -- so dividing a
    # 4 ha compartment out of a 900 ha forest does not hand it the 30 ha floor
    # the forest as a whole earns.
    #
    # An explicit `sliver_area_m2` (the API's own parameter) still wins, so a
    # caller that asks for a size gets it.
    #
    # TWO sizes, deliberately. The floor and the SQL pre-filter are not the same
    # knob even though they used to share one variable:
    #
    #   * `fetch_sliver_m2` is the `WHERE ST_Area >= ...` in `class_pieces`. It
    #     only trims the payload crossing the wire, and a trim *discards* area --
    #     so it stays at the spec's 0.1 ha default. Raising it to the floor makes
    #     every sub-floor piece vanish instead of merging, which loses coverage
    #     and returns `no_nasa_quality_coverage` for any scope smaller than the
    #     floor. (That is what the first cut of this row did, and the scope and
    #     sub-hectare tests caught it.)
    #   * `floor_m2` is the minimum size worth KEEPING, and it belongs to the
    #     Python steps -- `_fill_holes` / `_absorb_slivers` -- which merge a small
    #     piece into its neighbour rather than dropping it. `_absorb_slivers`
    #     keeps an orphan rather than deleting it ("do not delete area"), so a
    #     floor equal to the whole area leaves exactly one piece instead of none.
    fetch_sliver_m2 = (
        sliver_area_m2
        if sliver_area_m2 is not None
        else NASA_QUALITY.default_sliver_m2
    )
    carve_shape = None
    if sliver_area_m2 is None:
        carve_shape = _boundary_shape(db, calc, scope)
        floor_m2 = (
            effective_floor_ha(NASA_QUALITY, _area_m2(carve_shape)) * SQM_PER_HA
        )
    else:
        floor_m2 = sliver_area_m2

    # Rule 19: the scope goes into the SQL fetch (per-compartment on a divide,
    # whole forest otherwise), not only into the Python clip below.
    classed = class_pieces(
        calc,
        db,
        NASA_QUALITY,
        sliver_m2=fetch_sliver_m2,
        scope_wkt=scope.wkt if scope is not None else None,
    )
    if not classed:
        raise ValueError("no_nasa_quality_coverage")
    pieces = [geom for _cls, geom in classed]
    pieces = _clip_to_scope(pieces, scope)

    pieces = _fill_holes(pieces, floor_m2, protect_geom=hole_protect_geom(db, calc))
    pieces = _dedupe_overlaps(pieces)
    pieces, absorbed = _absorb_slivers(pieces, floor_m2, force_absorb_orphans)
    # Reused from the floor computation above when that ran, so the boundary
    # polygon is fetched once per preview instead of twice.
    boundary_shape = (
        carve_shape if carve_shape is not None else _boundary_shape(db, calc, scope)
    )
    pieces = _absorb_coverage_gaps(pieces, boundary_shape)
    pieces = _explode_multiparts(pieces)
    pieces = [make_valid(p) for p in pieces if p is not None and not p.is_empty]
    pieces.sort(key=lambda p: -_area_m2(p))

    # Re-absorb AFTER the single-part explode (same rationale as canopy).
    pieces, _reabsorbed = _absorb_slivers(pieces, floor_m2, force_absorb_orphans)
    absorbed += _reabsorbed
    pieces = [make_valid(p) for p in pieces if p is not None and not p.is_empty]
    pieces.sort(key=lambda p: -_area_m2(p))

    total_ha = sum(_area_m2(p) for p in pieces) / SQM_PER_HA
    boundary_ha = _area_m2(boundary_shape) / SQM_PER_HA

    edges = _adjacency_edges(pieces)

    if desired_n is not None:
        merged = _merge_plan(pieces, edges, desired_n)
        merged.sort(key=lambda p: -_area_m2(p))
        pieces = merged
        edges = _adjacency_edges(pieces)

    centroids = []
    for p in pieces:
        try:
            centroids.append(p.representative_point() if not p.is_empty else p.centroid)
        except Exception:
            logger.exception(
                "representative point failed - the block will be generated "
                "without a centroid, so it cannot be labelled on the map"
            )
            centroids.append(None)

    valid = [(i, c) for i, c in enumerate(centroids) if c is not None]
    names = _nearest_natural_names(
        db, [c.x for _, c in valid], [c.y for _, c in valid], str(calc.id)
    )
    name_map = {i: nm for (i, _), nm in zip(valid, names)}

    features = []
    for i, p in enumerate(pieces, start=1):
        # Dominant code per OUTPUT piece, re-derived from the final geometry.
        # `dominant_class` (not `dominant_code`) so a piece whose dominant is the
        # anonymous code 0 can be shown as "Non-forest (0)" instead of a blank
        # cell indistinguishable from no-coverage (RS-2.14).
        try:
            dom = dominant_class(p.wkt, db, NASA_QUALITY)
        except Exception:
            logger.exception(
                "dominant_code failed for a generated piece - it is labelled "
                "with no NASA quality rather than a guessed one"
            )
            dom = DominantClass(None, None, DOMINANT_FAILED)
        code = dom.code
        entry = NASA_FOREST_QUALITY.get(code) if code is not None else None
        props = {
            "index": i,
            "name": _serial(level, i),
            "block_name": _serial(level, i),
            "natural_name": name_map.get(i - 1),
            "nasa_quality": code,
            "nasa_quality_label": (
                entry.name_en
                if entry is not None
                else (NASA_QUALITY.label(code) if code is not None else None)
            ),
            # The class as the raster has it, 0 included, plus why `nasa_quality`
            # is the value it is. `dominant_nasa_code` is what commit persists.
            "dominant_nasa_code": dom.raw_code,
            "nasa_quality_reason": dom.reason,
            "area_hectares": round(_area_m2(p) / SQM_PER_HA, 4),
        }
        features.append(
            {"type": "Feature", "properties": props, "geometry": p.__geo_interface__}
        )

    meta = {
        "source_layer": "rasters.nasa_forest_2020",
        "basis": "NASA 2020 forest quality",
        "level": level,
        "boundary_ha": round(boundary_ha, 2),
        "pieces_ha": round(total_ha, 2),
        "slivers_absorbed": absorbed,
        "piece_count": len(features),
        # Derived from the floor in force, not a hardcoded 5 ha: this is the
        # count the "minimize" button jumps to, so it has to agree with the
        # floor reported directly above it (RS-2.9). Guarded against a zero or
        # negative floor, and clamped to at least 1 so a sub-floor forest still
        # has a target instead of dividing by nothing.
        "minimize_n": max(1, int(total_ha // _applied_floor_ha(floor_m2)))
        if _applied_floor_ha(floor_m2) > 0
        else 1,
        "adjacency_edge_count": len(edges),
        # The SQL pre-filter size, NOT the floor -- they are two different knobs
        # (see the floor block above), and conflating them here would report the
        # floor twice and hide the pre-filter entirely.
        "sliver_area_m2": fetch_sliver_m2,
        "minimize_floor_ha": _applied_floor_ha(floor_m2),
    }

    return {
        "meta": meta,
        "pieces": {"type": "FeatureCollection", "features": features},
        "edges": edges,
    }


def preview_forest_health_blocks(
    db,
    calc,
    level: str = "blocks",
    desired_n: Optional[int] = None,
    sliver_area_m2: Optional[float] = None,
    force_absorb_orphans: bool = False,
    scope: Optional[Any] = None,
) -> Dict[str, Any]:
    """Stage 1, NDVI forest-health source (`rasters.nepal_forest_health`,
    code 1-5 = Stressed..Excellent). Same shape as `preview_nasa_quality_blocks`
    (RS-9.1, resurrecting P3/RS-3.1): carved through the generic engine driven
    by `NDVI_HEALTH`, 10 m pixels (the finest categorical source so far, hence
    the 12 m smoothing radius the spec already carries rather than the 22 m the
    27/30 m sources use).

    Code 0 is NoData here (unlike NASA's 0, which is a real non-forest class,
    D50) — carved as anonymous geometry so the tiling stays exact, but a piece
    whose dominant code is 0 never claims a health class.
    """
    if calc.boundary_geom is None:
        raise ValueError("no_boundary")

    from app.core.forest_types import FOREST_HEALTH_CLASSES
    from app.services.raster_class_vectorize import (
        DOMINANT_FAILED,
        NDVI_HEALTH,
        DominantClass,
        class_pieces,
        dominant_class,
        effective_floor_ha,
    )

    fetch_sliver_m2 = (
        sliver_area_m2
        if sliver_area_m2 is not None
        else NDVI_HEALTH.default_sliver_m2
    )
    carve_shape = None
    if sliver_area_m2 is None:
        carve_shape = _boundary_shape(db, calc, scope)
        floor_m2 = (
            effective_floor_ha(NDVI_HEALTH, _area_m2(carve_shape)) * SQM_PER_HA
        )
    else:
        floor_m2 = sliver_area_m2

    classed = class_pieces(
        calc,
        db,
        NDVI_HEALTH,
        sliver_m2=fetch_sliver_m2,
        scope_wkt=scope.wkt if scope is not None else None,
    )
    if not classed:
        raise ValueError("no_forest_health_coverage")
    pieces = [geom for _cls, geom in classed]
    pieces = _clip_to_scope(pieces, scope)

    pieces = _fill_holes(pieces, floor_m2, protect_geom=hole_protect_geom(db, calc))
    pieces = _dedupe_overlaps(pieces)
    pieces, absorbed = _absorb_slivers(pieces, floor_m2, force_absorb_orphans)
    boundary_shape = (
        carve_shape if carve_shape is not None else _boundary_shape(db, calc, scope)
    )
    pieces = _absorb_coverage_gaps(pieces, boundary_shape)
    pieces = _explode_multiparts(pieces)
    pieces = [make_valid(p) for p in pieces if p is not None and not p.is_empty]
    pieces.sort(key=lambda p: -_area_m2(p))

    pieces, _reabsorbed = _absorb_slivers(pieces, floor_m2, force_absorb_orphans)
    absorbed += _reabsorbed
    pieces = [make_valid(p) for p in pieces if p is not None and not p.is_empty]
    pieces.sort(key=lambda p: -_area_m2(p))

    total_ha = sum(_area_m2(p) for p in pieces) / SQM_PER_HA
    boundary_ha = _area_m2(boundary_shape) / SQM_PER_HA

    edges = _adjacency_edges(pieces)

    if desired_n is not None:
        merged = _merge_plan(pieces, edges, desired_n)
        merged.sort(key=lambda p: -_area_m2(p))
        pieces = merged
        edges = _adjacency_edges(pieces)

    centroids = []
    for p in pieces:
        try:
            centroids.append(p.representative_point() if not p.is_empty else p.centroid)
        except Exception:
            logger.exception(
                "representative point failed - the block will be generated "
                "without a centroid, so it cannot be labelled on the map"
            )
            centroids.append(None)

    valid = [(i, c) for i, c in enumerate(centroids) if c is not None]
    names = _nearest_natural_names(
        db, [c.x for _, c in valid], [c.y for _, c in valid], str(calc.id)
    )
    name_map = {i: nm for (i, _), nm in zip(valid, names)}

    features = []
    for i, p in enumerate(pieces, start=1):
        try:
            dom = dominant_class(p.wkt, db, NDVI_HEALTH)
        except Exception:
            logger.exception(
                "dominant_code failed for a generated piece - it is labelled "
                "with no forest-health class rather than a guessed one"
            )
            dom = DominantClass(None, None, DOMINANT_FAILED)
        code = dom.code
        entry = FOREST_HEALTH_CLASSES.get(code) if code is not None else None
        props = {
            "index": i,
            "name": _serial(level, i),
            "block_name": _serial(level, i),
            "natural_name": name_map.get(i - 1),
            "health_class": code,
            "health_class_label": (
                entry.name_en
                if entry is not None
                else (NDVI_HEALTH.label(code) if code is not None else None)
            ),
            "health_class_reason": dom.reason,
            "area_hectares": round(_area_m2(p) / SQM_PER_HA, 4),
        }
        features.append(
            {"type": "Feature", "properties": props, "geometry": p.__geo_interface__}
        )

    meta = {
        "source_layer": "rasters.nepal_forest_health",
        "basis": "NDVI forest health",
        "level": level,
        "boundary_ha": round(boundary_ha, 2),
        "pieces_ha": round(total_ha, 2),
        "slivers_absorbed": absorbed,
        "piece_count": len(features),
        "minimize_n": max(1, int(total_ha // _applied_floor_ha(floor_m2)))
        if _applied_floor_ha(floor_m2) > 0
        else 1,
        "adjacency_edge_count": len(edges),
        "sliver_area_m2": fetch_sliver_m2,
        "minimize_floor_ha": _applied_floor_ha(floor_m2),
    }

    return {
        "meta": meta,
        "pieces": {"type": "FeatureCollection", "features": features},
        "edges": edges,
    }


def preview_landcover_blocks(
    db,
    calc,
    level: str = "blocks",
    desired_n: Optional[int] = None,
    sliver_area_m2: Optional[float] = None,
    force_absorb_orphans: bool = False,
    scope: Optional[Any] = None,
    forest_classes: Optional[Tuple[int, ...]] = None,
) -> Dict[str, Any]:
    """Stage 1, ESA WorldCover source (`rasters.esa_world_cover`, RS-9.2,
    resurrecting P3.7). Same shape as the other sources, with one addition
    (D24): **Mode A, "Forest vs Other", is a GROUPING, not a filter** — every
    ESA class still gets geometry, grouped into whichever bucket the caller's
    `forest_classes` assigns it to, so an unticked class becomes part of the
    "Other" band rather than a gap that `_absorb_coverage_gaps`/the Remainder
    Block would fill arbitrarily (rule 9).

    ``forest_classes``: the ESA codes to treat as "forest" (default `(10, 20)`
    — Tree cover + Shrubland, D24's own default). Every other code in
    `ESA_LANDCOVER.codes` becomes "other". Passing the full code tuple
    (`ESA_LANDCOVER.codes`) is Mode B — every class carved and labelled
    separately, since then nothing is grouped together.
    """
    if calc.boundary_geom is None:
        raise ValueError("no_boundary")

    from app.core.forest_types import ESA_WORLD_COVER
    from app.services.raster_class_vectorize import (
        DOMINANT_FAILED,
        ESA_LANDCOVER,
        DominantClass,
        class_pieces,
        dominant_class,
        effective_floor_ha,
    )

    forest_set = set(forest_classes) if forest_classes is not None else {10, 20}

    def _mode_a_group(code: int) -> str:
        return "forest" if code in forest_set else "other"

    fetch_sliver_m2 = (
        sliver_area_m2
        if sliver_area_m2 is not None
        else ESA_LANDCOVER.default_sliver_m2
    )
    carve_shape = None
    if sliver_area_m2 is None:
        carve_shape = _boundary_shape(db, calc, scope)
        floor_m2 = (
            effective_floor_ha(ESA_LANDCOVER, _area_m2(carve_shape)) * SQM_PER_HA
        )
    else:
        floor_m2 = sliver_area_m2

    classed = class_pieces(
        calc,
        db,
        ESA_LANDCOVER,
        sliver_m2=fetch_sliver_m2,
        scope_wkt=scope.wkt if scope is not None else None,
    )
    if not classed:
        raise ValueError("no_landcover_coverage")
    pieces = [geom for _cls, geom in classed]
    pieces = _clip_to_scope(pieces, scope)

    pieces = _fill_holes(pieces, floor_m2, protect_geom=hole_protect_geom(db, calc))
    pieces = _dedupe_overlaps(pieces)
    pieces, absorbed = _absorb_slivers(pieces, floor_m2, force_absorb_orphans)
    boundary_shape = (
        carve_shape if carve_shape is not None else _boundary_shape(db, calc, scope)
    )
    pieces = _absorb_coverage_gaps(pieces, boundary_shape)
    pieces = _explode_multiparts(pieces)
    pieces = [make_valid(p) for p in pieces if p is not None and not p.is_empty]
    pieces.sort(key=lambda p: -_area_m2(p))

    pieces, _reabsorbed = _absorb_slivers(pieces, floor_m2, force_absorb_orphans)
    absorbed += _reabsorbed
    pieces = [make_valid(p) for p in pieces if p is not None and not p.is_empty]
    pieces.sort(key=lambda p: -_area_m2(p))

    total_ha = sum(_area_m2(p) for p in pieces) / SQM_PER_HA
    boundary_ha = _area_m2(boundary_shape) / SQM_PER_HA

    edges = _adjacency_edges(pieces)

    if desired_n is not None:
        merged = _merge_plan(pieces, edges, desired_n)
        merged.sort(key=lambda p: -_area_m2(p))
        pieces = merged
        edges = _adjacency_edges(pieces)

    centroids = []
    for p in pieces:
        try:
            centroids.append(p.representative_point() if not p.is_empty else p.centroid)
        except Exception:
            logger.exception(
                "representative point failed - the block will be generated "
                "without a centroid, so it cannot be labelled on the map"
            )
            centroids.append(None)

    valid = [(i, c) for i, c in enumerate(centroids) if c is not None]
    names = _nearest_natural_names(
        db, [c.x for _, c in valid], [c.y for _, c in valid], str(calc.id)
    )
    name_map = {i: nm for (i, _), nm in zip(valid, names)}

    features = []
    for i, p in enumerate(pieces, start=1):
        try:
            dom = dominant_class(p.wkt, db, ESA_LANDCOVER)
        except Exception:
            logger.exception(
                "dominant_code failed for a generated piece - it is labelled "
                "with no land-cover class rather than a guessed one"
            )
            dom = DominantClass(None, None, DOMINANT_FAILED)
        code = dom.code
        entry = ESA_WORLD_COVER.get(code) if code is not None else None
        props = {
            "index": i,
            "name": _serial(level, i),
            "block_name": _serial(level, i),
            "natural_name": name_map.get(i - 1),
            "landcover": code,
            "landcover_label": (
                entry.name_en
                if entry is not None
                else (ESA_LANDCOVER.label(code) if code is not None else None)
            ),
            # D24: the group this piece's dominant code falls into under the
            # CALLER's forest_classes choice — "forest"/"other"/None (code is
            # anonymous, i.e. NoData). Mode A's UI reads this; Mode B ignores
            # it and shows `landcover_label` directly.
            "landcover_group": _mode_a_group(code) if code is not None else None,
            "landcover_reason": dom.reason,
            "area_hectares": round(_area_m2(p) / SQM_PER_HA, 4),
        }
        features.append(
            {"type": "Feature", "properties": props, "geometry": p.__geo_interface__}
        )

    meta = {
        "source_layer": "rasters.esa_world_cover",
        "basis": "ESA WorldCover land cover",
        "level": level,
        "boundary_ha": round(boundary_ha, 2),
        "pieces_ha": round(total_ha, 2),
        "slivers_absorbed": absorbed,
        "piece_count": len(features),
        "minimize_n": max(1, int(total_ha // _applied_floor_ha(floor_m2)))
        if _applied_floor_ha(floor_m2) > 0
        else 1,
        "adjacency_edge_count": len(edges),
        "sliver_area_m2": fetch_sliver_m2,
        "minimize_floor_ha": _applied_floor_ha(floor_m2),
        "forest_classes": sorted(forest_set),
    }

    return {
        "meta": meta,
        "pieces": {"type": "FeatureCollection", "features": features},
        "edges": edges,
    }


def preview_elevation_blocks(
    db,
    calc,
    level: str = "blocks",
    desired_n: Optional[int] = None,
    sliver_area_m2: Optional[float] = None,
    force_absorb_orphans: bool = False,
    scope: Optional[Any] = None,
    elevation_bands: Optional[int] = None,
) -> Dict[str, Any]:
    """Stage 1, DEM elevation source (`rasters.dem`, RS-9.3, owner directive
    2026-10-01: "divide by contour line", a fixed number of bands computed
    per-forest). Unlike every other source, this is the CONTINUOUS path —
    `reclass_pieces`/`band_table_for`, not `class_pieces` — because elevation
    has no fixed class vocabulary; the bands themselves are computed from
    THIS forest's own min/max elevation (rule 16: from the boundary, never a
    per-compartment slice, so "band 2" is the same altitude range everywhere
    in one forest).

    `elevation_bands` (default 3, same "Low/Mid/High" vocabulary the spec's
    `label_fn` already carries; 4-5 fall back to "Zone N"): how many
    equal-elevation-interval bands to cut. At 30 m DEM resolution the
    vectorized boundary between two bands traces that elevation's isoline at
    pixel granularity — a real, stepped contour line, which is the point.

    DEM stays ALSO an always-on attribute regardless of whether it is ever
    used as a carve source (RS-2.19) — `elevation_min_m/_mean_m/_max_m` and
    the RELATIVE (percentile-of-units, not this scheme) zone are computed for
    every unit in `commit_blocks` no matter which source carved it.
    """
    if calc.boundary_geom is None:
        raise ValueError("no_boundary")

    from app.services.raster_class_vectorize import (
        DEM_ELEVATION,
        DOMINANT_FAILED,
        DominantClass,
        band_table_for,
        dominant_band,
        effective_floor_ha,
        reclass_pieces,
    )

    n_bands = elevation_bands if elevation_bands is not None else 3

    fetch_sliver_m2 = (
        sliver_area_m2
        if sliver_area_m2 is not None
        else DEM_ELEVATION.default_sliver_m2
    )
    carve_shape = None
    if sliver_area_m2 is None:
        carve_shape = _boundary_shape(db, calc, scope)
        floor_m2 = (
            effective_floor_ha(DEM_ELEVATION, _area_m2(carve_shape)) * SQM_PER_HA
        )
    else:
        floor_m2 = sliver_area_m2

    # Rule 16: stats (and therefore the band cuts) come from the FOREST
    # BOUNDARY, never the scope being carved — a divide of one compartment
    # must not recompute "High" relative to just that compartment.
    boundary_wkt_for_stats = _boundary_shape(db, calc, None).wkt
    bands = band_table_for(calc, db, DEM_ELEVATION, boundary_wkt_for_stats, n_bands=n_bands)
    if not bands:
        raise ValueError("no_elevation_coverage")

    classed = reclass_pieces(
        calc,
        db,
        DEM_ELEVATION,
        bands,
        sliver_m2=fetch_sliver_m2,
        scope_wkt=scope.wkt if scope is not None else None,
    )
    if not classed:
        raise ValueError("no_elevation_coverage")
    pieces = [geom for _cls, geom in classed]
    pieces = _clip_to_scope(pieces, scope)

    pieces = _fill_holes(pieces, floor_m2, protect_geom=hole_protect_geom(db, calc))
    pieces = _dedupe_overlaps(pieces)
    pieces, absorbed = _absorb_slivers(pieces, floor_m2, force_absorb_orphans)
    boundary_shape = (
        carve_shape if carve_shape is not None else _boundary_shape(db, calc, scope)
    )
    pieces = _absorb_coverage_gaps(pieces, boundary_shape)
    pieces = _explode_multiparts(pieces)
    pieces = [make_valid(p) for p in pieces if p is not None and not p.is_empty]
    pieces.sort(key=lambda p: -_area_m2(p))

    pieces, _reabsorbed = _absorb_slivers(pieces, floor_m2, force_absorb_orphans)
    absorbed += _reabsorbed
    pieces = [make_valid(p) for p in pieces if p is not None and not p.is_empty]
    pieces.sort(key=lambda p: -_area_m2(p))

    total_ha = sum(_area_m2(p) for p in pieces) / SQM_PER_HA
    boundary_ha = _area_m2(boundary_shape) / SQM_PER_HA

    edges = _adjacency_edges(pieces)

    if desired_n is not None:
        merged = _merge_plan(pieces, edges, desired_n)
        merged.sort(key=lambda p: -_area_m2(p))
        pieces = merged
        edges = _adjacency_edges(pieces)

    centroids = []
    for p in pieces:
        try:
            centroids.append(p.representative_point() if not p.is_empty else p.centroid)
        except Exception:
            logger.exception(
                "representative point failed - the block will be generated "
                "without a centroid, so it cannot be labelled on the map"
            )
            centroids.append(None)

    valid = [(i, c) for i, c in enumerate(centroids) if c is not None]
    names = _nearest_natural_names(
        db, [c.x for _, c in valid], [c.y for _, c in valid], str(calc.id)
    )
    name_map = {i: nm for (i, _), nm in zip(valid, names)}

    band_by_code = {code: (lo, hi) for lo, hi, code in bands}

    features = []
    for i, p in enumerate(pieces, start=1):
        try:
            dom = dominant_band(p.wkt, db, DEM_ELEVATION, bands)
        except Exception:
            logger.exception(
                "dominant_band failed for a generated piece - it is labelled "
                "with no elevation zone rather than a guessed one"
            )
            dom = DominantClass(None, None, DOMINANT_FAILED)
        code = dom.code
        rng = band_by_code.get(code) if code is not None else None
        props = {
            "index": i,
            "name": _serial(level, i),
            "block_name": _serial(level, i),
            "natural_name": name_map.get(i - 1),
            # NOT "elevation_zone" -- that name is RS-2.19's forest-relative
            # percentile attribute (`dominant_elevation_zone`), computed for
            # every unit regardless of source. This is the DEM carve's OWN
            # per-forest contour band, a different number with a different
            # meaning; see migration 108's docstring.
            "contour_band": code,
            "contour_band_label": (
                DEM_ELEVATION.label(code) if code is not None else None
            ),
            # The forest-wide cut this piece's band falls in (m), so the UI can
            # show "High (2143-2810 m)" instead of a bare band number — the
            # cuts are per-forest (rule 16), not a fixed national table.
            "contour_band_range_m": (
                [round(rng[0], 1), round(rng[1], 1)] if rng is not None else None
            ),
            "area_hectares": round(_area_m2(p) / SQM_PER_HA, 4),
        }
        features.append(
            {"type": "Feature", "properties": props, "geometry": p.__geo_interface__}
        )

    meta = {
        "source_layer": "rasters.dem",
        "basis": "Elevation (contour bands)",
        "level": level,
        "boundary_ha": round(boundary_ha, 2),
        "pieces_ha": round(total_ha, 2),
        "slivers_absorbed": absorbed,
        "piece_count": len(features),
        "minimize_n": max(1, int(total_ha // _applied_floor_ha(floor_m2)))
        if _applied_floor_ha(floor_m2) > 0
        else 1,
        "adjacency_edge_count": len(edges),
        "sliver_area_m2": fetch_sliver_m2,
        "minimize_floor_ha": _applied_floor_ha(floor_m2),
        "elevation_bands": n_bands,
        "band_ranges_m": [[round(lo, 1), round(hi, 1)] for lo, hi, _code in bands],
    }

    return {
        "meta": meta,
        "pieces": {"type": "FeatureCollection", "features": features},
        "edges": edges,
    }


def preview_forest_type_blocks(
    db,
    calc,
    level: str = "blocks",
    desired_n: Optional[int] = None,
    sliver_area_m2: Optional[float] = None,
    force_absorb_orphans: bool = False,
    scope: Optional[Any] = None,
) -> Dict[str, Any]:
    """Stage 1, FRTC forest-type source (`rasters.forest_type`, RS-9.5, is
    RS-4.2 — blocked since RS-1.3 on RS-0.2 (the legend) then RS-4.1a (the
    class-26 contradiction), both resolved by owner directive 2026-10-01).
    Same shape as `preview_nasa_quality_blocks`: carved through the generic
    engine driven by `FRTC_FOREST_TYPE`, 26 classes (1-25 named types).

    Code 26 ("Unclassified" in this app — the raster's own legend calls it
    "Non forest", RS-9.5) is carved as anonymous geometry so tiling stays
    exact, but a piece whose dominant code is 26 never claims one of the 25
    named forest types.
    """
    if calc.boundary_geom is None:
        raise ValueError("no_boundary")

    from app.core.forest_types import FRTC_FOREST_TYPES
    from app.services.raster_class_vectorize import (
        DOMINANT_FAILED,
        FRTC_FOREST_TYPE,
        DominantClass,
        class_pieces,
        dominant_class,
        effective_floor_ha,
    )

    fetch_sliver_m2 = (
        sliver_area_m2
        if sliver_area_m2 is not None
        else FRTC_FOREST_TYPE.default_sliver_m2
    )
    carve_shape = None
    if sliver_area_m2 is None:
        carve_shape = _boundary_shape(db, calc, scope)
        floor_m2 = (
            effective_floor_ha(FRTC_FOREST_TYPE, _area_m2(carve_shape)) * SQM_PER_HA
        )
    else:
        floor_m2 = sliver_area_m2

    classed = class_pieces(
        calc,
        db,
        FRTC_FOREST_TYPE,
        sliver_m2=fetch_sliver_m2,
        scope_wkt=scope.wkt if scope is not None else None,
    )
    if not classed:
        raise ValueError("no_forest_type_coverage")
    pieces = [geom for _cls, geom in classed]
    pieces = _clip_to_scope(pieces, scope)

    pieces = _fill_holes(pieces, floor_m2, protect_geom=hole_protect_geom(db, calc))
    pieces = _dedupe_overlaps(pieces)
    pieces, absorbed = _absorb_slivers(pieces, floor_m2, force_absorb_orphans)
    boundary_shape = (
        carve_shape if carve_shape is not None else _boundary_shape(db, calc, scope)
    )
    pieces = _absorb_coverage_gaps(pieces, boundary_shape)
    pieces = _explode_multiparts(pieces)
    pieces = [make_valid(p) for p in pieces if p is not None and not p.is_empty]
    pieces.sort(key=lambda p: -_area_m2(p))

    pieces, _reabsorbed = _absorb_slivers(pieces, floor_m2, force_absorb_orphans)
    absorbed += _reabsorbed
    pieces = [make_valid(p) for p in pieces if p is not None and not p.is_empty]
    pieces.sort(key=lambda p: -_area_m2(p))

    total_ha = sum(_area_m2(p) for p in pieces) / SQM_PER_HA
    boundary_ha = _area_m2(boundary_shape) / SQM_PER_HA

    edges = _adjacency_edges(pieces)

    if desired_n is not None:
        merged = _merge_plan(pieces, edges, desired_n)
        merged.sort(key=lambda p: -_area_m2(p))
        pieces = merged
        edges = _adjacency_edges(pieces)

    centroids = []
    for p in pieces:
        try:
            centroids.append(p.representative_point() if not p.is_empty else p.centroid)
        except Exception:
            logger.exception(
                "representative point failed - the block will be generated "
                "without a centroid, so it cannot be labelled on the map"
            )
            centroids.append(None)

    valid = [(i, c) for i, c in enumerate(centroids) if c is not None]
    names = _nearest_natural_names(
        db, [c.x for _, c in valid], [c.y for _, c in valid], str(calc.id)
    )
    name_map = {i: nm for (i, _), nm in zip(valid, names)}

    features = []
    for i, p in enumerate(pieces, start=1):
        try:
            dom = dominant_class(p.wkt, db, FRTC_FOREST_TYPE)
        except Exception:
            logger.exception(
                "dominant_code failed for a generated piece - it is labelled "
                "with no forest type rather than a guessed one"
            )
            dom = DominantClass(None, None, DOMINANT_FAILED)
        code = dom.code
        entry = FRTC_FOREST_TYPES.get(code) if code is not None else None
        props = {
            "index": i,
            "name": _serial(level, i),
            "block_name": _serial(level, i),
            "natural_name": name_map.get(i - 1),
            "forest_type": code,
            "forest_type_label": (
                entry.name_en
                if entry is not None
                else (FRTC_FOREST_TYPE.label(code) if code is not None else None)
            ),
            "forest_type_reason": dom.reason,
            "area_hectares": round(_area_m2(p) / SQM_PER_HA, 4),
        }
        features.append(
            {"type": "Feature", "properties": props, "geometry": p.__geo_interface__}
        )

    meta = {
        "source_layer": "rasters.forest_type",
        "basis": "FRTC 2015 forest type",
        "level": level,
        "boundary_ha": round(boundary_ha, 2),
        "pieces_ha": round(total_ha, 2),
        "slivers_absorbed": absorbed,
        "piece_count": len(features),
        "minimize_n": max(1, int(total_ha // _applied_floor_ha(floor_m2)))
        if _applied_floor_ha(floor_m2) > 0
        else 1,
        "adjacency_edge_count": len(edges),
        "sliver_area_m2": fetch_sliver_m2,
        "minimize_floor_ha": _applied_floor_ha(floor_m2),
    }

    return {
        "meta": meta,
        "pieces": {"type": "FeatureCollection", "features": features},
        "edges": edges,
    }


# ---------------------------------------------------------------------------
# Union (P10, RS-10.2) -- the composite multi-attribute layer. Two sources,
# not one with a mode flag (plan §P10 correction #1): `union_zonal` (this
# function, Mode B, default) and `union_fusion` (Mode A, RS-10.3, not yet
# built). Unlike every source above, this is not a `RasterClassSpec` carve --
# it orchestrates OTHER already-existing layers/tables (plan §P10 correction
# #2), which is why it cannot follow the one-spec-one-table template the rest
# of this file does.
# ---------------------------------------------------------------------------


def preview_union_zonal_blocks(
    db,
    calc,
    level: str = "blocks",
    desired_n: Optional[int] = None,
    sliver_area_m2: Optional[float] = None,
    force_absorb_orphans: bool = False,
    scope: Optional[Any] = None,
) -> Dict[str, Any]:
    """Union, Mode B (`union_zonal`, RS-10.2) -- MMU polygons as the fixed
    base partition; the other 7 classified rasters plus DEM get their
    dominant class per MMU piece by zonal majority (the exact
    `dominant_class`/`dominant_band`/per-source functions every other
    `preview_*_blocks` already uses to re-derive a piece's class -- this
    function's only new work is calling seven of them against one shared
    base instead of one against its own carve); sub-area gets its category by
    largest-area vector overlap against `ForestSubArea`.

    Auto-creates an MMU layer first (owner directive, RS-10.0) if this
    forest has none yet, at a 5 ha sliver floor -- not the 1 ha SSOT default
    (`MMU_SLIVER_AREA_M2`), because "otherwise huge number of MMU will be
    produced" (owner, 2026-10-01). That auto-create is scoped to this one
    call: it does not touch the SSOT constant, and a planner creating MMU
    through the ordinary Auto-Block dialog still gets the 1 ha default. The
    auto-created layer is a completely normal layer afterward -- promotable,
    deletable, re-runnable; this function does not pin or protect it. An MMU
    carve failure (e.g. a forest too small/degenerate for river+ridge
    division) surfaces as that failure (`ValueError("no_boundary")` or
    whatever `preview_mmu_blocks`/`commit_blocks` itself raises), not a
    generic Union error.

    `sliver_area_m2`/`force_absorb_orphans`/`desired_n` here govern the
    UNION layer's own pieces (inherited unchanged from the MMU base — Union
    adds attributes, it does not re-carve geometry), not the auto-created
    MMU layer's floor, which is always 5 ha regardless of what this call
    passes.
    """
    if calc.boundary_geom is None:
        raise ValueError("no_boundary")

    from app.models.forest_sub_area import ForestSubArea
    from app.services.aspect_vectorize import ASPECT_LABELS, aspect_dominant_code
    from app.services.canopy_vectorize import CANOPY_CLASS_LABELS, canopy_dominant_class
    from app.services.raster_class_vectorize import (
        DEM_ELEVATION,
        ESA_LANDCOVER,
        FRTC_FOREST_TYPE,
        NASA_QUALITY,
        NDVI_HEALTH,
        DominantClass,
        band_table_for,
        dominant_band,
        dominant_class,
    )
    from app.services.sustainable_fm.sfm_config import resolve_params
    from app.services.sustainable_fm.slope_vectorize import BAND_LABELS, slope_profile

    # --- RS-10.0: auto-create MMU at a 5 ha floor if this forest has none ---
    mmu_layer = (
        db.query(RasterLayer)
        .filter(RasterLayer.calculation_id == calc.id, RasterLayer.source == "mmu")
        .order_by(RasterLayer.created_at.desc())
        .first()
    )
    mmu_auto_created = False
    if mmu_layer is None:
        mmu_preview = preview_mmu_blocks(db, calc, level="blocks", sliver_area_m2=50000.0)
        mmu_blocks_payload = [
            {**f["properties"], "geometry": f["geometry"]}
            for f in mmu_preview["pieces"]["features"]
        ]
        if not mmu_blocks_payload:
            # RS-10.0: an MMU carve failure surfaces as that failure, not a
            # generic Union error -- same shape `no_mmu_coverage` below uses.
            raise ValueError("no_mmu_coverage")
        commit_blocks(
            db, calc, mmu_blocks_payload, level="blocks", source="mmu", allow_legacy=True,
        )
        mmu_layer = (
            db.query(RasterLayer)
            .filter(RasterLayer.calculation_id == calc.id, RasterLayer.source == "mmu")
            .order_by(RasterLayer.created_at.desc())
            .first()
        )
        mmu_auto_created = True

    mmu_rows = (
        db.query(ForestBlock)
        .filter(ForestBlock.raster_layer_id == mmu_layer.id)
        .order_by(ForestBlock.index)
        .all()
    )
    if not mmu_rows:
        raise ValueError("no_mmu_coverage")

    from geoalchemy2.shape import to_shape

    pieces = [to_shape(r.geometry) for r in mmu_rows]

    # Elevation bands: once per forest boundary (rule 16), reused for every
    # MMU piece below -- never recomputed per piece, which would make "High"
    # mean a different altitude in every piece (plan §P10 correction #3).
    boundary_wkt_for_stats = _boundary_shape(db, calc, None).wkt
    bands = band_table_for(calc, db, DEM_ELEVATION, boundary_wkt_for_stats, n_bands=3)

    params = resolve_params(db, calc.id)

    # Sub-areas: real vector geometry, not a raster vote. Fetched once,
    # largest-overlap computed per MMU piece below.
    sub_areas = (
        db.query(ForestSubArea).filter(ForestSubArea.calculation_id == calc.id).all()
    )
    sub_area_shapes = [(sa, to_shape(sa.geometry)) for sa in sub_areas]

    features = []
    for i, (row, p) in enumerate(zip(mmu_rows, pieces), start=1):
        wkt = p.wkt

        try:
            slope_band = (slope_profile(wkt, db, params) or {}).get("dominant_band")
        except Exception:
            logger.exception("union_zonal: slope_profile failed for an MMU piece")
            slope_band = None
        slope_label = BAND_LABELS.get(slope_band, (None, None))[1] if slope_band else None

        try:
            aspect_code = aspect_dominant_code(wkt, db)
        except Exception:
            logger.exception("union_zonal: aspect_dominant_code failed for an MMU piece")
            aspect_code = None
        aspect_label = ASPECT_LABELS.get(aspect_code) if aspect_code else None

        try:
            canopy_code = canopy_dominant_class(wkt, db)
        except Exception:
            logger.exception("union_zonal: canopy_dominant_class failed for an MMU piece")
            canopy_code = None
        canopy_label = CANOPY_CLASS_LABELS.get(canopy_code) if canopy_code else None

        def _dom(spec, label):
            try:
                dom = dominant_class(wkt, db, spec)
            except Exception:
                logger.exception("union_zonal: dominant_class(%s) failed for an MMU piece", label)
                return DominantClass(None, None, "failed")
            return dom

        nasa_dom = _dom(NASA_QUALITY, "nasa_quality")
        health_dom = _dom(NDVI_HEALTH, "forest_health")
        landcover_dom = _dom(ESA_LANDCOVER, "landcover")
        forest_type_dom = _dom(FRTC_FOREST_TYPE, "forest_type")

        try:
            contour_dom = dominant_band(wkt, db, DEM_ELEVATION, bands) if bands else DominantClass(None, None, "no_bands")
        except Exception:
            logger.exception("union_zonal: dominant_band failed for an MMU piece")
            contour_dom = DominantClass(None, None, "failed")

        # Sub-area: largest-area vector overlap, not a raster vote. No
        # overlap -> None/"Unassigned" (the normal case for most of a
        # forest), never an error. Private Land (`is_excluded`) is tagged,
        # not omitted.
        best_sa = None
        best_overlap_m2 = 0.0
        for sa, sa_shape in sub_area_shapes:
            try:
                inter = p.intersection(sa_shape)
            except Exception:  # noqa: BLE001 -- an invalid sub-area shape cannot overlap this unit; skip it
                continue
            if inter.is_empty:
                continue
            area = _area_m2(inter)
            if area > best_overlap_m2:
                best_overlap_m2 = area
                best_sa = sa

        props = {
            "index": i,
            "name": f"Union-{i}",
            "block_name": f"Union-{i}",
            "natural_name": row.natural_name,
            "area_hectares": round(_area_m2(p) / SQM_PER_HA, 4),
            "dominant_slope_band": slope_band,
            "slope_band_label": slope_label,
            "dominant_aspect": aspect_code,
            "aspect_label": aspect_label,
            "dominant_canopy_class": canopy_code,
            "canopy_class_label": canopy_label,
            "dominant_nasa_quality": nasa_dom.code,
            "dominant_nasa_code": nasa_dom.raw_code,
            "dominant_health_class": health_dom.code,
            "dominant_landcover": landcover_dom.code,
            "dominant_forest_type": forest_type_dom.code,
            "dominant_contour_band": contour_dom.code,
            "sub_area_category": best_sa.category if best_sa is not None else None,
            "sub_area_excluded": bool(best_sa.is_excluded) if best_sa is not None else False,
        }
        features.append(
            {"type": "Feature", "properties": props, "geometry": p.__geo_interface__}
        )

    total_ha = sum(_area_m2(p) for p in pieces) / SQM_PER_HA
    meta = {
        "source_layer": "union_zonal",
        "base_layer": "mmu",
        "mmu_auto_created": mmu_auto_created,
        "mmu_layer_id": str(mmu_layer.id),
        "total_area_ha": round(total_ha, 4),
        "piece_count": len(features),
    }
    return {
        "meta": meta,
        "pieces": {"type": "FeatureCollection", "features": features},
        "edges": [],
    }


def preview_union_fusion_blocks(
    db,
    calc,
    level: str = "blocks",
    desired_n: Optional[int] = None,
    sliver_area_m2: Optional[float] = None,
    force_absorb_orphans: bool = False,
    scope: Optional[Any] = None,
    sources: Optional[List[str]] = None,
    include_canopy: bool = True,
) -> Dict[str, Any]:
    """Union, Mode A (`union_fusion`, RS-10.3/RS-10.3b) -- pixel-level
    fusion of the SQL-queryable classified rasters into one composite code
    per pixel (`union_fusion_vectorize.union_fusion_pieces`), vectorized in
    a single pass instead of several independently-generalized ones
    colliding.

    ``sources`` (RS-10.3b, owner question 2026-10-01: "Can user select
    some of the raster instead select all raster?"): which OPTIONAL
    attributes to fuse, any subset of
    `union_fusion_vectorize.ALL_OPTIONAL_SOURCE_KEYS` (aspect, forest_type,
    nasa_quality, forest_health, landcover, dem). ``None`` (the default)
    fuses all of them, matching the original RS-10.3 behaviour. Slope is
    ALWAYS included and is the gate -- it cannot be deselected. Selecting
    fewer sources means fewer distinct combinations exist to carve, which
    directly answers the "make it more usable" ask: fewer, larger pieces,
    and a proportionally faster `dominant_composite` re-derivation pass
    (RS-10.3's own build note measured 13.3s/129 pieces fusing all 6
    optional sources on a 316 ha forest -- fewer sources only improves on
    that).

    ``include_canopy`` -- canopy is attached per FINAL piece afterward via
    the same zonal call `union_zonal` uses (`canopy_dominant_class`), never
    part of the pixel stack itself -- its data source is a GeoTIFF read
    through `rasterio`, not a PostGIS raster table (see
    `union_fusion_vectorize`'s own docstring). Set ``False`` to skip that
    per-piece call entirely when canopy isn't wanted.

    Then: the shared sliver-absorb/merge tail every other source uses
    (bare geometry, same as `union_zonal`'s own MMU-derived pieces); per
    OUTPUT piece, `dominant_composite` re-derives the true combination from
    the final (possibly merged) shape's own pixels -- majority-voting the
    COMPOSITE INTEGER, never the individual slots, which is what
    guarantees a merged piece can only ever report a combination that is
    real somewhere in it, not a synthesized one (the plan's "whole-tuple,
    never per-attribute" sliver rule, reached here by re-derivation rather
    than neighbor-inheritance); then two bounded vector intersections
    against MMU (so no piece crosses an MMU boundary) and `ForestSubArea`
    (largest-overlap, same as `union_zonal`).

    Same RS-10.0 MMU auto-create (5 ha floor) as `union_zonal` -- this
    mode also needs MMU boundaries for its own final intersection pass.
    """
    if calc.boundary_geom is None:
        raise ValueError("no_boundary")

    from app.models.forest_sub_area import ForestSubArea
    from app.services.canopy_vectorize import CANOPY_CLASS_LABELS, canopy_dominant_class
    from app.services.raster_class_vectorize import DEM_ELEVATION, band_table_for
    from app.services.union_fusion_vectorize import (
        ALL_OPTIONAL_SOURCE_KEYS as _UNION_FUSION_ALL_OPTIONAL_SOURCES,
        DEFAULT_SLIVER_M2 as UNION_FUSION_DEFAULT_SLIVER_M2,
        dominant_composite,
        union_fusion_pieces,
        unpack_composite,
    )

    from geoalchemy2.shape import to_shape

    needs_dem_bands = sources is None or "dem" in sources

    # --- RS-10.0 (governs union_fusion equally -- it also needs MMU
    # boundaries for the final intersection pass below): auto-create MMU
    # at a 5 ha floor if this forest has none yet. ---
    mmu_layer = (
        db.query(RasterLayer)
        .filter(RasterLayer.calculation_id == calc.id, RasterLayer.source == "mmu")
        .order_by(RasterLayer.created_at.desc())
        .first()
    )
    mmu_auto_created = False
    if mmu_layer is None:
        mmu_preview = preview_mmu_blocks(db, calc, level="blocks", sliver_area_m2=50000.0)
        mmu_blocks_payload = [
            {**f["properties"], "geometry": f["geometry"]}
            for f in mmu_preview["pieces"]["features"]
        ]
        if not mmu_blocks_payload:
            raise ValueError("no_mmu_coverage")
        commit_blocks(
            db, calc, mmu_blocks_payload, level="blocks", source="mmu", allow_legacy=True,
        )
        mmu_layer = (
            db.query(RasterLayer)
            .filter(RasterLayer.calculation_id == calc.id, RasterLayer.source == "mmu")
            .order_by(RasterLayer.created_at.desc())
            .first()
        )
        mmu_auto_created = True

    mmu_rows = (
        db.query(ForestBlock)
        .filter(ForestBlock.raster_layer_id == mmu_layer.id)
        .order_by(ForestBlock.index)
        .all()
    )
    if not mmu_rows:
        raise ValueError("no_mmu_coverage")
    mmu_shapes = [(r, to_shape(r.geometry)) for r in mmu_rows]

    # Elevation bands: once per forest boundary (rule 16), the SAME table
    # union_zonal computes -- never a second independent one, or the two
    # modes would silently disagree on what "High" means. Only computed at
    # all when `dem` is among the selected sources (RS-10.3b) -- a run that
    # excludes DEM should not pay for this query or require DEM coverage.
    bands: List[tuple] = []
    if needs_dem_bands:
        boundary_wkt_for_stats = _boundary_shape(db, calc, None).wkt
        bands = band_table_for(calc, db, DEM_ELEVATION, boundary_wkt_for_stats, n_bands=3)
        if not bands:
            raise ValueError("no_elevation_coverage")

    # --- The pixel fusion itself ---
    fetch_sliver_m2 = sliver_area_m2 if sliver_area_m2 is not None else UNION_FUSION_DEFAULT_SLIVER_M2
    raw = union_fusion_pieces(
        calc, db, bands, sliver_m2=fetch_sliver_m2,
        scope_wkt=scope.wkt if scope is not None else None,
        sources=sources,
    )
    if not raw:
        raise ValueError("no_union_fusion_coverage")

    pieces = [geom for _code, geom in raw]
    pieces = _clip_to_scope(pieces, scope)
    pieces = _fill_holes(pieces, fetch_sliver_m2, protect_geom=hole_protect_geom(db, calc))
    pieces = _dedupe_overlaps(pieces)
    pieces, _absorbed = _absorb_slivers(pieces, fetch_sliver_m2, force_absorb_orphans)
    boundary_shape = _boundary_shape(db, calc, scope)
    pieces = _absorb_coverage_gaps(pieces, boundary_shape)
    pieces = _explode_multiparts(pieces)
    pieces = [make_valid(p) for p in pieces if p is not None and not p.is_empty]
    pieces.sort(key=lambda p: -_area_m2(p))
    pieces, _reabsorbed = _absorb_slivers(pieces, fetch_sliver_m2, force_absorb_orphans)
    pieces = [make_valid(p) for p in pieces if p is not None and not p.is_empty]
    pieces.sort(key=lambda p: -_area_m2(p))

    # --- MMU intersection: no piece may cross an MMU boundary. Each fused
    # piece is split by whichever MMU polygons it overlaps (a bounded,
    # non-combinatorial vector overlay -- at most a handful of MMU pieces
    # touch any one fused piece). ---
    mmu_split: list[tuple[Any, Any]] = []  # (geom, mmu_row)
    for p in pieces:
        touched_any = False
        for mmu_row, mmu_geom in mmu_shapes:
            if not mmu_geom.intersects(p):
                continue
            inter = make_valid(p.intersection(mmu_geom))
            if inter is None or inter.is_empty:
                continue
            touched_any = True
            for part in _explode_multiparts([inter]):
                if _area_m2(part) >= OVERLAP_EPSILON_M2:
                    mmu_split.append((part, mmu_row))
        if not touched_any:
            # Outside every MMU polygon (a sliver the MMU carve itself
            # absorbed elsewhere) -- keep the piece rather than silently
            # dropping real area, with no MMU reference.
            mmu_split.append((p, None))

    # Splitting against MMU boundaries can and does create new sub-floor
    # fragments that the EARLIER sliver-absorb pass never saw (RS-10.3 build
    # note: this was a real bug, found live -- 1226 pieces on a 316 ha test
    # forest, several under 0.001 ha). Re-absorb now, but ONLY within each
    # MMU group: a sliver must never be absorbed across an MMU boundary,
    # that would reintroduce the exact thing this split exists to prevent.
    by_mmu: Dict[Optional[str], List[Any]] = {}
    for g, m in mmu_split:
        key = str(m.id) if m is not None else None
        by_mmu.setdefault(key, []).append(g)
    mmu_by_id = {str(r.id): r for r, _g in mmu_shapes}
    mmu_split = []
    for key, group_geoms in by_mmu.items():
        absorbed_geoms, _n = _absorb_slivers(group_geoms, fetch_sliver_m2, force_absorb_orphans=True)
        row = mmu_by_id.get(key) if key is not None else None
        for g in absorbed_geoms:
            mmu_split.append((g, row))

    # Sub-areas: real vector geometry, largest-overlap, same rule as
    # union_zonal.
    sub_areas = db.query(ForestSubArea).filter(ForestSubArea.calculation_id == calc.id).all()
    sub_area_shapes = [(sa, to_shape(sa.geometry)) for sa in sub_areas]

    final_pieces = [g for g, _m in mmu_split]
    centroids = []
    for p in final_pieces:
        try:
            centroids.append(p.representative_point() if not p.is_empty else p.centroid)
        except Exception:
            logger.exception("union_fusion: representative point failed for a piece")
            centroids.append(None)
    valid = [(i, c) for i, c in enumerate(centroids) if c is not None]
    names = _nearest_natural_names(db, [c.x for _, c in valid], [c.y for _, c in valid], str(calc.id))
    name_map = {i: nm for (i, _), nm in zip(valid, names)}

    features = []
    for i, (p, mmu_row) in enumerate(mmu_split, start=1):
        wkt = p.wkt
        try:
            composite_code = dominant_composite(wkt, db, bands, sources=sources)
        except Exception:
            logger.exception("union_fusion: dominant_composite failed for a piece")
            composite_code = None
        # RS-10.3b: `unpack_composite` only returns keys for the sources
        # actually selected -- `.get(..., None)` below is how a deselected
        # attribute shows up, same shape as a selected-but-missing one, so
        # downstream code (commit_blocks, layer_features) does not need to
        # know which case it is.
        attrs = unpack_composite(composite_code, sources=sources) if composite_code is not None else {}

        # Owner report 2026-10-02: slope is the gate attribute for Union and
        # "the most important factor" -- the preview table needs a human
        # label/range (e.g. "19-31°"), not just the bare 0-3 code `attrs`
        # carries. `preview_union_zonal_blocks` already derives this the
        # same way (BAND_LABELS[band][1], English) -- mirrored here so both
        # Union modes show it identically.
        from app.services.sustainable_fm.slope_vectorize import BAND_LABELS as _SLOPE_BAND_LABELS
        slope_band_for_label = attrs.get("slope")
        slope_band_label = (
            _SLOPE_BAND_LABELS.get(slope_band_for_label, (None, None))[1]
            if slope_band_for_label else None
        )

        canopy_code = None
        canopy_label = None
        if include_canopy:
            try:
                canopy_code = canopy_dominant_class(wkt, db)
            except Exception:
                logger.exception("union_fusion: canopy_dominant_class failed for a piece")
                canopy_code = None
            canopy_label = CANOPY_CLASS_LABELS.get(canopy_code) if canopy_code else None

        best_sa = None
        best_overlap_m2 = 0.0
        for sa, sa_shape in sub_area_shapes:
            try:
                inter = p.intersection(sa_shape)
            except Exception:  # noqa: BLE001 -- an invalid sub-area shape cannot overlap this unit; skip it
                continue
            if inter.is_empty:
                continue
            area = _area_m2(inter)
            if area > best_overlap_m2:
                best_overlap_m2 = area
                best_sa = sa

        props = {
            "index": i,
            "name": f"Union-{i}",
            "block_name": f"Union-{i}",
            "natural_name": name_map.get(i - 1),
            "area_hectares": round(_area_m2(p) / SQM_PER_HA, 4),
            "dominant_slope_band": attrs.get("slope"),
            "slope_band_label": slope_band_label,
            "dominant_aspect": attrs.get("aspect"),
            "dominant_canopy_class": canopy_code,
            "canopy_class_label": canopy_label,
            "dominant_nasa_quality": attrs.get("nasa_quality"),
            "dominant_health_class": attrs.get("forest_health"),
            "dominant_landcover": attrs.get("landcover"),
            "dominant_forest_type": attrs.get("forest_type"),
            "dominant_contour_band": attrs.get("dem_band"),
            "sub_area_category": best_sa.category if best_sa is not None else None,
            "sub_area_excluded": bool(best_sa.is_excluded) if best_sa is not None else False,
            "mmu_piece_id": str(mmu_row.id) if mmu_row is not None else None,
        }
        features.append({"type": "Feature", "properties": props, "geometry": p.__geo_interface__})

    total_ha = sum(_area_m2(p) for p in final_pieces) / SQM_PER_HA
    meta = {
        "source_layer": "union_fusion",
        "base_layer": "mmu",
        "mmu_auto_created": mmu_auto_created,
        "mmu_layer_id": str(mmu_layer.id),
        "total_area_ha": round(total_ha, 4),
        "piece_count": len(features),
        "sliver_area_m2": fetch_sliver_m2,
        # RS-10.3b: what was actually fused, for the frontend to confirm/
        # display and for debugging -- slope is implied and never listed
        # here since it can't be deselected.
        "fused_sources": sorted(sources) if sources is not None else sorted(_UNION_FUSION_ALL_OPTIONAL_SOURCES),
        "canopy_included": include_canopy,
    }
    return {
        "meta": meta,
        "pieces": {"type": "FeatureCollection", "features": features},
        "edges": [],
    }


def check_compartment_sampling_mutex(db, calc, level: str) -> None:
    """Refuse compartment-level creation on a forest that already has sampling.

    Compartments and block-level sampling are mutually exclusive: the
    ``check_dimension_exclusivity()`` trigger on ``forest_blocks`` rejects any
    ``is_compartment`` insert once a ``sampling_designs`` row exists. Left to the
    trigger, the user gets a bare database error (a 500) *after* designing the
    whole split. Checking here raises the same ``SAMPLING_MUTEX`` ``ValueError``
    the divide-compartment endpoints use, so the caller can answer with the
    bilingual 400 — and the preview can say so before any work is done.
    Block level is unaffected.
    """
    if level == "compartments":
        sampling_mutex_check(db, calc.id)


def _promoted_or_legacy_blocks_exist(db, calc) -> bool:
    """RS-2.16, narrowed 2026-10-01 (owner report): the whole-forest
    BLOCKS_EXIST refusal guards only LEGACY rows now -- not "a layer is
    promoted". A calculation with ANY number of layers, promoted or not, has
    room for another trial: carving by slope does not use up the right to
    also carve by aspect, NASA quality, or any other source, no matter which
    (if any) is currently promoted. This applies to every source uniformly,
    not a special case per source.

    The earlier version also refused once a layer was promoted, reasoning
    that "the real structure already exists". That broke the actual
    workflow the owner wants: carve several sources, COMPARE them as
    independent layers, and only then decide which one to assign (D51's own
    "Compare" requirement) -- which requires being able to keep adding trial
    layers after the first promotion, not only before it. Switching which
    layer is promoted was already supported (`promote_layer(force=True)`);
    this just stops that switch from needing to happen before a second trial
    can even be created.

    The one case that still refuses: any row with ``raster_layer_id IS
    NULL`` -- created before migration 107, or by a path RS-2.16 has not
    moved onto layers yet (manual draw, import, divide/cut/merge). Those
    rows have always been real structure with no layer to coexist
    alongside, and this change does not touch that.
    """
    return (
        db.query(ForestBlock)
        .filter(
            ForestBlock.calculation_id == calc.id,
            ForestBlock.raster_layer_id.is_(None),
        )
        .first()
        is not None
    )


def _create_layer(db, calc, source: str) -> RasterLayer:
    """A fresh, unpromoted layer for one commit call (RS-2.16). Each commit
    always starts a new layer rather than appending to an existing one of the
    same source -- re-running a source is a new trial, not silently growing
    the last one, and the layer panel needs a stable identity per trial to
    let the owner compare them (D51 "Compare")."""
    existing = (
        db.query(RasterLayer)
        .filter(RasterLayer.calculation_id == calc.id, RasterLayer.source == source)
        .count()
    )
    name = source if existing == 0 else f"{source} ({existing + 1})"
    layer = RasterLayer(calculation_id=calc.id, source=source, name=name)
    db.add(layer)
    db.flush()
    return layer


def commit_blocks(
    db,
    calc,
    blocks: List[Dict[str, Any]],
    level: str = "blocks",
    sliver_area_m2: Optional[float] = None,
    scope: Any = None,
    source: Optional[str] = None,
    allow_legacy: bool = False,
) -> List[Dict[str, Any]]:
    """Stage 2 — persist the accepted blocks as `forest_blocks` rows, all
    belonging to one new, unpromoted `raster_layers` row (RS-2.16; ``source``
    ``None`` skips layer creation for legacy callers that pre-date P2.5 —
    those rows keep ``raster_layer_id`` NULL and behave exactly as before).

    Refuses (``BLOCKS_EXIST``) only when LEGACY rows exist (see
    ``_promoted_or_legacy_blocks_exist`` — narrowed 2026-10-01: a promoted
    layer no longer refuses a new trial either, so any number of sources can
    be carved and compared before any decision is made), and
    (``SAMPLING_MUTEX``) when compartments are requested on a forest that has
    a sampling design.
    Sets ``division_level`` per level (1 = top level in BOTH branches after
    migration 094 — the branch is ``is_compartment``, never the depth) and
    stores the serial ``block_name`` + best-effort ``natural_name`` + whichever
    of ``dominant_slope_band``/``dominant_aspect``/``dominant_canopy_class`` its
    source populated — all optional, source-agnostic pass-through fields;
    this function doesn't care which preview produced them.

    ``sliver_area_m2`` (m², same floor the preview used): a force-merged
    orphan island arrives here as a disjoint MultiPolygon. Exploding that into
    one row per part would re-surface a below-threshold block in the attribute
    table, so any part below the floor is folded back into the largest part
    (one multi-part row) instead of becoming its own row. ``None`` disables
    the fold (legacy callers keep the old one-part-per-row behaviour).

    ``scope`` (shapely polygon, optional; FS-4a.6): the whole-forest
    auto-create resolves this from the virtual root (boundary minus private
    land, protection units punched out), so committed pieces never spill onto
    private land / protection units. A scope equal to the boundary is a no-op.
    """
    # ``allow_legacy``: the Union sources auto-create their MMU base layer. That
    # layer is an unpromoted helper (promote_layer still refuses while legacy
    # rows exist), so imported/divided units must not block it -- otherwise
    # both Union modes fail with BLOCKS_EXIST on any forest that has units.
    if not allow_legacy and _promoted_or_legacy_blocks_exist(db, calc):
        raise ValueError("BLOCKS_EXIST")
    check_compartment_sampling_mutex(db, calc, level)

    layer = _create_layer(db, calc, source) if source else None

    is_compartment = level == "compartments"
    div_level = 1

    created: List[Dict[str, Any]] = []
    block_rows: List[ForestBlock] = []
    for req in blocks:
        geom = _as_shapely(req.get("geometry"))
        if geom is None or geom.is_empty:
            raise ValueError("invalid_geometry")
        geom = make_valid(geom)
        if not isinstance(geom, (Polygon, MultiPolygon)):
            raise ValueError("invalid_geometry_type")
        # Fill any residual holes from client-side edits (defensive).
        filled = _fill_holes([geom], protect_geom=hole_protect_geom(db, calc))
        geom = filled[0] if filled else geom
        # FS-4a.6: the whole-forest auto-create resolves its shell from the
        # virtual root. Clipping keeps committed pieces inside the shell when
        # private land / protection units exist; a scope equal to the boundary
        # leaves the geometry untouched.
        if scope is not None:
            geom = _as_polygonal(make_valid(geom.intersection(scope)))
            if geom is None or geom.is_empty:
                continue
        # Single-part guarantee (user report, Phase C): a multipart geometry
        # would persist one row with several polygons — the same block serial
        # split across separate places. Persist each part as its own row.
        parts = _explode_multiparts([geom])
        # A client-side geometry op on the committed shape (e.g. the
        # Auto-Block designer's merge-glue trick for pieces a generalization
        # source left disconnected — see autoBlockMerge.ts) can leave a
        # needle-thin numerical-noise fragment alongside the real piece(s):
        # thousandths of a m² in area but real, non-trivial perimeter.
        # OVERLAP_EPSILON_M2 already defines "not really there" for this
        # module; reuse it here so noise never persists as its own tiny
        # block/compartment.
        parts = [p for p in parts if _area_m2(p) >= OVERLAP_EPSILON_M2]
        if not parts:
            continue
        # Fold any sub-floor part back into the largest part. A force-merged
        # orphan island is a disjoint MultiPolygon by construction; exploding
        # it into its own row is exactly what re-surfaced a below-threshold
        # block in the attribute table. Above-floor parts stay their own rows
        # (the Phase C single-part guarantee), sub-floor parts never do.
        if sliver_area_m2 is not None and len(parts) > 1:
            parts.sort(key=lambda p: -_area_m2(p))
            keep = [parts[0]]
            for part in parts[1:]:
                if _area_m2(part) < sliver_area_m2:
                    keep[0] = _as_polygonal(make_valid(keep[0].union(part)))
                else:
                    keep.append(part)
            parts = keep
        base_index = int(req.get("index") or 0)
        for pi, part in enumerate(parts, start=1):
            sqm = _area_m2(part)
            block = ForestBlock(
                calculation_id=calc.id,
                name=req.get("name")
                or req.get("block_name")
                or block_serial(req.get('index')),
                area_hectares=round(sqm / SQM_PER_HA, 4),
                area_sqm=round(sqm, 2),
                index=base_index + (pi - 1),
                is_compartment=is_compartment,
                division_level=div_level,
                block_name=req.get("block_name"),
                natural_name=req.get("natural_name"),
                raster_layer_id=layer.id if layer is not None else None,
        dominant_slope_band=_dominant_class(req, "dominant_slope_band"),
        dominant_aspect=_dominant_class(req, "dominant_aspect"),
        dominant_canopy_class=_dominant_class(req, "dominant_canopy_class"),
        # Raster-Sources codes (migration 105) — same source-agnostic
        # pass-through as the 084/085 fields above; each preview
        # populates only its own and the others stay null.
        dominant_health_class=_dominant_class(req, "dominant_health_class"),
        dominant_nasa_quality=_dominant_class(req, "dominant_nasa_quality"),
        # Raw NASA class incl. 0 = non-forest, so a NULL above is explicable
        # (RS-2.14). Same spelling in the preview payload and the column, so
        # `_dominant_class` finds it on the first `req.get`.
        dominant_nasa_code=_dominant_class(req, "dominant_nasa_code"),
        dominant_landcover=_dominant_class(req, "dominant_landcover"),
        dominant_elevation_zone=_dominant_class(req, "dominant_elevation_zone"),
        dominant_forest_type=_dominant_class(req, "dominant_forest_type"),
        dominant_contour_band=_dominant_class(req, "dominant_contour_band"),
        # Union (P10, RS-10.1/10.2) — largest-overlap ForestSubArea category
        # + Private Land tag. Source-agnostic pass-through like every field
        # above; NULL/false for every other origin's preview payload.
        sub_area_category=req.get("sub_area_category"),
        sub_area_excluded=bool(req.get("sub_area_excluded") or False),
                elevation_min_m=req.get("elevation_min_m"),
                elevation_mean_m=req.get("elevation_mean_m"),
                elevation_max_m=req.get("elevation_max_m"),
            )
            # The forced-orphan absorb path intentionally produces a
            # single-serial block whose geometry may remain a disjoint
            # MultiPolygon (largest-part + below-floor island). That is the
            # one explicit exception to the single-part invariant; every other
            # persist path still goes through the validator unchanged.
            if isinstance(part, MultiPolygon) and sliver_area_m2 is not None:
                set_committed_value(block, "geometry", from_shape(part, srid=4326))
            else:
                block.geometry = from_shape(part, srid=4326)
            db.add(block)
            db.flush()
            block_rows.append(block)
            created.append(
                {
                    "id": str(block.id),
                    "name": block.name,
                    "block_name": block.block_name,
                    "natural_name": block.natural_name,
                    "dominant_slope_band": block.dominant_slope_band,
                    "dominant_aspect": block.dominant_aspect,
                    "dominant_canopy_class": block.dominant_canopy_class,
                    "dominant_health_class": block.dominant_health_class,
                    "dominant_nasa_quality": block.dominant_nasa_quality,
                    "dominant_landcover": block.dominant_landcover,
                    "dominant_elevation_zone": block.dominant_elevation_zone,
                    "dominant_forest_type": block.dominant_forest_type,
                    "dominant_contour_band": block.dominant_contour_band,
                    "elevation_min_m": block.elevation_min_m,
                    "elevation_mean_m": block.elevation_mean_m,
                    "elevation_max_m": block.elevation_max_m,
                    "area_hectares": block.area_hectares,
                    "index": block.index,
                }
            )

    # RS-2.19: elevation is a read-only attribute of every unit, whichever
    # source carved it -- not just the (now-retired) DEM carve path. One
    # batched query for every piece this call just created, then the
    # forest-relative Low/Mid/High zone from THIS forest's own units.
    from .elevation_service import apply_elevation, assign_relative_elevation_zones

    apply_elevation(db, block_rows)
    assign_relative_elevation_zones(block_rows)
    db.flush()
    by_id = {str(b.id): b for b in block_rows}
    for c in created:
        b = by_id.get(c["id"])
        if b is not None:
            c["elevation_min_m"] = b.elevation_min_m
            c["elevation_mean_m"] = b.elevation_mean_m
            c["elevation_max_m"] = b.elevation_max_m
            c["dominant_elevation_zone"] = b.dominant_elevation_zone

    from .forest_units.write import structure_write

    with structure_write(db, calc, change="auto-create blocks"):
        _apply_management_orientation(db, calc, created)
    db.commit()
    return created


def _apply_management_orientation(
    db, calc, created: List[Dict[str, Any]]
) -> None:
    """Commit-time entry point (dict-shaped preview payload) -- thin wrapper
    over `_apply_management_orientation_to_ids`. See that function for the
    real logic and the RS-2.18 caveat about WHEN this call is actually
    able to do anything."""
    ids = [c["id"] for c in created if c.get("dominant_slope_band") is not None]
    if not ids:
        return
    updated = _apply_management_orientation_to_ids(db, calc, ids)
    if not updated:
        return
    by_id = {str(row.id): row for row in updated}
    for c in created:
        row = by_id.get(c["id"])
        if row is not None:
            c["management_orientation"] = row.management_orientation
            c["suggested_orientation"] = row.suggested_orientation
            c["orientation_justification_en"] = row.orientation_justification_en
            c["orientation_justification_ne"] = row.orientation_justification_ne


def _apply_management_orientation_to_ids(
    db, calc, block_ids: List[Any]
) -> List["ForestBlock"]:
    """Auto-suggest ``management_orientation`` for the given blocks (user
    report, 2026-09-12 -- extended 2026-10-01, see the bug note below) by
    running SFM's own classification pipeline once for the whole forest and
    copying each block's ``orientation`` across. Reuses
    `sustainable_fm.sfm_service.build_sfm` wholesale rather than re-deriving
    the same zone/species/type/orientation chain here — this is the exact
    machinery the SFM tab itself runs, so "Suggested Orientation" (read live
    from the same cache elsewhere) never disagrees with how this value was
    first seeded.

    Touches every given block, whatever source carved it (see the inline
    note below on why no slope-band filter is needed). Best-effort: SFM's pipeline touches several
    optional rasters (physiography, forest-type, species-association tables)
    that may be absent on a given deployment or for a given forest — any
    failure here must never break an otherwise-successful call, so it is
    logged and swallowed, leaving ``management_orientation`` NULL (the
    column's default, and still user-settable by hand afterward).

    **Bug this exists to fix (owner report, 2026-10-01): "After promoting in
    compartment/block ... Management Orientation / Suggested Orientation /
    Justification must be populated."** `build_sfm`'s own block list
    (`_leaf_units` -> `forest_units.queries.unit_rows` ->
    `promoted_or_unlayered`) only sees PROMOTED or legacy (unlayered) rows —
    RS-2.16/2.18's own promotion filtering, built earlier this session. A
    layer-scoped commit's rows are NEITHER at the moment `commit_blocks`
    calls the dict-shaped wrapper above (the layer is still an unpromoted
    trial by definition at that point) — so that call has been silently
    finding ZERO matches and leaving orientation NULL for every source,
    including plain `slope`, since RS-2.16 landed, not just union_zonal.
    Verified live against calc `fa52e156…`'s own slope layer. The real fix
    is this function being called AGAIN once promotion actually happens
    (`promote_layer`/`promote_layer_as_children`, both below), when the rows
    are finally visible to `build_sfm`. Returns the updated ``ForestBlock``
    rows (empty list on no-op or failure) so a caller can merge the result
    into its own response payload if it has one.
    """
    # No `dominant_slope_band` filter here (owner report 2026-10-01: these
    # fields "must be populated" after promotion, for any source). SFM's
    # "user" zone provider (`sfm_service._user_zone`) already uses the row's
    # own slope band when set and falls back to the slope raster when not --
    # so an Aspect/NASA/Canopy/Land-cover layer gets a real orientation too.
    # The commit-time wrapper above keeps its own slope-band pre-filter, so
    # an MMU commit still never pays for an SFM run.
    rows_to_check = db.query(ForestBlock).filter(ForestBlock.id.in_(block_ids)).all()
    ids = [r.id for r in rows_to_check]
    if not ids:
        return []
    try:
        from .sustainable_fm.sfm_service import build_sfm

        # variant="user": this is precisely the slope-sourced case the
        # "user" zone provider exists for (SV-1.2) -- it trusts each new
        # piece's own known dominant_slope_band instead of re-reading a
        # slope raster that may not cover this forest at all (the baseline
        # variant used before 2026-09-15 would silently classify with band
        # None wherever the raster had no coverage, defeating this
        # function's entire purpose on exactly the forests where it matters
        # most).
        sfm = build_sfm(calc, db, force=True, variant="user")
        orientation_by_name = {
            b.get("block_name"): {
                "orientation": b.get("orientation"),
                "justification_en": b.get("orientation_justification_en"),
                "justification_ne": b.get("orientation_justification_ne"),
            }
            for b in sfm.get("blocks", [])
            if isinstance(b, dict) and b.get("block_name")
        }
    except Exception:  # noqa: BLE001 -- best-effort suggestion, never fatal
        logger.warning(
            "management_orientation auto-suggestion failed for calc=%s "
            "(SFM pipeline) -- left NULL, still user-settable",
            calc.id, exc_info=True,
        )
        return []

    rows = [r for r in rows_to_check if r.id in set(ids)]
    updated: List["ForestBlock"] = []
    for row in rows:
        info = orientation_by_name.get(row.block_name) or orientation_by_name.get(row.name)
        if info:
            ori = info.get("orientation")
            if ori:
                row.management_orientation = ori
                row.suggested_orientation = ori
                row.orientation_justification_en = info.get("justification_en")
                row.orientation_justification_ne = info.get("justification_ne")
                updated.append(row)
    db.flush()
    return updated


# ---------------------------------------------------------------------------
# Promote / demote a layer (RS-2.17) — the act that turns one Auto-Block
# layer's rows into the calculation's authoritative blocks/compartments
# stream. Everything else (preview, commit) is source-agnostic and layer-
# scoped already; this is the one place "which layer is real" gets decided.
# ---------------------------------------------------------------------------


def promote_layer(
    db, calc, layer_id, as_level: str, force: bool = False
) -> Dict[str, Any]:
    """Promote ``layer_id`` to be the calculation's real structure.

    ``as_level`` is ``"blocks"`` or ``"compartments"`` — same vocabulary
    ``commit_blocks(level=...)`` uses. Raises:

    - ``LAYER_NOT_FOUND`` — no such layer for this calculation.
    - ``LEGACY_BLOCKS_EXIST`` — the calculation has pre-P2.5 rows
      (``raster_layer_id IS NULL``); those have no layer to demote, so
      promoting anything else would create two live streams at once. Not
      raised by ``force`` — there is nothing to switch away from.
    - ``PROMOTED_LAYER_EXISTS`` — a different layer is already promoted and
      ``force`` was not set (the "offers to switch" refusal, D51).
    - ``SAMPLING_MUTEX:...`` — compartments requested over a block-level
      sampling design (same check ``commit_blocks`` runs).

    With ``force=True``, any other promoted layer for this calculation is
    demoted first (its rows are untouched — they simply stop counting).
    """
    layer = (
        db.query(RasterLayer)
        .filter(RasterLayer.id == layer_id, RasterLayer.calculation_id == calc.id)
        .first()
    )
    if layer is None:
        raise ValueError("LAYER_NOT_FOUND")
    if as_level not in ("blocks", "compartments"):
        raise ValueError("bad_level")

    # Owner report 2026-10-02: "I ... tried to assign as block again but it
    # is not assigned. Neither I see any error." Root cause: a layer's
    # ForestBlock rows can be deleted from OUTSIDE this module entirely --
    # the ordinary compartment/block delete endpoints
    # (`compartments.py::delete_compartment`, `blocks.py`/`forests.py`'s
    # `delete_block`) have no idea a row came from a promoted layer and
    # never touch `raster_layers` -- so a layer can end up with ZERO
    # underlying rows while this function, with nothing else to check,
    # would otherwise flip `promoted_as` and commit a bare "success" with
    # nothing for the caller to show. Checked BEFORE any write below, so a
    # genuinely empty layer refuses loudly instead of lying.
    if not db.query(ForestBlock).filter(ForestBlock.raster_layer_id == layer.id).first():
        raise ValueError("EMPTY_LAYER")

    has_legacy = (
        db.query(ForestBlock)
        .filter(
            ForestBlock.calculation_id == calc.id,
            ForestBlock.raster_layer_id.is_(None),
        )
        .first()
        is not None
    )
    if has_legacy:
        raise ValueError("LEGACY_BLOCKS_EXIST")

    other_promoted = (
        db.query(RasterLayer)
        .filter(
            RasterLayer.calculation_id == calc.id,
            RasterLayer.promoted_as.isnot(None),
            RasterLayer.id != layer.id,
        )
        .first()
    )
    if other_promoted is not None and not force:
        raise ValueError("PROMOTED_LAYER_EXISTS")

    check_compartment_sampling_mutex(db, calc, as_level)

    from sqlalchemy.sql import func as sa_func

    if other_promoted is not None:
        other_promoted.promoted_as = None
        other_promoted.promoted_at = None
        # Owner report 2026-10-01: "I see this message 'union_zonal promoted'
        # but actually not promoted." Root cause: `raster_layers` carries a
        # partial UNIQUE index (`uq_raster_layers_one_promoted_per_calc`,
        # non-deferred, checked per-statement by Postgres) enforcing one
        # promoted layer per forest. Setting both this demotion AND the new
        # layer's promotion in the SAME `db.flush()` call left their UPDATE
        # order up to SQLAlchemy's unit-of-work, which does not guarantee
        # "demote the old row" runs before "promote the new row" -- when it
        # didn't, both rows briefly had `promoted_as='blocks'` at once and
        # Postgres raised `UniqueViolation`, caught by nothing in this
        # function or the API layer, so the request failed with a 500 the
        # frontend's generic error handling likely rendered unhelpfully (or,
        # on the luck-of-the-draw orderings where it didn't collide, silently
        # worked — this was flaky, not consistently broken, which is why it
        # went unnoticed). Flushing the demotion HERE, on its own, guarantees
        # the old row is NULL in the database before the new row's
        # `promoted_as` is ever set, so the two writes can never collide.
        db.flush()

    is_compartment = as_level == "compartments"
    db.query(ForestBlock).filter(ForestBlock.raster_layer_id == layer.id).update(
        {ForestBlock.is_compartment: is_compartment}, synchronize_session=False
    )
    layer.promoted_as = as_level
    layer.promoted_at = sa_func.now()
    # Owner report 2026-10-01: Management Orientation/Suggested Orientation/
    # Justification must be populated once a layer actually becomes real
    # structure. Flushed BEFORE this call (not merely assigned in memory) so
    # build_sfm's own promoted_or_unlayered-filtered query -- run inside
    # this same session/transaction -- can actually see these rows as
    # promoted; see `_apply_management_orientation_to_ids`'s docstring for
    # the bug this closes (it affected every source, not just the one that
    # prompted the report).
    db.flush()
    promoted_rows = db.query(ForestBlock).filter(ForestBlock.raster_layer_id == layer.id).all()
    if promoted_rows:
        _apply_management_orientation_to_ids(db, calc, [b.id for b in promoted_rows])
    db.commit()
    return {
        "id": str(layer.id),
        "source": layer.source,
        "name": layer.name,
        "promoted_as": layer.promoted_as,
        "switched_from": str(other_promoted.id) if other_promoted is not None else None,
    }


def delete_layer(db, calc, layer_id) -> Dict[str, Any]:
    """Delete a trial layer and its pieces (owner report, 2026-10-01: "I can
    not remove auto created layer. Make it deletable.").

    Refuses on a PROMOTED layer (``PROMOTED_CANNOT_DELETE``) — its rows are
    the forest's real blocks/compartments, not a trial to discard; demote it
    first (`demote_layer`), which is a reversible, non-destructive act, unlike
    this one. An unpromoted layer's rows are not real structure yet (RS-2.16),
    so deleting it is safe: `forest_blocks.raster_layer_id` is
    `ON DELETE CASCADE` (migration 107), so its pieces are removed by the
    database itself, not by a second query here.
    """
    layer = (
        db.query(RasterLayer)
        .filter(RasterLayer.id == layer_id, RasterLayer.calculation_id == calc.id)
        .first()
    )
    if layer is None:
        raise ValueError("LAYER_NOT_FOUND")
    if layer.promoted_as is not None:
        raise ValueError("PROMOTED_CANNOT_DELETE")
    db.delete(layer)
    db.commit()
    return {"ok": True, "id": str(layer_id)}


def demote_layer(db, calc, layer_id) -> Dict[str, Any]:
    """Demote a promoted layer back to a non-counting overlay. Raises
    ``LAYER_NOT_FOUND`` for a missing/foreign layer id."""
    layer = (
        db.query(RasterLayer)
        .filter(RasterLayer.id == layer_id, RasterLayer.calculation_id == calc.id)
        .first()
    )
    if layer is None:
        raise ValueError("LAYER_NOT_FOUND")
    layer.promoted_as = None
    layer.promoted_at = None
    db.commit()
    return {"id": str(layer.id), "promoted_as": None}


def demote_orphaned_layers(db, raster_layer_ids) -> None:
    """Owner report 2026-10-02: "I ... tried to assign as block again but it
    is not assigned. Neither I see any error." Root cause: the ordinary
    compartment/block delete endpoints (``compartments.py::delete_compartment``,
    ``blocks.py``/``forests.py``'s ``delete_block``) have no idea a row came
    from a promoted ``RasterLayer`` and never touched it -- so deleting a
    promoted layer's LAST underlying row left the ``RasterLayer`` row
    silently orphaned: still ``promoted_as='compartments'``/``'blocks'``,
    now with zero real rows under it. A later ``promote_layer`` call on
    that orphan now refuses loudly (``EMPTY_LAYER``) instead of lying, but
    the orphan itself still needs clearing so it stops claiming to be the
    forest's real structure with nothing there.

    Called by every delete path that can remove a ``ForestBlock`` row with
    a non-null ``raster_layer_id`` (compartments.py, blocks.py, forests.py),
    right after the delete is committed, with the set of
    ``raster_layer_id``s those deleted rows carried (collected BEFORE the
    delete, since the rows are gone afterward). A layer that still has
    surviving rows is left untouched -- this only demotes layers that are
    now genuinely empty. Best-effort: never raises, so a cleanup failure
    here can never turn a successful delete into a failed one.
    """
    if not raster_layer_ids:
        return
    try:
        for raster_layer_id in set(raster_layer_ids):
            if raster_layer_id is None:
                continue
            still_has_rows = (
                db.query(ForestBlock)
                .filter(ForestBlock.raster_layer_id == raster_layer_id)
                .first()
                is not None
            )
            if still_has_rows:
                continue
            layer = db.query(RasterLayer).filter(RasterLayer.id == raster_layer_id).first()
            if layer is not None and layer.promoted_as is not None:
                layer.promoted_as = None
                layer.promoted_at = None
        db.commit()
    except Exception:  # noqa: BLE001 -- best-effort cleanup, never blocks a delete
        logger.exception("demote_orphaned_layers: cleanup failed, leaving orphan(s) for a later promote_layer to catch")
        db.rollback()


def _source_attribute(source: str, block: "ForestBlock") -> Tuple[Optional[str], Any, Optional[str]]:
    """``(display_label, raw_code, human_label)`` for one block's classification
    under ``source`` -- the ONE column an Auto-Block layer's attribute table
    should show (owner directive 2026-10-01: "No slope related column name"
    [on a NASA layer] -- each layer's table carries only its own source's
    attribute, not the other eight `dominant_*` columns, which would all be
    blank for it anyway). ``(None, None, None)`` for ``mmu`` -- river/ridge
    carving has no classification, only `natural_name`.
    """
    from app.core.forest_types import (
        ESA_WORLD_COVER,
        FOREST_HEALTH_CLASSES,
        FRTC_FOREST_TYPES,
        NASA_FOREST_QUALITY,
    )
    from .aspect_vectorize import ASPECT_DEGREE_RANGE
    from .canopy_vectorize import CANOPY_CLASS_LABELS
    from .raster_class_vectorize import ASPECT_CLASSES, DEM_ELEVATION, SLOPE_CLASSES
    from .sustainable_fm.slope_vectorize import BAND_LABELS as SLOPE_DEGREE_RANGE

    if source == "slope":
        code = block.dominant_slope_band
        # Owner report 2026-10-01: "it would be better if we provide the
        # slope range like gentle(>19)" -- appends the same °-range SFM's
        # own slope-class digitizing aid already shows (§15.2 zonation),
        # rather than inventing a second number.
        name = SLOPE_CLASSES.label(code) if code is not None else None
        rng = SLOPE_DEGREE_RANGE.get(code) if code is not None else None
        human = f"{name} ({rng[1]})" if name and rng else name
        return "Slope Band", code, human
    if source == "aspect":
        code = block.dominant_aspect
        name = ASPECT_CLASSES.label(code) if code is not None else None
        rng = ASPECT_DEGREE_RANGE.get(code) if code is not None else None
        human = f"{name} ({rng})" if name and rng else name
        return "Aspect", code, human
    if source == "canopy":
        code = block.dominant_canopy_class
        return "Canopy Class", code, (CANOPY_CLASS_LABELS.get(code) if code is not None else None)
    if source == "nasa_quality":
        code = block.dominant_nasa_quality
        entry = NASA_FOREST_QUALITY.get(code) if code is not None else None
        return "NASA Forest Quality", code, (entry.name_en if entry is not None else None)
    if source == "forest_health":
        code = block.dominant_health_class
        entry = FOREST_HEALTH_CLASSES.get(code) if code is not None else None
        return "Forest Health", code, (entry.name_en if entry is not None else None)
    if source == "landcover":
        code = block.dominant_landcover
        entry = ESA_WORLD_COVER.get(code) if code is not None else None
        return "Land Cover", code, (entry.name_en if entry is not None else None)
    if source == "dem":
        code = block.dominant_contour_band
        return "Elevation Band", code, (DEM_ELEVATION.label(code) if code is not None else None)
    if source == "forest_type":
        code = block.dominant_forest_type
        entry = FRTC_FOREST_TYPES.get(code) if code is not None else None
        return "Forest Type", code, (entry.name_en if entry is not None else None)
    return None, None, None


def layer_features(db, calc, layer_id) -> List[Dict[str, Any]]:
    """GeoJSON features for ONE Auto-Block layer's own rows (owner directive
    2026-10-01): geometry exactly as every other built-in layer serializes it
    (``shapely.mapping``, WGS84 — matches `blocks.py`'s own pattern), and
    properties limited to this layer's own classification, never the other
    eight `dominant_*` columns.
    """
    from geoalchemy2.shape import to_shape
    from shapely.geometry import mapping

    layer = (
        db.query(RasterLayer)
        .filter(RasterLayer.id == layer_id, RasterLayer.calculation_id == calc.id)
        .first()
    )
    if layer is None:
        raise ValueError("LAYER_NOT_FOUND")
    rows = (
        db.query(ForestBlock)
        .filter(ForestBlock.raster_layer_id == layer.id)
        .order_by(ForestBlock.index)
        .all()
    )
    # Owner report 2026-10-01: "elevation layer has only high, mid, low
    # value. High from m to m is expected alongside." The per-forest band
    # cut points (`band_table_for`, RS-9.3) are computed at carve time and
    # never persisted -- but every committed row already carries its own
    # `elevation_min_m`/`elevation_max_m` (RS-2.19, computed for every unit
    # regardless of source), so the band's actual observed range can be
    # reconstructed here by aggregating THIS layer's own rows per band,
    # rather than adding a new persisted column for it.
    band_range_m: Dict[int, Tuple[float, float]] = {}
    if layer.source == "dem":
        for row in rows:
            code = row.dominant_contour_band
            if code is None or row.elevation_min_m is None or row.elevation_max_m is None:
                continue
            lo, hi = float(row.elevation_min_m), float(row.elevation_max_m)
            prev = band_range_m.get(code)
            band_range_m[code] = (min(lo, prev[0]), max(hi, prev[1])) if prev else (lo, hi)

    is_union = layer.source in ("union_zonal", "union_fusion")

    out = []
    for row in rows:
        props: Dict[str, Any] = {
            "Name": row.block_name or row.name,
            # Owner directive 2026-10-01 (default per-source styling/labels):
            # the frontend keys its style lookup on the layer's SOURCE, not
            # the column label, so it needs this even though it duplicates
            # `RasterLayerInfo.source` the panel already has -- a map popup
            # or exported feature has no access to that sibling object.
            "_source": layer.source,
        }
        if row.natural_name:
            props["Natural Name"] = row.natural_name
        props["Area (ha)"] = row.area_hectares

        if is_union:
            # RS-10.4: Union is the deliberate exception to "one layer, one
            # column" (plan §P10 "Everything both modes share") -- showing
            # the combination is its entire purpose. All 9 at once, each
            # under its own source's usual column name, each with its own
            # `_<label>_code` the same ramp-styling convention every other
            # source already relies on.
            for source_key, label in (
                ("slope", "Slope Band"),
                ("aspect", "Aspect"),
                ("canopy", "Canopy Class"),
                ("nasa_quality", "NASA Forest Quality"),
                ("forest_health", "Forest Health"),
                ("landcover", "Land Cover"),
                ("forest_type", "Forest Type"),
                ("dem", "Elevation Band"),
            ):
                _, code, human = _source_attribute(source_key, row)
                if human is None and code is None:
                    continue
                props[label] = human if human is not None else code
                if code is not None:
                    props[f"_{label}_code"] = code
            props["Sub-area"] = row.sub_area_category or "Unassigned"
            if row.sub_area_excluded:
                props["Sub-area excluded (Private Land)"] = True
        else:
            label, code, human = _source_attribute(layer.source, row)
            if layer.source == "dem" and code is not None and human is not None:
                rng = band_range_m.get(code)
                if rng is not None:
                    human = f"{human} ({rng[0]:.0f}–{rng[1]:.0f} m)"
            if label is not None:
                props[label] = human if human is not None else code
                # The raw ordinal code too, under a derived key -- a ramp
                # style (slope/NASA/health/elevation bands) needs the NUMBER
                # to interpolate a position; the human label ("Steep") alone
                # can't be ranked generically, and DEM's band count varies
                # per forest so a fixed label->rank table doesn't work for
                # it anyway.
                if code is not None:
                    props[f"_{label}_code"] = code

        out.append(
            {
                "type": "Feature",
                "id": str(row.id),
                "properties": props,
                "geometry": mapping(to_shape(row.geometry)),
            }
        )
    return out


def promote_layer_as_children(
    db, calc, layer_id, parent_id, sliver_area_m2: Optional[float] = None,
) -> Dict[str, Any]:
    """RS-2.17 sub-unit assignment (owner directive 2026-10-01): promote one
    Auto-Block layer's pieces as the CHILDREN of one existing parent
    block/compartment -- sub-blocks under a block, sub-compartments under a
    compartment, matching the parent's own branch (same rule
    `resolve_divide_scope`/`commit_children` already enforce for the
    per-feature natural divide).

    Unlike the top-level `promote_layer` (RS-2.16), this does not touch
    `raster_layers.promoted_as` -- the source layer stays exactly as it was
    (still a non-counting trial overlay at the top level, still available to
    promote or assign elsewhere), because what changes here is the PARENT's
    structure, not the layer's own status. The new child rows are real
    structure from the moment they are created (parented under an existing
    real unit), so they are NOT tagged with `raster_layer_id` -- that field
    means "this row is part of an independent top-level layer awaiting a
    decision", which no longer describes a child.

    The layer's pieces were carved against the WHOLE FOREST boundary, not the
    chosen parent's extent, so each piece is re-clipped to the parent's scope
    here (`resolve_divide_scope`'s hole-punched extent) -- the same
    fill-holes / clip / explode / fold-slivers treatment `commit_children`
    gives a fresh natural-feature divide, just starting from already-carved
    geometry instead of a raster. A piece entirely outside the parent's scope
    contributes nothing; a piece straddling the parent's edge is clipped down
    to its own contribution. Each resulting part keeps ITS OWN source row's
    classification (slope band, NASA class, etc. -- whichever the layer's
    source populates), not the parent's -- `_persist_children`'s `extras`
    override is exactly "this piece's own values beat the parent's inherited
    ones".
    """
    from geoalchemy2.shape import to_shape

    from .compartment_divide_service import (
        MIN_COMPARTMENT_AREA_M2,
        _persist_children,
        _set_compartment_mode,
        _validate_parent_coverage,
        _write_history,
    )

    layer = (
        db.query(RasterLayer)
        .filter(RasterLayer.id == layer_id, RasterLayer.calculation_id == calc.id)
        .first()
    )
    if layer is None:
        raise ValueError("LAYER_NOT_FOUND")

    parent, layer_type, scope = resolve_divide_scope(db, calc, parent_id)
    if sliver_area_m2 is None:
        sliver_area_m2 = MIN_COMPARTMENT_AREA_M2

    rows = (
        db.query(ForestBlock)
        .filter(ForestBlock.raster_layer_id == layer.id)
        .order_by(ForestBlock.index)
        .all()
    )
    if not rows:
        raise ValueError("EMPTY_LAYER")

    pieces: List[Any] = []
    extras: List[Dict[str, Any]] = []
    for row in rows:
        geom = to_shape(row.geometry) if row.geometry is not None else None
        if geom is None or geom.is_empty:
            continue
        clipped = _as_polygonal(make_valid(geom.intersection(scope)))
        if clipped is None or clipped.is_empty:
            continue
        parts = [p for p in _explode_multiparts([clipped]) if _area_m2(p) >= OVERLAP_EPSILON_M2]
        if not parts:
            continue
        if len(parts) > 1:
            parts.sort(key=lambda p: -_area_m2(p))
            keep = [parts[0]]
            for part in parts[1:]:
                if _area_m2(part) < sliver_area_m2:
                    keep[0] = _as_polygonal(make_valid(keep[0].union(part)))
                else:
                    keep.append(part)
            parts = keep
        own = {
            "natural_name": row.natural_name,
            "dominant_slope_band": row.dominant_slope_band,
            "dominant_aspect": row.dominant_aspect,
            "dominant_canopy_class": row.dominant_canopy_class,
            "dominant_health_class": row.dominant_health_class,
            "dominant_nasa_quality": row.dominant_nasa_quality,
            "dominant_nasa_code": row.dominant_nasa_code,
            "dominant_landcover": row.dominant_landcover,
            "dominant_forest_type": row.dominant_forest_type,
            "dominant_contour_band": row.dominant_contour_band,
            # RS-10.1/10.2 (P10): without these two, a Union piece assigned
            # here would silently inherit the PARENT's sub-area classification
            # via `child_inherit_kwargs` instead of its own (`extras` is the
            # per-piece override; omitting a key here means "fall through to
            # the parent", which is correct for most columns but wrong for a
            # Union piece's own largest-overlap sub-area).
            "sub_area_category": row.sub_area_category,
            "sub_area_excluded": row.sub_area_excluded,
        }
        for part in parts:
            pieces.append(part)
            extras.append(own)

    if not pieces:
        raise ValueError("NO_OVERLAP")

    child_ids = _persist_children(
        db, calc, parent, layer_type, pieces,
        naming_pattern="", created_by=None, extras=extras, allow_multipart=True,
    )
    # The layer may reach only PART of the parent (a carve that stops short, or a parent the layer
    # barely overlaps). Whatever no child covers becomes a remainder sub-unit -- the same G2 rule a
    # parent reshape applies -- so the children always tile the parent: sub-unit total = parent area.
    from .forest_units.operations.reshape import reclip_children as _complete_parent

    if parent.geometry is not None:
        child_ids = list(child_ids) + _complete_parent(db, calc, parent.id, to_shape(parent.geometry))[
            "remainder_added"
        ]
    _validate_parent_coverage(db, calc, parent, child_ids)
    _write_history(
        db, calc, parent,
        method="raster_layer_assign",
        direction=None,
        parameters={"source": layer.source, "layer_id": str(layer.id)},
        n_children=len(child_ids),
        naming_pattern="",
        notes=f"Assigned from Auto-Block layer '{layer.name}' ({layer.source})",
        created_by=None,
    )
    if layer_type == "compartments":
        _set_compartment_mode(calc)
    # Owner report 2026-10-01: same orientation fix as `promote_layer` above
    # -- these children are real (unlayered) structure from the moment
    # `_persist_children` flushed them, so they are already visible to
    # build_sfm's promoted_or_unlayered-filtered query; no extra flush
    # needed here, unlike the top-level promote path.
    if child_ids:
        _apply_management_orientation_to_ids(db, calc, child_ids)
    db.commit()
    return {
        "ok": True,
        "parent_id": str(parent.id),
        "layer_type": layer_type,
        "child_ids": child_ids,
        "n_children": len(child_ids),
    }


def list_layers(db, calc) -> List[Dict[str, Any]]:
    """Every Auto-Block layer for this calculation, for the layer panel."""
    rows = (
        db.query(RasterLayer)
        .filter(RasterLayer.calculation_id == calc.id)
        .order_by(RasterLayer.created_at)
        .all()
    )
    return [
        {
            "id": str(r.id),
            "source": r.source,
            "name": r.name,
            "promoted_as": r.promoted_as,
            "promoted_at": r.promoted_at.isoformat() if r.promoted_at else None,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Divide a SELECTED feature by a natural basis (river/ridge, slope, aspect, canopy)
# ---------------------------------------------------------------------------
# The whole-forest flow above refuses once any block exists (BLOCKS_EXIST). This is
# its per-feature sibling: the same four sources, clipped to one block / compartment,
# persisted as its children (block -> compartments, compartment -> sub-compartments)
# under exactly the rules `compartment_divide_service` already applies to an
# equal-area divide (sampling mutex, once-only, lock, private-land / protection holes).

# The single source of truth for "which natural bases can we divide along".
# ``app/api/editing.py`` used to keep a second, function-local copy of this map
# (``_PREVIEW_FNS``, rebuilt on every preview request) and a third membership
# check (``DIVIDE_SOURCES``). One dict now, imported by both call sites, so a new
# source cannot be registered in one place and forgotten in the other (RS-0.3).
PREVIEW_FN_BY_SOURCE = {
    "mmu": preview_mmu_blocks,
    "slope": preview_slope_blocks,
    "aspect": preview_aspect_blocks,
    "canopy": preview_canopy_blocks,
    "nasa_quality": preview_nasa_quality_blocks,
    # RS-9.1/9.2 (P9, owner directive 2026-10-01): resurrects P3/P3.7 — the
    # carve engine and RasterClassSpecs already existed (P1), only these two
    # wrappers + this registration were missing.
    "forest_health": preview_forest_health_blocks,
    "landcover": preview_landcover_blocks,
    # RS-9.3 (P9): continuous path (band_table_for/reclass_pieces), not
    # class_pieces — see preview_elevation_blocks's own docstring.
    "dem": preview_elevation_blocks,
    # RS-9.5 (P9): RS-4.1a resolved 2026-10-01 — class 26 is anonymous
    # ("Unclassified"), same treatment as NASA's code 0.
    "forest_type": preview_forest_type_blocks,
    # RS-10.2 (P10): Mode B/default. Orchestrates the other sources above
    # against an MMU base rather than carving its own raster — see this
    # function's own docstring for why it cannot follow the spec/table
    # template every other entry here does.
    "union_zonal": preview_union_zonal_blocks,
    # RS-10.3 (P10): Mode A/opt-in. Shares the same MMU-auto-create
    # prerequisite as union_zonal but otherwise orchestrates
    # union_fusion_vectorize's pixel-stack fusion instead.
    "union_fusion": preview_union_fusion_blocks,
}
DIVIDE_SOURCES = tuple(PREVIEW_FN_BY_SOURCE)

# Every caller that needs a source's preview function goes through here, so an
# unknown source always fails the same way. The service layer raises the bare
# ``ValueError("bad_source")`` it has always raised; the API layer maps that one
# code to ``blocks.bad_source`` via ``_auto_divide_error`` / ``i18n_error``, which
# is what makes the three endpoints' error *shapes* identical rather than merely
# both being 400.
SOURCE_ERROR_CODE = "bad_source"


def resolve_source_fn(source: str):
    """Return the preview function for ``source``, or raise ``bad_source``."""
    fn = PREVIEW_FN_BY_SOURCE.get(source)
    if fn is None:
        raise ValueError(SOURCE_ERROR_CODE)
    return fn


def is_valid_source(source: str) -> bool:
    """Membership test for endpoints that only need a yes/no (no exception)."""
    return source in PREVIEW_FN_BY_SOURCE


def resolve_divide_scope(db, calc, parent_id):
    """Guard + resolve the feature to divide -> ``(parent, layer_type, scope)``.

    ``scope`` is the parent's polygon minus private land and protection units (a
    permanent hole, same as the equal-area divide); children tile ``scope``.
    Raises the divide service's own ``ValueError`` guard messages.
    """
    from . import geometry_edit_service as geo
    from .compartment_divide_service import (
        ERR_LOCKED,
        ERR_ONCE_ONLY,
        ERR_PARENT_NOT_FOUND,
        _exclusion_for_parent,
        _resolve_parent,
    )

    row = (
        db.query(ForestBlock)
        .filter(ForestBlock.id == parent_id, ForestBlock.calculation_id == calc.id)
        .first()
    )
    if row is None:
        raise ValueError(ERR_PARENT_NOT_FOUND)
    # FS-4a.6 (D3/D1): the children follow the parent's BRANCH, one level
    # deeper. The retired block -> compartments chain is gone -- a block's
    # natural divide carves SUB-BLOCKS, a compartment's carves
    # sub-compartments, and (A1) any deeper level may be divided again. The
    # only child layers this resolve ever returns are "sub_blocks" and
    # "sub_compartments".
    layer_type = "sub_blocks" if not row.is_compartment else "sub_compartments"
    parent = _resolve_parent(db, parent_id, layer_type)
    # FS-4a.5: the equal-area divide's own calc-wide "only ONE block may own
    # compartments" restriction (`_check_once_only`) is gone now too -- this
    # function was the precedent for removing it, and the two guards are
    # identical again. What holds here, same as there: the lock, and each
    # feature is divided once (next check). There is NO sampling mutex on this
    # path: sub-blocks on a forest that carries a block-level sampling design
    # are legal (parity with the equal-area block divide), and sub-compartments
    # keep exactly today's behaviour.
    if parent.is_locked:
        raise ValueError(ERR_LOCKED)
    # A feature is divided once: a second set would stack on the first.
    if db.query(ForestBlock).filter(ForestBlock.parent_block_id == parent.id).count() > 0:
        raise ValueError(ERR_ONCE_ONLY)

    parent_geom = geo.as_shapely(parent.geometry)
    if parent_geom is None or parent_geom.is_empty:
        raise ValueError("invalid_geometry")
    exclude = _exclusion_for_parent(db, calc, parent_geom)
    scope = parent_geom.difference(exclude) if exclude is not None else parent_geom
    scope = _as_polygonal(make_valid(scope))
    if scope is None or scope.is_empty:
        raise ValueError("no_coverage_in_feature")
    return parent, layer_type, scope


def resolve_root_scope(db, calc):
    """Whole-forest auto-create source (FS-4a.6): the virtual root shell of the
    forest -- ``forest_area_geom`` (boundary minus private land, decision D8)
    with the protection units punched out -- mirroring the equal-area root
    carve in ``operations/divide.py``. Returns ``(scope, excluded)`` where
    ``excluded`` is True when the shell is smaller than the drawn boundary
    (private land and/or protection units shape it), which tells the caller to
    skip the boundary-tiled coverage remainder (the scope-aware coverage
    invariant is FS-3.1's job). A boundary with no private land / protection
    returns the boundary itself as the scope (a no-op for legacy forests).
    """
    from .forest_units.area_model import outer_boundary_geom
    from .forest_units.operations.virtual_root import resolve_divide_source

    polygon, exclude_geom = resolve_divide_source(db, calc, None)
    if polygon is None:
        raise ValueError("no_boundary")
    if exclude_geom is not None and not exclude_geom.is_empty:
        scope = _as_polygonal(make_valid(polygon.difference(exclude_geom)))
        if scope is None or scope.is_empty:
            raise ValueError("no_coverage_in_feature")
    else:
        scope = polygon
    outer = outer_boundary_geom(calc)
    excluded = False
    if outer is not None:
        excluded = _area_m2(scope) < _area_m2(outer) - 1e-6
    return scope, excluded


def _punch_scope_holes(result: Dict[str, Any], scope: Any) -> None:
    """The shared pipeline fills interior holes below the sliver floor, which would quietly
    give a small private-land / protection hole back to a child. The hole is permanent, so
    re-clip every piece to the scope (in place) and correct the areas."""
    total_m2 = 0.0
    for feat in result["pieces"]["features"]:
        g = _as_polygonal(make_valid(shape(feat["geometry"])).intersection(scope))
        if g is None or g.is_empty:
            continue
        feat["geometry"] = g.__geo_interface__
        feat["properties"]["area_hectares"] = round(_area_m2(g) / SQM_PER_HA, 4)
        total_m2 += _area_m2(g)
    result["meta"]["pieces_ha"] = round(total_m2 / SQM_PER_HA, 2)


def _count_undivided_blocks(db, calc, divided) -> int:
    """Blocks (other than ``divided``) that still have no compartments."""
    from sqlalchemy import exists
    from sqlalchemy.orm import aliased

    child = aliased(ForestBlock)
    return (
        db.query(ForestBlock)
        .filter(
            ForestBlock.calculation_id == calc.id,
            ForestBlock.is_compartment.is_(False),
            ForestBlock.id != divided.id,
            ~exists().where(child.parent_block_id == ForestBlock.id),
        )
        .count()
    )


def _child_pattern(layer_type: str) -> str:
    """Default child-name pattern of a per-parent natural divide: the sub-unit
    pattern of the parent's BRANCH (D3/C1) -- ``{parent_name}-SB{index}`` on
    the block branch, ``{parent_name}-SC{index}`` on the compartment branch."""
    if layer_type in ("compartments", "sub_compartments"):
        return "{parent_name}-SC{index}"
    return "{parent_name}-SB{index}"


def preview_children(
    db,
    calc,
    parent_id,
    source: str = "mmu",
    desired_n: Optional[int] = None,
    sliver_area_m2: Optional[float] = None,
    force_absorb_orphans: bool = False,
    nodata_min_m2: Optional[float] = None,
    level: Optional[str] = None,
) -> Dict[str, Any]:
    """Stage 1 for one feature - the chosen source's pieces inside it, named as the
    children they will become. Writes nothing."""
    from .compartment_divide_service import MIN_COMPARTMENT_AREA_M2, _apply_naming_pattern

    fn = resolve_source_fn(source)
    parent, layer_type, scope = resolve_divide_scope(db, calc, parent_id)
    if level is not None and level != layer_type:
        # FS-4a.6: ``level`` accepts the branch-inferred child layer ("sub_blocks"
        # for a block parent, "sub_compartments" for a compartment parent) and
        # nothing else -- the chain's block->compartments is gone.
        raise ValueError("bad_level")
    if sliver_area_m2 is None:
        # a child is at least the 1 ha the equal-area divide already enforces
        sliver_area_m2 = MIN_COMPARTMENT_AREA_M2
    kwargs: Dict[str, Any] = dict(
        level="compartments",
        desired_n=desired_n,
        sliver_area_m2=sliver_area_m2,
        force_absorb_orphans=force_absorb_orphans,
        scope=scope,
    )
    if source == "canopy" and nodata_min_m2 is not None:
        kwargs["nodata_min_m2"] = nodata_min_m2
    result = fn(db, calc, **kwargs)
    _punch_scope_holes(result, scope)

    pattern = _child_pattern(layer_type)
    parent_block_name = parent.block_name or parent.name
    for feat in result["pieces"]["features"]:
        props = feat["properties"]
        from ..core.naming_strategies import top_unit_name

        name = _apply_naming_pattern(pattern, top_unit_name(parent_block_name), top_unit_name(parent.name), props["index"])
        props["name"] = name
        props["block_name"] = name
    result["meta"].update(
        {
            "parent_id": str(parent.id),
            "parent_name": parent.name,
            "child_layer": layer_type,
            "source": source,
        }
    )
    return result


def commit_children(
    db,
    calc,
    parent_id,
    blocks: List[Dict[str, Any]],
    source: str = "mmu",
    sliver_area_m2: Optional[float] = None,
    created_by=None,
    level: Optional[str] = None,
) -> Dict[str, Any]:
    """Stage 2 for one feature - persist the accepted pieces as children of the
    parent. Re-runs every guard (state may have changed since the preview)."""
    from . import geometry_edit_service as geo
    from .compartment_divide_service import (
        MIN_COMPARTMENT_AREA_M2,
        _persist_children,
        _set_compartment_mode,
        _validate_parent_coverage,
        _write_history,
    )

    parent, layer_type, scope = resolve_divide_scope(db, calc, parent_id)
    if level is not None and level != layer_type:
        raise ValueError("bad_level")
    if sliver_area_m2 is None:
        sliver_area_m2 = MIN_COMPARTMENT_AREA_M2

    pieces: List[Any] = []
    extras: List[Dict[str, Any]] = []
    for req in blocks:
        geom = _as_shapely(req.get("geometry"))
        if geom is None or geom.is_empty:
            raise ValueError("invalid_geometry")
        geom = make_valid(geom)
        if not isinstance(geom, (Polygon, MultiPolygon)):
            raise ValueError("invalid_geometry_type")
        # Fill holes a client-side edit left, THEN clip to the scope: the clip is what
        # keeps private land / protection units a permanent hole, and it also means the
        # client can never put a child outside the feature.
        filled = _fill_holes([geom], protect_geom=hole_protect_geom(db, calc))
        geom = filled[0] if filled else geom
        geom = _as_polygonal(make_valid(geom.intersection(scope)))
        if geom is None or geom.is_empty:
            continue
        parts = [p for p in _explode_multiparts([geom]) if _area_m2(p) >= OVERLAP_EPSILON_M2]
        if not parts:
            continue
        if len(parts) > 1:
            # a below-floor fragment is folded into the largest part, as in commit_blocks
            parts.sort(key=lambda p: -_area_m2(p))
            keep = [parts[0]]
            for part in parts[1:]:
                if _area_m2(part) < sliver_area_m2:
                    keep[0] = _as_polygonal(make_valid(keep[0].union(part)))
                else:
                    keep.append(part)
            parts = keep
        own = {
            "natural_name": req.get("natural_name"),
            "dominant_slope_band": _dominant_class(req, "dominant_slope_band"),
            "dominant_aspect": _dominant_class(req, "dominant_aspect"),
            "dominant_canopy_class": _dominant_class(req, "dominant_canopy_class"),
            # Raster-Sources codes (migration 105) — same source-agnostic
            # pass-through as the 084/085 fields above.
        "dominant_health_class": _dominant_class(req, "dominant_health_class"),
        "dominant_nasa_quality": _dominant_class(req, "dominant_nasa_quality"),
        "dominant_nasa_code": _dominant_class(req, "dominant_nasa_code"),
        "dominant_landcover": _dominant_class(req, "dominant_landcover"),
        "dominant_elevation_zone": _dominant_class(req, "dominant_elevation_zone"),
            "elevation_min_m": req.get("elevation_min_m"),
            "elevation_mean_m": req.get("elevation_mean_m"),
            "elevation_max_m": req.get("elevation_max_m"),
        }
        for part in parts:
            pieces.append(part)
            extras.append(own)
    if len(pieces) < 2:
        raise ValueError("DIVISION_TOO_FEW: A division needs at least two pieces - nothing was changed.")

    created_ids = _persist_children(
        db, calc, parent, layer_type, pieces, "", created_by, extras=extras,
        # A below-floor sliver folded into a disjoint neighbour above stays a
        # genuine MultiPolygon (the same deliberate exception `commit_blocks`
        # already documents for the whole-forest case) -- tell the shared
        # persist helper to accept it instead of raising MultiPartFeatureError
        # for a shape this function produced on purpose.
        allow_multipart=True,
    )
    _write_history(
        db, calc, parent, f"auto_{source}"[:50], None,
        {"source": source, "sliver_area_m2": sliver_area_m2, "min_area_sqm": MIN_COMPARTMENT_AREA_M2},
        len(created_ids), _child_pattern(layer_type), None, created_by,
    )
    if layer_type != "sub_blocks":
        _set_compartment_mode(calc)
    from .forest_units.write import structure_write

    with structure_write(db, calc, change=f"auto-divide {parent.name}"):
        _validate_parent_coverage(db, calc, parent, created_ids)
    db.commit()
    return {
        "parent_id": str(parent.id),
        "children": created_ids,
        "n_children": len(created_ids),
        "child_layer": layer_type,
        # Analysis units come from the deepest level that exists, so a block with no compartments is
        # left out of the analysis while others are divided. Say how many are still waiting.
        "undivided_blocks": _count_undivided_blocks(db, calc, parent) if layer_type == "compartments" else 0,
    }
