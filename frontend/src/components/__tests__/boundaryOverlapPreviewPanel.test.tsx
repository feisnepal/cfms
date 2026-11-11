import { describe, it, expect, vi, beforeEach, beforeAll } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

beforeAll(() => {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  })
  // jsdom lacks a usable getComputedStyle for these mocked map primitives.
  window.getComputedStyle = vi.fn(() => ({ getPropertyValue: () => '' }) as unknown as CSSStyleDeclaration)
  // jsdom lacks ResizeObserver; react-leaflet's measured container needs it.
  window.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof window.ResizeObserver
})

// PE-7 — shared mutable ref the mocked `Marker`/`CircleMarker` read when a
// test fires a simulated interaction, since a real Leaflet drag (mouse
// physics against `getBoundingClientRect`) does not work in jsdom. Vertex
// markers are identified by their real `position` prop (lat/lng), which the
// mock also renders as data attributes.
const { dragTargetRef } = vi.hoisted(() => ({ dragTargetRef: { current: { lat: 0, lng: 0 } } }))

vi.mock('react-leaflet', () => ({
  MapContainer: ({ children }: { children: React.ReactNode }) => <div data-testid="mock-map">{children}</div>,
  TileLayer: () => <div data-testid="tile-layer" />,
  GeoJSON: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="mock-geojson">{children}</div>
  ),
  Tooltip: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="mock-tooltip">{children}</div>
  ),
  useMap: () => ({ fitBounds: vi.fn() }),
  // PE-2 — vertex marker. `onClick` simulates a Leaflet `dragend` landing on
  // `dragTargetRef.current`; `onDoubleClick` simulates the delete gesture.
  Marker: ({ position, eventHandlers }: any) => (
    <button
      type="button"
      data-testid="mock-vertex-marker"
      data-lat={position[0]}
      data-lng={position[1]}
      onClick={() => eventHandlers?.dragend?.({ target: { getLatLng: () => dragTargetRef.current } })}
      onDoubleClick={() => eventHandlers?.dblclick?.({})}
    />
  ),
  // PE-2 — segment-midpoint "insert vertex" handle.
  CircleMarker: ({ center, eventHandlers }: any) => (
    <button
      type="button"
      data-testid="mock-midpoint-marker"
      data-lat={center[0]}
      data-lng={center[1]}
      onClick={() => eventHandlers?.click?.({})}
    />
  ),
  // PE-4b — live in-drag overlap segment; rendering is not under test here.
  Polyline: () => <div data-testid="mock-polyline" />,
}))

const mockPreview = vi.fn()
const mockConfirm = vi.fn()
const mockApiPost = vi.fn()

vi.mock('../../services/api', () => ({
  default: { post: (...args: unknown[]) => mockApiPost(...args) },
  forestApi: {
    previewBoundaryOverlap: (...args: unknown[]) => mockPreview(...args),
    confirmBoundary: (...args: unknown[]) => mockConfirm(...args),
  },
  boundaryApi: {
    previewBoundaryOverlap: (...args: unknown[]) => mockPreview(...args),
    confirmBoundary: (...args: unknown[]) => mockConfirm(...args),
  },
}))

vi.mock('../../hooks/useNearbyForests', () => ({
  getBoundaryStatusStyle: () => ({ color: '#228B22', fillColor: '#228B22' }),
  BOUNDARY_STATUS_STYLES: { draft: {}, validated: {} },
}))

vi.mock('antd', async () => {
  const actual = await vi.importActual<typeof import('antd')>('antd')
  return { ...actual, message: { success: vi.fn(), error: vi.fn(), warning: vi.fn() } }
})

import BoundaryOverlapPreviewPanel from '../BoundaryOverlapPreviewPanel'

const POLY: GeoJSON.Geometry = { type: 'Polygon', coordinates: [[[80, 28], [81, 28], [81, 29], [80, 29], [80, 28]]] }
const CLIPPED: GeoJSON.Geometry = { type: 'Polygon', coordinates: [[[80, 28], [80.6, 28], [80.6, 29], [80, 29], [80, 28]]] }
const NBR: GeoJSON.Geometry = { type: 'Polygon', coordinates: [[[80.6, 28], [81, 28], [81, 29], [80.6, 29], [80.6, 28]]] }

