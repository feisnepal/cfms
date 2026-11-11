import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import type { GeoJSON } from 'geojson'
import { useWorkspaceStore, createInitialState } from '../../store/workspaceStore'
import {
  flushDigitizeBuffer,
  flushDigitizeBufferWithRetry,
  ConflictFlushError,
  featureIdOf,
  chunkBy,
  CHUNK_SIZE,
} from '../useDraftSync'

const pointFeature = (fid: string): GeoJSON.Feature => ({
  type: 'Feature',
  geometry: { type: 'Point', coordinates: [85.5, 27.5] },
  properties: { featureId: fid, name: `Point ${fid}` },
})

function jsonResponse(body: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: () => Promise.resolve(body),
  } as Response
}

describe('useDraftSync helpers (GD 1.3.4)', () => {
  it('featureIdOf reads featureId / id / top-level id', () => {
    expect(featureIdOf(pointFeature('f1'))).toBe('f1')
    expect(featureIdOf({ type: 'Feature', geometry: null, properties: { id: 'p1' } } as any)).toBe('p1')
    expect(featureIdOf({ id: 'top', type: 'Feature', geometry: null, properties: {} } as any)).toBe('top')
  })

  it('chunkBy splits into chunks of the given size', () => {
    expect(chunkBy([1, 2, 3, 4, 5], 2)).toEqual([[1, 2], [3, 4], [5]])
    expect(chunkBy([1], 25)).toEqual([[1]])
    expect(chunkBy([], 25)).toEqual([])
  })

  describe('flushDigitizeBuffer', () => {
    const originalFetch = globalThis.fetch

    beforeEach(() => {
      vi.stubGlobal('fetch', originalFetch)
      localStorage.clear()
    })

    afterEach(() => {
      vi.unstubAllGlobals()
    })

    it('sends chunks of 25 with one Idempotency-Key and returns the mapping', async () => {
      const seen: RequestInit[] = []
      let cumulative = 0
      const fetchMock = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
        seen.push(init as RequestInit)
        const body = JSON.parse(init?.body as string) as { features: { clientTempId: string }[] }
        const mapping: Record<string, string> = {}
        for (const f of body.features) mapping[f.clientTempId] = `server-${f.clientTempId}`
        cumulative += body.features.length
        return jsonResponse({ mapping, feature_count: cumulative })
      })

      const buffer = Array.from({ length: 55 }, (_, i) => pointFeature(`f${i}`))
      const result = await flushDigitizeBuffer('calc-1', 7, buffer, {
        fetchImpl: fetchMock as typeof fetch,
        idempotencyKey: 'idem-1',
      })

      expect(fetchMock).toHaveBeenCalledTimes(3)
      const keys = new Set(seen.map((i) => (i.headers as Record<string, string>)['Idempotency-Key']))
      expect(keys).toEqual(new Set(['idem-1']))
      const chunkSizes = seen.map((i) => (JSON.parse(i.body as string) as { features: unknown[] }).features.length)
      expect(chunkSizes).toEqual([25, 25, 5])
      expect(Object.keys(result.mapping).length).toBe(55)
      expect(result.mapping.f0).toBe('server-f0')
      expect(result.featureCount).toBe(55)
    })

    it('throws on a non-ok response so the caller can mark error', async () => {
      const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ detail: 'boom' }, false, 500))
      await expect(
        flushDigitizeBuffer('calc-1', 7, [pointFeature('f1')], { fetchImpl: fetchMock as typeof fetch }),
      ).rejects.toThrow(/500/)
    })

    it('throws ConflictFlushError on 409 (optimistic concurrency)', async () => {
      const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ detail: 'conflict' }, false, 409))
      await expect(
        flushDigitizeBuffer('calc-1', 7, [pointFeature('f1')], { fetchImpl: fetchMock as typeof fetch }),
      ).rejects.toBeInstanceOf(ConflictFlushError)
    })

    it('injects a _vectorClock on sent features (Gap 9.2 LWW)', async () => {
      let sentBody: any = null
      const fetchMock = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
        sentBody = JSON.parse(init?.body as string)
        return jsonResponse({ mapping: {}, feature_count: 1 })
      })
      await flushDigitizeBuffer('calc-1', 7, [pointFeature('f1')], { fetchImpl: fetchMock as typeof fetch })
      const sent = sentBody.features[0].feature as Record<string, unknown>
      const clock = (sent.properties as Record<string, unknown>)._vectorClock as {
        deviceId: string
        timestamp: number
        sequence: number
      }
      expect(clock).toBeDefined()
      expect(typeof clock.deviceId).toBe('string')
      expect(clock.timestamp).toBeGreaterThan(0)
      expect(clock.sequence).toBeGreaterThan(0)
    })
  })

  describe('flushDigitizeBufferWithRetry (GD 1.3.5)', () => {
    it('fails twice then succeeds, reusing the same idempotency key', async () => {
      const keys: string[] = []
      let calls = 0
      const fetchMock = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
        calls++
        const hdr = (init?.headers as Record<string, string>)
        keys.push(hdr['Idempotency-Key'])
        if (calls <= 2) return jsonResponse({ detail: 'network' }, false, 500)
        return jsonResponse({ mapping: { f1: 'server-f1' }, feature_count: 1 })
      })

      const result = await flushDigitizeBufferWithRetry('calc-1', 7, [pointFeature('f1')], {
        fetchImpl: fetchMock as typeof fetch,
        maxAttempts: 3,
      })
      expect(calls).toBe(3)
      expect(new Set(keys).size).toBe(1)
      expect(result.mapping.f1).toBe('server-f1')
    })

    it('does not retry ConflictFlushError (409) — surfaced immediately', async () => {
      const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ detail: 'conflict' }, false, 409))
      await expect(
        flushDigitizeBufferWithRetry('calc-1', 7, [pointFeature('f1')], {
          fetchImpl: fetchMock as typeof fetch,
          maxAttempts: 3,
        }),
      ).rejects.toBeInstanceOf(ConflictFlushError)
      expect(fetchMock).toHaveBeenCalledTimes(1)
    })

    it('gives up after maxAttempts and surfaces the last error', async () => {
      const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ detail: 'nope' }, false, 500))
      await expect(
        flushDigitizeBufferWithRetry('calc-1', 7, [pointFeature('f1')], {
          fetchImpl: fetchMock as typeof fetch,
          maxAttempts: 2,
        }),
      ).rejects.toThrow(/500/)
      expect(fetchMock).toHaveBeenCalledTimes(2)
    })
  })
})

