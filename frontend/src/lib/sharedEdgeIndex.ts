import type { Feature, Geometry } from 'geojson';

/**
 * SharedEdgeIndex — E2.3 frontend mirror of the backend's R6 no-gap /
 * no-overlap validator (backend: geometry_edit_service.SpatialHashIndex +
 * check_shared_edge_integrity).
 *
 * Data-first, object-identity-free: built from the layer's GeoJSON features
 * (the same data react-leaflet renders), so it survives map refresh and never
 * depends on which circle-marker instance "owns" a vertex.
 *
 * Use case (E2.2b/E2.3): on the first drag-release (`pm:markerdragend`) we
 * validate the edited feature *synchronously* against its spatial neighbours
 * before POSTing.  Two classes of failure are caught here to avoid a wasted
 * round-trip and to give sub-frame feedback:
 *
 *  - GAP: a neighbour that shared an edge/vertex with the pre-edit snapshot
 *    now drifts farther than the edge tolerance away — the move opened a hole.
 *  - OVERLAP: an edited edge properly crosses a neighbour edge.
 *
 * All geometry comes from layer GeoJSON (never object identity).  The server
 * remains the authority (409 TOPOLOGY_REJECTED); this index is a fast-path
 * that literally mirrors the backend's threshold constants so the two agree.
 */

export const SNAP_TOLERANCE_M = 150; // == MAX_EDGE_TOLERANCE_M (backend)
export const MIN_SLIVER_AREA_M2 = 100; // == MIN_SLIVER_AREA_M2 (backend)

const METRES_TO_DEG = 1 / 111_320;

export function metresToDegrees(m: number): number {
  return m * METRES_TO_DEG;
}

/** Cell side (degrees) for the spatial grid — a coarse bbox pre-filter. */
export const CELL_DEGREES = metresToDegrees(SNAP_TOLERANCE_M * 2);

type Point = readonly [number, number];
type Segment = readonly [Point, Point];

function asPoints(c: unknown): Point[] {
  if (!Array.isArray(c)) return [];
  return (c as Array<any>)
    .filter((p) => Array.isArray(p) && p.length >= 2)
    .map((p) => [Number(p[0]), Number(p[1])] as Point);
}

/** All closed rings of a Polygon/MultiPolygon. */
/**
 * EXTERIOR rings only, in document order (Polygon → its shell; MultiPolygon →
 * each part's shell).  This is the index space the vertex rules run in: the
 * backend's `iter_vertices` walks `exterior.coords[:-1]`, so anything that
 * produces or consumes a flat VERTEX INDEX must use this, not `polygonRings`.
 *
 * `polygonRings` returns holes too, which is right for distance and crossing
 * tests but wrong for indexing — the two index spaces diverged for any polygon
 * with a hole (VR-2 / defect D-3).  Holes are not editable and are not indexed.
 */
export function exteriorRings(geom: Geometry | null | undefined): Point[][] {
  const c = (geom as any)?.coordinates;
  if (!c) return [];
  switch (geom!.type) {
    case 'Polygon':
      return c.length ? [asPoints(c[0])] : [];
    case 'MultiPolygon':
      return c.filter((poly: any) => poly?.length).map((poly: any) => asPoints(poly[0]));
    default:
      return [];
  }
}

/** ALL rings (shell + holes).  For distance / crossing tests, never for indices. */
export function polygonRings(geom: Geometry | null | undefined): Point[][] {
  const c = (geom as any)?.coordinates;
  if (!c) return [];
  switch (geom!.type) {
    case 'Polygon':
      return c.map((ring: any) => asPoints(ring));
    case 'MultiPolygon':
      return c.flatMap((poly: any) => poly.map((ring: any) => asPoints(ring)));
    default:
      return [];
  }
}

/** All vertices of a LineString / MultiLineString. */
function lineVertices(geom: Geometry | null | undefined): Point[] {
  const c = (geom as any)?.coordinates;
  if (!c) return [];
  switch (geom!.type) {
    case 'LineString':
      return asPoints(c);
    case 'MultiLineString':
      return c.flatMap((line: any) => asPoints(line));
    default:
      return [];
  }
}

export function allVertices(geom: Geometry | null | undefined): Point[] {
  const rings = polygonRings(geom).flat();
  return rings.length ? rings : lineVertices(geom);
}

export function haversineM(a: Point, b: Point): number {
  const R = 6371000;
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(b[1] - a[1]);
  const dLng = toRad(b[0] - a[0]);
  const s =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(a[1])) * Math.cos(toRad(b[1])) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(s));
}

export function minVertexDistanceM(a: Point[], b: Point[]): number {
  if (a.length === 0 || b.length === 0) return Infinity;
  let best = Infinity;
  for (const pa of a) {
    for (const pb of b) {
      const d = haversineM(pa, pb);
      if (d < best) best = d;
    }
  }
  return best;
}

