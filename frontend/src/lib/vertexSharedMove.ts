import type { Feature, Geometry } from 'geojson'
import { metresToDegrees } from './sharedEdgeIndex'
import {
  isOnBoundary,
  iterVertices,
  pointSegmentDistanceM,
  VERTEX_COINCIDENCE_TOLERANCE_M,
} from './vertexClassifier'

/**
 * Radius within which a neighbour's vertex counts as THE SAME vertex.
 *
 * Deliberately the 1 m coincidence tolerance, NOT the 150 m
 * `SNAP_TOLERANCE_M` neighbour SEARCH radius this module used to use — the
 * same confusion commit `bdcc223` fixed in the classifier.  At 150 m a block
 * only ~340 m across has many vertices inside the radius, and the search took
 * the FIRST match in ring order rather than the nearest, so a shared-vertex
 * drag translated an unrelated vertex of the neighbour.  That deformed the
 * neighbour instead of following the drag, and R6 then correctly rejected the
 * result as an overlap — the "moving a shared vertex is rejected due to
 * overlap" report (2026-08-19).
 */
const COINCIDENCE_TOL_DEG = metresToDegrees(VERTEX_COINCIDENCE_TOLERANCE_M)

/**
 * vertexSharedMove — V-2 frontend propagation for atomic shared-vertex moves.
 *
 * When the user drags a *coincident* shared vertex (a vertex that another
 * same-level feature has at the SAME coordinate), the backend rewrites both
 * geometries in one transaction (`shared_moves`).  This module mirrors the
 * backend's V-2 semantics so the frontend can:
 *
 *   1. build the `shared_moves` payload before POSTing;
 *   2. validate the drag against the *propagated* neighbour set (rule 4 —
 *      "validate against where the neighbours WILL be", not where they are),
 *      so a shared drag passes the local R6 pre-check instead of rejecting
 *      itself.
 *
 * Data-first like SharedEdgeIndex / vertexClassifier: everything comes from
 * the layer GeoJSON the map renders.  Indices are flat over exterior rings
 * (closing duplicate dropped), matching vertexClassifier exactly.
 */

export interface SharedMoveItem {
  feature_id: string
  geometry: Geometry
}

export interface SharedMoveResult {
  moves: SharedMoveItem[]
  /** Same-level features with moved neighbours replaced by propagated geometry
   *  (unmoved neighbours keep their original geometry) — feed to the local R6
   *  pre-check so it validates against the post-gesture set. */
  propagatedFeatures: Array<{ id: string; geometry: Geometry }>
}

const EPS = 1e-12

function samePoint(a: readonly number[], b: readonly number[]): boolean {
  return Math.abs(a[0] - b[0]) < EPS && Math.abs(a[1] - b[1]) < EPS
}

/** Deep-clone a GeoJSON geometry keyed for vertex translation. */
function cloneGeom(geom: Geometry): unknown {
  return JSON.parse(JSON.stringify(geom))
}

/**
 * Translate the vertex at `flatIndex` (flat over exterior rings, closing
 * duplicate dropped — vertexClassifier order) by (dx, dy).  Returns a NEW
 * geometry; the input is untouched.  Handles Polygon + MultiPolygon and
 * keeps the ring closed (updates the closing duplicate when the moved vertex
 * is also ring[0]).
 */
export function translateVertex(geom: Geometry, flatIndex: number, dx: number, dy: number): Geometry {
  const c: any = cloneGeom(geom)
  const polys =
    c.type === 'MultiPolygon' ? c.coordinates : c.type === 'Polygon' ? [c.coordinates] : []
  let flat = 0
  for (const poly of polys) {
    // EXTERIOR ring only — the flat index space excludes holes (see
    // `exteriorRings`), so walking every ring here would write to the wrong
    // vertex on any polygon that has one.
    for (const ring of poly.slice(0, 1)) {
      const n = ring.length
      const count = n > 1 && samePoint(ring[0], ring[n - 1]) ? n - 1 : n
      for (let vi = 0; vi < count; vi++) {
        if (flat === flatIndex) {
          const closed = n > 1 && samePoint(ring[0], ring[n - 1])
          const p = ring[vi]
          ring[vi] = [p[0] + dx, p[1] + dy]
          // keep the closing duplicate in sync when ring[0] moved
          if (vi === 0 && closed) {
            ring[n - 1] = [ring[0][0], ring[0][1]]
          }
          return c as Geometry
        }
        flat += 1
      }
    }
  }
  return c as Geometry
}

