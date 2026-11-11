import { union as turfUnion, buffer as turfBuffer } from '@turf/turf';
import type { Feature, Geometry } from 'geojson';

/**
 * Client-side parity of backend `auto_block_service._merge_plan` for the
 * Auto-Block designer: a "largest-anchor" merge.  The server preview already
 * returns post-sliver-absorb pieces plus an `edges` adjacency graph, so this
 * lib only has to (a) pick anchors, (b) assign every non-anchor piece to an
 * adjacent anchor, (c) union the geometry per group.
 *
 * Lock semantics: a locked piece is ALWAYS an anchor (it can absorb neighbours
 * but is never absorbed), which RAISES the effective minimum block count to
 * the number of locked pieces.
 */

export const SQM_PER_HA = 10000;
export const DEFAULT_FLOOR_HA = 5;

/** One preview piece as delivered by POST .../auto-blocks/preview. */
export interface AutoBlockPiece {
  index: number;
  name: string;
  block_name: string;
  natural_name: string | null;
  area_hectares: number;
  geometry: Geometry;
}

/** Shared-edge adjacency edge as delivered by the preview endpoint. */
export interface AdjacencyEdge {
  a: number;
  b: number;
  shared_m: number;
}

/** Result of one merge-plan computation. */
export interface MergePlan {
  /** Anchor piece index per block (descending by anchor area). */
  anchors: number[];
  /** For every piece index: the anchor index its family merges into. */
  familyOf: Record<number, number>;
  /** All pieces (server order) with the anchor flag per index. */
  pieces: AutoBlockPiece[];
  /** Effective N actually used (>= requested; raised by lock count). */
  effectiveN: number;
  /** Effective minimum N (>= 1; raised when pieces are locked). */
  minN: number;
}

/** Lower bound on blocks: ceil(total_ha / floorHa). */
export function minimizeN(totalHa: number, floorHa = DEFAULT_FLOOR_HA): number {
  if (!Number.isFinite(totalHa) || totalHa <= 0) return 1;
  return Math.max(1, Math.ceil(totalHa / floorHa));
}

export interface BuildMergePlanOptions {
  pieces: AutoBlockPiece[];
  edges: AdjacencyEdge[];
  /** Target block count from the slider (clamped to [minN, pieceCount]). */
  n: number;
  /** Piece indices that must be kept whole as anchors (0-based). */
  locked?: number[];
  floorHa?: number;
}

export function buildMergePlan(opts: BuildMergePlanOptions): MergePlan {
  const { pieces, edges, locked = [], floorHa = DEFAULT_FLOOR_HA } = opts;
  const count = pieces.length;
  if (count === 0) {
    return { anchors: [], familyOf: {}, pieces, effectiveN: 0, minN: 1 };
  }

  const lockedSet = new Set(locked.filter((i) => i >= 0 && i < count));
  // Locked pieces are always their own block, so they RAISE the effective
  // minimum N.  The 5 ha floor is NOT a hard clamp on the slider — it only
  // drives the "Minimize" button recommendation (plan D7); the user may merge
  // below it.  Hence minN = locked count (capped at piece count).
  const minN = Math.min(count, Math.max(1, lockedSet.size));
  const effectiveN = Math.min(count, Math.max(minN, Math.min(opts.n, count)));

  const byAreaDesc = [...Array(count).keys()].sort(
    (a, b) => pieces[b].area_hectares - pieces[a].area_hectares,
  );

  // Anchors = locked pieces (in descending-area order) + next-largest unlocked.
  const anchors: number[] = [];
  const anchorSet = new Set<number>();
  for (const i of byAreaDesc) {
    if (anchors.length >= effectiveN) break;
    if (lockedSet.has(i) && !anchorSet.has(i)) {
      anchorSet.add(i);
      anchors.push(i);
    }
  }
  for (const i of byAreaDesc) {
    if (anchors.length >= effectiveN) break;
    if (!anchorSet.has(i)) {
      anchorSet.add(i);
      anchors.push(i);
    }
  }

  // Quickly map pieces to their best adjacent anchor.
  let edgeIndex = edges;
  const bestAnchorOf = new Map<number, { anchor: number; shared: number }>();
  const syncMap = (pieceIdx: number, anchor: number, shared: number) => {
    const cur = bestAnchorOf.get(pieceIdx);
    if (!cur || shared > cur.shared) bestAnchorOf.set(pieceIdx, { anchor, shared });
  };
  for (const e of edgeIndex) {
    const aIn = anchorSet.has(e.a);
    const bIn = anchorSet.has(e.b);
    if (aIn && !bIn) syncMap(e.b, e.a, e.shared_m);
    else if (bIn && !aIn) syncMap(e.a, e.b, e.shared_m);
  }

  const familyOf: Record<number, number> = {};
  // Fold non-anchors with no direct anchor neighbour into the smallest anchor
  // (parity with backend `_merge_plan`).
  const unassignedIdx: number[] = [];
  for (const pieceIdx of byAreaDesc) {
    if (anchorSet.has(pieceIdx)) {
      familyOf[pieceIdx] = pieceIdx;
      continue;
    }
    const best = bestAnchorOf.get(pieceIdx);
    if (!best) {
      unassignedIdx.push(pieceIdx);
      continue;
    }
    familyOf[pieceIdx] = best.anchor;
  }
  if (unassignedIdx.length > 0) {
    const smallestAnchor = [...anchors].sort(
      (a, b) => pieces[a].area_hectares - pieces[b].area_hectares,
    )[0];
    for (const pieceIdx of unassignedIdx) familyOf[pieceIdx] = smallestAnchor;
  }

  return { anchors, familyOf, pieces, effectiveN, minN };
}

