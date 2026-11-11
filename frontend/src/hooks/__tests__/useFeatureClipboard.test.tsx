import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import type { GeoJSON } from 'geojson'

vi.mock('antd', () => {
  const message = { success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn() }
  // Auto-confirm: the dialog's OK is pressed immediately.
  const Modal = {
    confirm: vi.fn((o: { onOk?: () => void }) => { o.onOk?.() }),
    error: vi.fn(),
    info: vi.fn(),
  }
  return { message, Modal }
})
vi.mock('../../i18n/hooks', () => ({
  useT: () => (key: string, params?: unknown) => (params ? `${key}:${JSON.stringify(params)}` : key),
}))
vi.mock('../../lib/featureRowOps', () => ({
  deleteFeatureRow: vi.fn(async () => ({})),
  fetchDeleteGuard: vi.fn(async () => ({ blocked: false, reasons: [] })),
  snapshotFeature: vi.fn(async () => ({ snapshot: { row: 1 } })),
}))
vi.mock('../../lib/featurePasteApi', async () => {
  const actual = await vi.importActual<typeof import('../../lib/featurePasteApi')>('../../lib/featurePasteApi')
  return {
    ...actual, // keep the real PasteRejectedError so instanceof checks behave
    createSubAreaFromPaste: vi.fn(),
    appendFeaturesToImportedLayer: vi.fn(async () => undefined),
    fetchImportedFeatures: vi.fn(async () => []),
    importClipboardAsLayer: vi.fn(),
  }
})

import { message, Modal } from 'antd'
import { deleteFeatureRow, fetchDeleteGuard } from '../../lib/featureRowOps'
import {
  PasteRejectedError,
  createSubAreaFromPaste,
  appendFeaturesToImportedLayer,
  fetchImportedFeatures,
  importClipboardAsLayer,
} from '../../lib/featurePasteApi'
import { areaHectares } from '../../lib/featureClipboard'
import { useWorkspaceStore } from '../../store/workspaceStore'
import { useFeatureClipboardStore } from '../../store/featureClipboardStore'
import { useFeatureClipboard } from '../useFeatureClipboard'
import type { GeometryOperation } from '../../lib/editOperations'

const CALC = 'calc-1'
const poly = (x: number, props: Record<string, unknown> = {}): GeoJSON.Feature => ({
  type: 'Feature',
  geometry: { type: 'Polygon', coordinates: [[[x, 27], [x + 0.01, 27], [x + 0.01, 27.01], [x, 27.01], [x, 27]]] },
  properties: props,
})

const layerData: Record<string, GeoJSON.Feature[]> = {}
const pushed: GeometryOperation[] = []

function mount() {
  pushed.length = 0
  const pushOp = vi.fn((op: GeometryOperation) => { pushed.push(op) })
  const pushAndExecute = vi.fn((op: GeometryOperation, run: () => void) => { pushed.push(op); run() })
  const rootRef = { current: document.createElement('div') }
  const hook = renderHook(() => useFeatureClipboard({
    calculationId: CALC,
    getLayerFeatures: (id) => (layerData[id] as GeoJSON.Feature[]) ?? null,
    pushOp, pushAndExecute, rootRef,
  }))
  return { ...hook, pushOp, pushAndExecute }
}

function selectIn(layer: string, ids: string[]) {
  act(() => {
    useWorkspaceStore.setState({
      activeLayerId: layer as never,
      activeImportedLayerId: null,
      selection: { layerId: layer, featureIds: ids, mode: 'replace' },
    })
  })
}

