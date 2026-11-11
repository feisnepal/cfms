import { describe, it, expect } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useDigitizeSnap, DEFAULT_SNAP_TOLERANCE_M } from '../useDigitizeSnap'

// A north-south line at lng=0, from lat=0 to lat=1 — roughly 111 km long, so a
// point a few metres east of it is a small fraction of a degree away.
const LINE_FEATURE: GeoJSON.Feature = {
  type: 'Feature',
  properties: {},
  geometry: { type: 'LineString', coordinates: [[0, 0], [0, 1]] },
}

// ~0.00003 deg longitude ≈ 3.3 m at the equator.
const NEAR = { lat: 0.5, lng: 0.00003 }
// ~0.0001 deg longitude ≈ 11 m at the equator — inside a generous tolerance,
// outside a tight one.
const MID = { lat: 0.5, lng: 0.0001 }

describe('useDigitizeSnap — configurable tolerance', () => {
  it('defaults to DEFAULT_SNAP_TOLERANCE_M (5 m) when no tolerance is passed', () => {
    const { result } = renderHook(() => useDigitizeSnap())
    const snapped = result.current.snapVertex(NEAR, [LINE_FEATURE])
    expect(snapped.lng).toBeCloseTo(0, 5)
    expect(DEFAULT_SNAP_TOLERANCE_M).toBe(5)
  })

  it('snaps within a wider tolerance', () => {
    const { result } = renderHook(() => useDigitizeSnap(20))
    const snapped = result.current.snapVertex(MID, [LINE_FEATURE])
    expect(snapped.lng).toBeCloseTo(0, 5)
  })

  it('does not snap once the point is farther than the tolerance', () => {
    const { result } = renderHook(() => useDigitizeSnap(1))
    const snapped = result.current.snapVertex(MID, [LINE_FEATURE])
    expect(snapped).toEqual(MID)
  })

  it('snaps against a Polygon neighbour (its boundary), not just a LineString', () => {
    // Regression: turf.nearestPointOnLine silently returns [null, null] for a
    // Polygon geometry rather than throwing — neighbour outlines in the
    // boundary preview ARE Polygons, so this must work.
    const neighbourPolygon: GeoJSON.Feature = {
      type: 'Feature',
      properties: {},
      geometry: { type: 'Polygon', coordinates: [[[0, -1], [0, 2], [1, 2], [1, -1], [0, -1]]] },
    }
    const { result } = renderHook(() => useDigitizeSnap(20))
    const snapped = result.current.snapVertex({ lat: 0.5, lng: -0.0001 }, [neighbourPolygon])
    expect(snapped.lng).toBeCloseTo(0, 4)
    expect(Number.isNaN(snapped.lat)).toBe(false)
  })

  it('a tighter tolerance snaps less eagerly than a looser one for the same point', () => {
    const tight = renderHook(() => useDigitizeSnap(1))
    const loose = renderHook(() => useDigitizeSnap(20))
    const tightResult = tight.result.current.snapVertex(MID, [LINE_FEATURE])
    const looseResult = loose.result.current.snapVertex(MID, [LINE_FEATURE])
    expect(tightResult).toEqual(MID) // untouched
    expect(looseResult.lng).toBeCloseTo(0, 5) // snapped onto the line
  })
})
