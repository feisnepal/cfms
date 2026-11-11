import { describe, it, expect, vi } from 'vitest'
import type { Feature, Geometry, Polygon } from 'geojson'
import {
  geometryToLatLngs,
  captureSnapshot,
  restoreLayerFromSnapshot,
  enableGeometryEdit,
  enableMoveGesture,
  TOPOLOGY_REJECTED,
} from '../geometryEditLifecycle'
import { computeSharedMoves } from '../vertexSharedMove'

const poly: Feature<Polygon> = {
  type: 'Feature',
  properties: { id: 'p1' },
  geometry: {
    type: 'Polygon',
    coordinates: [[
      [10, 20], [11, 20], [11, 21], [10, 21], [10, 20],
    ]],
  },
}

function fakeLayer() {
  const set: unknown[] = []
  const layer = {
    setLatLngs: vi.fn((v: unknown) => { set.push(v) }),
    toGeoJSON: vi.fn(() => poly),
  }
  Object.defineProperty(layer, '__set', { get: () => set[set.length - 1] })
  return layer as any
}

describe('geometryToLatLngs', () => {
  it('converts polygon rings to latlng arrays in lat,lng order', () => {
    const out = geometryToLatLngs(poly.geometry) as any
    expect(out[0][0].lat).toBe(20)
    expect(out[0][0].lng).toBe(10)
  })
  it('handles Point', () => {
    const out = geometryToLatLngs({ type: 'Point', coordinates: [99, 45] }) as any
    expect(out[0].lat).toBe(45)
    expect(out[0].lng).toBe(99)
  })
  it('returns [] for null geometry', () => {
    expect(geometryToLatLngs(null)).toEqual([])
  })
})

describe('restoreLayerFromSnapshot', () => {
  it('calls setLatLngs with snapshot coords', () => {
    const layer = fakeLayer()
    restoreLayerFromSnapshot(layer, poly)
    expect(layer.setLatLngs).toHaveBeenCalled()
    const arg = layer.setLatLngs.mock.calls[0][0] as any
    expect(arg[0][0].lat).toBe(20)
  })
  it('is a no-op for layers without setLatLngs', () => {
    expect(() => restoreLayerFromSnapshot({} as any, poly)).not.toThrow()
  })
})

describe('captureSnapshot', () => {
  it('reads a toGeoJSON()-backed layer', () => {
    const snap = captureSnapshot(fakeLayer())
    expect(snap?.geometry?.type).toBe('Polygon')
  })
  it('returns null when toGeoJSON throws', () => {
    const bad = { toGeoJSON: () => { throw new Error('boom') } }
    expect(captureSnapshot(bad as any)).toBeNull()
  })
})

