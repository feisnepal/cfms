import { describe, it, expect } from 'vitest'
import type { MultiPolygon, Polygon } from 'geojson'
import {
  isEditablePolygon,
  getOpenRing,
  moveVertex,
  insertVertex,
  deleteVertex,
  segmentMidpoints,
  ringVertices,
  pointInAnyNeighbour,
  isEditableAreal,
  arealVertices,
  arealMidpoints,
  moveArealVertex,
  insertArealVertex,
  deleteArealVertex,
} from '../previewVertexEdit'

// A simple square: (0,0) (1,0) (1,1) (0,1), closed.
const SQUARE: Polygon = {
  type: 'Polygon',
  coordinates: [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
}

describe('previewVertexEdit — pure ring editing', () => {
  it('isEditablePolygon accepts Polygon, rejects MultiPolygon/other', () => {
    expect(isEditablePolygon(SQUARE)).toBe(true)
    expect(isEditablePolygon({ type: 'MultiPolygon', coordinates: [] } as any)).toBe(false)
    expect(isEditablePolygon(null)).toBe(false)
    expect(isEditablePolygon(undefined)).toBe(false)
  })

  it('getOpenRing drops the closing duplicate vertex', () => {
    const ring = getOpenRing(SQUARE)
    expect(ring).toEqual([[0, 0], [1, 0], [1, 1], [0, 1]])
  })

  it('moveVertex updates one vertex and keeps the ring closed', () => {
    const moved = moveVertex(SQUARE, 1, [2, 0])
    expect(getOpenRing(moved)).toEqual([[0, 0], [2, 0], [1, 1], [0, 1]])
    const closingRing = moved.coordinates[0]
    expect(closingRing[0]).toEqual(closingRing[closingRing.length - 1])
  })

  it('moveVertex on index 0 keeps the closing vertex synced', () => {
    const moved = moveVertex(SQUARE, 0, [5, 5])
    const ring = moved.coordinates[0]
    expect(ring[0]).toEqual([5, 5])
    expect(ring[ring.length - 1]).toEqual([5, 5])
  })

  it('moveVertex is a no-op for an out-of-range index', () => {
    expect(moveVertex(SQUARE, 99, [9, 9])).toBe(SQUARE)
    expect(moveVertex(SQUARE, -1, [9, 9])).toBe(SQUARE)
  })

  it('insertVertex adds a vertex on the given segment', () => {
    const withMid = insertVertex(SQUARE, 0, [0.5, 0])
    expect(getOpenRing(withMid)).toEqual([[0, 0], [0.5, 0], [1, 0], [1, 1], [0, 1]])
  })

  it('insertVertex on the closing segment (index n-1) wraps to the start', () => {
    const withMid = insertVertex(SQUARE, 3, [0, 0.5])
    // segment 3 -> 0 (wrap): insert lands after index 3, i.e. at the end
    expect(getOpenRing(withMid)).toEqual([[0, 0], [1, 0], [1, 1], [0, 1], [0, 0.5]])
  })

  it('deleteVertex removes a vertex', () => {
    const deleted = deleteVertex(SQUARE, 1)
    expect(getOpenRing(deleted)).toEqual([[0, 0], [1, 1], [0, 1]])
  })

  it('deleteVertex refuses to shrink below a triangle', () => {
    const triangle: Polygon = { type: 'Polygon', coordinates: [[[0, 0], [1, 0], [0, 1], [0, 0]]] }
    expect(deleteVertex(triangle, 0)).toBe(triangle)
  })

  it('segmentMidpoints returns one midpoint per edge, including the closing edge', () => {
    const mids = segmentMidpoints(SQUARE)
    expect(mids).toHaveLength(4)
    expect(mids[0]).toEqual({ index: 0, lng: 0.5, lat: 0 })
    // closing edge: (0,1) -> (0,0)
    expect(mids[3]).toEqual({ index: 3, lng: 0, lat: 0.5 })
  })

  it('ringVertices returns lat/lng per open-ring vertex with matching index', () => {
    const verts = ringVertices(SQUARE)
    expect(verts).toEqual([
      { index: 0, lng: 0, lat: 0 },
      { index: 1, lng: 1, lat: 0 },
      { index: 2, lng: 1, lat: 1 },
      { index: 3, lng: 0, lat: 1 },
    ])
  })

  it('pointInAnyNeighbour detects a point inside a neighbour polygon', () => {
    const neighbour: Polygon = {
      type: 'Polygon',
      coordinates: [[[2, 2], [4, 2], [4, 4], [2, 4], [2, 2]]],
    }
    expect(pointInAnyNeighbour({ lat: 3, lng: 3 }, [neighbour])).toBe(true)
    expect(pointInAnyNeighbour({ lat: 10, lng: 10 }, [neighbour])).toBe(false)
  })

  it('pointInAnyNeighbour tolerates a malformed neighbour geometry without throwing', () => {
    const malformed = { type: 'Polygon', coordinates: [] } as unknown as Polygon
    expect(() => pointInAnyNeighbour({ lat: 0, lng: 0 }, [malformed])).not.toThrow()
  })
})

describe('previewVertexEdit — MultiPolygon (CO-1: a neighbour split the boundary)', () => {
  // Two disjoint squares.
  const MULTI: MultiPolygon = {
    type: 'MultiPolygon',
    coordinates: [
      [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
      [[[5, 5], [7, 5], [7, 7], [5, 7], [5, 5]]],
    ],
  }

  it('isEditableAreal accepts Polygon and non-empty MultiPolygon, rejects the rest', () => {
    expect(isEditableAreal(SQUARE)).toBe(true)
    expect(isEditableAreal(MULTI)).toBe(true)
    expect(isEditableAreal({ type: 'MultiPolygon', coordinates: [] })).toBe(false)
    expect(isEditableAreal({ type: 'LineString', coordinates: [[0, 0], [1, 1]] } as never)).toBe(false)
    expect(isEditableAreal(null)).toBe(false)
  })

  it('arealVertices tags every part exterior-ring vertex with its poly index', () => {
    const vs = arealVertices(MULTI)
    expect(vs).toHaveLength(8)
    expect(vs.filter((v) => v.poly === 0)).toHaveLength(4)
    expect(vs.filter((v) => v.poly === 1)).toHaveLength(4)
    expect(vs.find((v) => v.poly === 1 && v.index === 0)).toMatchObject({ lat: 5, lng: 5 })
  })

  it('arealMidpoints returns 4 per part', () => {
    expect(arealMidpoints(MULTI).filter((m) => m.poly === 1)).toHaveLength(4)
  })

  it('moveArealVertex edits only the addressed part and stays a MultiPolygon', () => {
    const moved = moveArealVertex(MULTI, { poly: 1, index: 0 }, [9, 9]) as MultiPolygon
    expect(moved.type).toBe('MultiPolygon')
    expect(moved.coordinates[0]).toEqual(MULTI.coordinates[0]) // part 0 untouched
    expect(moved.coordinates[1][0][0]).toEqual([9, 9])
    expect(moved.coordinates[1][0][4]).toEqual([9, 9]) // ring re-closed
  })

  it('insert / delete address the right part; delete respects that part’s triangle floor', () => {
    const ins = insertArealVertex(MULTI, { poly: 0, index: 0 }, [0.5, 0]) as MultiPolygon
    expect(arealVertices(ins).filter((v) => v.poly === 0)).toHaveLength(5)

    const del = deleteArealVertex(ins, { poly: 0, index: 1 }) as MultiPolygon
    expect(arealVertices(del).filter((v) => v.poly === 0)).toHaveLength(4)

    // part 1 is a square (4) → one delete OK (→ triangle), a second is refused
    const d1 = deleteArealVertex(MULTI, { poly: 1, index: 0 }) as MultiPolygon
    expect(arealVertices(d1).filter((v) => v.poly === 1)).toHaveLength(3)
    const d2 = deleteArealVertex(d1, { poly: 1, index: 0 })
    expect(arealVertices(d2 as MultiPolygon).filter((v) => v.poly === 1)).toHaveLength(3)
  })

  it('a plain Polygon still round-trips through the areal helpers as a Polygon', () => {
    const moved = moveArealVertex(SQUARE, { poly: 0, index: 1 }, [2, 0])
    expect(moved.type).toBe('Polygon')
    expect((moved as Polygon).coordinates[0][1]).toEqual([2, 0])
  })
})
