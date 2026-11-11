/**
 * sfmApi.compareSfm client test (SV-1.7).
 *
 * Using the MSW handlers, asserts the client hits
 * /api/calculations/{id}/sustainable-fm/compare and returns the typed
 * compare payload (both blobs + per-block divergence + forest deltas).
 */
import { describe, expect, it } from 'vitest'
import { sfmApi } from '../api'

describe('sfmApi.compareSfm', () => {
  it('fetches the compare payload and returns the typed shape', async () => {
    const data = await sfmApi.compareSfm('calc-1')

    // Top level: both variants, a divergence list, forest deltas, identical flag.
    expect(data.identical).toBe(false)
    expect(data.baseline.source).toBe('raster')
    expect(data.user.source).toBe('mixed')
    expect(data.user.input_token).toContain('|user')

    // Per-block divergence rows carry before/after pairs + source tags.
    expect(data.blocks).toHaveLength(1)
    const row = data.blocks[0]
    expect(row.block_name).toBe('Block 1')
    expect(row.slope_band).toEqual({ before: 2, after: 3 })
    expect(row.slope_source).toBe('workspace')
    expect(row.orientation_source).toBe('raster')
    expect(row.area_source).toBe('shared')

    // Forest-level deltas (absent keys = unchanged).
    expect(data.forest.production_area_ha).toEqual({ before: 10, after: 5 })
    expect(data.forest.total_annual_harvest_m3).toEqual({ before: 200, after: 100 })
    expect(data.forest.felling_series?.[0].annual_harvest_m3).toEqual({
      before: 200,
      after: 100,
    })
    expect(data.forest.sampling?.[0].stratum).toEqual({
      before: 'production',
      after: 'protection',
    })
  })
})