beforeEach(() => {
  // clearAllMocks keeps mockImplementation()s, so a test that made a feature
  // "blocked" would leak into the next. Put every mock back to its default.
  vi.clearAllMocks()
  vi.mocked(deleteFeatureRow).mockReset().mockResolvedValue({})
  vi.mocked(fetchDeleteGuard).mockReset().mockResolvedValue({ layer_type: 'x', feature_id: 'x', blocked: false, reasons: [] })
  vi.mocked(createSubAreaFromPaste).mockReset()
  vi.mocked(importClipboardAsLayer).mockReset()
  vi.mocked(appendFeaturesToImportedLayer).mockReset().mockResolvedValue(undefined)
  vi.mocked(fetchImportedFeatures).mockReset().mockResolvedValue([])
  vi.mocked(Modal.confirm).mockReset().mockImplementation(((o: { onOk?: () => void }) => { o.onOk?.() }) as never)
  Object.keys(layerData).forEach((k) => delete layerData[k])
  useFeatureClipboardStore.setState({ clipboard: null })
  useWorkspaceStore.setState({
    activeLayerId: null, activeImportedLayerId: null, structureLocked: false, layerLocks: {},
    importedLayers: [], importedLayerFeatures: {}, digitizeDraftFeatures: {},
    selection: { layerId: null, featureIds: [], mode: 'replace' },
    toolbarMode: 'select',
  })
})

describe('Copy', () => {
  beforeEach(() => {
    layerData.blocks = [poly(85, { id: 'b1', name: 'One' }), poly(86, { id: 'b2', name: 'Two' }), poly(87, { id: 'b3', name: 'Three' })]
  })

  it('copies only the selected features, with attributes but without identity', () => {
    const { result } = mount()
    selectIn('blocks', ['b1', 'b3'])
    act(() => { result.current.copy() })
    const cb = useFeatureClipboardStore.getState().clipboard!
    expect(cb.features).toHaveLength(2)
    expect(cb.wholeLayer).toBe(false)
    expect(cb.features.map((f) => f.properties)).toEqual([{ name: 'One' }, { name: 'Three' }]) // id stripped
    expect(vi.mocked(message.success).mock.calls[0][0]).toContain('editing.copy.done:')
  })

  it('copies the whole layer when nothing is selected', () => {
    const { result } = mount()
    selectIn('blocks', [])
    act(() => { result.current.copy() })
    const cb = useFeatureClipboardStore.getState().clipboard!
    expect(cb.features).toHaveLength(3)
    expect(cb.wholeLayer).toBe(true)
    expect(vi.mocked(message.success).mock.calls[0][0]).toContain('editing.copy.doneWhole')
  })

  it('says so when there is no active layer', () => {
    const { result } = mount()
    act(() => { result.current.copy() })
    expect(useFeatureClipboardStore.getState().clipboard).toBeNull()
    expect(message.info).toHaveBeenCalledWith('editing.copy.noLayer')
  })
})

