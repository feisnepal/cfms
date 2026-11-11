import {
  area as turfArea,
  bbox as turfBbox,
  cleanCoords as turfCleanCoords,
  lineIntersect as turfLineIntersect,
  lineString as turfLineString,
  polygon as turfPolygon,
} from '@turf/turf';
import type { Feature, Geometry, Polygon } from 'geojson';
import { MIN_SLIVER_AREA_M2 } from './sharedEdgeIndex';

export { MIN_SLIVER_AREA_M2 };
export const SQM_PER_HA = 10000; // == SQM_PER_HA (backend)

export interface SplitPreviewResult {
  /** Polygon pieces that would result from the cut (slivers already dropped). */
  pieces: Feature<Polygon>[];
  /** Area in hectares of each piece (turf geodesic area / 10000). */
  partHa: number[];
  /** Area in hectares of the source polygon the cut is applied to. */
  parentHa: number;
  /** Sum of the surviving pieces' areas (ha). */
  totalHa: number;
  /** Human warnings — the caller decides whether to block (warn-only here). */
  warnings: string[];
}

/**
 * Mirror of backend `geometry_edit_service._extend_cut_line_ends`: extrapolate
 * the first and last cut segments outward along their own direction so the line
 * pierces the polygon's bounding box edge-to-edge.  Interior vertices (zig-zag)
 * are preserved exactly.
 */
export function extendCutLineEnds(
  coords: Array<[number, number]>,
  bounds: [number, number, number, number],
): Array<[number, number]> {
  const [minx, miny, maxx, maxy] = bounds;
  const pad = Math.max(maxx - minx, maxy - miny) * 2 + 1e-6;
  const n = coords.length;
  if (n <= 1) return coords.slice();
  const out: Array<[number, number]> = [];
  const [p0, p1] = coords;
  let dx = p0[0] - p1[0];
  let dy = p0[1] - p1[1];
  let mag = Math.hypot(dx, dy);
  if (mag > 1e-12) out.push([p0[0] + (dx / mag) * pad, p0[1] + (dy / mag) * pad]);
  else out.push([p0[0] + pad, p0[1]]);
  for (let i = 1; i < n - 1; i++) out.push(coords[i]);
  const pn = coords[n - 1];
  const pm = coords[n - 2];
  dx = pn[0] - pm[0];
  dy = pn[1] - pm[1];
  mag = Math.hypot(dx, dy);
  if (mag > 1e-12) out.push([pn[0] + (dx / mag) * pad, pn[1] + (dy / mag) * pad]);
  else out.push([pn[0] + pad, pn[1]]);
  return out;
}

/** Cumulative planar distances along a polyline. */
function cumDist(coords: Array<[number, number]>): number[] {
  const out: number[] = [0];
  for (let i = 1; i < coords.length; i++) {
    const [ax, ay] = coords[i - 1];
    const [bx, by] = coords[i];
    out.push(out[i - 1] + Math.hypot(bx - ax, by - ay));
  }
  return out;
}

/** Project a point onto the nearest segment of a polyline → (distanceAlong, coord). */
function projectOnPolyline(
  p: [number, number],
  coords: Array<[number, number]>,
): { dist: number; coord: [number, number] } {
  const d = cumDist(coords);
  let best = Infinity;
  let bestDist = 0;
  let bestCoord: [number, number] = p;
  for (let i = 0; i < coords.length - 1; i++) {
    const a = coords[i];
    const b = coords[i + 1];
    const abx = b[0] - a[0];
    const aby = b[1] - a[1];
    const len2 = abx * abx + aby * aby;
    const t = len2 > 0 ? ((p[0] - a[0]) * abx + (p[1] - a[1]) * aby) / len2 : 0;
    const tt = Math.max(0, Math.min(1, t));
    const cx = a[0] + abx * tt;
    const cy = a[1] + aby * tt;
    const dd = Math.hypot(p[0] - cx, p[1] - cy);
    if (dd < best) {
      best = dd;
      bestDist = d[i] + tt * Math.sqrt(len2);
      bestCoord = [cx, cy];
    }
  }
  return { dist: bestDist, coord: bestCoord };
}

/** Subset of a polyline between two distances along it, inclusive of both ends. */
function subPolylineCoords(
  coords: Array<[number, number]>,
  d0: number,
  d1: number,
): Array<[number, number]> {
  const d = cumDist(coords);
  const lo = Math.min(d0, d1);
  const hi = Math.max(d0, d1);
  const out: Array<[number, number]> = [];
  let prev: [number, number] | null = null;
  for (let i = 1; i < coords.length; i++) {
    const segStart = d[i - 1];
    const segEnd = d[i];
    if (segEnd < lo) continue;
    if (segStart > hi) break;
    const denom = segEnd - segStart || 1;
    const t0 = Math.max(0, (lo - segStart) / denom);
    const t1 = Math.min(1, (hi - segStart) / denom);
    const [ax, ay] = coords[i - 1];
    const [bx, by] = coords[i];
    const p0: [number, number] = [ax + (bx - ax) * t0, ay + (by - ay) * t0];
    const p1: [number, number] = [ax + (bx - ax) * t1, ay + (by - ay) * t1];
    if (!prev) {
      out.push(p0);
    } else if (Math.abs(p0[0] - prev[0]) > 1e-9 || Math.abs(p0[1] - prev[1]) > 1e-9) {
      out.push(p0);
    }
    out.push(p1);
    prev = p1;
  }
  return out;
}

function dedupeRing(ring: Array<[number, number]>): Array<[number, number]> {
  const out: Array<[number, number]> = [];
  for (const c of ring) {
    const last = out[out.length - 1];
    if (!last || Math.abs(c[0] - last[0]) > 1e-9 || Math.abs(c[1] - last[1]) > 1e-9) out.push(c);
  }
  return out;
}

