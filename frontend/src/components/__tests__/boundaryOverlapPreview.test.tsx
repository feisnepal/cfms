import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('axios', async () => {
  const actual = await vi.importActual<typeof import('axios')>('axios')
  const mockApi = {
    create: vi.fn(() => ({
      get: vi.fn().mockResolvedValue({ data: {} }),
      post: vi.fn().mockResolvedValue({ data: {} }),
      put: vi.fn().mockResolvedValue({ data: {} }),
      delete: vi.fn().mockResolvedValue({ data: {} }),
      patch: vi.fn().mockResolvedValue({ data: {} }),
      interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
    })),
    post: vi.fn(),
    get: vi.fn(),
  }
  return { ...actual, default: mockApi, __esModule: true }
})

import api, { forestApi, boundaryApi } from '../../services/api'
import type { PreviewResponse } from '../../types/boundary-relations'
import { GAP_STYLE } from '../../types/boundary-relations'
import { getBoundaryStatusStyle, BOUNDARY_STATUS_STYLES } from '../../hooks/useNearbyForests'

const POLY: GeoJSON.Geometry = {
  type: 'Polygon',
  coordinates: [[[80, 28], [81, 28], [81, 29], [80, 29], [80, 28]]],
}

describe('PF-1 — boundary overlap+gap API client', () => {
  beforeEach(() => vi.clearAllMocks())

  it('previewBoundaryOverlap POSTs /api/forests/boundary/preview', async () => {
    const spy = vi.spyOn(api, 'post').mockResolvedValue({ data: { status: 'ok' } } as never)
    await forestApi.previewBoundaryOverlap({ geometry: POLY, method: 'upload' })
    expect(spy).toHaveBeenCalledWith('/api/forests/boundary/preview', { geometry: POLY, method: 'upload' })
    // boundaryApi alias hits same URL
    await boundaryApi.previewBoundaryOverlap({ geometry: POLY, method: 'digitize', forest_id: 'abc' })
    expect(spy).toHaveBeenLastCalledWith('/api/forests/boundary/preview', { geometry: POLY, method: 'digitize', forest_id: 'abc' })
  })

  it('confirmBoundary POSTs /api/forests/boundary/confirm', async () => {
    const spy = vi.spyOn(api, 'post').mockResolvedValue({ data: { id: '1' } } as never)
    await forestApi.confirmBoundary({
      resolved_geometry: POLY,
      original_geometry: POLY,
      forest_name: 'Test CF',
      method: 'upload',
    })
    expect(spy).toHaveBeenCalledWith('/api/forests/boundary/confirm', {
      resolved_geometry: POLY,
      original_geometry: POLY,
      forest_name: 'Test CF',
      method: 'upload',
    })
  })

  it('includeGapInBoundary POSTs /api/forests/boundary/include-gap with calculation_id', async () => {
    const spy = vi.spyOn(api, 'post').mockResolvedValue({ data: { id: '1' } } as never)
    await forestApi.includeGapInBoundary(
      { geometry: POLY, original_geometry: POLY, forest_name: 'CF', method: 'upload', gaps: [{ forest_id: 'f1', gap_ha: 1.2 }] },
      'calc-123',
    )
    expect(spy).toHaveBeenCalledWith('/api/forests/boundary/include-gap', expect.objectContaining({
      geometry: POLY,
      calculation_id: 'calc-123',
      gaps: [{ forest_id: 'f1', gap_ha: 1.2 }],
    }))
    // alias
    await boundaryApi.includeGapInBoundary(
      { geometry: POLY, original_geometry: POLY, forest_name: 'CF', method: 'upload', gaps: [] },
    )
    expect(spy).toHaveBeenLastCalledWith('/api/forests/boundary/include-gap', expect.objectContaining({ geometry: POLY }))
  })

  it('fetchNearbyRelations GETs /api/forests/{id}/nearby', async () => {
    const spy = vi.spyOn(api, 'get').mockResolvedValue({ data: { forests: [] } } as never)
    await forestApi.fetchNearbyRelations('forest-xyz')
    expect(spy).toHaveBeenCalledWith('/api/forests/forest-xyz/nearby')
    await boundaryApi.fetchNearbyRelations('forest-xyz')
    expect(spy).toHaveBeenCalledTimes(2)
  })

  it('relation types mirror the backend schema (PreviewResponse + gap fields)', () => {
    const fake: PreviewResponse = {
      status: 'ok',
      orig_area_ha: 10,
      resolved_area_ha: 9,
      removed_ha: 1,
      removed_pct: 10,
      requires_confirmation: false,
      overlapping_forests: [{ id: '1', name: 'A', overlap_ha: 1, forest_area_ha: 10, gap_ha: 0.5, gap_shape: 'ribbon', gap_size: 'small', adjacent: true }],
      gaps: [{ id: '2', name: 'B', overlap_ha: 0, gap_ha: 2.1, gap_shape: 'ribbon', gap_size: 'medium', gap_geometry: POLY, adjacent: true }],
      gap_total_ha: 2.1,
      warnings: [],
    }
    expect(fake.gaps[0].gap_shape).toBe('ribbon')
    expect(fake.overlapping_forests[0].gap_ha).toBe(0.5)
  })

  it('reuses neighbour status styles and exposes gap style', () => {
    expect(getBoundaryStatusStyle('validated').color).toBeTruthy()
    expect(BOUNDARY_STATUS_STYLES.draft).toBeDefined()
    expect(GAP_STYLE.color).toBe('#F59E0B')
    expect(GAP_STYLE.dashArray).toBe('6 3')
    expect(GAP_STYLE.fillOpacity).toBe(0.15)
  })
})
