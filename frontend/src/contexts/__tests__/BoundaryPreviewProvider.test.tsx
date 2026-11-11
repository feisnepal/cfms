import { describe, it, expect, vi, beforeEach, beforeAll } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { BoundaryPreviewProvider, useBoundaryPreview } from '../BoundaryPreviewContext'
import type { Geometry } from 'geojson'

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

vi.mock('react-leaflet', () => ({
  MapContainer: ({ children }: { children: React.ReactNode }) => <div data-testid="mock-map">{children}</div>,
  TileLayer: () => <div data-testid="tile-layer" />,
  GeoJSON: () => <div data-testid="mock-geojson" />,
  Marker: ({ children }: { children?: React.ReactNode }) => <div data-testid="mock-marker">{children}</div>,
  CircleMarker: () => <div data-testid="mock-circle-marker" />,
  Polyline: () => <div data-testid="mock-polyline" />,
  Tooltip: ({ children }: { children?: React.ReactNode }) => <div data-testid="mock-tooltip">{children}</div>,
  useMap: () => ({ fitBounds: vi.fn() }),
}))

vi.mock('@turf/turf', () => ({
  union: vi.fn((a: unknown) => a),
}))

const mockPreview = vi.fn()
const mockConfirm = vi.fn()
const mockInclude = vi.fn()

vi.mock('../../services/api', () => ({
  default: { post: vi.fn() },
  forestApi: {
    previewBoundaryOverlap: (...args: unknown[]) => mockPreview(...args),
    confirmBoundary: (...args: unknown[]) => mockConfirm(...args),
    includeGapInBoundary: (...args: unknown[]) => mockInclude(...args),
  },
  boundaryApi: {
    previewBoundaryOverlap: (...args: unknown[]) => mockPreview(...args),
    confirmBoundary: (...args: unknown[]) => mockConfirm(...args),
    includeGapInBoundary: (...args: unknown[]) => mockInclude(...args),
  },
}))

vi.mock('../../hooks/useNearbyForests', () => ({
  getBoundaryStatusStyle: () => ({ color: '#228B22', fillColor: '#228B22' }),
  BOUNDARY_STATUS_STYLES: { draft: {}, validated: {} },
}))

vi.mock('antd', async (importOriginal) => {
  const actual: any = await importOriginal()
  return {
    ...actual,
    Modal: ({ children }: any) => <div data-testid="preview-modal">{children}</div>,
  }
})

const geom: Geometry = {
  type: 'Polygon',
  coordinates: [[[84, 28], [84.1, 28], [84.1, 28.1], [84, 28.1], [84, 28]]],
}

function Trigger({ onResolved }: { onResolved?: (r: { id: string }) => void }) {
  const { reviewBoundary } = useBoundaryPreview()
  return (
    <button onClick={() => reviewBoundary({ geometry: geom, forestName: 'Preview CF', method: 'upload', onResolved })}>
      review
    </button>
  )
}

beforeEach(() => {
  mockPreview.mockReset()
  mockConfirm.mockReset()
  mockInclude.mockReset()
  mockConfirm.mockResolvedValue({ id: 'calc-xyz' })
  mockPreview.mockResolvedValue({
    status: 'validated',
    overlapping_forests: [{ id: 'n-1', name: 'Nbr', overlap_ha: 0.5, gap_ha: 0, gap_shape: 'none', gap_size: 'none', adjacent: true }],
    gaps: [],
    gap_total_ha: 0,
    requires_confirmation: true,
  })
})

describe('BoundaryPreviewProvider', () => {
  it('renders the preview panel when reviewBoundary is called', async () => {
    const onResolved = vi.fn()
    render(
      <BoundaryPreviewProvider>
        <Trigger onResolved={onResolved} />
      </BoundaryPreviewProvider>,
    )
    fireEvent.click(screen.getByText('review'))
    // fetch preview fires on mount of the panel
    expect(await screen.findByTestId('preview-modal')).toBeTruthy()
    expect(mockPreview).toHaveBeenCalledTimes(1)
    expect(screen.getByTestId('boundary-preview-panel')).toBeTruthy()
  })

  it('calls onResolved with the returned calc id when the user accepts', async () => {
    const onResolved = vi.fn()
    render(
      <BoundaryPreviewProvider>
        <Trigger onResolved={onResolved} />
      </BoundaryPreviewProvider>,
    )
    fireEvent.click(screen.getByText('review'))
    await screen.findByTestId('preview-modal')
    await waitFor(() => expect(screen.queryByTestId('preview-loading')).toBeFalsy())
    fireEvent.click(screen.getByTestId('btn-accept'))
    await waitFor(() => expect(onResolved).toHaveBeenCalled())
    expect(onResolved).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'calc-xyz' }),
    )
  })
})