const PREVIEW_OVERLAP = {
  status: 'acceptable',
  orig_area_ha: 100,
  resolved_area_ha: 60,
  removed_ha: 40,
  removed_pct: 40,
  requires_confirmation: true,
  reason: null,
  overlapping_forests: [{ id: 'of-1', name: 'East CF', overlap_ha: 40, forest_area_ha: 120, geometry: NBR }],
  resolved_geometry: CLIPPED,
  original_geometry: POLY,
  warnings: [],
}

const PREVIEW_CLEAN = {
  ...PREVIEW_OVERLAP,
  status: 'no_overlap',
  removed_ha: 0,
  overlapping_forests: [],
  resolved_geometry: POLY,
}

describe('BoundaryOverlapPreviewPanel — clip only', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockPreview.mockResolvedValue(PREVIEW_OVERLAP)
    mockConfirm.mockResolvedValue({ id: 'new-id' })
    mockApiPost.mockResolvedValue({ data: { dispute_id: 1 } })
  })

  it('shows the clip summary and the overlapping forest', async () => {
    render(<BoundaryOverlapPreviewPanel geometry={POLY} forestName="Test CF" method="upload" onCancel={vi.fn()} onDone={vi.fn()} />)
    await waitFor(() => expect(mockPreview).toHaveBeenCalled())
    expect(await screen.findByTestId('clip-summary')).toBeTruthy()
    // "East CF" now appears twice: the summary list and the new map tooltip label.
    expect(screen.getAllByText(/East CF/).length).toBeGreaterThan(0)
    expect(screen.queryByTestId('relations-table')).toBeNull()
  })

  it('Accept saves the clipped geometry via confirmBoundary', async () => {
    render(<BoundaryOverlapPreviewPanel geometry={POLY} forestName="Test CF" method="upload" calculationId="calc-1" onCancel={vi.fn()} onDone={vi.fn()} />)
    await waitFor(() => expect(mockPreview).toHaveBeenCalled())
    fireEvent.click(await screen.findByTestId('btn-accept'))
    await waitFor(() =>
      expect(mockConfirm).toHaveBeenCalledWith(
        expect.objectContaining({ resolved_geometry: CLIPPED, forest_name: 'Test CF', calculation_id: 'calc-1' }),
      ),
    )
  })

  it('after Accept it shows a done state and does not re-run the preview (no loop)', async () => {
    render(<BoundaryOverlapPreviewPanel geometry={POLY} forestName="Test CF" method="upload" calculationId="calc-1" onCancel={vi.fn()} onDone={vi.fn()} />)
    await waitFor(() => expect(mockPreview).toHaveBeenCalledTimes(1))
    fireEvent.click(await screen.findByTestId('btn-accept'))
    await waitFor(() => expect(mockConfirm).toHaveBeenCalled())
    expect(await screen.findByTestId('preview-done')).toBeTruthy()
    expect(screen.queryByTestId('clip-summary')).toBeNull()
    // preview was NOT fetched again
    expect(mockPreview).toHaveBeenCalledTimes(1)
  })

  it('shows "no overlap" when nothing is clipped', async () => {
    mockPreview.mockResolvedValue(PREVIEW_CLEAN)
    render(<BoundaryOverlapPreviewPanel geometry={POLY} forestName="Test CF" method="upload" onCancel={vi.fn()} onDone={vi.fn()} />)
    await waitFor(() => expect(mockPreview).toHaveBeenCalled())
    expect(await screen.findByTestId('no-overlap')).toBeTruthy()
    expect(screen.queryByTestId('clip-summary')).toBeNull()
  })

  it('Edit invokes onEdit with the clipped geometry', async () => {
    const onEdit = vi.fn()
    render(<BoundaryOverlapPreviewPanel geometry={POLY} forestName="Test CF" method="upload" onCancel={vi.fn()} onDone={vi.fn()} onEdit={onEdit} />)
    await waitFor(() => expect(mockPreview).toHaveBeenCalled())
    fireEvent.click(await screen.findByTestId('btn-edit'))
    expect(onEdit).toHaveBeenCalledWith(CLIPPED)
  })

  it('reject preview disables Accept', async () => {
    mockPreview.mockResolvedValue({
      ...PREVIEW_OVERLAP,
      status: 'reject',
      reason: 'remaining_too_small',
      resolved_geometry: null,
    })
    render(<BoundaryOverlapPreviewPanel geometry={POLY} forestName="Test CF" method="upload" onCancel={vi.fn()} onDone={vi.fn()} />)
    await waitFor(() => expect(mockPreview).toHaveBeenCalled())
    expect(await screen.findByTestId('reject-alert')).toBeTruthy()
    expect(((await screen.findByTestId('btn-accept')) as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(screen.getByTestId('btn-accept'))
    expect(mockConfirm).not.toHaveBeenCalled()
  })

  it('Dispute opens the form and submits against the overlapping forest', async () => {
    render(<BoundaryOverlapPreviewPanel geometry={POLY} forestName="Test CF" method="upload" onCancel={vi.fn()} onDone={vi.fn()} />)
    await waitFor(() => expect(mockPreview).toHaveBeenCalled())
    fireEvent.click(await screen.findByTestId('btn-dispute'))
    expect(await screen.findByTestId('dispute-modal')).toBeTruthy()
    const inner = document.querySelector('textarea') as HTMLTextAreaElement
    fireEvent.change(inner, { target: { value: 'This land is ours, please review the boundary.' } })
    const okBtn = document.querySelector('.ant-modal-footer .ant-btn-primary') as HTMLElement
    if (okBtn) fireEvent.click(okBtn)
    await waitFor(() =>
      expect(mockApiPost).toHaveBeenCalledWith(
        '/api/forests/boundary/dispute',
        expect.objectContaining({ forest_id: 'of-1' }),
      ),
    )
  })
})

