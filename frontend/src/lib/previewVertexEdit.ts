/**
 * PE-2 — pure ring-editing helpers for the boundary preview's inline vertex
 * editor (`BoundaryOverlapPreviewPanel`). Framework-free on purpose: the
 * Leaflet/react-leaflet wiring in the panel does nothing but read a marker's
 * `getLatLng()` and hand it to one of these, so the geometry logic itself is
 * testable without a DOM or a map instance (mirrors
 * `lib/__tests__/vertexEdit.sweep.test.ts`'s approach).
 *
 * Scope: each polygon's **exterior ring**. A `MultiPolygon` (a neighbour split
 * the boundary in two, CO-1) is edited ring-by-ring — every part's outer ring
 * is draggable — via the `areal*` helpers below; the older `Polygon`-only
 * functions are kept for callers that never see a MultiPolygon. Interior rings
 * (holes), if present, are carried through unchanged.
 */
import type { Geometry, MultiPolygon, Polygon, Position } from 'geojson'
import * as turf from '@turf/turf'

/** Minimum vertex count a ring may be reduced to (still a valid triangle). */
const MIN_RING_VERTICES = 3

export function isEditablePolygon(geom: Geometry | null | undefined): geom is Polygon {
  return !!geom && geom.type === 'Polygon' && Array.isArray(geom.coordinates?.[0])
}

/** Exterior ring WITHOUT the closing duplicate vertex (index i === last is dropped). */
export function getOpenRing(geom: Polygon): Position[] {
  const ring = geom.coordinates[0]
  if (ring.length < 2) return ring.slice()
  const first = ring[0]
  const last = ring[ring.length - 1]
  const closed = first[0] === last[0] && first[1] === last[1]
  return closed ? ring.slice(0, -1) : ring.slice()
}

function withOpenRing(geom: Polygon, openRing: Position[]): Polygon {
  const closed = openRing.length > 0 ? [...openRing, openRing[0]] : openRing
  return { type: 'Polygon', coordinates: [closed, ...geom.coordinates.slice(1)] }
}

/** Move vertex `index` (into the OPEN ring) to `[lng, lat]`. No-op if out of range. */
export function moveVertex(geom: Polygon, index: number, to: [number, number]): Polygon {
  const ring = getOpenRing(geom)
  if (index < 0 || index >= ring.length) return geom
  ring[index] = to
  return withOpenRing(geom, ring)
}

/** Insert a new vertex on the segment `(afterIndex -> afterIndex+1)`, mod ring length. */
export function insertVertex(geom: Polygon, afterIndex: number, at: [number, number]): Polygon {
  const ring = getOpenRing(geom)
  const n = ring.length
  if (n === 0) return geom
  const insertAt = (((afterIndex % n) + n) % n) + 1
  ring.splice(insertAt, 0, at)
  return withOpenRing(geom, ring)
}

/** Delete vertex `index`. Refuses to shrink the ring below {@link MIN_RING_VERTICES}. */
export function deleteVertex(geom: Polygon, index: number): Polygon {
  const ring = getOpenRing(geom)
  if (ring.length <= MIN_RING_VERTICES) return geom
  if (index < 0 || index >= ring.length) return geom
  ring.splice(index, 1)
  return withOpenRing(geom, ring)
}

export interface SegmentMidpoint {
  /** Insert lands on the segment `index -> index+1` (mod ring length). */
  index: number
  lat: number
  lng: number
}

export function segmentMidpoints(geom: Polygon): SegmentMidpoint[] {
  const ring = getOpenRing(geom)
  const n = ring.length
  const out: SegmentMidpoint[] = []
  for (let i = 0; i < n; i++) {
    const a = ring[i]
    const b = ring[(i + 1) % n]
    out.push({ index: i, lng: (a[0] + b[0]) / 2, lat: (a[1] + b[1]) / 2 })
  }
  return out
}

export interface VertexPoint {
  index: number
  lat: number
  lng: number
}

export function ringVertices(geom: Polygon): VertexPoint[] {
  return getOpenRing(geom).map(([lng, lat], index) => ({ index, lat, lng }))
}

// ── MultiPolygon-aware editing (CO-1) ───────────────────────────────────────
// A boundary that a neighbour clipped in two is a MultiPolygon. The preview's
// inline editor addresses a vertex by `{ poly, index }` — polygon `poly`'s
// exterior ring, open-ring index `index` — and every operation preserves the
// input's geometry type (Polygon in → Polygon out; MultiPolygon in → out).

/** Address of one editable vertex: exterior ring of polygon `poly`, open index. */
export interface ArealVId {
  poly: number
  index: number
}