describe('Delete (multi-select, one confirm)', () => {
  beforeEach(() => {
    layerData.sub_areas = [poly(85, { id: 's1', name: 'A' }), poly(86, { id: 's2', name: 'B' }), poly(87, { id: 's3', name: 'C' })]
  })

  it('confirms ONCE, deletes every selected feature, and records ONE undo step', async () => {
    const { result, pushAndExecute } = mount()
    selectIn('sub_areas', ['s1', 's3'])
    await act(async () => { await result.current.deleteSelected() })

    expect(Modal.confirm).toHaveBeenCalledTimes(1)
    expect(deleteFeatureRow).toHaveBeenCalledTimes(2)
    expect(vi.mocked(deleteFeatureRow).mock.calls.map((c) => c[0].featureId).sort()).toEqual(['s1', 's3'])
    expect(pushAndExecute).toHaveBeenCalledTimes(1)
    const op = pushed[0]
    expect(op.kind).toBe('batch')
    expect(op.kind === 'batch' && op.operations.map((o) => o.kind)).toEqual(['feature_delete', 'feature_delete'])
    expect(useWorkspaceStore.getState().selection.featureIds).toEqual([])
  })

  it('a single selected feature records a plain delete, not a batch', async () => {
    const { result } = mount()
    selectIn('sub_areas', ['s2'])
    await act(async () => { await result.current.deleteSelected() })
    expect(pushed).toHaveLength(1)
    expect(pushed[0].kind).toBe('feature_delete')
  })

  it('one blocked feature refuses the WHOLE batch: nothing is deleted, nothing is recorded', async () => {
    vi.mocked(fetchDeleteGuard).mockImplementation(async (ctx) => (
      ctx.featureId === 's2'
        ? { layer_type: 'sub_areas', feature_id: 's2', blocked: true, reasons: [{ type: 'sample_plots', count: 4 }] }
        : { layer_type: 'sub_areas', feature_id: ctx.featureId, blocked: false, reasons: [] }
    ))
    const { result } = mount()
    selectIn('sub_areas', ['s1', 's2', 's3'])
    await act(async () => { await result.current.deleteSelected() })

    expect(Modal.error).toHaveBeenCalledTimes(1)
    expect(String(vi.mocked(Modal.error).mock.calls[0][0].content)).toContain('B') // names what is blocked
    expect(Modal.confirm).not.toHaveBeenCalled()
    expect(deleteFeatureRow).not.toHaveBeenCalled()
    expect(pushed).toHaveLength(0)
  })

  it('declining the confirm deletes nothing', async () => {
    vi.mocked(Modal.confirm).mockImplementationOnce(((o: { onCancel?: () => void }) => { o.onCancel?.() }) as never)
    const { result } = mount()
    selectIn('sub_areas', ['s1', 's2'])
    await act(async () => { await result.current.deleteSelected() })
    expect(deleteFeatureRow).not.toHaveBeenCalled()
    expect(pushed).toHaveLength(0)
  })

  it('a failure part-way records only what was actually deleted and reports it', async () => {
    let n = 0
    vi.mocked(deleteFeatureRow).mockImplementation(async () => {
      n += 1
      if (n === 2) throw new Error('server said no')
      return {}
    })
    const { result } = mount()
    selectIn('sub_areas', ['s1', 's2', 's3'])
    await act(async () => { await result.current.deleteSelected() })

    expect(pushed).toHaveLength(1)
    expect(pushed[0].kind).toBe('feature_delete') // exactly one succeeded → a single undoable delete
    expect(vi.mocked(message.error).mock.calls[0][0]).toContain('editing.delete.partial')
    expect(vi.mocked(message.error).mock.calls[0][0]).toContain('server said no')
  })

  it('cannot delete on a layer that is not deletable, or with nothing selected', async () => {
    layerData.sample_plots = [poly(85, { id: 'p1' })]
    const { result } = mount()
    selectIn('sample_plots', ['p1'])
    expect(result.current.canDelete).toBe(false)
    await act(async () => { await result.current.deleteSelected() })
    expect(deleteFeatureRow).not.toHaveBeenCalled()

    selectIn('sub_areas', [])
    await act(async () => { await result.current.deleteSelected() })
    expect(message.info).toHaveBeenCalledWith('editing.delete.nothingSelected')
  })

  it('is disabled while the structure is locked', () => {
    const { result } = mount()
    selectIn('sub_areas', ['s1'])
    expect(result.current.canDelete).toBe(true)
    act(() => { useWorkspaceStore.setState({ structureLocked: true }) })
    expect(result.current.canDelete).toBe(false)
  })
})

