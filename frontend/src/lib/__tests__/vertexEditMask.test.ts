import { describe, it, expect, vi } from 'vitest'
import type { Feature, Polygon, MultiPolygon } from 'geojson'
import {
  collectVertexMarkers,
  editableCoordinates,
  firstRingVertex,
  maskVertexMarkers,
  pointInPolygon,
  pointInRing,
  shellGeometryFor,
} from '../vertexEditMask'
import { LAYER_TYPES } from '../vertexClassifier'

function poly(coords: number[][][], id?: string): Feature<Polygon> {
  return { type: 'Feature', properties: { id }, geometry: { type: 'Polygon', coordinates: coords } }
}
function geomOf(coords: number[][][]): Polygon {
  return { type: 'Polygon', coordinates: coords }
}

const BOUNDARY = [[[83.0, 27.0], [84.0, 27.0], [84.0, 28.0], [83.0, 28.0], [83.0, 27.0]]] as number[][][]
const A = [[[83.2, 27.2], [83.5, 27.2], [83.5, 27.8], [83.2, 27.8], [83.2, 27.2]]] as number[][][]
const B = [[[83.5, 27.2], [83.8, 27.2], [83.8, 27.8], [83.5, 27.8], [83.5, 27.2]]] as number[][][]

describe('editableCoordinates', () => {
  it('maps editable flat indices to [lng, lat] coordinates', () => {
    const out = editableCoordinates(geomOf(A), {
      layerType: LAYER_TYPES.blocks,
      sameLevelFeatures: [poly(B, 'b')],
      parentShell: geomOf(BOUNDARY),
    })
    expect(out).toEqual([[83.5, 27.2], [83.5, 27.8]]) // the interior shared edge
  })

  it('boundary (Rule A): every vertex editable when no structure exists', () => {
    expect(editableCoordinates(geomOf(BOUNDARY), { layerType: LAYER_TYPES.boundary })).toHaveLength(4)
  })

  it('returns [] for null geometry', () => {
    expect(editableCoordinates(null, { layerType: LAYER_TYPES.blocks })).toEqual([])
  })
})

describe('shellGeometryFor', () => {
  // Both compartments sit strictly INSIDE the enclosing block.
  const block = [[[83.0, 27.0], [84.0, 27.0], [84.0, 28.0], [83.0, 28.0], [83.0, 27.0]]] as number[][][]
  const c1 = [[[83.2, 27.2], [83.6, 27.2], [83.6, 27.8], [83.2, 27.8], [83.2, 27.2]]] as number[][][]
  const c2 = [[[83.6, 27.2], [84.0, 27.2], [84.0, 27.8], [83.6, 27.8], [83.6, 27.2]]] as number[][][]

  it('finds the coarser feature CONTAINING the edited feature (compartment → block)', () => {
    const shell = shellGeometryFor(
      LAYER_TYPES.compartments,
      'c1',
      [poly(c1, 'c1'), poly(c2, 'c2')] as Feature<Polygon>[],
      [poly(block, 'blockA')] as Feature<Polygon>[],
    )
    expect(shell).toEqual({ type: 'Polygon', coordinates: block })
  })

  it('returns null when no shell level exists (blocks → no boundary)', () => {
    expect(shellGeometryFor(LAYER_TYPES.blocks, 'a', [poly(A, 'a')] as Feature<Polygon>[], [])).toBeNull()
  })

  it('returns null for the boundary layer (no parent)', () => {
    expect(shellGeometryFor(LAYER_TYPES.boundary, 'boundary', [] as Feature<Polygon>[], [] as Feature<Polygon>[])).toBeNull()
  })
})