/**
 * Set the vertex at `flatIndex` (vertexClassifier order) to an absolute
 * coordinate.  Returns a NEW geometry; keeps the ring's closing duplicate in
 * sync when ring[0] is the one that moved.
 */
export function setVertex(geom: Geometry, flatIndex: number, x: number, y: number): Geometry {
  const c: any = cloneGeom(geom)
  const polys =
    c.type === 'MultiPolygon' ? c.coordinates : c.type === 'Polygon' ? [c.coordinates] : []
  let flat = 0
  for (const poly of polys) {
    // EXTERIOR ring only — the flat index space excludes holes (see
    // `exteriorRings`), so walking every ring here would write to the wrong
    // vertex on any polygon that has one.
    for (const ring of poly.slice(0, 1)) {
      const n = ring.length
      const closed = n > 1 && samePoint(ring[0], ring[n - 1])
      const count = closed ? n - 1 : n
      for (let vi = 0; vi < count; vi++) {
        if (flat === flatIndex) {
          ring[vi] = [x, y]
          if (vi === 0 && closed) ring[n - 1] = [x, y]
          return c as Geometry
        }
        flat += 1
      }
    }
  }
  return c as Geometry
}

/**
 * Insert `insert` into the ring segment that passes through `at`.
 *
 * Used for a MID-EDGE shared vertex: the edited feature has a vertex sitting
 * on a neighbour's straight segment, but the neighbour has no vertex there.
 * Dragging it used to move one side only, so the shared edge tore open and R6
 * refused the gesture — the vertex looked editable and simply could not be
 * moved.  Giving the neighbour a vertex at the destination keeps the two
 * sides sharing the edge, which is what topological editing does.
 *
 * Picks the NEAREST qualifying segment and skips segments whose endpoint is
 * already at `at` (that is the coincident case, handled before this).
 * Returns a new geometry, or null when no segment carries the point.
 */
export function insertOnSegmentThrough(
  geom: Geometry,
  at: readonly number[],
  insert: readonly number[],
  toleranceM: number = VERTEX_COINCIDENCE_TOLERANCE_M,
): Geometry | null {
  const c: any = cloneGeom(geom)
  const polys =
    c.type === 'MultiPolygon' ? c.coordinates : c.type === 'Polygon' ? [c.coordinates] : []

  let best: { ring: number[][]; index: number; d: number } | null = null
  for (const poly of polys) {
    for (const ring of poly) {
      const n = ring.length
      if (n < 2) continue
      const closed = samePoint(ring[0], ring[n - 1])
      const count = closed ? n - 1 : n
      for (let i = 0; i < count; i++) {
        const p = ring[i]
        const q = ring[(i + 1) % count]
        // An endpoint AT `at` means this is the coincident case, not mid-edge.
        // Always the fixed 1 m coincidence radius — "is this the same vertex?"
        // is a different question from `toleranceM`'s "is the point on this
        // segment?", so the two must not share a threshold.
        if (dist(p, at) <= COINCIDENCE_TOL_DEG || dist(q, at) <= COINCIDENCE_TOL_DEG) continue
        const d = pointSegmentDistanceM(
          at[0] as number, at[1] as number,
          p[0], p[1], q[0], q[1],
        )
        if (d <= toleranceM && (best === null || d < best.d)) {
          best = { ring, index: i, d }
        }
      }
    }
  }
  if (!best) return null
  best.ring.splice(best.index + 1, 0, [insert[0] as number, insert[1] as number])
  return c as Geometry
}

function dist(a: readonly number[], b: readonly number[]): number {
  const dx = (a[0] as number) - (b[0] as number)
  const dy = (a[1] as number) - (b[1] as number)
  return Math.hypot(dx, dy)
}

export interface PropagationInput {
  /** Edited feature id (excluded from neighbour search). */
  featureId: string
  /** Pre-gesture geometry of the edited feature (snapshot). */
  snapshot: Geometry | null | undefined
  /** Post-gesture geometry of the edited feature. */
  updated: Geometry | null | undefined
  /** All same-level features INCLUDING the edited one (map data). */
  layerFeatures: Array<{ id?: string | number; geometry: Geometry | null } | Feature>
}