function closeRing(ring: Array<[number, number]>): Array<[number, number]> {
  const r = dedupeRing(ring);
  const last = r[r.length - 1];
  const first = r[0];
  if (Math.abs(last[0] - first[0]) > 1e-9 || Math.abs(last[1] - first[1]) > 1e-9) r.push(first);
  return r;
}

function shoelace(ring: Array<[number, number]>): number {
  let sum = 0;
  for (let i = 0; i < ring.length - 1; i++) {
    const [ax, ay] = ring[i];
    const [bx, by] = ring[i + 1];
    sum += ax * by - bx * ay;
  }
  return sum / 2;
}

/** Largest exterior ring (by |area|) of a Polygon / MultiPolygon geometry. */
function largestRing(geom: Geometry | undefined): Array<[number, number]> | null {
  if (!geom) return null;
  const rings: Array<[number, number]>[] = [];
  if (geom.type === 'Polygon') rings.push(geom.coordinates[0] as Array<[number, number]>);
  else if (geom.type === 'MultiPolygon') {
    for (const p of geom.coordinates) rings.push(p[0] as Array<[number, number]>);
  }
  if (rings.length === 0) return null;
  rings.sort((a, b) => Math.abs(shoelace(b)) - Math.abs(shoelace(a)));
  return rings[0];
}

/**
 * Split a polygon's exterior ring by a cut line, mirroring the backend flow:
 * extend line ends → compute ring↔cut intersections → slice the ring into arcs
 * between consecutive intersection points (by distance along the ring, so the
 * ring's seam/duplicate vertex is irrelevant) → rebuild one closed polygon per
 * arc with the cut subsegment as the shared edge.  This is the same arc pairing
 * shapely's split produces.
 */
function splitRingByCut(
  ring: Array<[number, number]>,
  cutCoords: Array<[number, number]>,
): Array<Array<[number, number]>> {
  const ringLine = turfLineString(ring);
  const cutLine = turfLineString(cutCoords);
  const intersections = turfLineIntersect(ringLine, cutLine).features.map(
    (f) => f.geometry.coordinates as [number, number],
  );
  if (intersections.length < 2) return [];
  const ringD = cumDist(ring);
  const breakDistances = intersections
    .map((pt) => projectOnPolyline(pt, ring).dist)
    .sort((a, b) => a - b);
  const uniq: number[] = [];
  for (const d of breakDistances) {
    if (uniq.length === 0 || d - uniq[uniq.length - 1] > 1e-9) uniq.push(d);
  }
  if (uniq.length < 2) return [];
  const ringEnd = ringD[ringD.length - 1];
  const arcs: Array<Array<[number, number]>> = [];
  for (let j = 0; j < uniq.length; j++) {
    const d0 = uniq[j];
    const d1 = uniq[(j + 1) % uniq.length];
    const arc =
      d0 <= d1
        ? subPolylineCoords(ring, d0, d1)
        : [
            ...subPolylineCoords(ring, d0, ringEnd),
            ...subPolylineCoords(ring, 0, d1),
          ];
    arcs.push(dedupeRing(arc));
  }
  return arcs;
}

export function computeSplitPreview(
  geometry: Geometry | undefined,
  cutCoords: Array<[number, number]>,
): SplitPreviewResult {
  const empty = (warnings: string[]): SplitPreviewResult => ({
    pieces: [],
    partHa: [],
    parentHa: 0,
    totalHa: 0,
    warnings,
  });
  const ring = largestRing(geometry);
  if (!ring) return empty(['Selected feature has no polygon geometry.']);
  const ringClosed = closeRing(ring);
  const bounds = turfBbox(turfPolygon([ringClosed])) as [number, number, number, number];
  const cut = extendCutLineEnds(cutCoords, bounds);
  if (cut.length < 2) return empty(['Draw at least 2 points on the cut line.']);

  const warnings: string[] = [];
  const rawArcs = splitRingByCut(ringClosed, cut);
  if (rawArcs.length === 0) warnings.push('Cut line does not cross the polygon.');

  const pieces: Feature<Polygon>[] = [];
  for (const arc of rawArcs) {
    if (arc.length < 2) continue;
    const a0 = arc[0];
    const a1 = arc[arc.length - 1];
    const pa = projectOnPolyline(a0, cut);
    const pb = projectOnPolyline(a1, cut);
    if (Math.abs(pa.dist - pb.dist) < 1e-9) continue;
    const brute = subPolylineCoords(cut, Math.min(pa.dist, pb.dist), Math.max(pa.dist, pb.dist));
    const bridge = pa.dist > pb.dist ? brute : brute.reverse();
    const ringBuilt = closeRing([...arc, ...bridge]);
    ringBuilt[ringBuilt.length - 1] = ringBuilt[0]; // exact closure (turf requirement)
    const poly = turfCleanCoords(turfPolygon([ringBuilt])) as Feature<Polygon>;
    if (turfArea(poly) < MIN_SLIVER_AREA_M2) continue;
    pieces.push(poly);
  }
  if (rawArcs.length > 0 && pieces.length < 2) {
    warnings.push('Cut produces fewer than 2 viable pieces — the split may be rejected.');
  }

  const parentHa = turfArea(turfPolygon([ringClosed])) / SQM_PER_HA;
  const partHa = pieces.map((p) => turfArea(p) / SQM_PER_HA);
  const totalHa = partHa.reduce((a, b) => a + b, 0);
  return { pieces, partHa, parentHa, totalHa, warnings };
}