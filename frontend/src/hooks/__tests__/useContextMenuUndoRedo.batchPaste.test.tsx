import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import type { GeoJSON } from 'geojson'

vi.mock('../../lib/featureRowOps', () => ({
  deleteFeatureRow: vi.fn(async () => ({})),
  restoreFeatureRow: vi.fn(async () => ({})),
}))
vi.mock('../../lib/featurePasteApi', () => ({
  createSubAreaFromPaste: vi.fn(),
  appendFeaturesToImportedLayer: vi.fn(async () => undefined),
  fetchImportedFeatures: vi.fn(async () => []),
}))

import { deleteFeatureRow, restoreFeatureRow } from '../../lib/featureRowOps'
import {
  createSubAreaFromPaste,
  appendFeaturesToImportedLayer,
  fetchImportedFeatures,
} from '../../lib/featurePasteApi'
import { useContextMenuUndoRedo } from '../useContextMenuUndoRedo'
import {
  createBatchOperation,
  createFeatureDeleteOperation,
  createFeaturePasteOperation,
} from '../../lib/operationFactories'
import { useWorkspaceStore } from '../../store/workspaceStore'

const CALC = 'calc-1'
const feat = (name: string): GeoJSON.Feature => ({
  type: 'Feature',
  geometry: { type: 'Point', coordinates: [85, 27] },
  properties: { name },
})

/** A layer delete op the way MapWorkspace records it for an imported row. */
const importedDelete = (index: number) =>
  createFeatureDeleteOperation(CALC, 'import_7', `f${index}`, { feature: feat(`row${index}`) }, 'user', {
    importLayerId: 7, featureIndex: index,
  })

const indicesOf = (fn: unknown): Array<number | undefined> =>
  (fn as ReturnType<typeof vi.fn>).mock.calls.map((c) => (c[0] as { featureIndex?: number }).featureIndex)

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  useWorkspaceStore.setState({ importedLayerFeatures: { 7: [feat('a'), feat('b'), feat('c'), feat('d'), feat('e'), feat('f')] } })
})

describe('batch undo / redo (multi-delete is ONE history step)', () => {
  it('undo restores the deleted rows lowest index first, one at a time', async () => {
    let inFlight = 0
    let maxInFlight = 0
    vi.mocked(restoreFeatureRow).mockImplementation(async () => {
      inFlight += 1
      maxInFlight = Math.max(maxInFlight, inFlight)
      await new Promise((r) => setTimeout(r, 5))
      inFlight -= 1
      return {} as never
    })
    const { result } = renderHook(() => useContextMenuUndoRedo())

    // Executed highest index first (so each recorded index stayed valid).
    const batch = createBatchOperation([importedDelete(5), importedDelete(2), importedDelete(0)], { label: 'Delete 3' })
    act(() => { result.current.pushOp(batch) })
    await waitFor(() => expect(result.current.canUndo).toBe(true))

    act(() => { result.current.undo() })
    await waitFor(() => expect(restoreFeatureRow).toHaveBeenCalledTimes(3))

    expect(indicesOf(restoreFeatureRow)).toEqual([0, 2, 5]) // reverse of execution order
    expect(maxInFlight).toBe(1) // never two restores racing on the same list
  })

  it('redo replays the deletes in the original order', async () => {
    const { result } = renderHook(() => useContextMenuUndoRedo())
    const batch = createBatchOperation([importedDelete(5), importedDelete(2), importedDelete(0)], { label: 'Delete 3' })
    act(() => { result.current.pushOp(batch) })
    await waitFor(() => expect(result.current.canUndo).toBe(true))

    act(() => { result.current.undo() })
    await waitFor(() => expect(restoreFeatureRow).toHaveBeenCalledTimes(3))
    await waitFor(() => expect(result.current.canRedo).toBe(true))

    act(() => { result.current.redo() })
    await waitFor(() => expect(deleteFeatureRow).toHaveBeenCalledTimes(3))
    expect(indicesOf(deleteFeatureRow)).toEqual([5, 2, 0])
  })

  it('a single ordinary delete still undoes through the same path', async () => {
    const { result } = renderHook(() => useContextMenuUndoRedo())
    act(() => { result.current.pushOp(importedDelete(3)) })
    await waitFor(() => expect(result.current.canUndo).toBe(true))
    act(() => { result.current.undo() })
    await waitFor(() => expect(restoreFeatureRow).toHaveBeenCalledTimes(1))
    expect(indicesOf(restoreFeatureRow)).toEqual([3])
  })
})

