import { describe, it, expect, beforeEach, vi } from 'vitest'
import { useWorkspaceStore } from '../workspaceStore'
import { LAYER_ORDER, LAYER_DEFAULT_VISIBILITY, resolveLayerOrder } from '../../lib/layerRegistry'
import { defaultComposition } from '../../lib/mapComposition'

describe('workspaceStore shell-state (U01)', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
    // Reset only the shell fields under test (avoid reset() which swaps real actions for stubs).
    useWorkspaceStore.setState({
      selectedFeatureId: null,
      geometryVersion: 0,
      dirty: false,
      uiMode: 'advanced',
      userRoles: [],
      syncStatus: 'synced',
      syncConflict: 'none',
      serverGeometryVersion: 0,
      mapCompositions: [],
      activeCompositionId: null,
      selection: { layerId: null, featureIds: [], mode: 'replace' },
      activeLayerId: null,
      layerLocks: {},
      calculationId: null,
      importedLayers: [],
      importedLayerFeatures: {},
      importedFeatureVersion: {},
      layerLoadKeys: {},
      lastRefreshErrors: {},
    })
  })

  it('has correct shell defaults, including syncConflict:none', () => {
    const s = useWorkspaceStore.getState()
    expect(s.selectedFeatureId).toBeNull()
    expect(s.geometryVersion).toBe(0)
    expect(s.dirty).toBe(false)
    expect(s.uiMode).toBe('advanced')
    expect(s.userRoles).toEqual([])
    expect(s.syncStatus).toBe('synced')
    expect(s.syncConflict).toBe('none')
    expect(s.serverGeometryVersion).toBe(0)
    expect(s.mapCompositions).toEqual([])
    expect(s.activeCompositionId).toBeNull()
  })

  it('persists uiMode across a store instance (localStorage, partialize)', () => {
    const s = useWorkspaceStore.getState()
    s.setUiMode('simple')
    expect(useWorkspaceStore.getState().uiMode).toBe('simple')
    const persisted = localStorage.getItem('workspace-store')
    expect(persisted).toBeTruthy()
    const parsed = JSON.parse(persisted!)
    expect(parsed.state.uiMode).toBe('simple')
  })

  it('bumpGeometryVersion increments the clock and clears a stale conflict', () => {
    const s = useWorkspaceStore.getState()
    s.bumpGeometryVersion()
    expect(useWorkspaceStore.getState().geometryVersion).toBe(1)
    // raise a conflict then bump → conflict cleared
    useWorkspaceStore.setState({ syncConflict: 'stale_server' })
    s.bumpGeometryVersion()
    expect(useWorkspaceStore.getState().syncConflict).toBe('none')
    expect(useWorkspaceStore.getState().geometryVersion).toBe(2)
  })

  it('reconcileVersion no-ops when server <= local', () => {
    const s = useWorkspaceStore.getState()
    const r0 = s.reconcileVersion(0)
    expect(r0.rejected).toBe(false)
    s.bumpGeometryVersion() // local = 1
    const r1 = useWorkspaceStore.getState().reconcileVersion(1)
    expect(r1.rejected).toBe(false)
    expect(useWorkspaceStore.getState().geometryVersion).toBe(1)
    expect(useWorkspaceStore.getState().syncConflict).toBe('none')
  })

  it('reconcileVersion absorbs a server bump when clean (no UI flag)', () => {
    const s = useWorkspaceStore.getState() // dirty=false, local=0
    const r = s.reconcileVersion(3)
    expect(r.rejected).toBe(false)
    expect(useWorkspaceStore.getState().geometryVersion).toBe(3)
    expect(useWorkspaceStore.getState().serverGeometryVersion).toBe(3)
    expect(useWorkspaceStore.getState().syncConflict).toBe('none')
  })

  it('reconcileVersion flags stale_server (never auto-merges) when dirty', () => {
    const s = useWorkspaceStore.getState()
    s.setDirty(true)
    const r = useWorkspaceStore.getState().reconcileVersion(5)
    expect(r.rejected).toBe(true)
    expect(useWorkspaceStore.getState().syncConflict).toBe('stale_server')
    // local geometryVersion must NOT absorb the server value
    expect(useWorkspaceStore.getState().geometryVersion).toBe(0)
    expect(useWorkspaceStore.getState().serverGeometryVersion).toBe(5)
  })

  it('selectFeatureGlobal sets SSOT and syncs the derived selection projection', () => {
    const s = useWorkspaceStore.getState()
    s.setActiveLayer('blocks')
    s.selectFeatureGlobal('f1')
    const after = useWorkspaceStore.getState()
    expect(after.selectedFeatureId).toBe('f1')
    expect(after.selection.layerId).toBe('blocks')
    expect(after.selection.featureIds).toEqual(['f1'])
    // selecting null clears both
    after.selectFeatureGlobal(null)
    expect(useWorkspaceStore.getState().selectedFeatureId).toBeNull()
    expect(useWorkspaceStore.getState().selection.featureIds).toEqual([])
  })

  it('selectFeatureGlobal is a guarded same-id no-op', () => {
    const s = useWorkspaceStore.getState()
    s.selectFeatureGlobal('f1')
    const before = useWorkspaceStore.getState().selection
    s.selectFeatureGlobal('f1') // same id → no re-set
    expect(useWorkspaceStore.getState().selection).toBe(before)
  })

  it('selectFeatureGlobal is a guarded same-id no-op', () => {
    const s = useWorkspaceStore.getState()
    s.selectFeatureGlobal('f1')
    const before = useWorkspaceStore.getState().selection
    s.selectFeatureGlobal('f1') // same id → no re-set
    expect(useWorkspaceStore.getState().selection).toBe(before)
  })

  // U10 — next/prev feature navigation (wrap-around in survey order)
  describe('U10 selectNextFeature / selectPreviousFeature', () => {
    it('selectNextFeature wraps to first after last', () => {
      const s = useWorkspaceStore.getState()
      // Mock imported layer with 3 features in survey order
      s.setImportedLayerFeatures(1, [
        { type: 'Feature', id: 'f1', properties: { featureId: 'f1' }, geometry: { type: 'Point', coordinates: [0, 0] } },
        { type: 'Feature', id: 'f2', properties: { featureId: 'f2' }, geometry: { type: 'Point', coordinates: [1, 1] } },
        { type: 'Feature', id: 'f3', properties: { featureId: 'f3' }, geometry: { type: 'Point', coordinates: [2, 2] } },
      ])
      s.setActiveImportedLayer(1)
      s.selectFeatureGlobal('f1')
      s.selectNextFeature()
      expect(useWorkspaceStore.getState().selectedFeatureId).toBe('f2')
      s.selectNextFeature()
      expect(useWorkspaceStore.getState().selectedFeatureId).toBe('f3')
      s.selectNextFeature() // wrap to first
      expect(useWorkspaceStore.getState().selectedFeatureId).toBe('f1')
    })

    it('selectPreviousFeature wraps to last after first', () => {
      const s = useWorkspaceStore.getState()
      s.setImportedLayerFeatures(2, [
        { type: 'Feature', id: 'f1', properties: { featureId: 'f1' }, geometry: { type: 'Point', coordinates: [0, 0] } },
        { type: 'Feature', id: 'f2', properties: { featureId: 'f2' }, geometry: { type: 'Point', coordinates: [1, 1] } },
        { type: 'Feature', id: 'f3', properties: { featureId: 'f3' }, geometry: { type: 'Point', coordinates: [2, 2] } },
      ])
      s.setActiveImportedLayer(2)
      s.selectFeatureGlobal('f1')
      s.selectPreviousFeature() // wrap to last
      expect(useWorkspaceStore.getState().selectedFeatureId).toBe('f3')
      s.selectPreviousFeature()
      expect(useWorkspaceStore.getState().selectedFeatureId).toBe('f2')
      s.selectPreviousFeature()
      expect(useWorkspaceStore.getState().selectedFeatureId).toBe('f1')
    })

    it('no-op when only one feature', () => {
      const s = useWorkspaceStore.getState()
      s.setImportedLayerFeatures(3, [
        { type: 'Feature', id: 'f1', properties: { featureId: 'f1' }, geometry: { type: 'Point', coordinates: [0, 0] } },
      ])
      s.setActiveImportedLayer(3)
      s.selectFeatureGlobal('f1')
      s.selectNextFeature()
      expect(useWorkspaceStore.getState().selectedFeatureId).toBe('f1')
      s.selectPreviousFeature()
      expect(useWorkspaceStore.getState().selectedFeatureId).toBe('f1')
    })

    it('no-op when no active layer or no selection', () => {
      const s = useWorkspaceStore.getState()
      s.selectNextFeature()
      s.selectPreviousFeature()
      expect(useWorkspaceStore.getState().selectedFeatureId).toBeNull()
    })
  })

  describe('per-layer manual lock (UI-only)', () => {
    it('defaults unlocked for every layer', () => {
      const s = useWorkspaceStore.getState()
      expect(s.layerLocks.boundary).toBeUndefined()
      expect(s.layerLocks.blocks).toBeUndefined()
    })

    it('toggleLayerLock flips a layer lock on and off', () => {
      const s = useWorkspaceStore.getState()
      s.toggleLayerLock('boundary')
      expect(useWorkspaceStore.getState().layerLocks.boundary).toBe(true)
      s.toggleLayerLock('boundary')
      expect(useWorkspaceStore.getState().layerLocks.boundary).toBe(false)
    })

    it('setLayerLock writes an explicit value and preserves sibling layers', () => {
      const s = useWorkspaceStore.getState()
      s.setLayerLock('blocks', true)
      s.setLayerLock('boundary', true)
      s.setLayerLock('blocks', false)
      const locks = useWorkspaceStore.getState().layerLocks
      expect(locks.boundary).toBe(true)
      expect(locks.blocks).toBe(false)
      expect(locks.sub_areas).toBeUndefined()
    })

    it('imported layers lock under their prefixed key', () => {
      const s = useWorkspaceStore.getState()
      s.setLayerLock('imported:7', true)
      expect(useWorkspaceStore.getState().layerLocks['imported:7']).toBe(true)
      expect(useWorkspaceStore.getState().layerLocks.boundary).toBeUndefined()
    })
  })

  describe('noteLayerLoaded (P1 layer load clock)', () => {
    it('increments per layer and preserves sibling counters', () => {
      const s = useWorkspaceStore.getState()
      s.noteLayerLoaded('compartments')
      s.noteLayerLoaded('compartments')
      s.noteLayerLoaded('blocks')
      const keys = useWorkspaceStore.getState().layerLoadKeys
      expect(keys['compartments']).toBe(2)
      expect(keys['blocks']).toBe(1)
      expect(keys['sub_areas']).toBeUndefined()
    })
  })

  describe('refreshAll (P1 unified refresh)', () => {
    const importLayer7 = {
      id: 7, name: 'L', purpose: 'boundary', format: 'geojson', featureCount: 1,
      geometryTypes: ['Polygon'], visible: true, order: 0,
    }
    const feature7 = {
      type: 'Feature', id: 'f7',
      geometry: { type: 'Point', coordinates: [0, 0] },
      properties: {},
    }

    afterEach(() => {
      vi.unstubAllGlobals()
    })

    it('debounces a second call while syncing (no double bump, no fetch)', async () => {
      const s = useWorkspaceStore.getState()
      useWorkspaceStore.setState({
        syncStatus: 'syncing',
        calculationId: 'calc-1',
        importedLayers: [importLayer7 as any],
      })
      const fetchMock = vi.fn()
      vi.stubGlobal('fetch', fetchMock)
      await s.refreshAll()
      expect(useWorkspaceStore.getState().geometryVersion).toBe(0)
      expect(fetchMock).not.toHaveBeenCalled()
    })

    it('no-ops without a calculationId', async () => {
      const s = useWorkspaceStore.getState()
      await s.refreshAll()
      expect(useWorkspaceStore.getState().geometryVersion).toBe(0)
      expect(useWorkspaceStore.getState().syncStatus).toBe('synced')
    })

    it('bumps geometryVersion once and reaches synced (no imported layers)', async () => {
      const s = useWorkspaceStore.getState()
      useWorkspaceStore.setState({ calculationId: 'calc-1', importedLayers: [] })
      await s.refreshAll()
      const after = useWorkspaceStore.getState()
      expect(after.geometryVersion).toBe(1)
      expect(after.syncStatus).toBe('synced')
      expect(after.lastRefreshErrors).toEqual({})
    })

    it('re-pulls imported features into importedLayerFeatures and bumps both clocks', async () => {
      const s = useWorkspaceStore.getState()
      useWorkspaceStore.setState({
        calculationId: 'calc-1',
        importedLayers: [importLayer7 as any],
      })
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ type: 'FeatureCollection', features: [feature7] }),
      })
      vi.stubGlobal('fetch', fetchMock)
      await s.refreshAll()
      expect(fetchMock).toHaveBeenCalledTimes(1)
      const calledUrl = String(fetchMock.mock.calls[0][0])
      expect(calledUrl).toContain('/api/v1/workspace/calc-1/import-layers/7/features')
      const after = useWorkspaceStore.getState()
      expect(after.importedLayerFeatures[7]).toHaveLength(1)
      expect(after.importedFeatureVersion[7]).toBe(1)
      expect(after.geometryVersion).toBe(1)
      expect(after.syncStatus).toBe('synced')
      expect(after.lastRefreshErrors).toEqual({})
    })

    it('records a partial failure in lastRefreshErrors but still bumps', async () => {
      const s = useWorkspaceStore.getState()
      useWorkspaceStore.setState({
        calculationId: 'calc-1',
        importedLayers: [importLayer7 as any],
      })
      vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('boom')))
      await s.refreshAll()
      const after = useWorkspaceStore.getState()
      expect(after.geometryVersion).toBe(1)
      expect(after.syncStatus).toBe('synced')
      expect(after.lastRefreshErrors['imported:7']).toBeTruthy()
    })
  })
})

