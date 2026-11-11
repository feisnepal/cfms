import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { useWorkspaceStore, createInitialState } from '../workspaceStore'
import type { GeoJSON } from 'geojson'

const pointFeature: GeoJSON.Feature = {
  type: 'Feature',
  geometry: { type: 'Point', coordinates: [85.5, 27.5] },
  properties: { featureId: 'f1', name: 'Point 1' },
}

const polygonFeature: GeoJSON.Feature = {
  type: 'Feature',
  geometry: {
    type: 'Polygon',
    coordinates: [[[85.0, 27.0], [85.1, 27.0], [85.1, 27.1], [85.0, 27.1], [85.0, 27.0]]],
  },
  properties: { featureId: 'f2' },
}

function mockFetchOnce(body: unknown, init?: { ok?: boolean; status?: number }) {
  const res = {
    ok: init?.ok ?? true,
    status: init?.status ?? 200,
    json: () => Promise.resolve(body),
  }
  return vi.fn().mockResolvedValue(res)
}

describe('workspaceStore digitize (GD 1.3.1)', () => {
  const originalFetch = globalThis.fetch

  const realActions = {
    addImportedLayer: useWorkspaceStore.getState().addImportedLayer,
    setActiveDigitizeContext: useWorkspaceStore.getState().setActiveDigitizeContext,
    enqueueDigitizeFeature: useWorkspaceStore.getState().enqueueDigitizeFeature,
    removeDigitizeFeature: useWorkspaceStore.getState().removeDigitizeFeature,
    setDigitizeSyncState: useWorkspaceStore.getState().setDigitizeSyncState,
    createDigitizeLayer: useWorkspaceStore.getState().createDigitizeLayer,
    finalizeDigitizeLayer: useWorkspaceStore.getState().finalizeDigitizeLayer,
    discardDigitizeLayer: useWorkspaceStore.getState().discardDigitizeLayer,
    setCalculationId: useWorkspaceStore.getState().setCalculationId,
  }

  function resetStore() {
    useWorkspaceStore.setState({
      ...createInitialState(),
      ...realActions,
    })
  }

  beforeEach(() => {
    resetStore()
  })

  afterEach(() => {
    globalThis.fetch = originalFetch
    vi.restoreAllMocks()
  })

  describe('createDigitizeLayer', () => {
    it('calls POST digitize-layers and adds an isDraft imported layer', async () => {
      const fetchMock = mockFetchOnce({
        id: 42,
        name: 'Inventory Draft',
        purpose: 'inventory',
        draft_status: 'active',
        feature_count: 0,
        geometry_types: ['Point'],
        is_draft: true,
      })
      globalThis.fetch = fetchMock as unknown as typeof fetch

      const layer = await useWorkspaceStore.getState().createDigitizeLayer(
        'calc-1',
        'inventory',
        'Inventory Draft',
      )

      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/api/v1/workspace/calc-1/digitize-layers'),
        expect.objectContaining({ method: 'POST' }),
      )
      expect(fetchMock.mock.calls[0][1].body).toBe(
        JSON.stringify({ purpose: 'inventory', name: 'Inventory Draft' }),
      )
      expect(layer.isDraft).toBe(true)
      expect(layer.draftStatus).toBe('active')

      const layers = useWorkspaceStore.getState().importedLayers
      expect(layers).toHaveLength(1)
      expect(layers[0]).toMatchObject({
        id: 42,
        name: 'Inventory Draft',
        purpose: 'inventory',
        format: 'digitize',
        isDraft: true,
        draftStatus: 'active',
      })
    })

    it('throws and does not add a layer on non-ok response', async () => {
      const fetchMock = mockFetchOnce(
        { detail: 'Unknown purpose: bogus' },
        { ok: false, status: 400 },
      )
      globalThis.fetch = fetchMock as unknown as typeof fetch

      await expect(
        useWorkspaceStore.getState().createDigitizeLayer('calc-1', 'bogus', 'Bad'),
      ).rejects.toThrow('Unknown purpose: bogus')

      expect(useWorkspaceStore.getState().importedLayers).toHaveLength(0)
    })
  })

  describe('digitizeDraftFeatures buffer', () => {
    it('enqueueDigitizeFeature appends to the layer buffer', () => {
      useWorkspaceStore.getState().enqueueDigitizeFeature(10, pointFeature)
      useWorkspaceStore.getState().enqueueDigitizeFeature(10, polygonFeature)

      const buffered = useWorkspaceStore.getState().digitizeDraftFeatures[10]
      expect(buffered).toHaveLength(2)
      expect(buffered[0].properties?.featureId).toBe('f1')
      expect(buffered[1].properties?.featureId).toBe('f2')
    })

    it('enqueueDigitizeFeature seeds purpose defaults (GD 2.2.5)', () => {
      useWorkspaceStore.getState().addImportedLayer({
        id: 10,
        name: 'Tree Points',
        purpose: 'inventory',
        format: 'digitize',
        featureCount: 0,
        geometryTypes: ['Point'],
        visible: true,
        order: 0,
        isDraft: true,
        draftStatus: 'active',
      })
      useWorkspaceStore.getState().enqueueDigitizeFeature(10, pointFeature)

      const buffered = useWorkspaceStore.getState().digitizeDraftFeatures[10]
      expect(buffered[0].properties).toMatchObject({
        species: '',
        dbh: 0,
        height: 0,
        gps_type: 'manual',
        featureId: 'f1',
      })
    })

    it('enqueueDigitizeFeature keeps feature-provided values over defaults', () => {
      useWorkspaceStore.getState().addImportedLayer({
        id: 11,
        name: 'Water',
        purpose: 'water',
        format: 'digitize',
        featureCount: 0,
        geometryTypes: ['LineString'],
        visible: true,
        order: 0,
        isDraft: true,
        draftStatus: 'active',
      })
      const f: GeoJSON.Feature = {
        ...pointFeature,
        properties: { type: 'river', featureId: 'w1' },
      }
      useWorkspaceStore.getState().enqueueDigitizeFeature(11, f)

      const buffered = useWorkspaceStore.getState().digitizeDraftFeatures[11]
      expect(buffered[0].properties?.type).toBe('river')
    })

    it('removeDigitizeFeature removes by featureId', () => {
      const s = useWorkspaceStore.getState()
      s.enqueueDigitizeFeature(10, pointFeature)
      s.enqueueDigitizeFeature(10, polygonFeature)

      s.removeDigitizeFeature(10, 'f2')

      const buffered = useWorkspaceStore.getState().digitizeDraftFeatures[10]
      expect(buffered).toHaveLength(1)
      expect(buffered[0].properties?.featureId).toBe('f1')
    })

    it('removeDigitizeFeature falls back to the top-level id', () => {
      const feature = {
        ...pointFeature,
        id: 'geo-1',
        properties: {},
      } as GeoJSON.Feature
      useWorkspaceStore.getState().enqueueDigitizeFeature(10, feature)

      useWorkspaceStore.getState().removeDigitizeFeature(10, 'geo-1')
      expect(useWorkspaceStore.getState().digitizeDraftFeatures[10]).toHaveLength(0)
    })

    it('setDigitizeSyncState gates the sync state machine', () => {
      useWorkspaceStore.getState().setDigitizeSyncState('syncing')
      expect(useWorkspaceStore.getState().digitizeSyncState).toBe('syncing')
      useWorkspaceStore.getState().setDigitizeSyncState('idle')
      expect(useWorkspaceStore.getState().digitizeSyncState).toBe('idle')
    })
  })

  describe('finalizeDigitizeLayer', () => {
    it('marks the layer finalized on succeeded status', async () => {
      useWorkspaceStore.getState().addImportedLayer({
        id: 7,
        name: 'Draft',
        purpose: 'inventory',
        format: 'digitize',
        featureCount: 3,
        geometryTypes: ['Point'],
        visible: true,
        order: 0,
        isDraft: true,
        draftStatus: 'active',
      })

      globalThis.fetch = mockFetchOnce({
        status: 'succeeded',
        draft_status: 'finalized',
        feature_count: 3,
      }) as unknown as typeof fetch

      const result = await useWorkspaceStore.getState().finalizeDigitizeLayer('calc-1', 7)

      expect(result).toMatchObject({ status: 'succeeded' })
      const layer = useWorkspaceStore.getState().importedLayers.find((l) => l.id === 7)!
      expect(layer.isDraft).toBe(false)
      expect(layer.draftStatus).toBe('finalized')
    })

    it('keeps the layer as syncing draft for an async queued response', async () => {
      useWorkspaceStore.getState().addImportedLayer({
        id: 8,
        name: 'Draft',
        purpose: 'inventory',
        format: 'digitize',
        featureCount: 3,
        geometryTypes: ['Point'],
        visible: true,
        order: 0,
        isDraft: true,
        draftStatus: 'active',
      })

      globalThis.fetch = mockFetchOnce({
        task_id: 'abc123',
        status: 'queued',
        poll_interval_s: 2,
      }) as unknown as typeof fetch

      await useWorkspaceStore.getState().finalizeDigitizeLayer('calc-1', 8)

      const layer = useWorkspaceStore.getState().importedLayers.find((l) => l.id === 8)!
      expect(layer.isDraft).toBe(true)
      expect(layer.draftStatus).toBe('syncing')
    })

    it('marks draftStatus validation_failed and throws on non-ok response', async () => {
      useWorkspaceStore.getState().addImportedLayer({
        id: 9,
        name: 'Draft',
        purpose: 'inventory',
        format: 'digitize',
        featureCount: 1,
        geometryTypes: ['Point'],
        visible: true,
        order: 0,
        isDraft: true,
        draftStatus: 'active',
      })

      globalThis.fetch = mockFetchOnce(
        { detail: 'Layer has no features to finalize' },
        { ok: false, status: 400 },
      ) as unknown as typeof fetch

      await expect(
        useWorkspaceStore.getState().finalizeDigitizeLayer('calc-1', 9),
      ).rejects.toThrow('Layer has no features to finalize')

      const layer = useWorkspaceStore.getState().importedLayers.find((l) => l.id === 9)!
      expect(layer.draftStatus).toBe('validation_failed')
    })
  })

  describe('discardDigitizeLayer (GD 2.2.4)', () => {
    it('DELETE the layer and clears buffer + context + toolbar', async () => {
      useWorkspaceStore.getState().addImportedLayer({
        id: 20,
        name: 'Draft',
        purpose: 'inventory',
        format: 'digitize',
        featureCount: 2,
        geometryTypes: ['Point'],
        visible: true,
        order: 0,
        isDraft: true,
        draftStatus: 'active',
      })
      useWorkspaceStore.getState().setActiveImportedLayer(20)
      useWorkspaceStore.getState().setToolbarMode('draw_point')
      useWorkspaceStore.getState().setActiveDigitizeContext({ mode: 'draft', layer: { id: 20, name: 'Draft', purpose: 'inventory', format: 'digitize', featureCount: 2, geometryTypes: ['Point'], visible: true, order: 0, isDraft: true, draftStatus: 'active' } })
      useWorkspaceStore.getState().enqueueDigitizeFeature(20, pointFeature)

      const fetchMock = mockFetchOnce({ ok: true }) as unknown as typeof fetch
      globalThis.fetch = fetchMock

      await useWorkspaceStore.getState().discardDigitizeLayer('calc-1', 20)

      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/api/v1/workspace/calc-1/import-layers/20'),
        expect.objectContaining({ method: 'DELETE' }),
      )
      const after = useWorkspaceStore.getState()
      expect(after.importedLayers).toHaveLength(0)
      expect(after.digitizeDraftFeatures[20]).toBeUndefined()
      expect(after.activeDigitizeContext).toBeNull()
      expect(after.toolbarMode).toBe('select')
      expect(after.activeImportedLayerId).toBeNull()
      expect(after.digitizeSyncState).toBe('idle')
    })

    it('throws and keeps the layer on DELETE failure', async () => {
      useWorkspaceStore.getState().addImportedLayer({
        id: 21,
        name: 'Draft',
        purpose: 'inventory',
        format: 'digitize',
        featureCount: 1,
        geometryTypes: ['Point'],
        visible: true,
        order: 0,
        isDraft: true,
        draftStatus: 'active',
      })
      globalThis.fetch = mockFetchOnce(
        { detail: 'Forbidden' },
        { ok: false, status: 403 },
      ) as unknown as typeof fetch

      await expect(
        useWorkspaceStore.getState().discardDigitizeLayer('calc-1', 21),
      ).rejects.toThrow('Forbidden')

      expect(useWorkspaceStore.getState().importedLayers).toHaveLength(1)
    })
  })

  describe('setCalculationId resets digitize state', () => {
    it('clears context, buffer and sync state on calc switch', () => {
      const s = useWorkspaceStore.getState()
      s.setActiveDigitizeContext({ mode: 'draft', layer: { id: 5, name: 'x', purpose: 'inventory', format: 'digitize', featureCount: 0, geometryTypes: [], visible: true, order: 0, isDraft: true } })
      s.enqueueDigitizeFeature(5, pointFeature)
      s.setDigitizeSyncState('error')

      s.setCalculationId('calc-2')

      const after = useWorkspaceStore.getState()
      expect(after.activeDigitizeContext).toBeNull()
      expect(after.digitizeDraftFeatures).toEqual({})
      expect(after.digitizeSyncState).toBe('idle')
    })
  })
})