describe('useDraftSync store integration (GD 1.3.4)', () => {
  const originalFetch = globalThis.fetch
  const realActions = {
    enqueueDigitizeFeature: useWorkspaceStore.getState().enqueueDigitizeFeature,
    setDigitizeDraftFeatures: useWorkspaceStore.getState().setDigitizeDraftFeatures,
    clearDigitizeDraftFeatures: useWorkspaceStore.getState().clearDigitizeDraftFeatures,
    setDigitizeSyncState: useWorkspaceStore.getState().setDigitizeSyncState,
    setImportedLayerFeatures: useWorkspaceStore.getState().setImportedLayerFeatures,
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

  it('buffers features on enqueue and clears on clearDigitizeDraftFeatures', () => {
    useWorkspaceStore.getState().enqueueDigitizeFeature(7, pointFeature('f1'))
    useWorkspaceStore.getState().enqueueDigitizeFeature(7, pointFeature('f2'))
    expect(useWorkspaceStore.getState().digitizeDraftFeatures[7]).toHaveLength(2)

    useWorkspaceStore.getState().clearDigitizeDraftFeatures(7)
    expect(useWorkspaceStore.getState().digitizeDraftFeatures[7]).toBeUndefined()
  })

  it('sync state transitions idle → syncing → idle after a successful flush', async () => {
    const fetchMock = vi.fn().mockImplementation(async (url: RequestInfo | URL, init?: RequestInit) => {
      const body = JSON.parse(init?.body as string) as { features: { clientTempId: string }[] }
      const mapping: Record<string, string> = {}
      for (const f of body.features) mapping[f.clientTempId] = `server-${f.clientTempId}`
      return jsonResponse({ mapping, feature_count: body.features.length })
    })
    vi.stubGlobal('fetch', fetchMock)

    useWorkspaceStore.getState().enqueueDigitizeFeature(7, pointFeature('f1'))
    expect(useWorkspaceStore.getState().digitizeSyncState).toBe('idle')

    useWorkspaceStore.getState().setDigitizeSyncState('syncing')
    expect(useWorkspaceStore.getState().digitizeSyncState).toBe('syncing')

    const result = await flushDigitizeBuffer('calc-1', 7, useWorkspaceStore.getState().digitizeDraftFeatures[7])
    expect(result.mapping.f1).toBe('server-f1')

    useWorkspaceStore.getState().clearDigitizeDraftFeatures(7)
    useWorkspaceStore.getState().setDigitizeSyncState('idle')
    expect(useWorkspaceStore.getState().digitizeSyncState).toBe('idle')
    expect(useWorkspaceStore.getState().digitizeDraftFeatures[7]).toBeUndefined()
  })

  it('retains the buffer and stays error when the flush fails', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ detail: 'x' }, false, 409))
    vi.stubGlobal('fetch', fetchMock)

    useWorkspaceStore.getState().enqueueDigitizeFeature(7, pointFeature('f1'))
    useWorkspaceStore.getState().setDigitizeSyncState('error')

    await expect(
      flushDigitizeBuffer('calc-1', 7, useWorkspaceStore.getState().digitizeDraftFeatures[7]),
    ).rejects.toThrow()

    expect(useWorkspaceStore.getState().digitizeSyncState).toBe('error')
    expect(useWorkspaceStore.getState().digitizeDraftFeatures[7]).toHaveLength(1)
  })

  it('CHUNK_SIZE is 25 per the bulk endpoint contract', () => {
    expect(CHUNK_SIZE).toBe(25)
  })
})