describe('layerAlpha + hiddenFeatureIds are per-calculation (styling-plan polish)', () => {
  beforeEach(() => {
    localStorage.clear()
    useWorkspaceStore.setState({ layerAlpha: {}, hiddenFeatureIds: {}, calculationId: 'calc-A' })
  })

  it('setLayerAlpha keys by <calcId>::<layerId>', () => {
    useWorkspaceStore.getState().setLayerAlpha('blocks', 0.5)
    expect(useWorkspaceStore.getState().layerAlpha).toEqual({ 'calc-A::blocks': 0.5 })
  })

  it('toggleFeatureHidden / clearHiddenFeatures key by <calcId>::<layerId>; a second calc is untouched', () => {
    const s = useWorkspaceStore.getState()
    s.toggleFeatureHidden('sub_areas', 'sa-1')
    s.toggleFeatureHidden('sub_areas', 'sa-2')
    expect(useWorkspaceStore.getState().hiddenFeatureIds['calc-A::sub_areas']).toEqual(['sa-1', 'sa-2'])

    useWorkspaceStore.setState({ calculationId: 'calc-B' })
    expect(useWorkspaceStore.getState().hiddenFeatureIds['calc-B::sub_areas']).toBeUndefined()

    useWorkspaceStore.setState({ calculationId: 'calc-A' })
    useWorkspaceStore.getState().toggleFeatureHidden('sub_areas', 'sa-1') // un-hide
    expect(useWorkspaceStore.getState().hiddenFeatureIds['calc-A::sub_areas']).toEqual(['sa-2'])
    useWorkspaceStore.getState().clearHiddenFeatures('sub_areas')
    expect(useWorkspaceStore.getState().hiddenFeatureIds['calc-A::sub_areas']).toBeUndefined()
  })

  it('both slices are in the persisted partition', () => {
    useWorkspaceStore.getState().setLayerAlpha('blocks', 0.3)
    useWorkspaceStore.getState().toggleFeatureHidden('blocks', 'b9')
    const raw = JSON.parse(localStorage.getItem('workspace-store') || '{}')
    expect(raw.state.layerAlpha).toEqual({ 'calc-A::blocks': 0.3 })
    expect(raw.state.hiddenFeatureIds).toEqual({ 'calc-A::blocks': ['b9'] })
  })
})