// PE-2 through PE-5 — inline vertex editing in the preview.
describe('BoundaryOverlapPreviewPanel — inline vertex editing (PE)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockPreview.mockResolvedValue(PREVIEW_OVERLAP)
    mockConfirm.mockResolvedValue({ id: 'new-id' })
    mockApiPost.mockResolvedValue({ data: { dispute_id: 1 } })
    dragTargetRef.current = { lat: 0, lng: 0 }
  })

  async function renderAndEnterEditMode() {
    render(
      <BoundaryOverlapPreviewPanel
        geometry={POLY}
        forestName="Test CF"
        method="upload"
        calculationId="calc-1"
        onCancel={vi.fn()}
        onDone={vi.fn()}
      />,
    )
    await waitFor(() => expect(mockPreview).toHaveBeenCalledTimes(1))
    fireEvent.click(await screen.findByTestId('btn-edit-vertices'))
  }

  function findVertexAt(lat: number, lng: number): HTMLElement {
    const buttons = screen.getAllByTestId('mock-vertex-marker')
    const match = buttons.find(
      (b) => Number(b.getAttribute('data-lat')) === lat && Number(b.getAttribute('data-lng')) === lng,
    )
    if (!match) throw new Error(`no vertex marker at (${lat}, ${lng})`)
    return match
  }

  it('renders one vertex marker per exterior-ring vertex of the clipped boundary', async () => {
    await renderAndEnterEditMode()
    // CLIPPED's open ring has 4 distinct vertices.
    expect(screen.getAllByTestId('mock-vertex-marker')).toHaveLength(4)
  })

  it('dragging a vertex changes the geometry Accept sends — even before the debounced recompute fires', async () => {
    await renderAndEnterEditMode()
    const vertex = findVertexAt(28, 80) // CLIPPED's (80, 28) corner
    dragTargetRef.current = { lat: 27, lng: 79 }
    fireEvent.click(vertex) // simulated dragend
    // Accept fires immediately — no manual Recompute click, no timer advance.
    fireEvent.click(screen.getByTestId('btn-accept'))
    await waitFor(() => expect(mockConfirm).toHaveBeenCalled())
    const sent = mockConfirm.mock.calls[0][0].resolved_geometry
    expect(sent.coordinates[0][0]).toEqual([79, 27])
    // Accept did not wait on a second preview call.
    expect(mockPreview).toHaveBeenCalledTimes(1)
  })

  it('regression: dragging a second vertex does not discard the first vertex\'s edit', async () => {
    // All vertex markers mount together on first load; a stale closure bound
    // at that mount (rather than reading the geometry fresh at drag time)
    // would make the second commit overwrite the first edit right back to
    // its pre-drag position — this is exactly what a user reported seeing.
    await renderAndEnterEditMode()
    const v0 = findVertexAt(28, 80) // CLIPPED's (80, 28) corner
    dragTargetRef.current = { lat: 27, lng: 79 }
    fireEvent.click(v0) // simulated drag+dragend on vertex 0

    const v3 = findVertexAt(29, 80) // CLIPPED's (80, 29) corner, untouched so far
    dragTargetRef.current = { lat: 30, lng: 79.5 }
    fireEvent.click(v3) // simulated drag+dragend on vertex 3

    fireEvent.click(screen.getByTestId('btn-accept'))
    await waitFor(() => expect(mockConfirm).toHaveBeenCalled())
    const sentRing = mockConfirm.mock.calls[0][0].resolved_geometry.coordinates[0]
    expect(sentRing).toContainEqual([79, 27]) // vertex 0's edit survived
    expect(sentRing).toContainEqual([79.5, 30]) // vertex 3's edit also present
  })

  it('dragging a vertex into a neighbour auto-recomputes (debounced) to the server-clipped edge', async () => {
    const RECLIPPED: GeoJSON.Geometry = { type: 'Polygon', coordinates: [[[80, 28], [80.6, 28], [80.6, 28.9], [80, 29], [80, 28]]] }
    mockPreview
      .mockResolvedValueOnce(PREVIEW_OVERLAP)
      .mockResolvedValueOnce({ ...PREVIEW_OVERLAP, resolved_geometry: RECLIPPED })
    await renderAndEnterEditMode()
    const vertex = findVertexAt(28, 80)
    dragTargetRef.current = { lat: 28.5, lng: 80.8 } // inside NBR's bbox
    vi.useFakeTimers()
    try {
      fireEvent.click(vertex)
      await vi.advanceTimersByTimeAsync(500)
    } finally {
      vi.useRealTimers()
    }
    // Wait for the DOM to actually reflect RECLIPPED's vertex, not just for
    // the mock to have been called — `mockPreview`'s call count flips the
    // instant the fetch fires, before the resulting `setPreview` → re-seed
    // `editedGeometry` effect chain has committed.
    await waitFor(() => {
      const has = screen
        .getAllByTestId('mock-vertex-marker')
        .some((b) => Number(b.getAttribute('data-lng')) === 80.6 && Number(b.getAttribute('data-lat')) === 28.9)
      expect(has).toBe(true)
    })
    fireEvent.click(screen.getByTestId('btn-accept'))
    await waitFor(() => expect(mockConfirm).toHaveBeenCalled())
    const sent = mockConfirm.mock.calls[0][0].resolved_geometry
    expect(sent).toEqual(RECLIPPED)
  })

  it('the manual "Recompute now" control is available but Accept does not require it', async () => {
    await renderAndEnterEditMode()
    expect(screen.getByTestId('btn-recompute')).toBeTruthy()
    // btn-accept is enabled (not disabled) with zero edits and zero recompute clicks.
    expect((screen.getByTestId('btn-accept') as HTMLButtonElement).disabled).toBe(false)
  })

  it('clicking a midpoint inserts a vertex on that segment', async () => {
    await renderAndEnterEditMode()
    expect(screen.getAllByTestId('mock-midpoint-marker')).toHaveLength(4)
    const midpoint = screen.getAllByTestId('mock-midpoint-marker').find(
      (b) => Number(b.getAttribute('data-lat')) === 28 && Number(b.getAttribute('data-lng')) === 80.3,
    )!
    fireEvent.click(midpoint)
    fireEvent.click(screen.getByTestId('btn-accept'))
    await waitFor(() => expect(mockConfirm).toHaveBeenCalled())
    const sent = mockConfirm.mock.calls[0][0].resolved_geometry
    expect(sent.coordinates[0]).toHaveLength(6) // 4 original + 1 inserted + closing dup
  })

  it('double-clicking a vertex deletes it', async () => {
    await renderAndEnterEditMode()
    const vertex = findVertexAt(29, 80) // CLIPPED's (80, 29) corner
    fireEvent.doubleClick(vertex)
    fireEvent.click(screen.getByTestId('btn-accept'))
    await waitFor(() => expect(mockConfirm).toHaveBeenCalled())
    const sent = mockConfirm.mock.calls[0][0].resolved_geometry
    expect(sent.coordinates[0]).toHaveLength(4) // 4 original - 1 deleted + closing dup
  })

  it('the tolerance slider is exposed and changing it updates the displayed value', async () => {
    await renderAndEnterEditMode()
    expect(screen.getByTestId('inline-edit-panel').textContent).toMatch(/5 m/)
    const slider = document.querySelector('[role="slider"]') as HTMLElement
    expect(slider).toBeTruthy()
    fireEvent.keyDown(slider, { key: 'ArrowRight', code: 'ArrowRight', keyCode: 39, which: 39 })
    // Default 5m, step 0.5 → one ArrowRight should move it to 5.5m.
    await waitFor(() => expect(screen.getByTestId('inline-edit-panel').textContent).toMatch(/5\.5 m/))
  })
})

