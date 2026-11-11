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
  layerId: 'user_group',
  layerType: 'builtin' as const,
  layerName: 'User Group Boundary',
  visible: true,
  labelsShown: false,
  featureCount: 0,
  editable: false,
  locked: false,
  counts: { boundary: 1 },
  position: { x: 10, y: 10 },
  onClose: vi.fn(),
  map: null,
}

const item = (name: RegExp) => screen.getByRole('menuitem', { name })
const has = (name: RegExp) => screen.queryByRole('menuitem', { name }) != null

describe('LayerContextMenu — User Group Analysis', () => {
  it('runs the host handler and closes the menu', () => {
    const onUserGroupAnalysis = vi.fn()
    const onClose = vi.fn()
    render(<LayerContextMenu {...base} featureCount={1} onClose={onClose} onUserGroupAnalysis={onUserGroupAnalysis} />)

    fireEvent.click(item(/workspace\.userGroup\.analysisTitle/))

    expect(onUserGroupAnalysis).toHaveBeenCalledTimes(1)
    expect(onClose).toHaveBeenCalled()
  })

  it('is disabled (with the no-extent reason) when the layer has no features', () => {
    const onUserGroupAnalysis = vi.fn()
    render(<LayerContextMenu {...base} featureCount={0} onUserGroupAnalysis={onUserGroupAnalysis} />)

    const imp = item(/workspace\.userGroup\.analysisTitle/)
    expect(imp.getAttribute('aria-disabled')).toBe('true')
    expect(imp.getAttribute('aria-describedby')).toBeTruthy()
  })

  it('is left out when the host wires no handler', () => {
    render(<LayerContextMenu {...base} />)
    expect(has(/workspace\.userGroup\.analysisTitle/)).toBe(false)
  })

  it('is not offered on other layers even when a handler is wired', () => {
    render(<LayerContextMenu {...base} layerId="blocks" layerName="Blocks" onUserGroupAnalysis={vi.fn()} />)
    expect(has(/workspace\.userGroup\.analysisTitle/)).toBe(false)
  })

  it('auto-buffer is still offered alongside the analysis command', () => {
    render(<LayerContextMenu {...base} featureCount={1} onUserGroupAnalysis={vi.fn()} />)
    expect(has(/workspace\.userGroup\.autoBuffer/)).toBe(true)
    expect(has(/workspace\.userGroup\.analysisTitle/)).toBe(true)
  })
})