describe('toggleLayerVisibility — "visible unless explicitly false"', () => {
  beforeEach(() => {
    useWorkspaceStore.setState({ layerVisibility: {} })
  })

  it('hides a layer that was never seeded in initialLayerVisibility in ONE click', () => {
    // stem_mapping / compartments / sample_plots start `undefined` (not `true`).
    // The old `!undefined === true` meant the first click set `true` (still
    // shown) — you had to click twice to hide it.
    expect(useWorkspaceStore.getState().layerVisibility.stem_mapping).toBeUndefined()

    useWorkspaceStore.getState().toggleLayerVisibility('stem_mapping')
    expect(useWorkspaceStore.getState().layerVisibility.stem_mapping).toBe(false)

    useWorkspaceStore.getState().toggleLayerVisibility('stem_mapping')
    expect(useWorkspaceStore.getState().layerVisibility.stem_mapping).toBe(true)
  })

  it('still flips a seeded (true) layer to false and back', () => {
    useWorkspaceStore.setState({ layerVisibility: { boundary: true } })
    useWorkspaceStore.getState().toggleLayerVisibility('boundary')
    expect(useWorkspaceStore.getState().layerVisibility.boundary).toBe(false)
    useWorkspaceStore.getState().toggleLayerVisibility('boundary')
    expect(useWorkspaceStore.getState().layerVisibility.boundary).toBe(true)
  })
})