describe('pointInRing / pointInPolygon', () => {
  it('contains an interior point and excludes exterior points', () => {
    expect(pointInRing(83.4, 27.5, A[0])).toBe(true)
    expect(pointInRing(83.1, 27.5, A[0])).toBe(false)
  })

  it('excludes points inside holes', () => {
    const outer = [[83.0, 27.0], [84.0, 27.0], [84.0, 28.0], [83.0, 28.0], [83.0, 27.0]] as number[][]
    const ringHole = [[83.3, 27.3], [83.7, 27.3], [83.7, 27.7], [83.3, 27.7], [83.3, 27.3]] as number[][]
    const p: Polygon = { type: 'Polygon', coordinates: [outer, ringHole] }
    expect(pointInPolygon(83.5, 27.5, p)).toBe(false) // in the hole
    expect(pointInPolygon(83.1, 27.5, p)).toBe(true) // between hole and outer
  })

  it('handles MultiPolygon (inside any part)', () => {
    const mp: MultiPolygon = {
      type: 'MultiPolygon',
      coordinates: [
        [[[83.0, 27.0], [83.5, 27.0], [83.5, 27.5], [83.0, 27.5], [83.0, 27.0]]],
        [[[83.5, 27.5], [84.0, 27.5], [84.0, 28.0], [83.5, 28.0], [83.5, 27.5]]],
      ],
    }
    expect(pointInPolygon(83.2, 27.2, mp)).toBe(true)
    expect(pointInPolygon(83.9, 27.9, mp)).toBe(true)
    expect(pointInPolygon(84.5, 27.9, mp)).toBe(false)
  })

  it('firstRingVertex returns the exterior anchor', () => {
    expect(firstRingVertex(geomOf(BOUNDARY))).toEqual([83.0, 27.0])
    expect(firstRingVertex({ type: 'LineString', coordinates: [[1, 2], [3, 4]] } as any)).toBeNull()
  })
})

describe('collectVertexMarkers', () => {
  it('flattens Geoman nested marker arrays (incl. closing duplicate)', () => {
    const m0 = { getLatLng: () => ({ lng: 1, lat: 1 }) }
    const markers = collectVertexMarkers([[m0, { getLatLng: () => ({ lng: 2, lat: 2 }) }]])
    expect(markers).toHaveLength(2)
    expect(markers[0]).toBe(m0)
  })

  it('ignores non-marker fragments', () => {
    expect(collectVertexMarkers([[null, 'x', { getLatLng: () => ({}) }]])).toHaveLength(1)
    expect(collectVertexMarkers(undefined)).toEqual([])
  })
})

function fakeIcon() {
  const set = new Set<string>()
  return {
    classList: {
      add: (c: string) => set.add(c),
      remove: (c: string) => set.delete(c),
      toggle: (c: string, on: boolean) => { on ? set.add(c) : set.delete(c) },
      has: (c: string) => set.has(c),
    },
  }
}

function marker(lng: number, lat: number) {
  return {
    getLatLng: () => ({ lng, lat }),
    _icon: fakeIcon(),
    _middleMarkerNext: null as any,
    _middleMarkerPrev: null as any,
    leftM: null as any,
    rightM: null as any,
    setOpacity: vi.fn(),
    dragging: { enabled: () => false, enable: vi.fn(), disable: vi.fn() },
    options: {} as Record<string, unknown>,
  }
}

describe('maskVertexMarkers', () => {
  it('hides locked vertices + edges touching them; keeps editable markers', () => {
    // Square A (closed ring, incl. duplicate): interior shared edge x=83.5.
    const m0 = marker(83.5, 27.2)
    const m1 = marker(83.5, 27.8)
    const m2 = marker(83.2, 27.8)
    const m3 = marker(83.2, 27.2)
    const m4 = marker(83.5, 27.2) // closing duplicate of m0 — same coordinate
    const corner = [m0, m1, m2, m3, m4]
    const edgable = (l: any, r: any) => {
      const mid = marker(0, 0)
      mid.leftM = l; mid.rightM = r
      l._middleMarkerNext = mid
      r._middleMarkerPrev = mid
      return mid
    }
    edgable(m0, m1); edgable(m1, m2); edgable(m2, m3); edgable(m3, m4); edgable(m4, m0)
    const layer: any = { pm: { _markers: [corner] } }

    const editable = [[83.5, 27.2], [83.5, 27.8]] as [number, number][] // shared edge x=83.5
    const { masked, shown } = maskVertexMarkers(layer, editable)

    // Editable corner markers: m0 (83.5,27.2), m1 (83.5,27.8) and the closing
    // dup m4 (same coordinate as m0) stay visible; the x=83.2 unshared edge
    // (m2, m3) is locked and hides.
    expect(masked).toBe(2)
    expect(shown).toBe(3)
    expect(m0.setOpacity).toHaveBeenCalledWith(1)
    expect(m0.options.interactive).toBe(true)
    expect(m2.setOpacity).toHaveBeenCalledWith(0)
    expect(m2.options.interactive).toBe(false)
    expect(m2._icon.classList.has('pm-locked')).toBe(true)
    expect(m2.dragging.disable).toHaveBeenCalled()
    expect(m4.setOpacity).toHaveBeenCalledWith(1)
    expect(m4._icon.classList.has('pm-locked')).toBe(false)
  })

  it('hides middle markers on any edge touching a locked vertex', () => {
    const m0 = marker(83.5, 27.2)
    const m1 = marker(83.5, 27.8)
    const m2 = marker(83.2, 27.8)
    const midA = marker(0, 0)
    midA.leftM = m0; midA.rightM = m1; m0._middleMarkerNext = midA
    const midB = marker(0, 0)
    midB.leftM = m1; midB.rightM = m2; m1._middleMarkerNext = midB
    const layer: any = { pm: { _markers: [[m0, m1, m2]] } }

    maskVertexMarkers(layer, [[83.5, 27.2], [83.5, 27.8]] as [number, number][])
    expect(midA.setOpacity).toHaveBeenCalledWith(1) // between two editable corners
    expect(midB.setOpacity).toHaveBeenCalledWith(0) // touches locked m2
    expect(midB._icon.classList.has('pm-locked')).toBe(true)
  })

  it('no-ops on layers without geoman markers', () => {
    expect(maskVertexMarkers({ pm: { _markers: undefined } } as any, [[1, 2]])).toEqual({ masked: 0, shown: 0 })
    expect(maskVertexMarkers({} as any, [[1, 2]])).toEqual({ masked: 0, shown: 0 })
  })
})

