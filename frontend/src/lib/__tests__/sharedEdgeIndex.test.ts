import { describe, it, expect } from 'vitest'
import type { Feature, Polygon } from 'geojson'
import {
  SharedEdgeIndex,
  SNAP_TOLERANCE_M,
  MIN_SLIVER_AREA_M2,
  metresToDegrees,
  haversineM,
  minVertexDistanceM,
  polygonRings,
  allVertices,
  geometryBounds,
  segmentsIntersect,
} from '../sharedEdgeIndex'

function poly(coords: number[][][], id: string): Feature<Polygon> {
  return {
    type: 'Feature',
    properties: { id },
    geometry: { type: 'Polygon', coordinates: coords },
  }
}

// two adjacent ~1km squares sharing a vertical edge along x=0
const LEFT: number[][][] = [[
  [-0.01, 0], [0, 0], [0, 0.01], [-0.01, 0.01], [-0.01, 0],
]]
const RIGHT: number[][][] = [[
  [0, 0], [0.01, 0], [0.01, 0.01], [0, 0.01], [0, 0],
]]

describe('sharedEdgeIndex constants', () => {
  it('mirrors backend MAX_EDGE_TOLERANCE_M and MIN_SLIVER_AREA_M2', () => {
    expect(SNAP_TOLERANCE_M).toBe(150)
    expect(MIN_SLIVER_AREA_M2).toBe(100)
    expect(metresToDegrees(150)).toBeCloseTo(150 / 111_320, 9)
  })
})

describe('haversineM', () => {
  it('computes a plausible distance for 0.01 deg lat', () => {
    const m = haversineM([0, 0], [0, 0.01])
    expect(m).toBeGreaterThan(1000)
    expect(m).toBeLessThan(1200)
  })
})

describe('segmentsIntersect', () => {
  it('detects a proper X crossing', () => {
    expect(segmentsIntersect([0, 0], [1, 1], [0, 1], [1, 0])).toBe(true)
  })
  it('is false for collinear shared edges (healthy adjacence)', () => {
    expect(segmentsIntersect([0, 0], [1, 0], [0, 0], [2, 0])).toBe(false)
  })
  it('is false for endpoint touching', () => {
    expect(segmentsIntersect([0, 0], [1, 0], [1, 0], [1, 1])).toBe(false)
  })
})

const LEFT_GEOM: GeoJSON.Polygon = { type: 'Polygon', coordinates: LEFT }
const RIGHT_GEOM: GeoJSON.Polygon = { type: 'Polygon', coordinates: RIGHT }

describe('SharedEdgeIndex over adjacent polygons', () => {
  const features = [poly(LEFT, 'left'), poly(RIGHT, 'right')]

  it('indexes both features', () => {
    const idx = new SharedEdgeIndex(features)
    expect(idx.size).toBe(2)
  })

  it('finds neighbours by bbox pre-filter', () => {
    const idx = new SharedEdgeIndex(features)
    const cands = idx.neighborCandidates(LEFT_GEOM)
    expect(cands).toContain('right')
  })

  it('accepts a shared-edge neighbour (no gap, no overlap)', () => {
    const idx = new SharedEdgeIndex(features)
    const verdict = idx.validate(LEFT_GEOM, {
      excludeId: 'left',
      snapshot: LEFT_GEOM,
    })
    expect(verdict.ok).toBe(true)
  })

  it('flags GAP when a neighbour is pushed away past tolerance', () => {
    // edited right feature verified against its own pre-edit snapshot; the
    // drift (0.002 deg ~ 222 m) exceeds SNAP_TOLERANCE_M (150 m)
    const drifted: number[][][] = [[
      [0.002, 0], [0.012, 0], [0.012, 0.01], [0.002, 0.01], [0.002, 0],
    ]]
    const idx = new SharedEdgeIndex([poly(LEFT, 'left'), poly(drifted, 'right')])
    const verdict = idx.validate({ type: 'Polygon', coordinates: drifted }, {
      excludeId: 'right',
      snapshot: RIGHT_GEOM,
    })
    expect(verdict.ok).toBe(false)
    expect(verdict.witness).toBe('GAP')
  })

  it('flags OVERLAP when an edited edge properly crosses a neighbour', () => {
    const spike: number[][][] = [[
      [-0.01, 0.005], [0.02, 0.005], [-0.01, 0.006], [-0.01, 0.005],
    ]]
    const idx = new SharedEdgeIndex([poly(spike, 'spike'), poly(RIGHT, 'right')])
    const verdict = idx.validate({ type: 'Polygon', coordinates: spike }, { excludeId: 'spike' })
    expect(verdict.ok).toBe(false)
    expect(verdict.witness).toBe('OVERLAP')
  })
})

describe('geometry helpers', () => {
  it('polygonRings returns closed rings', () => {
    const rings = polygonRings(LEFT_GEOM)
    expect(rings.length).toBe(1)
    expect(allVertices(LEFT_GEOM)).toHaveLength(5)
  })
  it('geometryBounds spans the right extents', () => {
    const [minX, minY, maxX, maxY] = geometryBounds(LEFT_GEOM)
    expect(minX).toBeCloseTo(-0.01, 9)
    expect(maxX).toBeCloseTo(0, 9)
    expect(minY).toBeCloseTo(0, 9)
    expect(maxY).toBeCloseTo(0.01, 9)
  })
  it('minVertexDistanceM finds closest pair', () => {
    // LEFT and RIGHT share the edge x=0 → exact-0 distance
    const d = minVertexDistanceM(allVertices(LEFT_GEOM), allVertices(RIGHT_GEOM))
    expect(d).toBe(0)
    // a drifted neighbour is > 0
    const drifted = allVertices({ type: 'Polygon', coordinates: [[
      [0.002, 0.002], [0.012, 0.002], [0.012, 0.012], [0.002, 0.012], [0.002, 0.002],
    ]] })
    const d2 = minVertexDistanceM(allVertices(LEFT_GEOM), drifted)
    expect(d2).toBeGreaterThan(0)
  })
})