describe('Paste into sub-areas', () => {
  const clip = (features: GeoJSON.Feature[]) =>
    useFeatureClipboardStore.setState({
      clipboard: { calcId: CALC, sourceLayerKey: 'blocks', sourceLabel: 'Blocks', wholeLayer: false, features, copiedAt: 1 },
    })

  beforeEach(() => {
    layerData.sub_areas = [poly(90, { id: 'existing', name: 'Existing' })]
  })

  it('pastes at the exact coordinates, keeps the source name and category, and records one undo step', async () => {
    const src = poly(85, { name: 'Ridge', category: 'protected' })
    clip([src])
    vi.mocked(createSubAreaFromPaste).mockImplementation(async (_c, body) => ({
      id: 'new-1', geometry: body.geometry, area_hectares: areaHectares({ type: 'Feature', geometry: body.geometry, properties: {} }),
    }))
    const { result } = mount()
    selectIn('sub_areas', [])
    await act(async () => { await result.current.paste() })

    const body = vi.mocked(createSubAreaFromPaste).mock.calls[0][1]
    expect(body).toMatchObject({ name: 'Ridge', category: 'protected' })
    expect(body.geometry).toEqual(src.geometry) // no offset
    expect(pushed).toHaveLength(1)
    expect(pushed[0].kind).toBe('feature_paste')
    expect(message.success).toHaveBeenCalled()
    expect(useWorkspaceStore.getState().selection.featureIds).toEqual(['new-1']) // the pasted feature is selected
  })

  it('asks for a category once when the pasted features carry none, and applies it to all of them', async () => {
    clip([poly(85, { name: 'B1' }), poly(86, { name: 'B2' })])
    vi.mocked(createSubAreaFromPaste).mockImplementation(async (_c, body) => ({ id: `id-${body.name}`, geometry: body.geometry }))
    const { result } = mount()
    selectIn('sub_areas', [])

    let pending!: Promise<void>
    act(() => { pending = result.current.paste() })
    expect(result.current.categoryPrompt).toEqual({ count: 2 })
    await act(async () => { result.current.resolveCategoryPrompt('plantation'); await pending })

    expect(vi.mocked(createSubAreaFromPaste).mock.calls.map((c) => c[1].category)).toEqual(['plantation', 'plantation'])
    expect(result.current.categoryPrompt).toBeNull()
  })

  it('cancelling the category prompt creates nothing', async () => {
    clip([poly(85, { name: 'B1' })])
    const { result } = mount()
    selectIn('sub_areas', [])
    let pending!: Promise<void>
    act(() => { pending = result.current.paste() })
    await act(async () => { result.current.resolveCategoryPrompt(null); await pending })
    expect(createSubAreaFromPaste).not.toHaveBeenCalled()
    expect(pushed).toHaveLength(0)
  })

  it('tells the user what the server trimmed and what it refused', async () => {
    clip([
      poly(85, { name: 'Keep', category: 'protected' }),
      poly(86, { name: 'Trim', category: 'protected' }),
      poly(87, { name: 'Gone', category: 'protected' }),
    ])
    vi.mocked(createSubAreaFromPaste).mockImplementation(async (_c, body) => {
      if (body.name === 'Gone') throw new PasteRejectedError(400, 'Sub-area is entirely within existing sub-areas')
      const full = areaHectares({ type: 'Feature', geometry: body.geometry, properties: {} })
      return { id: `id-${body.name}`, geometry: body.geometry, area_hectares: body.name === 'Trim' ? full * 0.4 : full }
    })
    const { result } = mount()
    selectIn('sub_areas', [])
    await act(async () => { await result.current.paste() })

    expect(vi.mocked(message.warning).mock.calls[0][0]).toContain('"done":2')
    expect(vi.mocked(message.warning).mock.calls[0][0]).toContain('"trimmed":1')
    expect(vi.mocked(message.warning).mock.calls[0][0]).toContain('"rejected":1')
    expect(String(vi.mocked(Modal.info).mock.calls[0][0].content)).toContain('entirely within existing sub-areas')
    // What WAS created is still one undoable step.
    expect(pushed).toHaveLength(1)
    expect(pushed[0].kind === 'feature_paste' && pushed[0].state.createdIds).toEqual(['id-Keep', 'id-Trim'])
  })

  it('stops at the first lock and reports it, instead of failing feature by feature', async () => {
    clip([poly(85, { name: 'A', category: 'protected' }), poly(86, { name: 'B', category: 'protected' })])
    vi.mocked(createSubAreaFromPaste).mockRejectedValue(new PasteRejectedError(423, 'Structure is locked'))
    const { result } = mount()
    selectIn('sub_areas', [])
    await act(async () => { await result.current.paste() })
    expect(createSubAreaFromPaste).toHaveBeenCalledTimes(1)
    expect(message.error).toHaveBeenCalledWith('Structure is locked')
    expect(pushed).toHaveLength(0)
  })

  it('refuses to paste into a layer that cannot take it, with the reason', async () => {
    layerData.blocks = [poly(85, { id: 'b1' })]
    clip([poly(85, { name: 'X', category: 'protected' })])
    const { result } = mount()
    selectIn('blocks', [])
    expect(result.current.pasteIssue?.code).toBe('layer_not_pastable')
    await act(async () => { await result.current.paste() })
    expect(createSubAreaFromPaste).not.toHaveBeenCalled()
    expect(vi.mocked(message.warning).mock.calls[0][0]).toContain('editing.paste.reason.layer_not_pastable')
  })

  it('will not paste features copied from another calculation', () => {
    useFeatureClipboardStore.setState({
      clipboard: { calcId: 'some-other-calc', sourceLayerKey: 'blocks', sourceLabel: 'B', wholeLayer: false, features: [poly(85, { category: 'protected' })], copiedAt: 1 },
    })
    const { result } = mount()
    selectIn('sub_areas', [])
    expect(result.current.clipboardCount).toBe(0)
    expect(result.current.pasteIssue?.code).toBe('empty_clipboard')
  })
})

