import { describe, it, expect } from 'vitest'
import type { Feature, Polygon } from 'geojson'
import {
  classifyVertices,
  coordAtIndex,
  iterVertices,
  pointToBoundaryM,
  pointSegmentDistanceM,
  ringOfIndex,
  LAYER_TYPES,
} from '../vertexClassifier'

function poly(coords: number[][][], id: string): Feature<Polygon> {
  return {
    type: 'Feature',
    properties: { id },
    geometry: { type: 'Polygon', coordinates: coords },
  }
}

// Explicit ring order for deterministic indices (mirrors the backend tests).
const BOUNDARY: number[][][] = [[
  [83.0, 27.0], [84.0, 27.0], [84.0, 28.0], [83.0, 28.0],
]]
const A: number[][][] = [[
  [83.2, 27.2], [83.5, 27.2], [83.5, 27.8], [83.2, 27.8],
]]
const B: number[][][] = [[
  [83.5, 27.2], [83.8, 27.2], [83.8, 27.8], [83.5, 27.8],
]]

const A_GEOM: Polygon = { type: 'Polygon', coordinates: A }
const B_GEOM: Polygon = { type: 'Polygon', coordinates: B }
const BOUNDARY_GEOM: Polygon = { type: 'Polygon', coordinates: BOUNDARY }

describe('iterVertices / resolvers', () => {
  it('iterates flat indices over exterior rings', () => {
    const verts = iterVertices(A_GEOM)
    expect(verts).toHaveLength(4)
    expect(verts[0]).toEqual([0, [83.2, 27.2]])
    expect(verts[3]).toEqual([3, [83.2, 27.8]])
  })
  it('drops the closing duplicate of a closed ring', () => {
    const closed: number[][][] = [[
      [83.0, 27.0], [84.0, 27.0], [84.0, 28.0], [83.0, 28.0], [83.0, 27.0],
    ]]
    expect(iterVertices({ type: 'Polygon', coordinates: closed })).toHaveLength(4)
  })
  it('coordAtIndex / ringOfIndex resolve flat indices', () => {
    expect(coordAtIndex(A_GEOM, 1)).toEqual([83.5, 27.2])
    expect(coordAtIndex(A_GEOM, 99)).toBeNull()
    expect(ringOfIndex(A_GEOM, 2)).toEqual([0, 2])
    expect(ringOfIndex(A_GEOM, 99)).toBeNull()
  })
  it('handles MultiPolygon flat across polygons', () => {
    const mp: GeoJSON.MultiPolygon = {
      type: 'MultiPolygon',
      coordinates: [
        [[[83.0, 27.0], [83.5, 27.0], [83.5, 27.5], [83.0, 27.5]]],
        [[[83.5, 27.5], [84.0, 27.5], [84.0, 28.0], [83.5, 28.0]]],
      ],
    }
    expect(iterVertices(mp)).toHaveLength(8)
    expect(coordAtIndex(mp, 4)).toEqual([83.5, 27.5])
    expect(ringOfIndex(mp, 5)).toEqual([1, 1])
  })
})

describe('pointSegmentDistanceM / pointToBoundaryM', () => {
  it('returns ~0 for a point ON a segment', () => {
    const d = pointSegmentDistanceM(0, 0.005, 0, 0, 0, 0.01)
    expect(d).toBeLessThan(1)
  })
  it('returns the perpendicular distance for an off-line point', () => {
    // 0.005 deg longitude ≈ ~515 m at the equator-ish lat used here
    const d = pointSegmentDistanceM(0.005, 0.005, 0, 0, 0, 0.01)
    expect(d).toBeGreaterThan(400)
    expect(d).toBeLessThan(700)
  })
  it('pointToBoundaryM finds the nearest edge of a polygon', () => {
    // point just right of A's left edge x=83.2
    expect(pointToBoundaryM(83.2005, 27.5, A_GEOM)).toBeLessThan(100)
  })
})

