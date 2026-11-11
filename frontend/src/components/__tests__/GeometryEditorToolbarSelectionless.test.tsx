import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import GeometryEditorToolbar, { vertexTooltipKey } from '../GeometryEditorToolbar'

vi.mock('../../i18n/hooks', () => ({
  useT: () => (key: string) => key,
}))

describe('GeometryEditorToolbar — selectionless vertex_edit (V-3)', () => {
  it('vertex_edit enables with zero selections on a polygon layer; split/merge still require a row; move is not offered on polygons', () => {
    render(
      <GeometryEditorToolbar
        geometryTypes={['Polygon']}
        toolbarMode="select"
        onModeChange={vi.fn()}
        canUndo={false}
        canRedo={false}
        onUndo={vi.fn()}
        onRedo={vi.fn()}
        selectionCount={0}
      />,
    )
    expect(screen.getByRole('button', { name: 'editing.toolbar.vertices' })).not.toBeDisabled()
    expect(screen.getByRole('button', { name: 'editing.toolbar.split' })).toBeDisabled()
    // Move is point-only — it is not rendered at all on a polygon layer.
    expect(screen.queryByRole('button', { name: 'editing.toolbar.move' })).toBeNull()
  })

  it('vertex_edit also works on line layers (polyline skeletons) without selection', () => {
    render(
      <GeometryEditorToolbar
        geometryTypes={['LineString']}
        toolbarMode="select"
        onModeChange={vi.fn()}
        canUndo={false}
        canRedo={false}
        onUndo={vi.fn()}
        onRedo={vi.fn()}
        selectionCount={0}
      />,
    )
    expect(screen.getByRole('button', { name: 'editing.toolbar.vertices' })).not.toBeDisabled()
  })
})

/**
 * VR-4.1 — the vertex button's identity.  The old button used `SquarePen`
 * (the universal "edit / rename a record" glyph, and a near-twin of
 * draw_polygon's `Square`), the only verb-phrase label in a toolbar of nouns,
 * and a tooltip that promised unrestricted editing while Rules A/B lock most
 * vertices.
 */
describe('GeometryEditorToolbar — vertex tool identity (VR-4.1)', () => {
  const base = {
    geometryTypes: ['Polygon'],
    toolbarMode: 'select' as const,
    onModeChange: vi.fn(),
    canUndo: false,
    canRedo: false,
    onUndo: vi.fn(),
    onRedo: vi.fn(),
    selectionCount: 0,
  }

  it('renders the spline (node-tool) glyph, not the edit-record pencil', () => {
    render(<GeometryEditorToolbar {...base} />)
    const btn = screen.getByRole('button', { name: 'editing.toolbar.vertices' })
    const svg = btn.querySelector('svg')
    expect(svg?.getAttribute('class') || '').toContain('lucide-spline')
    expect(svg?.getAttribute('class') || '').not.toContain('square-pen')
  })

  it('is greyed out with a lock reason when the boundary is locked by structure', () => {
    render(<GeometryEditorToolbar {...base} layerId="boundary" vertexLockReason="boundary_locked" />)
    const btn = screen.getByRole('button', { name: 'editing.toolbar.vertices' })
    expect(btn).toBeDisabled()
    expect(btn.getAttribute('title')).toContain('editing.toolbar.editVertexTooltipLocked')
  })

  it('stays enabled on an unlocked boundary', () => {
    render(<GeometryEditorToolbar {...base} layerId="boundary" />)
    const btn = screen.getByRole('button', { name: 'editing.toolbar.vertices' })
    expect(btn).not.toBeDisabled()
    expect(btn.getAttribute('title')).toContain('editing.toolbar.editVertexTooltipBoundary')
  })

  it('tells structural layers that only shared edges move', () => {
    render(<GeometryEditorToolbar {...base} layerId="blocks" />)
    const btn = screen.getByRole('button', { name: 'editing.toolbar.vertices' })
    expect(btn.getAttribute('title')).toContain('editing.toolbar.editVertexTooltipShared')
  })

  it('appends the shortcut exactly once', () => {
    // Regression for "फिचरहरू चयन गर्नुहोस् (Esc) (Esc)" — selectTooltip used
    // to carry its own "(Esc)" while the composer appended another.
    render(<GeometryEditorToolbar {...base} />)
    const select = screen.getByRole('button', { name: 'editing.toolbar.select' })
    const title = select.getAttribute('title') || ''
    expect(title).toBe('editing.toolbar.selectTooltip (Esc)')
    expect(title.match(/\(Esc\)/g)).toHaveLength(1)
  })

  it('vertexTooltipKey maps every layer to its rule', () => {
    expect(vertexTooltipKey('boundary', 'boundary_locked')).toBe('editing.toolbar.editVertexTooltipLocked')
    expect(vertexTooltipKey('boundary', null)).toBe('editing.toolbar.editVertexTooltipBoundary')
    expect(vertexTooltipKey('blocks', null)).toBe('editing.toolbar.editVertexTooltipShared')
    expect(vertexTooltipKey('sub_blocks', null)).toBe('editing.toolbar.editVertexTooltipShared')
    expect(vertexTooltipKey('compartments', null)).toBe('editing.toolbar.editVertexTooltipShared')
    expect(vertexTooltipKey('sub_compartments', null)).toBe('editing.toolbar.editVertexTooltipShared')
    expect(vertexTooltipKey('sub_areas', null)).toBe('editing.toolbar.editVertexTooltipFree')
    expect(vertexTooltipKey(null, null)).toBe('editing.toolbar.editVertexTooltip')
  })
})