describe('BoundaryOverlapPreviewPanel — MultiPolygon clip (CO-1)', () => {
  // The neighbour clipped the boundary into two disjoint parts.
  const MULTI_CLIPPED: GeoJSON.Geometry = {
    type: 'MultiPolygon',
    coordinates: [
      [[[80, 28], [80.4, 28], [80.4, 28.4], [80, 28.4], [80, 28]]],
      [[[80.7, 28.7], [81, 28.7], [81, 29], [80.7, 29], [80.7, 28.7]]],
    ],
  }
  const PREVIEW_MULTI = { ...PREVIEW_OVERLAP, resolved_geometry: MULTI_CLIPPED }

  beforeEach(() => {
    vi.clearAllMocks()
    mockPreview.mockResolvedValue(PREVIEW_MULTI)
    mockConfirm.mockResolvedValue({ id: 'new-id' })
    dragTargetRef.current = { lat: 0, lng: 0 }
  })

  async function renderMultiAndEdit() {
    render(
      <BoundaryOverlapPreviewPanel
        geometry={POLY}
        forestName="Test CF"
        method="upload"
        calculationId="calc-1"
        onCancel={vi.fn()}
        onDone={vi.fn()}
      />,
    )
    await waitFor(() => expect(mockPreview).toHaveBeenCalledTimes(1))
    // The inline editor is offered for a MultiPolygon now, not just a Polygon.
    fireEvent.click(await screen.findByTestId('btn-edit-vertices'))
  }

  it('offers the inline editor and a marker for every part’s exterior-ring vertex', async () => {
    await renderMultiAndEdit()
    expect(screen.getByTestId('inline-edit-panel')).toBeTruthy()
    // 2 parts × 4 open-ring vertices.
    expect(screen.getAllByTestId('mock-vertex-marker')).toHaveLength(8)
  })

  it('dragging a vertex on the second part edits only that part; result stays a MultiPolygon', async () => {
    await renderMultiAndEdit()
    const markers = screen.getAllByTestId('mock-vertex-marker')
    const p1v0 = markers.find(
      (b) => Number(b.getAttribute('data-lat')) === 28.7 && Number(b.getAttribute('data-lng')) === 80.7,
    )!
    dragTargetRef.current = { lat: 28.75, lng: 80.75 }
    fireEvent.click(p1v0)
    fireEvent.click(await screen.findByTestId('btn-accept'))
    await waitFor(() => expect(mockConfirm).toHaveBeenCalled())
    const sent = mockConfirm.mock.calls[0][0].resolved_geometry
    expect(sent.type).toBe('MultiPolygon')
    expect(sent.coordinates[0]).toEqual(MULTI_CLIPPED.coordinates[0]) // part 0 untouched
    expect(sent.coordinates[1][0][0]).toEqual([80.75, 28.75])
  })
})