export type Bounds = readonly [number, number, number, number]; // minX minY maxX maxY

export function geometryBounds(geom: Geometry | null | undefined): Bounds {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const [x, y] of allVertices(geom)) {
    if (x < minX) minX = x;
    if (x > maxX) maxX = x;
    if (y < minY) minY = y;
    if (y > maxY) maxY = y;
  }
  return [minX, minY, maxX, maxY];
}

function bboxOverlap(a: Bounds, b: Bounds): boolean {
  return !(a[2] < b[0] || a[0] > b[2] || a[3] < b[1] || a[1] > b[3]);
}

function cellsForBounds(b: Bounds, cell: number): Set<string> {
  const cells = new Set<string>();
  if (![b[0], b[1], b[2], b[3]].every(isFinite)) return cells;
  const step = cell > 0 ? cell : CELL_DEGREES;
  for (let ix = Math.floor(b[0] / step); ix <= Math.floor(b[2] / step); ix++) {
    for (let iy = Math.floor(b[1] / step); iy <= Math.floor(b[3] / step); iy++) {
      cells.add(`${ix}:${iy}`);
    }
  }
  return cells;
}

const EPS = 1e-12;

function cross(ox: number, oy: number, ax: number, ay: number, bx: number, by: number): number {
  return (ax - ox) * (by - oy) - (ay - oy) * (bx - ox);
}

function onSegment(ax: number, ay: number, bx: number, by: number, px: number, py: number): boolean {
  return (
    Math.min(ax, bx) - EPS <= px && px <= Math.max(ax, bx) + EPS &&
    Math.min(ay, by) - EPS <= py && py <= Math.max(ay, by) + EPS
  );
}

/**
 * How far off a line a point may sit and still count as ON it, in degrees.
 * ~1e-9° ≈ 0.11 mm: seven orders of magnitude above double-precision noise at
 * these coordinates, and far below any overlap a user could intend.
 */
const COLLINEAR_TOL_DEG = 1e-9;

/**
 * Which side of the line (a→b) the point p lies on: +1, -1, or 0 for "on it".
 *
 * The raw cross product is scaled by the segment length, which turns it into a
 * signed PERPENDICULAR DISTANCE in degrees — a quantity that can be compared
 * against a real tolerance.  Comparing the raw cross product to exact zero (as
 * this test used to) is not robust: at forest coordinates (~85.76, ~27.41) the
 * differences that go into it are ~1e-4 and the subtraction cancels
 * catastrophically, so two collinear segments of a SHARED EDGE yield ~1e-17
 * with an arbitrary sign rather than 0.  The "any 0 term returns false" rule
 * below then never fired, every pair of adjacent blocks looked like a proper
 * crossing, and R6 rejected every shared-vertex drag with "overlaps an
 * adjacent feature" (live report 2026-08-19).
 */
function sideOfLine(
  ax: number, ay: number, bx: number, by: number, px: number, py: number,
): number {
  const len = Math.hypot(bx - ax, by - ay);
  if (len === 0) return 0;
  const perpendicular = cross(ax, ay, bx, by, px, py) / len;
  if (Math.abs(perpendicular) <= COLLINEAR_TOL_DEG) return 0;
  return perpendicular > 0 ? 1 : -1;
}

/**
 * True when segments (a,b) and (c,d) PROPERLY cross interior-to-interior.
 * Endpoint touching and collinear/overlapping edges return false — those are
 * the healthy shared-vertex / shared-edge cases, matching the backend's
 * abstraction (clean shared edges are adjacent, not overlapping).
 */
function segmentsProperlyCross(a: Point, b: Point, c: Point, d: Point): boolean {
  const [ax, ay] = a, [bx, by] = b, [cx, cy] = c, [dx, dy] = d;
  const s1 = sideOfLine(cx, cy, dx, dy, ax, ay);
  const s2 = sideOfLine(cx, cy, dx, dy, bx, by);
  const s3 = sideOfLine(ax, ay, bx, by, cx, cy);
  const s4 = sideOfLine(ax, ay, bx, by, dx, dy);
  return s1 * s2 < 0 && s3 * s4 < 0;
}

function ringSegments(ring: Point[]): Segment[] {
  const segs: Segment[] = [];
  const n = ring.length;
  if (n < 3) return segs;
  for (let i = 0; i < n; i++) {
    segs.push([ring[i], ring[(i + 1) % n]]);
  }
  return segs;
}

/** Public segment-crossing test (exported for tests). */
export function segmentsIntersect(
  a: Point, b: Point, c: Point, d: Point,
): boolean {
  return segmentsProperlyCross(a, b, c, d);
}

export type TopologyWitness = 'GAP' | 'OVERLAP';

export interface TopologyVerdict {
  ok: boolean;
  witness?: TopologyWitness;
  offendingIds?: string[];
  message?: string;
}