/**
 * VR-0 regression — the precision asymmetry that made the vertex tool render
 * ZERO handles in the browser while every unit test above stayed green.
 *
 * The two sides of the marker↔editable match are produced differently:
 *   - editable coords come from `layer.toGeoJSON()`, and Leaflet's `formatNum`
 *     rounds to 6 decimals;
 *   - marker coords come from `marker.getLatLng()` — the full-precision float.
 *
 * The tests above hand both sides the SAME tidy literals (83.5, 27.2), so they
 * could never observe the mismatch.  These use real captured coordinates from
 * calculation dba70e97 with the rounding applied to one side only.
 */
describe('maskVertexMarkers — Leaflet 6dp rounding asymmetry (VR-0)', () => {
  // Captured live: marker.getLatLng() vs the same vertex via toGeoJSON().
  const RAW: Array<[number, number]> = [
    [85.762339184, 27.413729172],
    [85.762002676, 27.413797105],
    [85.758027435, 27.412533482],
  ]
  const round6 = ([lng, lat]: [number, number]): [number, number] =>
    [Math.round(lng * 1e6) / 1e6, Math.round(lat * 1e6) / 1e6]

  it('shows a marker whose editable coordinate was rounded by toGeoJSON', () => {
    const markers = RAW.map(([lng, lat]) => marker(lng, lat))
    const layer: any = { pm: { _markers: [markers] } }

    // Editable set as the real code produces it: via toGeoJSON → 6 dp.
    const editable = [round6(RAW[0]), round6(RAW[1])]
    const { masked, shown } = maskVertexMarkers(layer, editable)

    expect(shown).toBe(2)   // was 0 before the KEY_ROUND fix
    expect(masked).toBe(1)  // the third vertex is genuinely not editable
    expect(markers[0].setOpacity).toHaveBeenCalledWith(1)
    expect(markers[1].setOpacity).toHaveBeenCalledWith(1)
    expect(markers[2].setOpacity).toHaveBeenCalledWith(0)
    expect(markers[2]._icon.classList.has('pm-locked')).toBe(true)
  })

  it('still distinguishes genuinely different vertices at 6 dp', () => {
    // ~2 m apart in longitude — must NOT collide into one key.
    const a = marker(85.762339184, 27.413729172)
    const b = marker(85.762359184, 27.413729172)
    const layer: any = { pm: { _markers: [[a, b]] } }

    const { masked, shown } = maskVertexMarkers(layer, [round6([85.762339184, 27.413729172])])
    expect(shown).toBe(1)
    expect(masked).toBe(1)
    expect(b._icon.classList.has('pm-locked')).toBe(true)
  })
})