describe('paste undo / redo', () => {
  it('sub-areas: undo deletes what the paste created; redo re-creates and the next undo removes the NEW ids', async () => {
    vi.mocked(createSubAreaFromPaste)
      .mockResolvedValueOnce({ id: 'new-1', geometry: feat('x').geometry })
      .mockResolvedValueOnce({ id: 'new-2', geometry: feat('x').geometry })
    const bodies = [
      { name: 'A', category: 'protected', geometry: feat('a').geometry, is_excluded: false },
      { name: 'B', category: 'protected', geometry: feat('b').geometry, is_excluded: false },
    ]
    const op = createFeaturePasteOperation(CALC, 'sub_areas', [feat('a'), feat('b')], ['old-1', 'old-2'], 'user', { payloads: bodies })
    const { result } = renderHook(() => useContextMenuUndoRedo())
    act(() => { result.current.pushOp(op) })
    await waitFor(() => expect(result.current.canUndo).toBe(true))

    act(() => { result.current.undo() })
    await waitFor(() => expect(deleteFeatureRow).toHaveBeenCalledTimes(2))
    expect(vi.mocked(deleteFeatureRow).mock.calls.map((c) => c[0].featureId)).toEqual(['old-2', 'old-1'])

    await waitFor(() => expect(result.current.canRedo).toBe(true))
    act(() => { result.current.redo() })
    await waitFor(() => expect(createSubAreaFromPaste).toHaveBeenCalledTimes(2))
    expect(vi.mocked(createSubAreaFromPaste).mock.calls.map((c) => c[1].name)).toEqual(['A', 'B'])
    await waitFor(() => expect(op.state.createdIds).toEqual(['new-1', 'new-2']))

    vi.mocked(deleteFeatureRow).mockClear()
    act(() => { result.current.undo() })
    await waitFor(() => expect(deleteFeatureRow).toHaveBeenCalledTimes(2))
    expect(vi.mocked(deleteFeatureRow).mock.calls.map((c) => c[0].featureId)).toEqual(['new-2', 'new-1'])
  })

  it('imported layer: undo deletes the appended tail from the highest index down; redo appends again', async () => {
    const pasted = [feat('p1'), feat('p2'), feat('p3')]
    const op = createFeaturePasteOperation(CALC, 'import_7', pasted, ['t1', 't2', 't3'], 'user', {
      importLayerId: 7, baseIndex: 6,
    })
    const { result } = renderHook(() => useContextMenuUndoRedo())
    act(() => { result.current.pushOp(op) })
    await waitFor(() => expect(result.current.canUndo).toBe(true))

    act(() => { result.current.undo() })
    await waitFor(() => expect(deleteFeatureRow).toHaveBeenCalledTimes(3))
    expect(indicesOf(deleteFeatureRow)).toEqual([8, 7, 6])
    expect(fetchImportedFeatures).toHaveBeenCalledWith(CALC, 7)

    await waitFor(() => expect(result.current.canRedo).toBe(true))
    act(() => { result.current.redo() })
    await waitFor(() => expect(appendFeaturesToImportedLayer).toHaveBeenCalledTimes(1))
    expect(vi.mocked(appendFeaturesToImportedLayer).mock.calls[0][3]).toBe('append')
  })
})