describe('classifyVertices', () => {
  it('boundary layer (Rule A): fully editable, no shell/no shared', () => {
    const res = classifyVertices(BOUNDARY_GEOM, { layerType: LAYER_TYPES.boundary })
    expect(res.editable).toEqual([0, 1, 2, 3])
    expect(res.shell).toEqual([])
    expect(res.shared).toEqual([])
    expect(res.vertexCount).toBe(4)
  })

  it('blocks: interior shared vertices editable (mirror of backend)', () => {
    const res = classifyVertices(A_GEOM, {
      layerType: LAYER_TYPES.blocks,
      sameLevelFeatures: [poly(B, 'b')],
      parentShell: BOUNDARY_GEOM,
    })
    expect(res.shared).toEqual([1, 2])
    expect(res.shell).toEqual([])
    expect(res.editable).toEqual([1, 2])
  })

  it('blocks: shell vertices locked even when shared (junction rule)', () => {
    const a: number[][][] = [[[83.0, 27.0], [83.5, 27.0], [83.5, 27.5], [83.0, 27.5]]]
    const b: number[][][] = [[[83.0, 27.5], [83.5, 27.5], [83.5, 28.0], [83.0, 28.0]]]
    const res = classifyVertices({ type: 'Polygon', coordinates: a }, {
      layerType: LAYER_TYPES.blocks,
      sameLevelFeatures: [poly(b, 'b')],
      parentShell: BOUNDARY_GEOM,
    })
    // (83.0,27.5) index 3 is shared AND on shell → locked
    expect(res.shared).toContain(3)
    expect(res.shell).toContain(3)
    expect(res.editable).not.toContain(3)
    expect(res.editable).toEqual([2])
  })

  it('mid-edge vertex on a shared segment is shared/editable', () => {
    const aMid: number[][][] = [[
      [83.2, 27.2], [83.5, 27.2], [83.5, 27.5], [83.5, 27.8], [83.2, 27.8],
    ]]
    const res = classifyVertices({ type: 'Polygon', coordinates: aMid }, {
      layerType: LAYER_TYPES.blocks,
      sameLevelFeatures: [poly(B, 'b')],
      parentShell: BOUNDARY_GEOM,
    })
    expect(res.shared).toContain(2)
    expect(res.editable).toContain(2)
  })

  it('mid-edge vertex off the shared segment is NOT shared', () => {
    const aOff: number[][][] = [[
      [83.2, 27.2], [83.5, 27.2], [83.45, 27.5], [83.5, 27.8], [83.2, 27.8],
    ]]
    const res = classifyVertices({ type: 'Polygon', coordinates: aOff }, {
      layerType: LAYER_TYPES.blocks,
      sameLevelFeatures: [poly(B, 'b')],
      parentShell: BOUNDARY_GEOM,
    })
    expect(res.shared).not.toContain(2)
    expect(res.editable).not.toContain(2)
  })

  it('isolated block touching the boundary → nothing editable', () => {
    const lone: number[][][] = [[[83.0, 27.0], [83.5, 27.0], [83.5, 27.5], [83.0, 27.5]]]
    const res = classifyVertices({ type: 'Polygon', coordinates: lone }, {
      layerType: LAYER_TYPES.blocks,
      sameLevelFeatures: [],
      parentShell: BOUNDARY_GEOM,
    })
    expect(res.editable).toEqual([])
    expect(res.shared).toEqual([])
  })

  it('compartment one level down: interior shared editable, shell locked', () => {
    const block: number[][][] = [[[83.0, 27.0], [84.0, 27.0], [84.0, 28.0], [83.0, 28.0]]]
    const c1: number[][][] = [[[83.2, 27.2], [83.6, 27.2], [83.6, 27.8], [83.2, 27.8]]]
    const c2: number[][][] = [[[83.6, 27.2], [84.0, 27.2], [84.0, 27.8], [83.6, 27.8]]]
    const res = classifyVertices({ type: 'Polygon', coordinates: c1 }, {
      layerType: LAYER_TYPES.compartments,
      sameLevelFeatures: [poly(c2, 'c2')],
      parentShell: { type: 'Polygon', coordinates: block },
    })
    expect(res.editable).toEqual([1, 2])
    expect(res.shell).toEqual([])
  })

  it('null/empty geometry → empty classification', () => {
    expect(classifyVertices(null, { layerType: LAYER_TYPES.blocks })).toEqual({
      shared: [], shell: [], editable: [], vertexCount: 0,
    })
  })
})
