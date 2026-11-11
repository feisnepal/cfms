import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import { setupServer } from 'msw/node'
import { handlers } from './mocks/handlers'

const server = setupServer(...handlers)

beforeAll(() => server.listen({ onUnhandledRequest: 'bypass' }))
afterAll(() => server.close())

describe('Boundary API (S11)', () => {
  it('previews boundary with no overlap', async () => {
    const resp = await fetch('/api/forests/boundary/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        geometry: { type: 'Polygon', coordinates: [[[0,0],[1,0],[1,1],[0,0]]] },
        method: 'digitize',
      }),
    })
    const data = await resp.json()
    expect(data.status).toBe('no_overlap')
    expect(data.resolved_area_ha).toBe(100)
  })

  it('confirms boundary creation', async () => {
    const resp = await fetch('/api/forests/boundary/confirm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        resolved_geometry: { type: 'Polygon', coordinates: [] },
        original_geometry: { type: 'Polygon', coordinates: [] },
        forest_name: 'Test Forest',
        method: 'digitize',
      }),
    })
    expect(resp.status).toBe(201)
    const data = await resp.json()
    expect(data.boundary_status).toBe('validated')
  })

  it('files a dispute', async () => {
    const resp = await fetch('/api/forests/boundary/dispute', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        forest_id: '00000000-0000-0000-0000-000000000001',
        reason_np: 'सिमाना मिल्दैन भन्ने कारणले विवाद दायर',
      }),
    })
    const data = await resp.json()
    expect(data.dispute_id).toBe(1)
    expect(data.status).toBe('open')
  })

  it('lists disputes', async () => {
    const resp = await fetch('/api/admin/boundary-disputes')
    const data = await resp.json()
    expect(data).toHaveLength(1)
    expect(data[0].status).toBe('open')
  })

  it('resolves a dispute', async () => {
    const resp = await fetch('/api/admin/boundary-disputes/1/resolve', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        forest_id: '00000000-0000-0000-0000-000000000001',
        new_boundary: { type: 'Polygon', coordinates: [] },
        reason_np: 'दुवै पक्ष सहमत भएपछि समाधान',
        resolution_type: 'edit_forest_2',
      }),
    })
    const data = await resp.json()
    expect(data.status).toBe('resolved')
    expect(data.forest_1_status).toBe('approved')
  })
})