describe('enableGeometryEdit — add vertex revert (no markerdragstart)', () => {
  // Regression for "added vertex can not be saved": an add has no drag-start,
  // so the snapshot must be captured at *arm* time. A server 409 on the add
  // must revert the layer to the pre-add geometry rather than leaving the new
  // vertex in place (snapshot===null → no revert → vertex appears unsaved).
  function makeFakes(before: Feature, after: Feature) {
    const listeners: Record<string, ((...a: any[]) => void)[]> = {}
    let mode: 'before' | 'after' = 'before'
    const layer: any = {
      on: vi.fn((k: string, fn: any) => { (listeners[k] ||= []).push(fn) }),
      off: vi.fn((k: string, fn: any) => { listeners[k] = (listeners[k] || []).filter((f) => f !== fn) }),
      pm: { enable: vi.fn(), disable: vi.fn(), enabled: vi.fn(() => false) },
      toGeoJSON: vi.fn(() => (mode === 'before' ? before : after)),
      setLatLngs: vi.fn(),
    }
    const map: any = {
      on: vi.fn((k: string, fn: any) => { (listeners[k] ||= []).push(fn) }),
      off: vi.fn((k: string, fn: any) => { listeners[k] = (listeners[k] || []).filter((f) => f !== fn) }),
    }
    const setAfter = () => { mode = 'after' }
    return { layer, map, listeners, setAfter }
  }

  it('reverts an added vertex using the arm-time snapshot on server 409', async () => {
    const before: Feature = { type: 'Feature', properties: { id: 'p1' }, geometry: { type: 'Polygon', coordinates: [[[10, 20], [11, 20], [11, 21], [10, 21], [10, 20]]] } }
    const after: Feature = { type: 'Feature', properties: { id: 'p1' }, geometry: { type: 'Polygon', coordinates: [[[10, 20], [10.5, 20.5], [11, 20], [11, 21], [10, 21], [10, 20]]] } }
    const { layer, map, listeners, setAfter } = makeFakes(before, after)

    const committed = false
    const cleanup = enableGeometryEdit(map, { get: () => layer, has: () => true } as any, 'p1', {
      commit: async () => ({ ok: false, status: 409, code: TOPOLOGY_REJECTED, message: 'nope' }),
      onReject: () => {},
      topology: null,
    })

    // arm-time snapshot must be the pre-add geometry (before)
    expect(layer.toGeoJSON).toHaveBeenCalled()
    // simulate Geoman add-vertex: layer now reports the AFTER geometry, fires pm:vertexadded
    setAfter()
    listeners['pm:vertexadded'].forEach((f) => f())

    // commit is async — flush
    await Promise.resolve()
    await Promise.resolve()

    // rejected add must revert to the pre-add (snapshot) geometry — the added
    // vertex [10.5,20.5] must NOT appear in the reverted latlngs.
    expect(layer.setLatLngs).toHaveBeenCalledTimes(1)
    const reverted = layer.setLatLngs.mock.calls[0][0] as any
    const ring = reverted[0] as any[]
    const pairs: number[][] = ring.map((ll: any) => [ll.lng, ll.lat])
    expect(pairs.some((p) => p[0] === 10.5 && p[1] === 20.5)).toBe(false)
    expect(pairs.some((p) => p[0] === 11 && p[1] === 20)).toBe(true) // pre-add vertex survives
    expect(committed).toBe(false)

    cleanup()
  })
})

describe('enableGeometryEdit — V-3 render-only mask', () => {
  // The mask option must be consulted for every armed layer at arm time and
  // re-applied after Geoman re-creates markers (vertex add/remove).
  function makeMaskFakes() {
    const listeners: Record<string, ((...a: any[]) => void)[]> = {}
    const layer: any = {
      on: vi.fn((k: string, fn: any) => { (listeners[k] ||= []).push(fn) }),
      off: vi.fn((k: string, fn: any) => { listeners[k] = (listeners[k] || []).filter((f) => f !== fn) }),
      pm: { enable: vi.fn(), disable: vi.fn(), enabled: vi.fn(() => false), _markers: [] },
      toGeoJSON: vi.fn(() => poly),
      setLatLngs: vi.fn(),
    }
    const map: any = {
      on: vi.fn((k: string, fn: any) => { (listeners[k] ||= []).push(fn) }),
      off: vi.fn((k: string, fn: any) => { listeners[k] = (listeners[k] || []).filter((f) => f !== fn) }),
    }
    return { layer, map, listeners }
  }

  it('calls mask per armed layer at arm time and again on vertex change', async () => {
    const { layer, map, listeners } = makeMaskFakes()
    const mask = vi.fn((_layer: unknown, _fid: string) => [[10, 20]] as [number, number][])
    const commit = vi.fn(async () => ({ ok: true, status: 200 }))

    enableGeometryEdit(map, { get: () => layer, has: () => true } as any, 'p1', {
      commit,
      onReject: vi.fn(),
      onCommitted: vi.fn(),
      topology: null,
      mask,
    })
    expect(mask).toHaveBeenCalled()
    expect(mask.mock.calls[mask.mock.calls.length - 1][0]).toBe(layer)
    expect(mask.mock.calls[mask.mock.calls.length - 1][1]).toBe('p1')

    listeners['pm:vertexadded'].forEach((f) => f())
    await Promise.resolve()
    expect(mask.mock.calls.length).toBeGreaterThanOrEqual(2)
    expect(commit).toHaveBeenCalledTimes(1)
  })

  it('mask === null leaves markers untouched (no masking)', () => {
    const { layer, map } = makeMaskFakes()
    const mask = vi.fn(() => null)
    enableGeometryEdit(map, { get: () => layer, has: () => true } as any, 'p1', {
      commit: async () => ({ ok: true }),
      onReject: vi.fn(),
      mask,
    })
    expect(mask).toHaveBeenCalled()
  })
})