describe('Paste into an imported layer', () => {
  it('appends the features exactly and records where they landed', async () => {
    useWorkspaceStore.setState({
      activeLayerId: null, activeImportedLayerId: 7,
      importedLayers: [{ id: 7, name: 'Roads', purpose: 'other', format: 'geojson', featureCount: 1, geometryTypes: ['Polygon'], visible: true, order: 0 }],
      importedLayerFeatures: { 7: [poly(80, { featureId: 'old' })] },
      selection: { layerId: 'imported:7', featureIds: [], mode: 'replace' },
    })
    useFeatureClipboardStore.setState({
      clipboard: { calcId: CALC, sourceLayerKey: 'blocks', sourceLabel: 'Blocks', wholeLayer: false, features: [poly(85, { name: 'N' })], copiedAt: 1 },
    })
    vi.mocked(fetchImportedFeatures).mockResolvedValue([poly(80, { featureId: 'old' }), poly(85, { featureId: 'new-x', name: 'N' })])
    const { result } = mount()
    await act(async () => { await result.current.paste() })

    expect(appendFeaturesToImportedLayer).toHaveBeenCalledTimes(1)
    const [, layerId, sent, mode] = vi.mocked(appendFeaturesToImportedLayer).mock.calls[0]
    expect(layerId).toBe(7)
    expect(mode).toBe('append')
    expect(sent[0].geometry).toEqual(poly(85).geometry)
    expect(pushed[0].kind === 'feature_paste' && pushed[0].baseIndex).toBe(1) // tail of the server list
  })

  it('is refused for an imported layer that has its own topology rules', () => {
    useWorkspaceStore.setState({
      activeLayerId: null, activeImportedLayerId: 8,
      importedLayers: [{ id: 8, name: 'Blocks import', purpose: 'blocks', format: 'geojson', featureCount: 1, geometryTypes: ['Polygon'], visible: true, order: 0 }],
      importedLayerFeatures: { 8: [] },
    })
    useFeatureClipboardStore.setState({
      clipboard: { calcId: CALC, sourceLayerKey: 'x', sourceLabel: 'X', wholeLayer: false, features: [poly(85)], copiedAt: 1 },
    })
    const { result } = mount()
    expect(result.current.pasteIssue?.code).toBe('purpose_not_pastable')
  })
})

