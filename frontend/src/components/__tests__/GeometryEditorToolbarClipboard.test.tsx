import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import GeometryEditorToolbar from '../GeometryEditorToolbar'

vi.mock('../../i18n/hooks', () => ({
  useT: () => (key: string) => key,
}))

const base = {
  geometryTypes: ['Polygon'],
  toolbarMode: 'select' as const,
  onModeChange: vi.fn(),
  canUndo: false,
  canRedo: false,
  onUndo: vi.fn(),
  onRedo: vi.fn(),
}

const copyBtn = () => screen.getByRole('button', { name: 'editing.toolbar.copy' })
const pasteBtn = () => screen.getByRole('button', { name: 'editing.toolbar.paste' })
const layerBtn = () => screen.getByRole('button', { name: 'editing.toolbar.pasteAsLayer' })
const deleteBtn = () => screen.getByRole('button', { name: 'common.delete' })

describe('GeometryEditorToolbar — Copy / Paste / Paste-as-layer / Delete', () => {
  it('Copy needs no selection: enabled with nothing selected, and calls onCopy', () => {
    const onCopy = vi.fn()
    render(<GeometryEditorToolbar {...base} selectionCount={0} canCopy onCopy={onCopy} copyTooltip="Copy all 4" />)
    expect(copyBtn()).not.toBeDisabled()
    expect(copyBtn().getAttribute('title')).toBe('Copy all 4 (Ctrl+C)')
    fireEvent.click(copyBtn())
    expect(onCopy).toHaveBeenCalledTimes(1)
  })

  it('Copy is disabled only when the layer has nothing to copy', () => {
    render(<GeometryEditorToolbar {...base} canCopy={false} onCopy={vi.fn()} />)
    expect(copyBtn()).toBeDisabled()
  })

  it('Copy still works on a locked structure — copying is not an edit — while edits stay disabled', () => {
    const onCopy = vi.fn()
    render(
      <GeometryEditorToolbar
        {...base} isLocked structureLockReason="frozen" selectionCount={2}
        canCopy onCopy={onCopy} onPaste={vi.fn()} onDeleteSelected={vi.fn()} canDelete
      />,
    )
    expect(copyBtn()).not.toBeDisabled()
    fireEvent.click(copyBtn())
    expect(onCopy).toHaveBeenCalledTimes(1)
    expect(pasteBtn()).toBeDisabled()
    expect(deleteBtn()).toBeDisabled()
  })

  it('Paste is disabled with the target layer\'s own reason as its tooltip, not a generic one', () => {
    const onPaste = vi.fn()
    render(
      <GeometryEditorToolbar
        {...base} canCopy onCopy={vi.fn()} onPaste={onPaste}
        pasteDisabledReason="This layer holds Polygon only"
      />,
    )
    expect(pasteBtn()).toBeDisabled()
    expect(pasteBtn().getAttribute('title')).toBe('This layer holds Polygon only')
    fireEvent.click(pasteBtn())
    expect(onPaste).not.toHaveBeenCalled()
  })

  it('Paste and Paste-as-layer call their handlers when nothing blocks them', () => {
    const onPaste = vi.fn()
    const onPasteAsLayer = vi.fn()
    render(
      <GeometryEditorToolbar
        {...base} canCopy onCopy={vi.fn()} onPaste={onPaste} onPasteAsLayer={onPasteAsLayer}
        pasteDisabledReason={null} pasteAsLayerDisabledReason={null}
      />,
    )
    fireEvent.click(pasteBtn())
    fireEvent.click(layerBtn())
    expect(onPaste).toHaveBeenCalledTimes(1)
    expect(onPasteAsLayer).toHaveBeenCalledTimes(1)
  })

  it('Paste-as-layer stays available when the target layer cannot take a paste (that is what it is for)', () => {
    render(
      <GeometryEditorToolbar
        {...base} canCopy onCopy={vi.fn()} onPaste={vi.fn()} onPasteAsLayer={vi.fn()}
        pasteDisabledReason="not pastable" pasteAsLayerDisabledReason={null}
      />,
    )
    expect(pasteBtn()).toBeDisabled()
    expect(layerBtn()).not.toBeDisabled()
  })

  it('Delete calls onDeleteSelected for the selection, and is disabled with none', () => {
    const onDeleteSelected = vi.fn()
    const { rerender } = render(
      <GeometryEditorToolbar {...base} selectionCount={0} canDelete={false} onDeleteSelected={onDeleteSelected} />,
    )
    expect(deleteBtn()).toBeDisabled()
    rerender(
      <GeometryEditorToolbar {...base} selectionCount={3} canDelete onDeleteSelected={onDeleteSelected} />,
    )
    expect(deleteBtn()).not.toBeDisabled()
    fireEvent.click(deleteBtn())
    expect(onDeleteSelected).toHaveBeenCalledTimes(1)
  })

  it('Delete stays disabled when the layer is not deletable even with a selection', () => {
    render(<GeometryEditorToolbar {...base} selectionCount={3} canDelete={false} onDeleteSelected={vi.fn()} />)
    expect(deleteBtn()).toBeDisabled()
  })

  it('the old, unwired Duplicate button is gone', () => {
    render(<GeometryEditorToolbar {...base} canCopy onCopy={vi.fn()} />)
    expect(screen.queryByRole('button', { name: 'editing.toolbar.duplicate' })).toBeNull()
  })
})
