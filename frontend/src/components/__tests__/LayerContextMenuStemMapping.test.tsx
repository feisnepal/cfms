import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import LayerContextMenu from '../LayerContextMenu'

// t(key, params) -> "key|{params}" so a test can assert both the label and its values.
vi.mock('../../i18n/hooks', () => ({
  useT: () => (key: string, params?: Record<string, unknown>) => (params ? `${key}|${JSON.stringify(params)}` : key),
}))
vi.mock('../../hooks/useContextMenuUndoRedo', () => ({
  useContextMenuUndoRedo: () => ({
    canUndo: false, canRedo: false, undo: vi.fn(), redo: vi.fn(), pushOp: vi.fn(), pushAndExecute: vi.fn(),
  }),
}))

const base = {
  layerId: 'stem_mapping',
  layerType: 'builtin' as const,
  layerName: 'Stem Mapping',
  visible: true,
  labelsShown: false,
  featureCount: 0,
  editable: false,
  readOnly: true,
  locked: false,
  counts: { boundary: 1 },
  position: { x: 10, y: 10 },
  onClose: vi.fn(),
  map: null,
}

const item = (name: RegExp) => screen.getByRole('menuitem', { name })
const has = (name: RegExp) => screen.queryByRole('menuitem', { name }) != null

describe('LayerContextMenu — Import Stem Mapping', () => {
  it('runs the host handler and closes the menu', () => {
    const onImportStemMapping = vi.fn()
    const onClose = vi.fn()
    render(<LayerContextMenu {...base} onClose={onClose} onImportStemMapping={onImportStemMapping} />)

    fireEvent.click(item(/layerPanel\.importStemMapping/))

    expect(onImportStemMapping).toHaveBeenCalledTimes(1)
    expect(onClose).toHaveBeenCalled()
  })

  it('stays enabled even when a census already exists — delete/re-import lives in the modal', () => {
    const onImportStemMapping = vi.fn()
    render(<LayerContextMenu {...base} featureCount={161} onImportStemMapping={onImportStemMapping} />)

    const imp = item(/layerPanel\.importStemMapping/)
    expect(imp.getAttribute('aria-disabled')).toBeNull()
    fireEvent.click(imp)
    expect(onImportStemMapping).toHaveBeenCalledTimes(1)
  })

  it('is left out when the host wires no handler', () => {
    render(<LayerContextMenu {...base} />)
    expect(has(/layerPanel\.importStemMapping/)).toBe(false)
  })

  it('is not offered on other layers even when a handler is wired', () => {
    render(<LayerContextMenu {...base} layerId="blocks" layerName="Blocks" onImportStemMapping={vi.fn()} />)
    expect(has(/layerPanel\.importStemMapping/)).toBe(false)
  })

  it('never offers a danger delete/clear of its own — data is removed through the modal', () => {
    render(<LayerContextMenu {...base} onImportStemMapping={vi.fn()} />)
    expect(has(/layerPanel\.clearLayerData/)).toBe(false)
    expect(has(/layerPanel\.deleteStemMappingData/)).toBe(false)
  })
})