describe('enableGeometryEdit — V-2 propagation-aware pre-check', () => {
  // A coincident shared-vertex drag must not self-reject: the local R6
  // pre-check runs against the PROPAGATED neighbour set (the neighbours WILL
  // move by the same delta), and the commit receives the shared_moves payload.
  function makeDragFakes(snapshot: Feature, after: Feature) {
    const listeners: Record<string, ((...a: any[]) => void)[]> = {}
    let mode: 'snapshot' | 'after' = 'snapshot'
    const layer: any = {
      on: vi.fn((k: string, fn: any) => { (listeners[k] ||= []).push(fn) }),
      off: vi.fn((k: string, fn: any) => { listeners[k] = (listeners[k] || []).filter((f) => f !== fn) }),
      pm: { enable: vi.fn(), disable: vi.fn(), enabled: vi.fn(() => false) },
      toGeoJSON: vi.fn(() => (mode === 'snapshot' ? snapshot : after)),
      setLatLngs: vi.fn(),
    }
    const map: any = {
      on: vi.fn((k: string, fn: any) => { (listeners[k] ||= []).push(fn) }),
      off: vi.fn((k: string, fn: any) => { listeners[k] = (listeners[k] || []).filter((f) => f !== fn) }),
    }
    const setAfter = () => { mode = 'after' }
    return { layer, map, listeners, setAfter }
  }

  const A_BEFORE: Feature<Polygon> = {
    type: 'Feature', properties: { id: 'a' },
    geometry: { type: 'Polygon', coordinates: [[[83.5, 27.2], [83.5001, 27.2], [83.5001, 27.2001], [83.5, 27.2001], [83.5, 27.2]]] },
  }
  const B_BEFORE: Feature<Polygon> = {
    type: 'Feature', properties: { id: 'b' },
    geometry: { type: 'Polygon', coordinates: [[[83.5001, 27.2], [83.5002, 27.2], [83.5002, 27.2001], [83.5001, 27.2001], [83.5001, 27.2]]] },
  }
  const A_AFTER: Feature<Polygon> = {
    type: 'Feature', properties: { id: 'a' },
    geometry: { type: 'Polygon', coordinates: [[[83.5, 27.2], [83.50012, 27.2], [83.5001, 27.2001], [83.5, 27.2001], [83.5, 27.2]]] },
  }

  it('commits with shared_moves when a coincident shared vertex drags', async () => {
    const { layer, map, listeners, setAfter } = makeDragFakes(A_BEFORE, A_AFTER)
    const commit = vi.fn(async (_f: Feature, _s: Feature, shared?: any) => {
      expect(shared?.moves).toHaveLength(1)
      expect(shared.moves[0].feature_id).toBe('b')
      return { ok: true, status: 200 }
    })

    enableGeometryEdit(map, { get: () => layer, has: () => true } as any, 'a', {
      commit,
      onReject: vi.fn(),
      onCommitted: vi.fn(),
      topology: null,
      sharedMove: (feature: Feature, snapshot: Feature) =>
        computeSharedMoves({
          featureId: 'a',
          snapshot: snapshot.geometry,
          updated: feature.geometry,
          layerFeatures: [A_BEFORE, B_BEFORE],
        }),
    })

    listeners['pm:markerdragstart'].forEach((f) => f())
    setAfter()
    listeners['pm:markerdragend'].forEach((f) => f())
    await Promise.resolve()
    await Promise.resolve()

    expect(commit).toHaveBeenCalledTimes(1)
    const sharedArg = commit.mock.calls[0][2]
    expect(sharedArg?.moves?.length).toBe(1)
  })

  it('passes the propagated pre-check (a naive original-set check would reject)', async () => {
    const { layer, map, listeners, setAfter } = makeDragFakes(A_BEFORE, A_AFTER)
    const commit = vi.fn(async () => ({ ok: true, status: 200 }))

    enableGeometryEdit(map, { get: () => layer, has: () => true } as any, 'a', {
      commit,
      onReject: vi.fn(),
      onCommitted: vi.fn(),
      topology: null,
      sharedMove: () => computeSharedMoves({
        featureId: 'a',
        snapshot: A_BEFORE.geometry,
        updated: A_AFTER.geometry,
        layerFeatures: [A_BEFORE, B_BEFORE],
      }),
    })

    listeners['pm:markerdragstart'].forEach((f) => f())
    setAfter()
    listeners['pm:markerdragend'].forEach((f) => f())
    await Promise.resolve()
    await Promise.resolve()

    // If the pre-check ran against the ORIGINAL B (still at x=10) after A's
    // vertex moved to x=12, it would flag a GAP and reject.  With propagation
    // B is validated at its MOVE position → ok → commit fires.
    expect(commit).toHaveBeenCalledTimes(1)
  })
})