// Independent per-piece generalization on the backend (see
// app/services/geom_generalize.py — the slope/aspect/canopy sources each
// smooth their own boundary without knowledge of their neighbours) can leave
// a sliver gap along a shared edge between two pieces the server's own
// `edges` list reports as adjacent. An exact boolean union honestly reports
// two such pieces as disconnected (a MultiPolygon) rather than merging them
// into one polygon — which then fails the server's single-polygon-per-block
// commit expectation with a 400. 30 m comfortably exceeds the largest
// smoothing radius any source uses (slope/aspect 22 m, canopy 6.5 m), so a
// gap caused by that generalization is always closed by it.
const AUTO_BLOCK_GLUE_EPSILON_M = 30;

/**
 * Whether a glue-shrink result is safe to commit: it must still be a real
 * polygon (a too-narrow merged piece can collapse to an empty/Point/LineString
 * ring-trace when the buffer shrink is applied — that would be rejected by the
 * server's commit geometry guard as a 400 «invalid_geometry»).
 */
export function isGlueShrinkUsable(
  shrunk: Feature | undefined,
): shrunk is Feature {
  return !!shrunk && !!shrunk.geometry &&
    (shrunk.geometry.type === 'Polygon' || shrunk.geometry.type === 'MultiPolygon');
}

/** Union the GeoJSON geometries of every piece in a family (single merged Feature). */
export function unionFamily(
  pieces: AutoBlockPiece[],
  familyOf: Record<number, number>,
  anchor: number,
): GeoJSON.Feature {
  const family = pieces
    .map((p, i) => ({ p, i }))
    .filter(({ i }) => familyOf[i] === anchor)
    .map(({ p }) => p.geometry);
  const features: Feature[] = family.map((g) => ({
    type: 'Feature' as const,
    properties: {},
    geometry: g,
  }));
  if (features.length === 1) return features[0];
  const collection = {
    type: 'FeatureCollection',
    features,
  };
  // turf's union (polygon-clipping) can throw "Unable to complete output ring"
  // on complex raster-derived polygons that share jagged edges. NEVER let that
  // escape — the preview renderer calls us from React and a throw would take
  // the whole designer down. Fall back to a MultiPolygon of the raw components,
  // which is always valid and which the server explodes into block rows.
  const rawMulti: Feature = {
    type: 'Feature' as const,
    properties: {},
    geometry: {
      type: 'MultiPolygon',
      coordinates: (features
        .map((f) => f.geometry)
        .filter(
          (g): g is GeoJSON.Polygon | GeoJSON.MultiPolygon =>
            !!g && (g.type === 'Polygon' || g.type === 'MultiPolygon'),
        ) as Array<GeoJSON.Polygon | GeoJSON.MultiPolygon>)
        .flatMap((g) => (g.type === 'Polygon' ? [g.coordinates] : g.coordinates)),
    },
  };
  let plain: Feature | undefined;
  try {
    plain = turfUnion(collection as never) as Feature | undefined;
  } catch {
    plain = rawMulti;
  }
  // The common case: pieces genuinely touch, the union is already one
  // connected polygon — leave it byte-for-byte as turf produced it.
  if (!plain || plain.geometry?.type !== 'MultiPolygon') return plain as Feature;
  // Disconnected — very likely the smoothing-gap artifact above. Re-union
  // after buffering each piece out just enough to bridge the gap, then
  // shrink the merged result back down by the same amount.
  try {
    const grown = features.map(
      (f) => turfBuffer(f, AUTO_BLOCK_GLUE_EPSILON_M, { units: 'meters' }) as Feature,
    );
    const grownUnion = turfUnion({ type: 'FeatureCollection', features: grown } as never) as
      | Feature
      | undefined;
    if (!grownUnion) return plain;
    const shrunk = turfBuffer(grownUnion, -AUTO_BLOCK_GLUE_EPSILON_M, {
      units: 'meters',
    }) as Feature | undefined;
    // The glue shrink can collapse a too-narrow merged piece to an empty or
    // non-polygonal geometry (a Point/LineString ring-trace) — that would be
    // REJECTED by the server's commit geometry guard, so the shrink is only
    // accepted when it is still a genuine polygon. Fall back to the honest
    // (disconnected) union otherwise: the server explodes a MultiPolygon into
    // separate block rows, so it is always a valid payload.
    return isGlueShrinkUsable(shrunk) ? shrunk : plain;
  } catch {
    // Glue attempt failed for any reason — fall back to the honest
    // (disconnected) union rather than silently dropping the merge.
    return plain;
  }
}