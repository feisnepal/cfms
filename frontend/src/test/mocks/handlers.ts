import { http, HttpResponse } from 'msw'

const MOCK_CALC_ID = 'calc-001'
const MOCK_BLOCK_ID = 'block-001'
const MOCK_SUB_AREA_ID = 'sa-001'
const MOCK_FEATURE_ID = 'feat-001'

export const geometryHandlers = [
  http.get(`/api/calculations/${MOCK_CALC_ID}/geometry`, () => {
    return HttpResponse.json({
      geometry: {
        type: 'Polygon',
        coordinates: [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]],
      },
    })
  }),

  http.get(`/api/calculations/${MOCK_CALC_ID}/blocks`, () => {
    return HttpResponse.json({
      blocks: [
        {
          id: MOCK_BLOCK_ID,
          name: 'Block A',
          geometry: { type: 'Polygon', coordinates: [[[1, 1], [5, 1], [5, 5], [1, 5], [1, 1]]] },
          area_hectares: 16.0,
          sub_area_count: 2,
        },
      ],
    })
  }),

  http.get(`/api/calculations/${MOCK_CALC_ID}/blocks/${MOCK_BLOCK_ID}`, () => {
    return HttpResponse.json({
      id: MOCK_BLOCK_ID,
      name: 'Block A',
      geometry: { type: 'Polygon', coordinates: [[[1, 1], [5, 1], [5, 5], [1, 5], [1, 1]]] },
      area_hectares: 16.0,
    })
  }),

  http.get(`/api/calculations/${MOCK_CALC_ID}/sub-areas`, () => {
    return HttpResponse.json({
      sub_areas: [
        {
          id: MOCK_SUB_AREA_ID,
          name: 'Sub-Area 1',
          category: 'plantation',
          block_id: MOCK_BLOCK_ID,
          block_name: 'Block A',
          geometry: { type: 'Polygon', coordinates: [[[2, 2], [4, 2], [4, 4], [2, 4], [2, 2]]] },
          area_hectares: 4.0,
          fill_color: '#90EE90',
        },
      ],
    })
  }),

  http.get(`/api/calculations/${MOCK_CALC_ID}/drawn-features`, () => {
    return HttpResponse.json({
      features: [
        {
          id: MOCK_FEATURE_ID,
          geometry: { type: 'Point', coordinates: [3, 3] },
          properties: { name: 'Sample Point', year: 2026, years: [2026] },
        },
      ],
    })
  }),

  http.post(`/api/calculations/${MOCK_CALC_ID}/blocks`, async ({ request }) => {
    const body = await request.json() as any
    return HttpResponse.json({
      id: 'block-new',
      name: body.properties?.name || 'New Block',
      geometry: body.geometry,
      area_hectares: 10.0,
    }, { status: 201 })
  }),

  http.post(`/api/calculations/${MOCK_CALC_ID}/sub-areas`, async ({ request }) => {
    const body = await request.json() as any
    return HttpResponse.json({
      id: 'sa-new',
      name: body.properties?.name || 'New Sub-Area',
      category: body.properties?.category || 'other',
      geometry: body.geometry,
      area_hectares: 2.0,
    }, { status: 201 })
  }),

  http.post(`/api/calculations/${MOCK_CALC_ID}/drawn-features`, async ({ request }) => {
    const body = await request.json() as any
    return HttpResponse.json({
      id: 'feat-new',
      geometry: body.geometry,
      properties: { name: body.properties?.name || 'New Feature', year: 2026 },
    }, { status: 201 })
  }),

  http.post(`/api/calculations/${MOCK_CALC_ID}/validate-overlap`, async ({ request }) => {
    const body = await request.json() as any
    return HttpResponse.json({
      valid: true,
      overlaps: [],
      message: 'No overlaps detected',
    })
  }),

  http.patch(`/api/calculations/${MOCK_CALC_ID}/blocks/${MOCK_BLOCK_ID}`, async ({ request }) => {
    const body = await request.json() as any
    return HttpResponse.json({
      id: MOCK_BLOCK_ID,
      name: body.properties?.name || 'Updated Block',
      geometry: body.geometry,
    })
  }),

  http.delete(`/api/calculations/${MOCK_CALC_ID}/blocks/${MOCK_BLOCK_ID}`, () => {
    return HttpResponse.json({ success: true })
  }),

  http.post('/api/calculations/:calcId/geometry/split', async ({ request }) => {
    const body = await request.json() as any
    return HttpResponse.json({
      success: true,
      pieces: [
        { type: 'Feature', geometry: body.geometry, properties: { name: 'Piece 1' } },
        { type: 'Feature', geometry: body.geometry, properties: { name: 'Piece 2' } },
      ],
      piece_count: 2,
      areas_ha: [5.0, 5.0],
      total_area_ha: 10.0,
    })
  }),

  http.patch('/api/calculations/:calcId/geometry/structure-lock', () => {
    return HttpResponse.json({ success: true, structure_locked: true })
  }),

  http.get('/api/dimension/labels', () => {
    return HttpResponse.json({ mode: 'block', labels: { compartment: 'Block', compartmentNp: 'ब्लक' } })
  }),

  http.post('/api/forests/boundary/preview', async ({ request }) => {
    return HttpResponse.json({
      status: 'no_overlap',
      orig_area_ha: 100,
      resolved_area_ha: 100,
      removed_ha: 0,
      removed_pct: 0,
      requires_confirmation: false,
      overlapping_forests: [],
      resolved_geometry: { type: 'Polygon', coordinates: [] },
    })
  }),

  http.post('/api/forests/boundary/confirm', async ({ request }) => {
    return HttpResponse.json({
      id: 'forest-new',
      boundary_status: 'validated',
      boundary_geom_updated_at: new Date().toISOString(),
      audit_id: 1,
    }, { status: 201 })
  }),

  http.post('/api/forests/boundary/dispute', async ({ request }) => {
    return HttpResponse.json({ dispute_id: 1, status: 'open' }, { status: 201 })
  }),

  http.get('/api/admin/boundary-disputes', () => {
    return HttpResponse.json([
      { id: 1, forest_id_1: 'f1', forest_id_2: 'f2', status: 'open', created_at: new Date().toISOString() },
    ])
  }),

  http.get('/api/admin/boundary-disputes/:disputeId', () => {
    return HttpResponse.json({
      id: 1,
      forest_id_1: 'f1',
      forest_id_2: 'f2',
      dispute_reason_np: 'सिमाना मिलेन',
      status: 'open',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    })
  }),

  http.post('/api/admin/boundary-disputes/:disputeId/resolve', async ({ request }) => {
    return HttpResponse.json({
      dispute_id: 1,
      status: 'resolved',
      forest_1_status: 'approved',
      forest_2_status: 'approved',
    })
  }),

  http.get('/api/forests/:forestId/nearby', () => {
    return HttpResponse.json({ forests: [], count: 0 })
  }),

  http.patch('/api/forests/:forestId/boundary-status', () => {
    return HttpResponse.json({
      id: 'f1',
      boundary_status: 'approved',
      boundary_status_changed_at: new Date().toISOString(),
      boundary_geom_updated_at: new Date().toISOString(),
    })
  }),
]

// Step 11 asks how many plan decisions are open; in tests with no forest data the answer is "none".
export const decisionHandlers = [
  http.get('/api/calculations/:id/decisions', () =>
    HttpResponse.json({ locked: false, locked_reason: null, open_count: 0, items: [] }),
  ),
]

export const handlers = [...geometryHandlers, ...decisionHandlers]