describe('Paste as a new layer', () => {
  const clip = () => useFeatureClipboardStore.setState({
    clipboard: {
      calcId: CALC, sourceLayerKey: 'blocks', sourceLabel: 'Blocks', wholeLayer: false, copiedAt: 1,
      features: [poly(85, { name: 'One' }), poly(86, { name: 'Two' })],
    },
  })

  it('is available even where a plain paste is not (that is what it is for), and needs only a clipboard', () => {
    layerData.blocks = [poly(85, { id: 'b1' })]
    const { result } = mount()
    selectIn('blocks', [])
    expect(result.current.pasteAsLayerIssue?.code).toBe('empty_clipboard')
    act(() => { clip() })
    expect(result.current.pasteIssue?.code).toBe('layer_not_pastable') // blocks cannot take a paste...
    expect(result.current.pasteAsLayerIssue).toBeNull() // ...but a new layer always can
  })

  it('imports EVERY copied feature as its own row of a new layer, then registers and opens it', async () => {
    vi.mocked(importClipboardAsLayer).mockResolvedValue({ id: 50, name: 'Blocks (copy)', featureCount: 2, geometryTypes: ['Polygon'] })
    vi.mocked(fetchImportedFeatures).mockResolvedValue([poly(85, { featureId: 'x1', name: 'One' }), poly(86, { featureId: 'x2', name: 'Two' })])
    clip()
    const { result } = mount()
    selectIn('blocks', [])
    await act(async () => { await result.current.pasteAsLayer() })

    const [calcId, sent, name] = vi.mocked(importClipboardAsLayer).mock.calls[0]
    expect(calcId).toBe(CALC)
    expect(sent).toHaveLength(2) // both features go up, exactly (no merging into one)
    expect(sent.map((f) => f.properties)).toEqual([{ name: 'One' }, { name: 'Two' }])
    expect(sent[0].geometry).toEqual(poly(85).geometry)
    expect(name).toContain('Blocks')

    const st = useWorkspaceStore.getState()
    expect(st.importedLayers.map((l) => l.id)).toContain(50)
    expect(st.importedLayers.find((l) => l.id === 50)).toMatchObject({ purpose: 'other', visible: true })
    expect(st.importedLayerFeatures[50]).toHaveLength(2)
    expect(st.activeImportedLayerId).toBe(50)
    expect(vi.mocked(message.success).mock.calls[0][0]).toContain('editing.paste.layerCreated')
  })

  it('does not name the layer after an existing one', async () => {
    useWorkspaceStore.setState({
      importedLayers: [{ id: 9, name: 'Blocks editing.paste.layerSuffix', purpose: 'other', format: 'geojson', featureCount: 1, geometryTypes: [], visible: true, order: 0 }],
    })
    vi.mocked(importClipboardAsLayer).mockResolvedValue({ id: 51, name: 'x', featureCount: 2, geometryTypes: [] })
    clip()
    const { result } = mount()
    await act(async () => { await result.current.pasteAsLayer() })
    expect(vi.mocked(importClipboardAsLayer).mock.calls[0][2]).toBe('Blocks editing.paste.layerSuffix 2')
  })

  it('reports a refused import and leaves the workspace untouched', async () => {
    vi.mocked(importClipboardAsLayer).mockRejectedValue(new PasteRejectedError(413, 'File too large'))
    clip()
    const { result } = mount()
    await act(async () => { await result.current.pasteAsLayer() })
    expect(message.error).toHaveBeenCalledWith('File too large')
    expect(useWorkspaceStore.getState().importedLayers).toEqual([])
    expect(useWorkspaceStore.getState().activeImportedLayerId).toBeNull()
  })

  it('does nothing (and says why) with an empty clipboard', async () => {
    const { result } = mount()
    await act(async () => { await result.current.pasteAsLayer() })
    expect(importClipboardAsLayer).not.toHaveBeenCalled()
    expect(vi.mocked(message.warning).mock.calls[0][0]).toContain('editing.paste.reason.empty_clipboard')
  })
})