describe('enableGeometryEdit — selectionless multi-layer (V-3)', () => {
  // No manual selection: MapWorkspace builds a layer-scoped registry view and
  // passes scopeIds[0] as the "primary".  Every armed layer gets markers; a
  // drag on ANY layer must commit THAT layer's id + geometry — never the
  // primary's (the old bug: dragging a neighbour/other-layer marker POSTed the
  // selected feature's unchanged geometry → "vertex moved but not saved").
  function makeLayeredFakes() {
    const A: Feature<Polygon> = {
      type: 'Feature', properties: { id: 'a' },
      geometry: { type: 'Polygon', coordinates: [[[10, 20], [11, 20], [11, 21], [10, 21], [10, 20]]] },
    }
    const B: Feature<Polygon> = {
      type: 'Feature', properties: { id: 'b' },
      geometry: { type: 'Polygon', coordinates: [[[12, 20], [13, 20], [13, 21], [12, 21], [12, 20]]] },
    }
    const B_AFTER: Feature<Polygon> = {
      type: 'Feature', properties: { id: 'b' },
      geometry: { type: 'Polygon', coordinates: [[[12.1, 20], [13, 20], [13, 21], [12, 21], [12.1, 20]]] },
    }
    const makeLayer = (initial: Feature) => {
      const listeners: Record<string, Array<() => void>> = {}
      let geom: Feature = initial
      const layer: any = {
        on: (k: string, fn: () => void) => { (listeners[k] ||= []).push(fn) },
        off: (k: string, fn: () => void) => { listeners[k] = (listeners[k] || []).filter((f) => f !== fn) },
        pm: { enable: vi.fn(), disable: vi.fn(), enabled: vi.fn(() => false) },
        toGeoJSON: vi.fn(() => geom),
        setLatLngs: vi.fn(),
      }
      return { layer, listeners, setGeom: (f: Feature) => { geom = f } }
    }
    const a = makeLayer(A)
    const b = makeLayer(B)
    const registry = {
      get: (id: string) => (id === 'a' ? a.layer : id === 'b' ? b.layer : undefined),
      forEach: (cb: (id: string, layer: unknown) => void) => { cb('a', a.layer); cb('b', b.layer) },
    } as any
    const map: any = {
      on: vi.fn((k: string, fn: () => void) => { (a.listeners[k] ||= []).push(fn); (b.listeners[k] ||= []).push(fn) }),
      off: vi.fn(),
    }
    return { a, b, registry, map, B_AFTER }
  }

  it('commits the DRAGGED layer id + geometry when the marker is on a non-primary armed layer', async () => {
    const { a, b, registry, map, B_AFTER } = makeLayeredFakes()
    const commit = vi.fn(async (_f: Feature, _s: Feature, _shared?: unknown, _fid?: string) => ({ ok: true, status: 200 }))

    // primary = 'a' (like scopeIds[0]); the drag happens on 'b'.
    enableGeometryEdit(map, registry, 'a', {
      commit,
      onReject: vi.fn(),
      onCommitted: vi.fn(),
      topology: null,
    })

    // both armed layers must get Geoman enabled + a per-layer commit closure
    expect(a.layer.pm.enable).toHaveBeenCalledTimes(1)
    expect(b.layer.pm.enable).toHaveBeenCalledTimes(1)

    b.setGeom(B_AFTER)
    b.listeners['pm:markerdragstart'].forEach((f) => f())
    b.listeners['pm:markerdragend'].forEach((f) => f())
    await Promise.resolve()
    await Promise.resolve()

    expect(commit).toHaveBeenCalledTimes(1)
    const [feature, , , featureId] = commit.mock.calls[0]
    expect(featureId).toBe('b')
    expect(((feature as unknown) as Feature<Polygon>).geometry.coordinates[0][0]).toEqual([12.1, 20])
  })

  it('vertex add/remove on a non-primary layer commits that layer id too', async () => {
    const { b, registry, map, B_AFTER } = makeLayeredFakes()
    const commit = vi.fn(async (_f: Feature, _s: Feature, _shared?: unknown, _fid?: string) => ({ ok: true, status: 200 }))

    enableGeometryEdit(map, registry, 'a', {
      commit,
      onReject: vi.fn(),
      onCommitted: vi.fn(),
      topology: null,
    })

    b.setGeom(B_AFTER)
    b.listeners['pm:vertexadded'].forEach((f) => f())
    await Promise.resolve()
    await Promise.resolve()

    expect(commit).toHaveBeenCalledTimes(1)
    expect(commit.mock.calls[0][3]).toBe('b')
  })

  it('rejects (reverts) the DRAGGED layer, not the primary', async () => {
    const { b, registry, map } = makeLayeredFakes()
    const commit = vi.fn(async (_f: Feature, _s: Feature, _shared?: unknown, _fid?: string) => ({ ok: false, status: 409, code: TOPOLOGY_REJECTED, message: 'overlap' }))

    enableGeometryEdit(map, registry, 'a', {
      commit,
      onReject: vi.fn(),
      onCommitted: vi.fn(),
      topology: null,
    })

    // simulate a drag on 'b' that the server rejects
    b.listeners['pm:markerdragstart'].forEach((f) => f())
    b.listeners['pm:markerdragend'].forEach((f) => f())
    await Promise.resolve()
    await Promise.resolve()

    // b's layer must be restored (setLatLngs called) and commit called once
    expect(commit).toHaveBeenCalledTimes(1)
    expect(commit.mock.calls[0][3]).toBe('b')
    expect(b.layer.setLatLngs).toHaveBeenCalledTimes(1)
  })
})
describe('enableGeometryEdit — V-4 shared-edge add/delete', () => {
  // A vertex added on / deleted from a SHARED edge must carry the neighbour
  // with it in the same commit; a change that would collapse the neighbour is
  // refused locally (no POST) and the layer reverts.
  function makeFakes(before: Feature, after: Feature) {
    const listeners: Record<string, ((...a: any[]) => void)[]> = {}
    let mode: 'before' | 'after' = 'before'
    const layer: any = {
      on: vi.fn((k: string, fn: any) => { (listeners[k] ||= []).push(fn) }),
      off: vi.fn((k: string, fn: any) => { listeners[k] = (listeners[k] || []).filter((f) => f !== fn) }),
      pm: { enable: vi.fn(), disable: vi.fn(), enabled: vi.fn(() => false) },
      toGeoJSON: vi.fn(() => (mode === 'before' ? before : after)),
      setLatLngs: vi.fn(),
    }
    const map: any = {
      on: vi.fn((k: string, fn: any) => { (listeners[k] ||= []).push(fn) }),
      off: vi.fn((k: string, fn: any) => { listeners[k] = (listeners[k] || []).filter((f) => f !== fn) }),
    }
    return { layer, map, listeners, setAfter: () => { mode = 'after' } }
  }

  const before: Feature = { type: 'Feature', properties: { id: 'a' }, geometry: { type: 'Polygon', coordinates: [[[0, 0], [0.01, 0], [0.01, 0.01], [0, 0.01], [0, 0]]] } }
  const after: Feature = { type: 'Feature', properties: { id: 'a' }, geometry: { type: 'Polygon', coordinates: [[[0, 0], [0.01, 0], [0.01, 0.005], [0.01, 0.01], [0, 0.01], [0, 0]]] } }
  const neighbour: Geometry = { type: 'Polygon', coordinates: [[[0.01, 0], [0.02, 0], [0.02, 0.01], [0.01, 0.01], [0.01, 0.005], [0.01, 0]]] }

  it('commits an added shared vertex together with the neighbour', async () => {
    const { layer, map, listeners, setAfter } = makeFakes(before, after)
    const commit = vi.fn(async (_f: Feature, _s: Feature, _shared?: unknown, _fid?: string) => ({ ok: true, status: 200 }))

    const cleanup = enableGeometryEdit(map, { get: () => layer, has: () => true } as any, 'a', {
      commit,
      onReject: vi.fn(),
      topology: null,
      sharedVertexChange: () => ({
        kind: 'add' as const,
        coord: [0.01, 0.005],
        propagation: {
          moves: [{ feature_id: 'b', geometry: neighbour }],
          propagatedFeatures: [{ id: 'b', geometry: neighbour }],
        },
      }),
    })

    setAfter()
    listeners['pm:vertexadded'].forEach((f) => f())
    await Promise.resolve()
    await Promise.resolve()

    expect(commit).toHaveBeenCalledTimes(1)
    const sharedMove = commit.mock.calls[0][2] as any
    expect(sharedMove?.moves).toHaveLength(1)
    expect(sharedMove.moves[0].feature_id).toBe('b')
    cleanup()
  })

  it('refuses a delete that would collapse the neighbour (no POST, reverts)', async () => {
    const { layer, map, listeners, setAfter } = makeFakes(after, before) // vertex removed
    const commit = vi.fn(async () => ({ ok: true, status: 200 }))
    const onReject = vi.fn()

    const cleanup = enableGeometryEdit(map, { get: () => layer, has: () => true } as any, 'a', {
      commit,
      onReject,
      topology: null,
      sharedVertexChange: () => ({
        kind: 'remove' as const,
        coord: [0.01, 0.005],
        propagation: null,
        blocked: 'DEGENERATE_RING' as const,
      }),
    })

    setAfter()
    listeners['pm:vertexremoved'].forEach((f) => f())
    await Promise.resolve()

    expect(commit).not.toHaveBeenCalled()
    expect(onReject).toHaveBeenCalledWith('VERTEX_CHANGE_BLOCKED', expect.any(String))
    expect(layer.setLatLngs).toHaveBeenCalled() // reverted to the pre-delete shape
    cleanup()
  })
})

