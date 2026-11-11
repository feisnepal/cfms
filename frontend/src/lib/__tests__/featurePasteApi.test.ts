import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../../services/api', () => ({
  forestApi: {
    addSubArea: vi.fn(),
    getImportedLayerFeatures: vi.fn(),
    importWorkspaceLayer: vi.fn(),
  },
}))
vi.mock('../../hooks/useDraftSync', () => ({
  flushDigitizeBufferWithRetry: vi.fn(),
}))

import { forestApi } from '../../services/api'
import { flushDigitizeBufferWithRetry } from '../../hooks/useDraftSync'
import {
  PasteRejectedError,
  appendFeaturesToImportedLayer,
  createSubAreaFromPaste,
  fetchImportedFeatures,
  importClipboardAsLayer,
} from '../featurePasteApi'

const BODY = {
  name: 'A', category: 'protected', is_excluded: false,
  geometry: { type: 'Polygon' as const, coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] },
}

/** What axios rejects with for a non-2xx response. */
const axiosError = (status: number, data: unknown) => ({
  isAxiosError: true, response: { status, data }, message: `Request failed with status code ${status}`,
})

beforeEach(() => vi.clearAllMocks())

describe('createSubAreaFromPaste', () => {
  it('returns what the server created', async () => {
    vi.mocked(forestApi.addSubArea).mockResolvedValue({ id: 's1', geometry: BODY.geometry, area_hectares: 3 })
    await expect(createSubAreaFromPaste('c1', BODY)).resolves.toMatchObject({ id: 's1', area_hectares: 3 })
    expect(forestApi.addSubArea).toHaveBeenCalledWith('c1', BODY)
  })

  it("turns a refusal into an exception carrying the server's own words (a plain string detail)", async () => {
    vi.mocked(forestApi.addSubArea).mockRejectedValue(axiosError(400, { detail: 'Sub-area is entirely within existing sub-areas' }))
    const err = await createSubAreaFromPaste('c1', BODY).catch((e) => e)
    expect(err).toBeInstanceOf(PasteRejectedError)
    expect(err.status).toBe(400)
    expect(err.message).toBe('Sub-area is entirely within existing sub-areas')
  })

  it('keeps the code and Nepali text of a structured refusal (e.g. the 423 structure lock)', async () => {
    vi.mocked(forestApi.addSubArea).mockRejectedValue(
      axiosError(423, { detail: { code: 'structure_locked', message: 'Structure is locked', message_np: 'संरचना लक छ' } }),
    )
    const err = await createSubAreaFromPaste('c1', BODY).catch((e) => e)
    expect(err).toMatchObject({ status: 423, code: 'structure_locked', message: 'Structure is locked', messageNp: 'संरचना लक छ' })
  })

  it('reports a network failure (no response) as a rejection instead of throwing something opaque', async () => {
    vi.mocked(forestApi.addSubArea).mockRejectedValue(new Error('Network Error'))
    const err = await createSubAreaFromPaste('c1', BODY).catch((e) => e)
    expect(err).toBeInstanceOf(PasteRejectedError)
    expect(err.message).toBe('Network Error')
  })
})

describe('fetchImportedFeatures', () => {
  it('returns the server list, and [] when it has none', async () => {
    vi.mocked(forestApi.getImportedLayerFeatures).mockResolvedValue({
      features: [{ type: 'Feature', geometry: null as never, properties: {} }],
    })
    await expect(fetchImportedFeatures('c1', 7)).resolves.toHaveLength(1)
    vi.mocked(forestApi.getImportedLayerFeatures).mockResolvedValue({} as never)
    await expect(fetchImportedFeatures('c1', 7)).resolves.toEqual([])
  })
})

describe('appendFeaturesToImportedLayer', () => {
  it("flushes through the digitizer's bulk endpoint in the requested mode", async () => {
    vi.mocked(flushDigitizeBufferWithRetry).mockResolvedValue({ mapping: {}, featureCount: 2 })
    await appendFeaturesToImportedLayer('c1', 7, [], 'append')
    expect(flushDigitizeBufferWithRetry).toHaveBeenCalledWith('c1', 7, [], { mode: 'append' })
  })

  it('reports a failed flush as a rejection', async () => {
    vi.mocked(flushDigitizeBufferWithRetry).mockRejectedValue(new Error('Bulk flush failed (500)'))
    const err = await appendFeaturesToImportedLayer('c1', 7, [], 'draft').catch((e) => e)
    expect(err).toBeInstanceOf(PasteRejectedError)
    expect(err.message).toBe('Bulk flush failed (500)')
  })
})

describe('importClipboardAsLayer', () => {
  const square = (x: number, name: string) => ({
    type: 'Feature' as const,
    properties: { name },
    geometry: { type: 'Polygon' as const, coordinates: [[[x, 27], [x + 1, 27], [x + 1, 28], [x, 27]]] },
  })

  it('uploads ONE GeoJSON file holding every feature, exactly, as a purpose-"other" layer', async () => {
    vi.mocked(forestApi.importWorkspaceLayer).mockResolvedValue({ id: 9, name: 'Blocks (copy)', feature_count: 2, geometry_types: ['Polygon'] })
    const feats = [square(85, 'One'), square(86, 'Two')]
    const created = await importClipboardAsLayer('c1', feats, 'Blocks (copy)')

    const [calc, file, opts] = vi.mocked(forestApi.importWorkspaceLayer).mock.calls[0]
    expect(calc).toBe('c1')
    expect(opts).toEqual({ purpose: 'other', customName: 'Blocks (copy)' })
    expect((file as File).name).toMatch(/\.geojson$/)
    const sent = JSON.parse(await (file as File).text())
    expect(sent.type).toBe('FeatureCollection')
    expect(sent.features).toEqual(feats) // every feature, attributes and coordinates untouched
    expect(created).toEqual({ id: 9, name: 'Blocks (copy)', featureCount: 2, geometryTypes: ['Polygon'] })
  })

  it("turns a server refusal (e.g. file too large) into a rejection carrying the server's words", async () => {
    vi.mocked(forestApi.importWorkspaceLayer).mockRejectedValue(axiosError(413, { detail: 'File exceeds the size limit' }))
    const err = await importClipboardAsLayer('c1', [square(85, 'One')], 'X').catch((e) => e)
    expect(err).toBeInstanceOf(PasteRejectedError)
    expect(err).toMatchObject({ status: 413, message: 'File exceeds the size limit' })
  })
})
