import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import { setupServer } from 'msw/node'
import { geometryHandlers } from './mocks/handlers'

const server = setupServer(...geometryHandlers)

const CALC_ID = 'calc-001'

beforeAll(() => server.listen({ onUnhandledRequest: 'bypass' }))
afterAll(() => server.close())

describe('Geometry API', () => {
  it('fetches boundary geometry', async () => {
    const resp = await fetch(`/api/calculations/${CALC_ID}/geometry`)
    const data = await resp.json()
    expect(data.geometry.type).toBe('Polygon')
  })

  it('fetches blocks', async () => {
    const resp = await fetch(`/api/calculations/${CALC_ID}/blocks`)
    const data = await resp.json()
    expect(data.blocks).toHaveLength(1)
    expect(data.blocks[0].name).toBe('Block A')
  })

  it('fetches sub-areas', async () => {
    const resp = await fetch(`/api/calculations/${CALC_ID}/sub-areas`)
    const data = await resp.json()
    expect(data.sub_areas).toHaveLength(1)
    expect(data.sub_areas[0].category).toBe('plantation')
  })

  it('fetches drawn features', async () => {
    const resp = await fetch(`/api/calculations/${CALC_ID}/drawn-features`)
    const data = await resp.json()
    expect(data.features).toHaveLength(1)
    expect(data.features[0].properties.name).toBe('Sample Point')
  })

  it('creates a new block', async () => {
    const resp = await fetch(`/api/calculations/${CALC_ID}/blocks`, {
      method: 'POST',
      body: JSON.stringify({ geometry: { type: 'Polygon', coordinates: [] }, properties: { name: 'New Block' } }),
      headers: { 'Content-Type': 'application/json' },
    })
    const data = await resp.json()
    expect(resp.status).toBe(201)
    expect(data.name).toBe('New Block')
  })

  it('validates overlap', async () => {
    const resp = await fetch(`/api/calculations/${CALC_ID}/validate-overlap`, {
      method: 'POST',
      body: JSON.stringify({ geometry: { type: 'Polygon', coordinates: [] } }),
      headers: { 'Content-Type': 'application/json' },
    })
    const data = await resp.json()
    expect(data.valid).toBe(true)
  })

  it('returns dimension labels', async () => {
    const resp = await fetch('/api/dimension/labels')
    const data = await resp.json()
    expect(data.mode).toBe('block')
  })
})