/**
 * Compute the shared-vertex propagation for one drag.
 *
 * Two kinds of shared vertex propagate, and both end with the neighbour
 * carrying the SAME destination coordinate:
 *
 *   - **coincident** — the neighbour already has a vertex at the original
 *     position; it is moved to the destination;
 *   - **mid-edge** — the vertex lies on the neighbour's segment but the
 *     neighbour has no vertex there; one is INSERTED at the destination.
 *     Without this the drag moved a single side, tearing the shared edge, and
 *     R6 refused a vertex the rules had rendered as editable (VR-5).
 *
 * Returns null when:
 *   - snapshot/updated missing or vertex counts differ (add/remove gesture);
 *   - no single flat vertex moved; or
 *   - no same-level feature shares the original position at all (a genuinely
 *     unshared vertex → plain single-feature commit).
 */
export function computeSharedMoves(input: PropagationInput): SharedMoveResult | null {
  const { featureId, snapshot, updated, layerFeatures } = input
  if (!snapshot || !updated) return null

  const before = iterVertices(snapshot)
  const after = iterVertices(updated)
  if (before.length !== after.length || before.length === 0) return null

  // Locate the moved flat vertex (exactly one coordinate change = a drag).
  let movedIndex = -1
  let from: readonly number[] = []
  let to: readonly number[] = []
  for (let i = 0; i < before.length; i++) {
    const a = before[i][1] as unknown as number[]
    const b = after[i][1] as unknown as number[]
    if (!samePoint(a, b)) {
      if (movedIndex !== -1) return null // >1 vertex changed — not a plain drag
      movedIndex = before[i][0]
      from = a
      to = b
    }
  }
  if (movedIndex < 0 || from.length < 2 || to.length < 2) return null
  const dx = (to[0] as number) - (from[0] as number)
  const dy = (to[1] as number) - (from[1] as number)
  if (Math.abs(dx) < EPS && Math.abs(dy) < EPS) return null

  const moves: SharedMoveItem[] = []
  const propagatedFeatures: Array<{ id: string; geometry: Geometry }> = []

  for (const f of layerFeatures) {
    const g = (f as any)?.geometry as Geometry | null
    if (!g) continue
    const id = String((f as any)?.id ?? (f as any)?.properties?.id ?? '')
    if (!id) continue

    // The edited feature itself keeps its post-gesture geometry in the index
    // (validate() excludes it by featureId).
    if (id === String(featureId)) {
      propagatedFeatures.push({ id, geometry: updated })
      continue
    }

    // Is a vertex of this feature COINCIDENT with the original position?
    // (vertexClassifier's `shared` includes mid-edge vertices, but those have
    // no coincident neighbour vertex → no propagation; only coincident shared
    // vertices propagate, per plan §4 V-2.)
    const [fx, fy] = from as [number, number]
    if (isOnBoundary(fx, fy, g)) {
      // NEAREST vertex within the coincidence radius — never merely the first
      // one in ring order (see COINCIDENCE_TOL_DEG).
      let targetIndex = -1
      let bestD = Infinity
      for (const [flat, [x, y]] of iterVertices(g)) {
        const d = (x - fx) ** 2 + (y - fy) ** 2
        if (d <= COINCIDENCE_TOL_DEG ** 2 && d < bestD) {
          bestD = d
          targetIndex = flat
        }
      }
      if (targetIndex >= 0) {
        // SET the partner's vertex to the drag's destination rather than
        // translating it by (dx, dy).  The edited geometry comes from
        // `layer.toGeoJSON()` (Leaflet rounds to 6 dp) while the partner comes
        // from the server payload at full precision, so translating leaves the
        // two sides up to ~0.1 m apart — a sliver that re-opens the edge on
        // every subsequent gesture.  Assigning the same destination makes the
        // shared vertex EXACTLY coincident on both units, which is the whole
        // point of the atomic move.
        const moved = setVertex(g, targetIndex, to[0] as number, to[1] as number)
        moves.push({ feature_id: id, geometry: moved })
        propagatedFeatures.push({ id, geometry: moved })
        continue
      }
      // MID-EDGE: the vertex sits on this neighbour's segment but the
      // neighbour has no vertex there.  Give it one at the destination so the
      // edge stays shared — otherwise only one side moves, the edge tears,
      // and R6 refuses a vertex the rules had presented as editable.
      const inserted = insertOnSegmentThrough(g, from, to)
      if (inserted) {
        moves.push({ feature_id: id, geometry: inserted })
        propagatedFeatures.push({ id, geometry: inserted })
        continue
      }
    }
    propagatedFeatures.push({ id, geometry: g })
  }

  if (moves.length === 0) return null
  return { moves, propagatedFeatures }
}

