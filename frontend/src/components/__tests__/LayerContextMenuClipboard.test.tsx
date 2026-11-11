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
  layerId: 'sub_areas',
  layerType: 'builtin' as const,
  layerName: 'Sub-Areas',
  visible: true,
  labelsShown: false,
  featureCount: 4,
  editable: true,
  locked: false,
  position: { x: 10, y: 10 },
  onClose: vi.fn(),
  map: null,
}

// Copy / paste live under the "Advanced" fly-out: open it when the row is not on the main list.
const openAdvanced = () => {
  const parent = screen.queryByRole('menuitem', { name: /layerPanel\.advanced/ })
  if (parent) fireEvent.mouseEnter(parent)
}
const item = (name: RegExp) => {
  if (!screen.queryByRole('menuitem', { name })) openAdvanced()
  return screen.getByRole('menuitem', { name })
}
const has = (name: RegExp) => {
  openAdvanced()
  return screen.queryByRole('menuitem', { name }) != null
}

describe('LayerContextMenu — feature clipboard commands', () => {
  it('shows Copy, Paste here and Paste as new layer and runs them for THIS layer', () => {
    const onCopyFeatures = vi.fn()
    const onPasteFeatures = vi.fn()
    const onPasteAsLayer = vi.fn()
    const onClose = vi.fn()
    render(
      <LayerContextMenu
        {...base}
        onClose={onClose}
        clipboardMenu={{ selectedCount: 0, clipboardCount: 3, paste: null }}
        onCopyFeatures={onCopyFeatures}
        onPasteFeatures={onPasteFeatures}
        onPasteAsLayer={onPasteAsLayer}
      />,
    )

    fireEvent.click(item(/layerPanel\.copyAll/))
    expect(onCopyFeatures).toHaveBeenCalledWith('sub_areas', 'builtin')
    expect(onClose).toHaveBeenCalled()

    fireEvent.click(item(/layerPanel\.pasteHere/))
    expect(onPasteFeatures).toHaveBeenCalledWith('sub_areas', 'builtin')

    fireEvent.click(item(/layerPanel\.pasteAsLayer/))
    expect(onPasteAsLayer).toHaveBeenCalledTimes(1)
  })

  it('Copy names the selection when there is one', () => {
    render(
      <LayerContextMenu
        {...base}
        clipboardMenu={{ selectedCount: 2, clipboardCount: 0, paste: null }}
        onCopyFeatures={vi.fn()}
        onPasteFeatures={vi.fn()}
        onPasteAsLayer={vi.fn()}
      />,
    )
    expect(item(/layerPanel\.copySelected\|\{"count":2\}/)).toBeTruthy()
  })

  it('a disabled Paste does nothing when clicked, and its reason (with parameters) is on the item', () => {
    const onPasteFeatures = vi.fn()
    render(
      <LayerContextMenu
        {...base}
        clipboardMenu={{
          selectedCount: 0,
          clipboardCount: 3,
          paste: { reasonKey: 'editing.paste.reason.geometry_mismatch', params: { have: 'Point', need: 'Polygon' } },
        }}
        onCopyFeatures={vi.fn()}
        onPasteFeatures={onPasteFeatures}
        onPasteAsLayer={vi.fn()}
      />,
    )
    const paste = item(/layerPanel\.pasteHere/)
    expect(paste.getAttribute('aria-disabled')).toBe('true')
    expect(paste.getAttribute('title')).toContain('editing.paste.reason.geometry_mismatch')
    expect(paste.getAttribute('title')).toContain('"need":"Polygon"')
    fireEvent.click(paste)
    expect(onPasteFeatures).not.toHaveBeenCalled()
  })

  it('leaves Paste out on a layer that can never take one, but keeps Copy and Paste as new layer', () => {
    render(
      <LayerContextMenu
        {...base}
        layerId="blocks"
        layerName="Blocks"
        clipboardMenu={{ selectedCount: 0, clipboardCount: 3, paste: 'never' }}
        onCopyFeatures={vi.fn()}
        onPasteFeatures={vi.fn()}
        onPasteAsLayer={vi.fn()}
      />,
    )
    expect(has(/layerPanel\.copyAll/)).toBe(true)
    expect(has(/layerPanel\.pasteHere/)).toBe(false)
    expect(has(/layerPanel\.pasteAsLayer/)).toBe(true)
  })

  it('Paste as new layer is disabled while nothing has been copied', () => {
    const onPasteAsLayer = vi.fn()
    render(
      <LayerContextMenu
        {...base}
        clipboardMenu={{ selectedCount: 0, clipboardCount: 0, paste: { reasonKey: 'editing.paste.reason.empty_clipboard' } }}
        onCopyFeatures={vi.fn()}
        onPasteFeatures={vi.fn()}
        onPasteAsLayer={onPasteAsLayer}
      />,
    )
    const asLayer = item(/layerPanel\.pasteAsLayer/)
    expect(asLayer.getAttribute('aria-disabled')).toBe('true')
    fireEvent.click(asLayer)
    expect(onPasteAsLayer).not.toHaveBeenCalled()
  })

  it('a host that wires no clipboard handlers gets none of the three commands', () => {
    render(<LayerContextMenu {...base} />)
    expect(has(/layerPanel\.copy/)).toBe(false)
    expect(has(/layerPanel\.pasteHere/)).toBe(false)
    expect(has(/layerPanel\.pasteAsLayer/)).toBe(false)
  })

  it('an imported layer is addressed by its own id and type', () => {
    const onCopyFeatures = vi.fn()
    render(
      <LayerContextMenu
        {...base}
        layerId="12"
        layerType="imported"
        layerName="My import"
        purpose="other"
        clipboardMenu={{ selectedCount: 0, clipboardCount: 0, paste: null }}
        onCopyFeatures={onCopyFeatures}
        onPasteFeatures={vi.fn()}
        onPasteAsLayer={vi.fn()}
      />,
    )
    fireEvent.click(item(/layerPanel\.copyAll/))
    expect(onCopyFeatures).toHaveBeenCalledWith('12', 'imported')
  })
})
