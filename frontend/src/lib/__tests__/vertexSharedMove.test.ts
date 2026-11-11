import { describe, it, expect } from 'vitest'
import type { Geometry } from 'geojson'
import { computeSharedMoves, computeSharedVertexChange, insertOnSegmentThrough, translateVertex } from '../vertexSharedMove'

function poly(coords: number[][][]): Geometry {
  return { type: 'Polygon', coordinates: coords }
}

// helper to read ring vertex
function ringAt(geom: Geometry, i: number): number[] {
  const c = (geom as any).coordinates[0]
  return [c[i][0], c[i][1]]
}

const A_BEFORE = poly([
  [
    [0, 0], [10, 0], [10, 10], [0, 10], [0, 0],
  ],
])
const B_BEFORE = poly([
  [
    [10, 0], [20, 0], [20, 10], [10, 10], [10, 0],
  ],
])

function features(...geoms: Geometry[]): Array<{ id: string; geometry: Geometry }> {
  return geoms.map((g, i) => ({ id: `f${i}`, geometry: g }))
}

describe('translateVertex', () => {
  it('moves the flat-indexed vertex and returns a new geometry', () => {
    const out = translateVertex(A_BEFORE, 1, 5, 2)
    expect(out).not.toBe(A_BEFORE)
    expect(ringAt(out, 1)).toEqual([15, 2])
    // untouched vertex
    expect(ringAt(out, 0)).toEqual([0, 0])
  })

  it('keeps a closed ring closed when ring[0] moves', () => {
    const closed = poly([[[1, 1], [2, 1], [2, 2], [1, 2], [1, 1]]])
    const out = translateVertex(closed, 0, 3, 4)
    expect(ringAt(out, 0)).toEqual([4, 5])
    expect(ringAt(out, 4)).toEqual([4, 5]) // closing dup synced
  })

  it('handles MultiPolygon flat indices', () => {
    const mp: Geometry = {
      type: 'MultiPolygon',
      coordinates: [
        [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
        [[[2, 0], [3, 0], [3, 1], [2, 1], [2, 0]]],
      ],
    }
    const out = translateVertex(mp, 4, 10, 10) // first vertex of second polygon
    const c = (out as any).coordinates
    expect(c[1][0][0][0]).toBe(12)
  })
})

describe('computeSharedMoves', () => {
  it('returns partners + propagated set when a coincident shared vertex moves', () => {
    // A and B share the vertical edge x=10 (flat vertex 1 = (10,0) on A and
    // flat vertex 0 = (10,0) on B).  Drag A's (10,0) → (12,0).
    const A_AFTER = poly([[[0, 0], [12, 0], [10, 10], [0, 10], [0, 0]]])
    const result = computeSharedMoves({
      featureId: 'f0',
      snapshot: A_BEFORE,
      updated: A_AFTER,
      layerFeatures: features(A_BEFORE, B_BEFORE),
    })
    expect(result).not.toBeNull()
    expect(result!.moves).toHaveLength(1)
    expect(result!.moves[0].feature_id).toBe('f1')
    // B's (10,0) must move to (12,0)
    expect(ringAt(result!.moves[0].geometry, 0)).toEqual([12, 0])
    // propagated set: f0 → post-gesture, f1 → moved
    expect(result!.propagatedFeatures).toHaveLength(2)
    const f1 = result!.propagatedFeatures.find((p) => p.id === 'f1')!
    expect(ringAt(f1.geometry, 0)).toEqual([12, 0])
    const f0 = result!.propagatedFeatures.find((p) => p.id === 'f0')!
    expect(f0.geometry).toBe(A_AFTER)
  })

  it('returns null when no same-level feature is coincident (mid-edge / unshared)', () => {
    const A_AFTER = poly([[[0, 0], [12, 0], [10, 10], [0, 10], [0, 0]]])
    // neighbour B is far away — no coincident vertex
    const far = poly([[[50, 0], [60, 0], [60, 10], [50, 10], [50, 0]]])
    const result = computeSharedMoves({
      featureId: 'f0',
      snapshot: A_BEFORE,
      updated: A_AFTER,
      layerFeatures: features(A_BEFORE, far),
    })
    expect(result).toBeNull()
  })

  it('returns null when snapshot is missing or counts differ', () => {
    expect(computeSharedMoves({
      featureId: 'f0',
      snapshot: null,
      updated: A_BEFORE,
      layerFeatures: features(A_BEFORE, B_BEFORE),
    })).toBeNull()

    const more = poly([[[0, 0], [5, 0], [10, 0], [10, 10], [0, 10], [0, 0]]])
    expect(computeSharedMoves({
      featureId: 'f0',
      snapshot: A_BEFORE,
      updated: more,
      layerFeatures: features(A_BEFORE, B_BEFORE),
    })).toBeNull()
  })

  it('returns null when multiple vertices moved (not a plain drag)', () => {
    const A_AFTER = poly([[[0, 0], [12, 2], [10, 10], [12, 10], [0, 0]]])
    expect(computeSharedMoves({
      featureId: 'f0',
      snapshot: A_BEFORE,
      updated: A_AFTER,
      layerFeatures: features(A_BEFORE, B_BEFORE),
    })).toBeNull()
  })

  it('propagates a 3-block junction to BOTH partners', () => {
    // f0/f1 share the x=10 vertical edge; f0's top-right corner (10,10) is
    // also the corner of C (f2, above f0).  Moving ONLY that single corner
    // propagates to f1 (whose top-right corner coincides) and f2.
    const C = poly([
      [
        [0, 10], [10, 10], [10, 20], [0, 20], [0, 10],
      ],
    ])
    const A_AFTER = poly([[[0, 0], [10, 0], [12, 10], [0, 10], [0, 0]]])
    const result = computeSharedMoves({
      featureId: 'f0',
      snapshot: A_BEFORE,
      updated: A_AFTER,
      layerFeatures: features(A_BEFORE, B_BEFORE, C),
    })
    expect(result).not.toBeNull()
    expect(result!.moves).toHaveLength(2)
    const f1 = result!.moves.find((m) => m.feature_id === 'f1')!
    const f2 = result!.moves.find((m) => m.feature_id === 'f2')!
    // f1's top-right corner (10,10) → (12,10)
    const f1Ring = (f1.geometry as any).coordinates[0]
    const f1Idx = f1Ring.findIndex((p: number[]) => p[0] === 12 && p[1] === 10)
    expect(f1Ring[f1Idx]).toEqual([12, 10])
    expect(f1Ring.findIndex((p: number[]) => p[0] === 10 && p[1] === 10)).toBe(-1)
    // f2's corner (10,10) → (12,10)
    const f2Ring = (f2.geometry as any).coordinates[0]
    const f2Idx = f2Ring.findIndex((p: number[]) => p[0] === 12 && p[1] === 10)
    expect(f2Ring[f2Idx]).toEqual([12, 10])
  })
})
// ─────────────────────────────────────────────────────────────────────────────
// V-4 (D4) — shared-edge add / delete
// ─────────────────────────────────────────────────────────────────────────────

describe('computeSharedVertexChange', () => {
  // A = [0,0]..[10,10]; B = [10,0]..[20,10] — they share the x=10 edge.
  it('inserts a vertex added on a shared edge into the neighbour too', () => {
    const aAfter = poly([[[0, 0], [10, 0], [10, 5], [10, 10], [0, 10], [0, 0]]])
    const res = computeSharedVertexChange({
      featureId: 'f0',
      snapshot: A_BEFORE,
      updated: aAfter,
      layerFeatures: features(A_BEFORE, B_BEFORE),
    })
    expect(res?.kind).toBe('add')
    expect(res?.coord).toEqual([10, 5])
    expect(res?.propagation?.moves).toHaveLength(1)
    const partner = res!.propagation!.moves[0]
    expect(partner.feature_id).toBe('f1')
    // B's shared edge is its WRAPPING segment ([10,10] → [10,0]) — the vertex
    // must land there, before the closing duplicate.
    const ring = (partner.geometry as any).coordinates[0]
    expect(ring).toEqual([[10, 0], [20, 0], [20, 10], [10, 10], [10, 5], [10, 0]])
  })

  it('deletes a shared vertex from the neighbour too', () => {
    const aWith = poly([[[0, 0], [10, 0], [10, 5], [10, 10], [0, 10], [0, 0]]])
    const bWith = poly([[[10, 0], [20, 0], [20, 10], [10, 10], [10, 5], [10, 0]]])
    const res = computeSharedVertexChange({
      featureId: 'f0',
      snapshot: aWith,
      updated: A_BEFORE, // [10,5] removed
      layerFeatures: features(aWith, bWith),
    })
    expect(res?.kind).toBe('remove')
    expect(res?.coord).toEqual([10, 5])
    expect(res?.propagation?.moves).toHaveLength(1)
    const ring = (res!.propagation!.moves[0].geometry as any).coordinates[0]
    expect(ring).toEqual([[10, 0], [20, 0], [20, 10], [10, 10], [10, 0]])
  })

  it('keeps the neighbour ring closed when the removed vertex was ring[0]', () => {
    const aWith = poly([[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]])
    const aAfter = poly([[[10, 0], [10, 10], [0, 10], [10, 0]]]) // [0,0] removed
    const bWith = poly([[[0, 0], [-10, 0], [-10, 10], [0, 10], [0, 0]]])
    const res = computeSharedVertexChange({
      featureId: 'f0',
      snapshot: aWith,
      updated: aAfter,
      layerFeatures: features(aWith, bWith),
    })
    expect(res?.kind).toBe('remove')
    const ring = (res!.propagation!.moves[0].geometry as any).coordinates[0]
    expect(ring[0]).toEqual(ring[ring.length - 1]) // still closed
    expect(ring).toEqual([[-10, 0], [-10, 10], [0, 10], [-10, 0]])
  })

  it('blocks a delete that would collapse the neighbour below a triangle', () => {
    const aWith = poly([[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]])
    const aAfter = poly([[[10, 0], [10, 10], [0, 10], [10, 0]]]) // [0,0] removed
    const triangle = poly([[[0, 0], [-10, 0], [-5, 10], [0, 0]]])
    const res = computeSharedVertexChange({
      featureId: 'f0',
      snapshot: aWith,
      updated: aAfter,
      layerFeatures: features(aWith, triangle),
    })
    expect(res?.blocked).toBe('DEGENERATE_RING')
    expect(res?.propagation).toBeNull()
  })

  it('returns no propagation when the edge is not shared', () => {
    const aAfter = poly([[[0, 0], [10, 0], [10, 10], [5, 10], [0, 10], [0, 0]]])
    const res = computeSharedVertexChange({
      featureId: 'f0',
      snapshot: A_BEFORE,
      updated: aAfter,
      layerFeatures: features(A_BEFORE, B_BEFORE),
    })
    expect(res?.kind).toBe('add')
    expect(res?.propagation).toBeNull()
  })

  it('returns null for a plain drag (no vertex count change)', () => {
    const dragged = translateVertex(A_BEFORE, 1, 1, 1)
    const res = computeSharedVertexChange({
      featureId: 'f0',
      snapshot: A_BEFORE,
      updated: dragged,
      layerFeatures: features(A_BEFORE, B_BEFORE),
    })
    expect(res).toBeNull()
  })
})


/**
 * Regression — "moving a shared vertex is rejected due to overlap" (2026-08-19).
 *
 * The partner-vertex search used SNAP_TOLERANCE_M (150 m, the neighbour SEARCH
 * radius) as the COINCIDENCE radius, and took the first match in ring order
 * rather than the nearest.  Real blocks are only a few hundred metres across,
 * so the far end of the very edge being dragged sits well inside 150 m and
 * comes first in the neighbour's ring — the propagation then moved the WRONG
 * corner, tearing the shared edge open, and R6 correctly rejected the result.
 *
 * The tests above cannot see this: they use coordinates 10 degrees apart
 * (~1000 km), where nothing but the true coincident vertex is ever in range.
 * These use real demo-forest coordinates and metre-scale spacing.
 */
describe('computeSharedMoves — coincidence radius (regression)', () => {
  const M = 1 / 111_320 // ~1 metre in degrees

  // Two adjacent rectangles sharing the vertical edge x=85.7620, the shape
  // auto-block generation actually produces.
  const P: [number, number] = [85.7620, 27.4137] // the dragged shared vertex
  const Q: [number, number] = [85.7620, 27.4145] // other end of the shared edge

  const LEFT = poly([[
    [85.7610, 27.4137], P, Q, [85.7610, 27.4145], [85.7610, 27.4137],
  ]])
  // RIGHT lists Q FIRST and the coincident P last — the ring order that made
  // the old "first within 150 m" search pick the wrong vertex.
  const RIGHT = poly([[
    Q, [85.7628, 27.4145], [85.7628, 27.4137], P, Q,
  ]])

  it('moves the COINCIDENT partner vertex, not a nearby one', () => {
    const to: [number, number] = [P[0] + 2 * M, P[1] + 2 * M] // 2 m drag
    const LEFT_AFTER = poly([[
      [85.7610, 27.4137], to, Q, [85.7610, 27.4145], [85.7610, 27.4137],
    ]])

    const result = computeSharedMoves({
      featureId: 'left',
      snapshot: LEFT,
      updated: LEFT_AFTER,
      layerFeatures: [
        { id: 'left', geometry: LEFT },
        { id: 'right', geometry: RIGHT },
      ],
    })

    expect(result).not.toBeNull()
    expect(result!.moves).toHaveLength(1)
    expect(result!.moves[0].feature_id).toBe('right')

    const ring = (result!.moves[0].geometry as any).coordinates[0]
    // index 3 is RIGHT's copy of P → follows the drag, exactly coincident.
    expect(ring[3][0]).toBeCloseTo(to[0], 12)
    expect(ring[3][1]).toBeCloseTo(to[1], 12)
    // index 0 is Q, ~89 m away — inside the OLD 150 m radius and first in ring
    // order, so this is the vertex the bug moved.  It must not move.
    expect(ring[0][0]).toBeCloseTo(Q[0], 12)
    expect(ring[0][1]).toBeCloseTo(Q[1], 12)
  })

  it('leaves the two sides EXACTLY coincident after the move', () => {
    // The edited geometry arrives from Leaflet at 6 dp while the partner comes
    // from the server at full precision; translating by (dx,dy) would leave a
    // sub-metre sliver, so the partner is SET to the drag destination.
    const to: [number, number] = [85.762018, 27.413718] // 6 dp, as Leaflet emits
    const LEFT_AFTER = poly([[
      [85.7610, 27.4137], to, Q, [85.7610, 27.4145], [85.7610, 27.4137],
    ]])
    const RIGHT_FULL = poly([[
      Q, [85.7628, 27.4145], [85.7628, 27.4137],
      [85.76200004, 27.41370007], // full-precision copy of P
      Q,
    ]])

    const result = computeSharedMoves({
      featureId: 'left',
      snapshot: LEFT,
      updated: LEFT_AFTER,
      layerFeatures: [
        { id: 'left', geometry: LEFT },
        { id: 'right', geometry: RIGHT_FULL },
      ],
    })

    const ring = (result!.moves[0].geometry as any).coordinates[0]
    expect(ring[3]).toEqual([to[0], to[1]]) // bit-identical, no drift
  })

  it('inserts into a neighbour that shares the edge but has no vertex there', () => {
    // MID-EDGE (VR-5).  The neighbour's segment passes through P but carries
    // no vertex at it.  Before VR-5 this returned null, the drag moved one
    // side only, the edge tore, and R6 refused a vertex the rules had shown
    // as editable.  Now the neighbour gains a vertex at the destination.
    const MID_ONLY = poly([[
      [85.76200, 27.41300], [85.76280, 27.41300], [85.76280, 27.41500],
      [85.76200, 27.41500], [85.76200, 27.41300],
    ]])
    const to: [number, number] = [P[0] + 2 * M, P[1] + 2 * M]
    const LEFT_AFTER = poly([[
      [85.7610, 27.4137], to, Q, [85.7610, 27.4145], [85.7610, 27.4137],
    ]])

    const result = computeSharedMoves({
      featureId: 'left',
      snapshot: LEFT,
      updated: LEFT_AFTER,
      layerFeatures: [
        { id: 'left', geometry: LEFT },
        { id: 'mid', geometry: MID_ONLY },
      ],
    })
    expect(result).not.toBeNull()
    expect(result!.moves).toHaveLength(1)
    const ring = (result!.moves[0].geometry as any).coordinates[0]
    const hasDest = ring.some((c: number[]) =>
      Math.abs(c[0] - to[0]) < 1e-12 && Math.abs(c[1] - to[1]) < 1e-12)
    expect(hasDest).toBe(true)
    // …and it grew by exactly one vertex.
    expect(ring.length).toBe(6)
  })

  it('leaves a genuinely unshared vertex alone', () => {
    // Far from every sibling → nothing to propagate, plain single-feature commit.
    const FAR = poly([[
      [85.7700, 27.4200], [85.7710, 27.4200], [85.7710, 27.4210],
      [85.7700, 27.4210], [85.7700, 27.4200],
    ]])
    const to: [number, number] = [P[0] + 2 * M, P[1] + 2 * M]
    const LEFT_AFTER = poly([[
      [85.7610, 27.4137], to, Q, [85.7610, 27.4145], [85.7610, 27.4137],
    ]])
    const result = computeSharedMoves({
      featureId: 'left',
      snapshot: LEFT,
      updated: LEFT_AFTER,
      layerFeatures: [{ id: 'left', geometry: LEFT }, { id: 'far', geometry: FAR }],
    })
    expect(result).toBeNull()
  })
})

describe('insertOnSegmentThrough', () => {
  // Real-scale coordinates: the helper measures point-to-segment distance in
  // METRES, so a degree-scale synthetic box would put every segment inside any
  // sane tolerance and prove nothing.
  const A: [number, number] = [85.7610, 27.4137]
  const B: [number, number] = [85.7620, 27.4137] // ~99 m east of A
  const C: [number, number] = [85.7620, 27.4145]
  const D: [number, number] = [85.7610, 27.4145]
  const BOX = poly([[A, B, C, D, A]])
  const MID_AB: [number, number] = [(A[0] + B[0]) / 2, A[1]]

  it('inserts into the segment carrying the point, after its start vertex', () => {
    const dest: [number, number] = [MID_AB[0], MID_AB[1] + 0.00002]
    const out = insertOnSegmentThrough(BOX, MID_AB, dest)!
    expect(out).not.toBeNull()
    const ring = (out as any).coordinates[0]
    expect(ring).toEqual([A, dest, B, C, D, A])
  })

  it('refuses when an endpoint already sits at the point (coincident case)', () => {
    expect(insertOnSegmentThrough(BOX, B, [B[0], B[1] + 0.00002])).toBeNull()
  })

  it('returns null when no segment carries the point', () => {
    // Interior of the box — on no edge at all.
    expect(insertOnSegmentThrough(BOX, [85.7615, 27.4141], [85.7615, 27.4142])).toBeNull()
  })

  it('keeps the ring closed', () => {
    const out = insertOnSegmentThrough(BOX, MID_AB, [MID_AB[0], MID_AB[1] + 0.00002])!
    const ring = (out as any).coordinates[0]
    expect(ring[0]).toEqual(ring[ring.length - 1])
  })

  it('picks the NEAREST carrying segment, not the first', () => {
    // A sliver whose two long edges both pass within tolerance of the point.
    const near: [number, number] = [85.76150, 27.41370]
    const SLIVER = poly([[
      [85.7610, 27.413708], [85.7620, 27.413708],   // seg 0 — ~0.9 m away, FIRST
      [85.7620, 27.4137], [85.7610, 27.4137],       // seg 2 — 0 m away, NEAREST
      [85.7610, 27.413708],
    ]])
    const out = insertOnSegmentThrough(SLIVER, near, [99, 99])!
    const ring = (out as any).coordinates[0]
    // Both long edges are inside the 1 m tolerance; the y=27.4137 one wins.
    // Insertion goes after that segment's start vertex, i.e. at index 3.
    expect(ring[2]).toEqual([85.7620, 27.4137])
    expect(ring[3]).toEqual([99, 99])
    expect(ring[4]).toEqual([85.7610, 27.4137])
  })
})