// ─────────────────────────────────────────────────────────────────────────────
// V-4 (D4) — shared-edge vertex ADD / DELETE
//
// A vertex inserted on a shared edge must be inserted on BOTH polygons at the
// same coordinate, and a shared vertex deleted must be deleted from BOTH —
// otherwise the two sides stop sharing that vertex: the shape survives the
// add/delete itself (an inserted midpoint lies on the straight segment), but
// the NEXT drag of that vertex would move one side only and tear the edge
// open.  Both directions reuse the V-2 `shared_moves` batch, so the backend
// writes every affected feature in one transaction and validates the whole
// batch through R6.
// ─────────────────────────────────────────────────────────────────────────────

export type VertexChangeKind = 'add' | 'remove'

export interface SharedVertexChange {
  kind: VertexChangeKind
  /** The added / removed coordinate on the edited feature. */
  coord: readonly number[]
  /** Partners to rewrite, or null when no same-level feature shares the edge
   *  (an unshared interior edit — commit the single feature as before). */
  propagation: SharedMoveResult | null
  /** Set when the change must be refused: applying it to a partner would
   *  collapse that ring below a triangle. */
  blocked?: 'DEGENERATE_RING'
}

type Ring = number[][]

/** Rings of a Polygon / MultiPolygon in document order (closing dup kept). */
function ringsOf(geom: Geometry | null | undefined): Ring[] {
  const g: any = geom
  if (!g) return []
  const polys = g.type === 'MultiPolygon' ? g.coordinates : g.type === 'Polygon' ? [g.coordinates] : []
  const out: Ring[] = []
  for (const poly of polys) for (const ring of poly) out.push(ring as Ring)
  return out
}

function isClosed(ring: Ring): boolean {
  const n = ring.length
  return n > 1 && samePoint(ring[0], ring[n - 1])
}

/** Ring without its closing duplicate. */
function openRing(ring: Ring): Ring {
  return isClosed(ring) ? ring.slice(0, -1) : ring.slice()
}

/** Same 1 m coincidence radius as the drag path — see COINCIDENCE_TOL_DEG. */
const TOL_DEG = COINCIDENCE_TOL_DEG

function near(a: readonly number[], b: readonly number[]): boolean {
  const dx = (a[0] as number) - (b[0] as number)
  const dy = (a[1] as number) - (b[1] as number)
  return dx * dx + dy * dy <= TOL_DEG * TOL_DEG
}

/**
 * Locate the single ring that gained / lost one vertex between `snapshot` and
 * `updated`, and return the changed coordinate plus its two ring neighbours
 * (wrap-aware) taken from the ring that CONTAINS the vertex — `updated` for an
 * add, `snapshot` for a remove.
 */
function diffRingVertex(
  snapshot: Geometry,
  updated: Geometry,
): { kind: VertexChangeKind; coord: number[]; before: number[]; after: number[] } | null {
  const prev = ringsOf(snapshot).map(openRing)
  const next = ringsOf(updated).map(openRing)
  if (prev.length === 0 || prev.length !== next.length) return null

  let changed = -1
  for (let i = 0; i < prev.length; i++) {
    const delta = next[i].length - prev[i].length
    if (delta === 0) continue
    if (Math.abs(delta) !== 1 || changed !== -1) return null // not a single add/remove
    changed = i
  }
  if (changed === -1) return null

  const kind: VertexChangeKind = next[changed].length > prev[changed].length ? 'add' : 'remove'
  const longer = kind === 'add' ? next[changed] : prev[changed]
  const shorter = kind === 'add' ? prev[changed] : next[changed]

  // First position where the rings diverge = where the vertex was inserted /
  // removed.  Identical prefixes mean it happened at the ring's tail.
  let k = shorter.length
  for (let i = 0; i < shorter.length; i++) {
    if (!samePoint(longer[i], shorter[i])) { k = i; break }
  }
  const L = longer.length
  if (L < 3) return null
  return {
    kind,
    coord: longer[k],
    before: longer[(k - 1 + L) % L],
    after: longer[(k + 1) % L],
  }
}

