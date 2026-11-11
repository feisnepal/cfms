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
  layerId: 'sample_plots',
  layerType: 'builtin' as const,
  layerName: 'Sample Plots',
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

describe('LayerContextMenu — Create sample plots', () => {
  it('runs the host handler and closes the menu', () => {
    const onCreateSamplePlots = vi.fn()
    const onClose = vi.fn()
    render(<LayerContextMenu {...base} onClose={onClose} onCreateSamplePlots={onCreateSamplePlots} />)

    fireEvent.click(item(/layerPanel\.createSamplePlots/))

    expect(onCreateSamplePlots).toHaveBeenCalledTimes(1)
    expect(onClose).toHaveBeenCalled()
  })

  it('a disabled command does nothing when clicked, and says why', () => {
    const onCreateSamplePlots = vi.fn()
    render(<LayerContextMenu {...base} featureCount={30} onCreateSamplePlots={onCreateSamplePlots} />)

    const create = item(/layerPanel\.createSamplePlots/)
    expect(create.getAttribute('aria-disabled')).toBe('true')
    expect(create.getAttribute('title')).toContain('layerPanel.samplePlotsExist')
    fireEvent.click(create)
    expect(onCreateSamplePlots).not.toHaveBeenCalled()
  })

  it('is left out when the host wires no handler', () => {
    render(<LayerContextMenu {...base} />)
    expect(has(/layerPanel\.createSamplePlots/)).toBe(false)
  })

  it('is not offered on other layers even when a handler is wired', () => {
    render(<LayerContextMenu {...base} layerId="blocks" layerName="Blocks" onCreateSamplePlots={vi.fn()} />)
    expect(has(/layerPanel\.createSamplePlots/)).toBe(false)
  })
})