describe('tool separation — vertex edits vertices, move moves the body', () => {
  // The two tools must not bleed into each other: the vertex tool used to leave
  // Geoman's `draggable` at its TRUE default (the option is `draggable`, not
  // `drag`) so a body drag was possible but never committed; the move tool used
  // `pm.enable({draggable:true})`, which is Geoman's EDIT mode and renders a
  // marker on every vertex — so move looked like (and acted as) vertex edit.
  function fakeLayer(extraPm: Record<string, unknown> = {}) {
    const listeners: Record<string, ((...a: any[]) => void)[]> = {}
    const layer: any = {
      on: vi.fn((k: string, fn: any) => { (listeners[k] ||= []).push(fn) }),
      off: vi.fn(),
      pm: { enable: vi.fn(), disable: vi.fn(), enabled: vi.fn(() => false), ...extraPm },
      toGeoJSON: vi.fn(() => poly),
      setLatLngs: vi.fn(),
    }
    const map: any = { on: vi.fn(), off: vi.fn() }
    return { layer, map, listeners }
  }

  it('vertex arm disables whole-feature dragging', () => {
    const { layer, map } = fakeLayer()
    const cleanup = enableGeometryEdit(map, { get: () => layer, has: () => true } as any, 'p1', {
      commit: async () => ({ ok: true, status: 200 }),
      onReject: vi.fn(),
      topology: null,
    })
    expect(layer.pm.enable).toHaveBeenCalledWith(expect.objectContaining({ draggable: false }))
    cleanup()
  })

  it('move arm uses drag-only Geoman API (no vertex markers)', () => {
    const enableLayerDrag = vi.fn()
    const disableLayerDrag = vi.fn()
    const { layer, map } = fakeLayer({ enableLayerDrag, disableLayerDrag })
    const cleanup = enableMoveGesture(map, { get: () => layer } as any, 'p1', {
      commit: async () => ({ ok: true, status: 200 }),
      onReject: vi.fn(),
      topology: null,
    })
    expect(enableLayerDrag).toHaveBeenCalledTimes(1)
    expect(layer.pm.enable).not.toHaveBeenCalled() // edit mode never armed
    cleanup()
    expect(disableLayerDrag).toHaveBeenCalled()
  })

  it('move arm falls back to draggable edit mode when layer-drag is unavailable', () => {
    const { layer, map } = fakeLayer()
    const cleanup = enableMoveGesture(map, { get: () => layer } as any, 'p1', {
      commit: async () => ({ ok: true, status: 200 }),
      onReject: vi.fn(),
      topology: null,
    })
    expect(layer.pm.enable).toHaveBeenCalledWith(expect.objectContaining({ draggable: true }))
    cleanup()
  })
})
