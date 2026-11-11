import type { Feature, Geometry } from 'geojson'
import { exteriorRings, metresToDegrees, polygonRings } from './sharedEdgeIndex'

/** Point-on-line tolerance for vertex classification — mirrors the backend
 *  `VERTEX_COINCIDENCE_TOLERANCE_M`.  Deliberately NOT the 150 m snap/search
 *  radius: that decides which neighbours are worth testing, not whether a
 *  vertex lies ON an edge.  Using it as the answer classified every vertex
 *  of a small forest as on the parent shell (an 11 ha forest spans ~340 m),
 *  locking all of them so no drag markers rendered at all. */
export const VERTEX_COINCIDENCE_TOLERANCE_M = 1.0

/**
 * vertexClassifier — V-1 frontend mirror of the backend's vertex
 * classification engine (`backend/app/services/vertex_classification_service.py`).
 *
 * Classifies every vertex of one polygon feature into:
 *
 *   - shared:  vertex on the common boundary of two same-level units — within
 *     VERTEX_COINCIDENCE_TOLERANCE_M of a same-level neighbour's *boundary* (covers vertex
 *     coincidence AND a mid-edge vertex on a neighbour's edge segment).
 *   - shell:   vertex on the enclosing parent shell at this level (forest
 *     boundary for blocks, block shell for compartments, compartment shell
 *     for sub-compartments).
 *   - editable: shared − shell.  Shell wins (rule 4).
 *
 * Data-first: same as SharedEdgeIndex, built from the layer GeoJSON the map
 * renders — never object identity.  Indices are flat over the geometry's
 * exterior rings (each ring's vertices in order, closing duplicate dropped),
 * matching the backend exactly so both sides agree on "which marker is where".
 */

export const LAYER_TYPES = {
  boundary: 'boundary',
  blocks: 'blocks',
  subBlocks: 'sub_blocks',
  compartments: 'compartments',
  subCompartments: 'sub_compartments',
} as const

export type ClassifiableLayerType =
  | typeof LAYER_TYPES.boundary
  | typeof LAYER_TYPES.blocks
  | typeof LAYER_TYPES.subBlocks
  | typeof LAYER_TYPES.compartments
  | typeof LAYER_TYPES.subCompartments

export interface VertexClassification {
  shared: number[]
  shell: number[]
  editable: number[]
  vertexCount: number
}

export type RingVertex = readonly [number, number]

/** Iterate (flatIndex, [x, y]) over a Polygon/MultiPolygon's exterior rings. */
export function iterVertices(geom: Geometry | null | undefined): Array<[number, RingVertex]> {
  // EXTERIOR rings only — mirrors the backend's `exterior.coords[:-1]`.
  const rings = exteriorRings(geom)
  const out: Array<[number, RingVertex]> = []
  let idx = 0
  for (const ring of rings) {
    // drop the closing duplicate of each ring (matches backend `coords[:-1]`)
    const n = ring.length
    const count = ring.length && n > 1 && ring[0][0] === ring[n - 1][0] && ring[0][1] === ring[n - 1][1] ? n - 1 : n
    for (let i = 0; i < count; i++) {
      out.push([idx, ring[i]])
      idx += 1
    }
  }
  return out
}

export function coordAtIndex(geom: Geometry | null | undefined, index: number): RingVertex | null {
  const hit = iterVertices(geom).find(([i]) => i === index)
  return hit ? hit[1] : null
}

/** Resolve a flat vertex index to (polyIndex, ringVertexIndex). */
export function ringOfIndex(geom: Geometry | null | undefined, index: number): [number, number] | null {
  const rings = exteriorRings(geom)
  let flat = 0
  for (let pi = 0; pi < rings.length; pi++) {
    const ring = rings[pi]
    const n = ring.length
    const count = n > 1 && ring[0][0] === ring[n - 1][0] && ring[0][1] === ring[n - 1][1] ? n - 1 : n
    for (let vi = 0; vi < count; vi++) {
      if (flat === index) return [pi, vi]
      flat += 1
    }
  }
  return null
}

/**
 * Distance from a point to a polygon feature's boundary (the edge linework).
 * Mirrors the backend's `Point.distance(boundary)` semantics using
 * point-to-segment distance so mid-edge points land on shared segments.
 */
export function pointToBoundaryM(x: number, y: number, geom: Geometry | null | undefined): number {
  let best = Infinity
  for (const ring of polygonRings(geom)) {
    const n = ring.length
    for (let i = 0; i < n; i++) {
      const a = ring[i]
      const b = ring[(i + 1) % n]
      const d = pointSegmentDistanceM(x, y, a[0], a[1], b[0], b[1])
      if (d < best) best = d
    }
  }
  return best
}

export function pointSegmentDistanceM(
  px: number,
  py: number,
  ax: number,
  ay: number,
  bx: number,
  by: number,
): number {
  // project p onto segment ab in a local planar frame (fine at metre scale)
  const dx = bx - ax
  const dy = by - ay
  const len2 = dx * dx + dy * dy
  const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / len2))
  const cx = ax + t * dx
  const cy = ay + t * dy
  const dLat = cy - py
  const dLng = cx - px
  return Math.hypot(dLat * 111_320, dLng * 111_320 * Math.cos((py * Math.PI) / 180))
}

export function isOnBoundary(x: number, y: number, geom: Geometry | null | undefined): boolean {
  return pointToBoundaryM(x, y, geom) <= VERTEX_COINCIDENCE_TOLERANCE_M
}

export interface ClassifyOptions {
  layerType: ClassifiableLayerType
  /** Same-level sibling features (edited feature EXCLUDED). */
  sameLevelFeatures?: Array<{ id?: string | number; geometry: Geometry | null } | Feature>
  /** Enclosing shell geometry (blocks → boundary geom; compartments → parent
   *  block; sub-compartments → parent compartment). */
  parentShell?: Geometry | null
}

export function classifyVertices(
  geom: Geometry | null | undefined,
  opts: ClassifyOptions,
): VertexClassification {
  const empty: VertexClassification = { shared: [], shell: [], editable: [], vertexCount: 0 }
  if (!geom) return empty

  const verts = iterVertices(geom)
  const vertexCount = verts.length
  if (vertexCount === 0) return empty

  if (opts.layerType === LAYER_TYPES.boundary) {
    // Rule A classifier: no shell, no same-level neighbours → fully editable.
    return {
      shared: [],
      shell: [],
      editable: verts.map(([i]) => i),
      vertexCount,
    }
  }

  const shell: number[] = []
  const shared: number[] = []
  const parentBoundary = opts.parentShell

  for (const [i, [x, y]] of verts) {
    if (parentBoundary && isOnBoundary(x, y, parentBoundary)) {
      shell.push(i)
    }
    const isShared = (opts.sameLevelFeatures ?? []).some((f) => {
      const g = f?.geometry as Geometry | null
      return !!g && isOnBoundary(x, y, g)
    })
    if (isShared) shared.push(i)
  }

  const editable = shared.filter((i) => !shell.includes(i))
  return { shared, shell, editable, vertexCount }
}
