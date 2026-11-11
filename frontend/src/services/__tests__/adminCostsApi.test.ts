/**
 * forestCostsApi client test (CF-1).
 *
 * Using the MSW handlers, asserts the client hits /api/admin/costs/forests
 * and returns typed data.
 */
import { describe, it, expect } from 'vitest'
import { forestCostsApi } from '../api'

describe('forestCostsApi.list', () => {
  it('fetches per-forest cost aggregation and returns typed rows', async () => {
    const data = await forestCostsApi.list()
    expect(data.grand_total).toBe(1.2)
    expect(data.currency).toBe('USD')
    expect(data.rows).toHaveLength(1)
    expect(data.rows[0]).toMatchObject({
      forest_name: 'Alpha',
      calculation_count: 2,
      total_cpu_seconds: 90,
      total_peak_memory_mb: 1536,
      total_cost: 1.2,
    })
  })
})