describe('From a layer context menu (a layer other than the active one)', () => {
  const point = (props: Record<string, unknown> = {}): GeoJSON.Feature => ({
    type: 'Feature', geometry: { type: 'Point', coordinates: [85, 27] }, properties: props,
  })
  const clip = (features: GeoJSON.Feature[]) =>
    useFeatureClipboardStore.setState({
      clipboard: { calcId: CALC, sourceLayerKey: 'blocks', sourceLabel: 'Blocks', wholeLayer: false, features, copiedAt: 1 },
    })

  beforeEach(() => {
    layerData.blocks = [poly(85, { id: 'b1', name: 'One' }), poly(86, { id: 'b2', name: 'Two' })]
    layerData.sub_areas = [poly(90, { id: 's1', name: 'Existing' })]
  })

  it('Copy takes the named layer, not the active one', () => {
    const { result } = mount()
    selectIn('sub_areas', [])
    act(() => { result.current.copy({ layerKey: 'blocks' }) })
    const cb = useFeatureClipboardStore.getState().clipboard!
    expect(cb.sourceLayerKey).toBe('blocks')
    expect(cb.features).toHaveLength(2)
    expect(cb.wholeLayer).toBe(true)
  })

  it('Copy takes that layer own selection when it has one', () => {
    const { result } = mount()
    selectIn('blocks', ['b2']) // the selection lives in blocks...
    act(() => { useWorkspaceStore.setState({ activeLayerId: 'sub_areas' as never }) }) // ...but sub_areas is active
    act(() => { result.current.copy({ layerKey: 'blocks' }) })
    const cb = useFeatureClipboardStore.getState().clipboard!
    expect(cb.features.map((f) => f.properties)).toEqual([{ name: 'Two' }])
    expect(cb.wholeLayer).toBe(false)
  })

  it('a selection in some OTHER layer is not mistaken for this layer selection', () => {
    const { result } = mount()
    selectIn('sub_areas', ['s1'])
    act(() => { result.current.copy({ layerKey: 'blocks' }) })
    expect(useFeatureClipboardStore.getState().clipboard!.features).toHaveLength(2) // the whole blocks layer
  })

  it('Copy of explicit features (a single row) copies exactly those', () => {
    const { result } = mount()
    selectIn('blocks', [])
    act(() => { result.current.copy({ features: [layerData.blocks[1]] }) })
    const cb = useFeatureClipboardStore.getState().clipboard!
    expect(cb.features).toHaveLength(1)
    expect(cb.features[0].properties).toEqual({ name: 'Two' })
    expect(cb.wholeLayer).toBe(false)
  })

  it('Copy from a layer with nothing to copy says so instead of overwriting the clipboard', () => {
    clip([poly(1, { name: 'kept' })])
    layerData.fieldbook = []
    const { result } = mount()
    act(() => { result.current.copy({ layerKey: 'fieldbook' }) })
    expect(message.warning).toHaveBeenCalledWith('editing.copy.nothing')
    expect(useFeatureClipboardStore.getState().clipboard!.features[0].properties).toEqual({ name: 'kept' })
  })

  it('Paste goes into the named layer even though another one is active', async () => {
    clip([poly(85, { name: 'Ridge', category: 'protected' })])
    vi.mocked(createSubAreaFromPaste).mockImplementation(async (_c, body) => ({ id: 'n1', geometry: body.geometry }))
    const { result } = mount()
    selectIn('blocks', []) // blocks is active: a plain toolbar paste would be refused here
    await act(async () => { await result.current.paste('sub_areas') })
    expect(createSubAreaFromPaste).toHaveBeenCalledTimes(1)
    expect(vi.mocked(createSubAreaFromPaste).mock.calls[0][1].name).toBe('Ridge')
  })

  it('Paste into a named layer that cannot take it is refused with the reason', async () => {
    clip([poly(85, { name: 'X', category: 'protected' })])
    const { result } = mount()
    selectIn('sub_areas', [])
    await act(async () => { await result.current.paste('blocks') })
    expect(createSubAreaFromPaste).not.toHaveBeenCalled()
    expect(vi.mocked(message.warning).mock.calls[0][0]).toContain('editing.paste.reason.layer_not_pastable')
  })

  it('Paste into an imported layer addresses it as imported:<id>', async () => {
    useWorkspaceStore.setState({
      importedLayers: [{ id: 7, name: 'Notes', purpose: 'other', format: 'geojson', featureCount: 1, geometryTypes: [], visible: true, order: 0 }],
      importedLayerFeatures: { 7: [poly(80, { featureId: 'old' })] },
    })
    clip([poly(85, { name: 'N' })])
    vi.mocked(fetchImportedFeatures).mockResolvedValue([poly(80, { featureId: 'old' }), poly(85, { featureId: 'n', name: 'N' })])
    const { result } = mount()
    selectIn('blocks', [])
    await act(async () => { await result.current.paste('imported:7') })
    expect(vi.mocked(appendFeaturesToImportedLayer).mock.calls[0][1]).toBe(7)
  })

  describe('pasteStateFor: what a layer menu is told', () => {
    it("is 'never' for layers that can never take a paste", () => {
      clip([poly(85, { category: 'protected' })])
      const { result } = mount()
      for (const key of ['boundary', 'blocks', 'compartments', 'sub_compartments', 'sample_plots', 'fieldbook', 'activity_features']) {
        expect(result.current.pasteStateFor(key)).toBe('never')
      }
    })

    it('is null for sub-areas when polygons are waiting', () => {
      clip([poly(85, { category: 'protected' })])
      const { result } = mount()
      expect(result.current.pasteStateFor('sub_areas')).toBeNull()
    })

    it('gives the reason (not never) for a state that can change: empty clipboard, wrong geometry, locked', () => {
      const first = mount()
      expect(first.result.current.pasteStateFor('sub_areas')).toMatchObject({ reasonKey: 'editing.paste.reason.empty_clipboard' })

      clip([point()])
      const second = mount()
      expect(second.result.current.pasteStateFor('sub_areas')).toEqual({
        reasonKey: 'editing.paste.reason.geometry_mismatch', params: { have: 'Point', need: 'Polygon' },
      })

      clip([poly(85, { category: 'protected' })])
      act(() => { useWorkspaceStore.setState({ structureLocked: true }) })
      const third = mount()
      expect(third.result.current.pasteStateFor('sub_areas')).toMatchObject({ reasonKey: 'editing.paste.reason.structure_locked' })
    })

    it('an imported layer: free-form purposes accept, topology purposes never do', () => {
      useWorkspaceStore.setState({
        importedLayers: [
          { id: 1, name: 'Free', purpose: 'other', format: 'geojson', featureCount: 0, geometryTypes: [], visible: true, order: 0 },
          { id: 2, name: 'Blocks import', purpose: 'blocks', format: 'geojson', featureCount: 0, geometryTypes: [], visible: true, order: 1 },
        ],
      })
      clip([poly(85)])
      const { result } = mount()
      expect(result.current.pasteStateFor('imported:1')).toBeNull()
      expect(result.current.pasteStateFor('imported:2')).toBe('never')
    })

    it('the active-layer answer follows the active layer', () => {
      clip([poly(85, { category: 'protected' })])
      const { result } = mount()
      selectIn('sub_areas', [])
      expect(result.current.activePasteState).toBeNull()
      selectIn('blocks', [])
      expect(result.current.activePasteState).toBe('never')
    })
  })

  it('selectedCountFor counts only the layer the selection belongs to', () => {
    const { result } = mount()
    selectIn('blocks', ['b1', 'b2'])
    expect(result.current.selectedCountFor('blocks')).toBe(2)
    expect(result.current.selectedCountFor('sub_areas')).toBe(0)
  })
})