/** Insert `coord` into the first ring segment whose endpoints match
 *  (`before`, `after`) in either orientation.  Returns true when inserted. */
function insertOnSegment(ring: Ring, coord: number[], before: number[], after: number[]): boolean {
  const open = openRing(ring)
  const L = open.length
  for (let i = 0; i < L; i++) {
    const p = open[i]
    const q = open[(i + 1) % L]
    if ((near(p, before) && near(q, after)) || (near(p, after) && near(q, before))) {
      ring.splice(i + 1, 0, [coord[0], coord[1]])
      return true
    }
  }
  return false
}

/** Remove the vertex nearest to `coord` (within tolerance).  Returns
 *  'ok' | 'miss' (no coincident vertex) | 'degenerate' (would break the ring). */
function removeCoincident(ring: Ring, coord: number[]): 'ok' | 'miss' | 'degenerate' {
  const closed = isClosed(ring)
  const open = openRing(ring)
  let best = -1
  let bestD = Infinity
  for (let i = 0; i < open.length; i++) {
    const dx = open[i][0] - coord[0]
    const dy = open[i][1] - coord[1]
    const d = dx * dx + dy * dy
    if (d <= TOL_DEG * TOL_DEG && d < bestD) { best = i; bestD = d }
  }
  if (best < 0) return 'miss'
  if (open.length - 1 < 3) return 'degenerate'
  ring.splice(best, 1)
  if (closed && best === 0) {
    // ring[0] changed → keep the closing duplicate in sync
    ring[ring.length - 1] = [ring[0][0], ring[0][1]]
  }
  return 'ok'
}

/**
 * Compute the both-sides propagation for a vertex ADD / DELETE gesture (D4).
 *
 * Returns null when the gesture is not a single-vertex add/remove (a drag, or
 * a structural change we do not understand) — the caller then keeps the plain
 * single-feature commit path.
 */
export function computeSharedVertexChange(input: PropagationInput): SharedVertexChange | null {
  const { featureId, snapshot, updated, layerFeatures } = input
  if (!snapshot || !updated) return null

  const diff = diffRingVertex(snapshot, updated)
  if (!diff) return null

  const moves: SharedMoveItem[] = []
  const propagatedFeatures: Array<{ id: string; geometry: Geometry }> = []
  let blocked: 'DEGENERATE_RING' | undefined

  for (const f of layerFeatures) {
    const g = (f as any)?.geometry as Geometry | null
    if (!g) continue
    const id = String((f as any)?.id ?? (f as any)?.properties?.id ?? '')
    if (!id) continue
    if (id === String(featureId)) {
      propagatedFeatures.push({ id, geometry: updated })
      continue
    }

    const candidate: any = cloneGeom(g)
    let touched = false
    for (const ring of ringsOf(candidate)) {
      if (diff.kind === 'add') {
        if (insertOnSegment(ring, diff.coord, diff.before, diff.after)) { touched = true; break }
      } else {
        const verdict = removeCoincident(ring, diff.coord)
        if (verdict === 'degenerate') { blocked = 'DEGENERATE_RING'; break }
        if (verdict === 'ok') { touched = true; break }
      }
    }
    if (blocked) break
    if (touched) {
      moves.push({ feature_id: id, geometry: candidate as Geometry })
      propagatedFeatures.push({ id, geometry: candidate as Geometry })
    } else {
      propagatedFeatures.push({ id, geometry: g })
    }
  }

  if (blocked) return { kind: diff.kind, coord: diff.coord, propagation: null, blocked }
  if (moves.length === 0) return { kind: diff.kind, coord: diff.coord, propagation: null }
  return { kind: diff.kind, coord: diff.coord, propagation: { moves, propagatedFeatures } }
}