/**
 * VR-5 — shared-edge midpoint rule.
 *
 * A midpoint used to appear only when BOTH its corners were editable.  On an
 * auto-divided layer that means never: an equal-area division cuts with
 * STRAIGHT segments, so every child vertex is a cut endpoint lying on the
 * parent shell, every corner is locked, and the layer offers no handle at all
 * (measured on बृन्दाबन — shell == vertexCount for all 8 compartments).
 *
 * The interior of a shared edge is not on the shell, so subdividing it moves
 * no locked vertex and the inserted vertex is shared-and-not-shell — i.e.
 * immediately editable.
 */
describe('maskVertexMarkers — shared-edge midpoint rule (VR-5)', () => {
  function edgeWithMidpoint(aLng: number, aLat: number, bLng: number, bLat: number) {
    const a = marker(aLng, aLat)
    const b = marker(bLng, bLat)
    const mid = marker((aLng + bLng) / 2, (aLat + bLat) / 2)
    mid.leftM = a
    mid.rightM = b
    a._middleMarkerNext = mid
    b._middleMarkerPrev = mid
    return { a, b, mid, layer: { pm: { _markers: [[a, b]] } } as any }
  }

  it('shows the midpoint of a shared edge even when BOTH corners are locked', () => {
    const { a, b, mid, layer } = edgeWithMidpoint(85.7620, 27.4137, 85.7620, 27.4145)
    // No editable corners at all — the auto-divide situation.
    maskVertexMarkers(layer, [], () => true)

    expect(a._icon.classList.has('pm-locked')).toBe(true)
    expect(b._icon.classList.has('pm-locked')).toBe(true)
    expect(mid._icon.classList.has('pm-locked')).toBe(false) // the escape hatch
    expect(mid.setOpacity).toHaveBeenCalledWith(1)
  })

  it('keeps the midpoint hidden when the edge is not insertable', () => {
    const { mid, layer } = edgeWithMidpoint(85.7620, 27.4137, 85.7620, 27.4145)
    maskVertexMarkers(layer, [], () => false)
    expect(mid._icon.classList.has('pm-locked')).toBe(true)
  })

  it('still shows a midpoint between two editable corners without any predicate', () => {
    const { mid, layer } = edgeWithMidpoint(85.7620, 27.4137, 85.7620, 27.4145)
    maskVertexMarkers(layer, [[85.7620, 27.4137], [85.7620, 27.4145]])
    expect(mid._icon.classList.has('pm-locked')).toBe(false)
  })

  it('the predicate never overrides a corner marker, only midpoints', () => {
    const { a, b, layer } = edgeWithMidpoint(85.7620, 27.4137, 85.7620, 27.4145)
    maskVertexMarkers(layer, [], () => true)
    expect(a._icon.classList.has('pm-locked')).toBe(true)
    expect(b._icon.classList.has('pm-locked')).toBe(true)
  })
})

describe('SL-5: an undivided top-level unit shown in a sub layer', () => {
  // The Sub-compartment layer lists every undivided unit, so C-2 (depth 1, no
  // parent) sits beside the children of divided C-1. C-2 has no parent id, so the
  // containment fallback finds ITSELF in the compartments layer as its shell and
  // every vertex is locked (the backend does the same: resolve_parent_shell).
  // Intended: boundaries of top-level units are moved in the Compartments layer,
  // where the neighbour set is complete.
  const C1 = [[[83.2, 27.2], [83.5, 27.2], [83.5, 27.8], [83.2, 27.8], [83.2, 27.2]]] as number[][][]
  const C2 = [[[83.5, 27.2], [83.8, 27.2], [83.8, 27.8], [83.5, 27.8], [83.5, 27.2]]] as number[][][]
  const compartments = [poly(C1, 'c1'), poly(C2, 'c2')]
  const c2InSubLayer = { ...poly(C2, 'c2'), properties: { id: 'c2', division_level: 1, parent_block_id: null } } as Feature<Polygon>

  it('uses the unit itself as its shell', () => {
    const shell = shellGeometryFor(LAYER_TYPES.subCompartments, 'c2', [c2InSubLayer], compartments)
    expect(shell).toEqual(geomOf(C2))
  })

  it('so no vertex is editable, even one shared with a neighbour', () => {
    const shell = shellGeometryFor(LAYER_TYPES.subCompartments, 'c2', [c2InSubLayer], compartments)
    const out = editableCoordinates(geomOf(C2), {
      layerType: LAYER_TYPES.subCompartments,
      sameLevelFeatures: [poly(C1, 'c1')],
      parentShell: shell,
    })
    expect(out).toEqual([])
  })
})