export interface ArealVertexPoint extends ArealVId {
  lat: number
  lng: number
}

export function isEditableAreal(
  geom: Geometry | null | undefined,
): geom is Polygon | MultiPolygon {
  if (!geom) return false
  if (geom.type === 'Polygon') return Array.isArray(geom.coordinates?.[0])
  if (geom.type === 'MultiPolygon') {
    return (
      Array.isArray(geom.coordinates) &&
      geom.coordinates.some((poly) => Array.isArray(poly?.[0]))
    )
  }
  return false
}

/** The polygon coordinate arrays of a Polygon (as one) or a MultiPolygon. */
function polygonsOf(geom: Polygon | MultiPolygon): Position[][][] {
  return geom.type === 'Polygon' ? [geom.coordinates] : geom.coordinates
}

/** Reassemble, keeping the original geometry type. */
function fromPolygons(
  type: 'Polygon' | 'MultiPolygon',
  polys: Position[][][],
): Polygon | MultiPolygon {
  return type === 'Polygon'
    ? ({ type: 'Polygon', coordinates: polys[0] } as Polygon)
    : ({ type: 'MultiPolygon', coordinates: polys } as MultiPolygon)
}

/** Every part's exterior-ring vertices, flattened, each tagged with its part. */
export function arealVertices(geom: Polygon | MultiPolygon): ArealVertexPoint[] {
  const out: ArealVertexPoint[] = []
  polygonsOf(geom).forEach((poly, p) => {
    const ext = poly[0]
    if (!Array.isArray(ext)) return
    getOpenRing({ type: 'Polygon', coordinates: [ext] }).forEach(([lng, lat], index) => {
      out.push({ poly: p, index, lat, lng })
    })
  })
  return out
}

/** Segment midpoints per part's exterior ring, tagged with the part. */
export function arealMidpoints(geom: Polygon | MultiPolygon): ArealVertexPoint[] {
  const out: ArealVertexPoint[] = []
  polygonsOf(geom).forEach((poly, p) => {
    const ext = poly[0]
    if (!Array.isArray(ext)) return
    segmentMidpoints({ type: 'Polygon', coordinates: [ext] }).forEach((m) => {
      out.push({ poly: p, index: m.index, lat: m.lat, lng: m.lng })
    })
  })
  return out
}

/** Apply a single-Polygon ring op to part `vid.poly` only; keep the outer type. */
function editPart(
  geom: Polygon | MultiPolygon,
  polyIndex: number,
  op: (part: Polygon) => Polygon,
): Polygon | MultiPolygon {
  const polys = polygonsOf(geom)
  const part = polys[polyIndex]
  if (!part || !Array.isArray(part[0])) return geom
  const edited = op({ type: 'Polygon', coordinates: part })
  const next = polys.slice()
  next[polyIndex] = edited.coordinates
  return fromPolygons(geom.type, next)
}

export function moveArealVertex(
  geom: Polygon | MultiPolygon,
  vid: ArealVId,
  to: [number, number],
): Polygon | MultiPolygon {
  return editPart(geom, vid.poly, (part) => moveVertex(part, vid.index, to))
}

export function insertArealVertex(
  geom: Polygon | MultiPolygon,
  vid: ArealVId,
  at: [number, number],
): Polygon | MultiPolygon {
  return editPart(geom, vid.poly, (part) => insertVertex(part, vid.index, at))
}

export function deleteArealVertex(
  geom: Polygon | MultiPolygon,
  vid: ArealVId,
): Polygon | MultiPolygon {
  return editPart(geom, vid.poly, (part) => deleteVertex(part, vid.index))
}

/**
 * PE-4b — cheap, client-side "did this point just enter a neighbour" test for
 * live drag feedback. Point-based (not segment-vs-polygon) on purpose: the
 * plan's language is "the instant it enters a neighbour polygon", which is
 * exactly what `booleanPointInPolygon` answers, at a fraction of the cost of
 * a segment/polygon intersection test on every `drag` tick.
 */
export function pointInAnyNeighbour(
  latlng: { lat: number; lng: number },
  neighbours: Geometry[],
): boolean {
  const pt = turf.point([latlng.lng, latlng.lat])
  for (const geom of neighbours) {
    if (!geom) continue
    try {
      if (geom.type === 'Polygon' || geom.type === 'MultiPolygon') {
        if (turf.booleanPointInPolygon(pt, geom as any)) return true
      }
    } catch {
      // malformed neighbour geometry — skip rather than crash the drag handler
    }
  }
  return false
}