describe('layer order and defaults come from the registry (owner 2026-09-29)', () => {
  beforeEach(() => {
    // NOT `setState(createInitialState())`: that object carries the no-op action
    // placeholders from the state factory, and merging it in would replace the
    // store's real `moveLayerUp` / `hideAllLayers` / `setActiveLayer` with
    // `() => {}` — the calls would silently do nothing and the test would pass
    // for the wrong reason. Reset only the two data slices.
    useWorkspaceStore.setState({
      layerOrder: { ...LAYER_ORDER },
      layerVisibility: { ...LAYER_DEFAULT_VISIBILITY },
    })
  })

  const sortedIds = () => {
    const { layerOrder } = useWorkspaceStore.getState()
    return Object.keys(LAYER_ORDER).sort(
      (a, b) => resolveLayerOrder(layerOrder, a) - resolveLayerOrder(layerOrder, b),
    )
  }

  it('a fresh store seeds every built-in layer, so nothing ties at order 0', () => {
    const { layerOrder, layerVisibility } = useWorkspaceStore.getState()
    expect(Object.keys(layerOrder).sort()).toEqual(Object.keys(LAYER_ORDER).sort())
    expect(Object.keys(layerVisibility).sort()).toEqual(Object.keys(LAYER_ORDER).sort())
  })

  it('renders in the owner\'s expected order', () => {
    expect(sortedIds()).toEqual([
      'boundary',
      'user_group',
      'blocks',
      'sub_blocks',
      'compartments',
      'sub_compartments',
      'sub_areas',
      'sample_plots',
      'stem_mapping',
      'activity_features',
      'fieldbook',
    ])
  })

  it("carries the owner's expected default show/hide", () => {
    const { layerVisibility } = useWorkspaceStore.getState()
    expect(layerVisibility).toMatchObject({
      boundary: true,
      user_group: false,
      blocks: true,
      sub_blocks: true,
      compartments: true,
      sub_compartments: true,
      sub_areas: false,
      sample_plots: true,
      stem_mapping: false,
      activity_features: false,
      fieldbook: false,
    })
  })

  it('show all / hide all now reach every built-in, not just the seeded few', () => {
    useWorkspaceStore.getState().hideAllLayers()
    expect(Object.values(useWorkspaceStore.getState().layerVisibility).every((v) => v === false)).toBe(true)
    useWorkspaceStore.getState().showAllLayers()
    expect(Object.values(useWorkspaceStore.getState().layerVisibility).every((v) => v === true)).toBe(true)
  })

  it('moveLayerUp swaps with the layer immediately above it', () => {
    // Field Book is last; moving it up puts it directly above Stem Mapping.
    useWorkspaceStore.getState().moveLayerUp('fieldbook')
    const ids = sortedIds()
    expect(ids.indexOf('fieldbook')).toBe(ids.indexOf('stem_mapping') + 1)
  })

  it('moveLayerDown swaps with the layer immediately below it', () => {
    // Blocks sits third; moving it down puts it directly below Sub-Blocks.
    useWorkspaceStore.getState().moveLayerDown('blocks')
    const ids = sortedIds()
    expect(ids.indexOf('blocks')).toBe(ids.indexOf('sub_blocks') + 1)
  })

  it('moveLayerUp on the top layer is a no-op', () => {
    const before = sortedIds()
    useWorkspaceStore.getState().moveLayerUp('boundary')
    expect(sortedIds()).toEqual(before)
  })

  it('activating a hidden layer reveals it (so drawing into it is not blind)', () => {
    expect(useWorkspaceStore.getState().layerVisibility.activity_features).toBe(false)
    useWorkspaceStore.getState().setActiveLayer('activity_features')
    expect(useWorkspaceStore.getState().layerVisibility.activity_features).toBe(true)
  })

  it('activating a visible layer does not change its visibility', () => {
    useWorkspaceStore.getState().setActiveLayer('boundary')
    expect(useWorkspaceStore.getState().layerVisibility.boundary).toBe(true)
  })
})