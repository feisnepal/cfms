import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  fetchDeleteGuard,
  snapshotFeature,
  deleteFeatureRow,
  restoreFeatureRow,
} from '../featureRowOps'

const CALC_ID = 'calc-1'

function mockFetch(response?: Partial<Response>, body?: unknown, status = 200) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body ?? {}),
  } as Response)
}

function setupHeaders() {
  localStorage.setItem('access_token', 'token-abc')
}

beforeEach(() => {
  localStorage.clear()
  vi.stubGlobal('fetch', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('fetchDeleteGuard', () => {
  it('returns the guard result from GET geometry/delete-guard', async () => {
    setupHeaders()
    vi.stubGlobal('fetch', mockFetch(
      undefined,
      {
        layer_type: 'blocks',
        feature_id: 'b1',
        blocked: true,
        reasons: [{ type: 'sample_plots', count: 3 }],
      },
      200,
    ))

    const guard = await fetchDeleteGuard({ calcId: CALC_ID, layerType: 'blocks', featureId: 'b1' })
    expect(guard.blocked).toBe(true)
    expect(guard.reasons[0].count).toBe(3)

    const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(url).toContain(`/api/v1/calculations/${CALC_ID}/geometry/delete-guard`)
    expect(init.headers.Authorization).toBe('Bearer token-abc')
  })

  it('throws when the guard endpoint fails', async () => {
    setupHeaders()
    vi.stubGlobal('fetch', mockFetch(undefined, {}, 500))
    await expect(
      fetchDeleteGuard({ calcId: CALC_ID, layerType: 'sub_areas', featureId: 's1' }),
    ).rejects.toThrow(/Delete guard failed/)
  })
})

describe('snapshotFeature', () => {
  it('captures a row snapshot from GET geometry/feature', async () => {
    setupHeaders()
    vi.stubGlobal('fetch', mockFetch(
      undefined,
      { layer_type: 'blocks', feature_id: 'b1', snapshot: { id: 'b1', name: 'B1' } },
      200,
    ))

    const res = await snapshotFeature({ calcId: CALC_ID, layerType: 'blocks', featureId: 'b1' })
    expect(res.snapshot.name).toBe('B1')
  })
})

describe('deleteFeatureRow', () => {
  it('deletes an imported-layer feature via the workspace index endpoint', async () => {
    setupHeaders()
    vi.stubGlobal('fetch', mockFetch(
      undefined,
      { feature_count: 2, deleted_feature: { id: 'f2' } },
      200,
    ))

    await deleteFeatureRow({
      calcId: CALC_ID,
      layerType: 'import_5',
      featureId: 'f2',
      importLayerId: 5,
      featureIndex: 1,
    })
    const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(url).toContain(`/workspace/${CALC_ID}/import-layers/5/features/1`)
    expect(init.method).toBe('DELETE')
  })

  it('requires importLayerId + featureIndex for import layers', async () => {
    await expect(
      deleteFeatureRow({ calcId: CALC_ID, layerType: 'import_5', featureId: 'f2' }),
    ).rejects.toThrow(/importLayerId \+ featureIndex/)
  })

  it('deletes the boundary via the legacy endpoint (accepts 204)', async () => {
    setupHeaders()
    vi.stubGlobal('fetch', mockFetch(undefined, {}, 204))
    await deleteFeatureRow({ calcId: CALC_ID, layerType: 'boundary', featureId: 'boundary' })
  })

  it('routes blocks to the forests DELETE endpoint', async () => {
    setupHeaders()
    vi.stubGlobal('fetch', mockFetch(undefined, {}, 204))
    await deleteFeatureRow({ calcId: CALC_ID, layerType: 'blocks', featureId: 'b1' })
    const [url] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(url).toBe(`/api/forests/calculations/${CALC_ID}/blocks/b1`)
  })

  // P7e, inverting the old expectation. This was the id-less route because one
  // row held the whole group, so deleting any feature deleted the ENTIRE user
  // group - correct only while a second polygon could not exist. Now each
  // polygon is its own row and its own feature, so the id goes in the path.
  it('routes user_group to the per-ROW delete endpoint', async () => {
    setupHeaders()
    vi.stubGlobal('fetch', mockFetch(undefined, {}, 204))
    await deleteFeatureRow({
      calcId: CALC_ID, layerType: 'user_group', featureId: '7',
    })
    const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(url).toBe(`/api/calculations/${CALC_ID}/user-group/7`)
    expect(init.method).toBe('DELETE')
  })
})

describe('restoreFeatureRow', () => {
  it('restores a builtin row via the restore-feature endpoint', async () => {
    setupHeaders()
    vi.stubGlobal('fetch', mockFetch(undefined, { success: true }, 200))

    await restoreFeatureRow(
      { calcId: CALC_ID, layerType: 'sub_areas', featureId: 's1' },
      { id: 's1', name: 'SA' },
    )
    const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(url).toContain(`/calculations/${CALC_ID}/geometry/restore-feature`)
    const body = JSON.parse(init.body)
    expect(body).toEqual({ layer_type: 'sub_areas', feature_id: 's1', snapshot: { id: 's1', name: 'SA' } })
  })

  it('re-inserts an imported feature at its original index', async () => {
    setupHeaders()
    vi.stubGlobal('fetch', mockFetch(undefined, {}, 200))

    await restoreFeatureRow(
      {
        calcId: CALC_ID,
        layerType: 'import_5',
        featureId: 'f1',
        importLayerId: 5,
        featureIndex: 0,
      },
      { feature: { id: 'f1' } },
    )
    const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(url).toContain(`/workspace/${CALC_ID}/import-layers/5/features/restore`)
    const body = JSON.parse(init.body)
    expect(body.feature_index).toBe(0)
  })
})