/**
 * Grid index over a set of polygon/line features.  Insert once per layer
 * refresh; query per edit with a bounds + tolerance pre-filter.
 */
export class SharedEdgeIndex {
  private cells = new Map<string, Set<string>>();
  private geoms = new Map<string, Geometry>();
  private cellDeg: number;

  constructor(
    features: Array<{ id?: string | number; geometry: Geometry | null } | Feature>,
    cellDeg: number = CELL_DEGREES,
  ) {
    this.cellDeg = cellDeg;
    for (const f of features as any[]) {
      const geom = f?.geometry as Geometry | null;
      if (!geom) continue;
      const id = String(f?.id ?? (f as any)?.properties?.id ?? '');
      if (!id) continue;
      this.insert(id, geom);
    }
  }

  insert(featureId: string, geom: Geometry): void {
    this.geoms.set(featureId, geom);
    for (const cell of cellsForBounds(geometryBounds(geom), this.cellDeg)) {
      let set = this.cells.get(cell);
      if (!set) {
        set = new Set<string>();
        this.cells.set(cell, set);
      }
      set.add(featureId);
    }
  }

  remove(featureId: string): void {
    this.geoms.delete(featureId);
  }

  get size(): number {
    return this.geoms.size;
  }

  /** Candidate neighbour ids for a geometry (bbox pre-filter only). */
  neighborCandidates(geom: Geometry): string[] {
    const seen = new Set<string>();
    for (const cell of cellsForBounds(geometryBounds(geom), this.cellDeg)) {
      for (const id of this.cells.get(cell) ?? []) seen.add(id);
    }
    return [...seen];
  }

  /**
   * Validate an edited geometry against its spatial neighbours.
   *
   * GAP test (only when a pre-edit `snapshot` is supplied): neighbours that
   * previously touched the snapshot (vertex within tolerance) but no longer
   * touch the edited shape are reported as a gap.  That is exactly the
   * "shared-edge vertex drifted away" failure mode R6 exists for.
   *
   * OVERLAP test: any two properly-crossing edges between the edited shape
   * and a neighbour = overlap (a shared/coincident edge does NOT count — that
   * is the healthy adjacence case).
   */
  validate(edited: Geometry, opts?: { excludeId?: string; snapshot?: Geometry | null }): TopologyVerdict {
    const vertsA = allVertices(edited);
    if (!vertsA.length) return { ok: false, witness: 'GAP', message: 'Edited geometry is empty.' };

    // Candidate neighbours: cells of the edited shape AND of the pre-edit
    // snapshot (a neighbour that drifts out of the edited bbox must still be
    // found via the snapshot it used to touch).
    const candidateIds = new Set(this.neighborCandidates(edited));
    if (opts?.snapshot) {
      for (const id of this.neighborCandidates(opts.snapshot)) candidateIds.add(id);
    }

    for (const id of candidateIds) {
      if (opts?.excludeId === id) continue;
      const nb = this.geoms.get(id);
      if (!nb) continue;

      // OVERLAP — proper edge crossing of the EDITED shape is unambiguous.
      if (bboxOverlap(geometryBounds(edited), geometryBounds(nb))
        && properEdgesCross(edited, nb)) {
        return {
          ok: false, witness: 'OVERLAP', offendingIds: [id],
          message: 'Edit rejected: overlaps an adjacent feature.',
        };
      }

      // GAP — only reported when the neighbour used to touch the snapshot but
      // no longer touches the edited shape.
      if (opts?.snapshot && bboxOverlap(geometryBounds(opts.snapshot), geometryBounds(nb))) {
        const prevTouching = minVertexDistanceM(allVertices(opts.snapshot), allVertices(nb)) <= SNAP_TOLERANCE_M;
        if (prevTouching) {
          const nowTouching = minVertexDistanceM(vertsA, allVertices(nb)) <= SNAP_TOLERANCE_M;
          if (!nowTouching) {
            return {
              ok: false, witness: 'GAP', offendingIds: [id],
              message: 'Edit rejected: creates a gap with an adjacent feature.',
            };
          }
        }
      }
    }
    return { ok: true };
  }
}

// -- geometry predicate helpers ---------------------------------------------------

function hasArea(geom: Geometry): boolean {
  return geom.type === 'Polygon' || geom.type === 'MultiPolygon'
    ? polygonRings(geom).some((r) => r.length >= 3)
    : false;
}

function properEdgesCross(edited: Geometry, nb: Geometry): boolean {
  if (!hasArea(edited) || !hasArea(nb)) return false;
  const segsA = polygonRings(edited).flatMap(ringSegments);
  const segsB = polygonRings(nb).flatMap(ringSegments);
  for (const s1 of segsA) {
    for (const s2 of segsB) {
      if (segmentsIntersect(s1[0], s1[1], s2[0], s2[1])) return true;
    }
  }
  return false;
}