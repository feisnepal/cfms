import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'

const authHandlers = [
  http.post('/api/auth/login', async () => {
    return HttpResponse.json({
      access_token: 'test-jwt-token',
      token_type: 'bearer',
    })
  }),
  http.get('/api/auth/me', async () => {
    return HttpResponse.json({
      id: '1',
      email: 'demo@forest.com',
      full_name: 'Demo User',
      role: 'admin',
    })
  }),
  http.get('/api/admin/costs/forests', async () => {
    return HttpResponse.json({
      rows: [
        { forest_name: 'Alpha', calculation_count: 2, total_cpu_seconds: 90, total_peak_memory_mb: 1536, total_cpu_cost: 0.8, total_memory_cost: 0.4, total_cost: 1.2, currency: 'USD', last_run_at: '2026-08-31T00:00:00Z' },
      ],
      grand_total: 1.2,
      currency: 'USD',
    })
  }),
  http.get('/api/calculations/:calcId/sustainable-fm/compare', async () => {
    return HttpResponse.json({
      baseline: {
        version: 1,
        params_hash: 'h-base',
        input_token: 'tok',
        generated_at: '2026-09-14T00:00:00Z',
        source: 'raster',
        zone_by_block: { 'Block 1': { sfm_zone: 'outer', inner_terai: false, dom_phys: null, slope_band: 2, slope_band_area_pct: {}, mean_altitude_m: 900 } },
        felling_series: [{ id: 1, type_no: 1, branch: 'a', method: 'SCI', C: 30, R: 3, N: null, area_ha: 10, annual_felling_area_ha: 1, gs_ge40_m3_per_ha: 200, gs_ge40_m3: 2000, pct: 10, annual_harvest_m3: 200, note_ne: '', note_en: '' }],
        forest_summary: { dominant_type_no: 1, type_area_breakdown: { '1': 10 }, production_area_ha: 10, protection_area_ha: 0, total_annual_harvest_m3: 200, sampling_plan: [] },
        narration: { methodology: { ne: '', en: '' }, findings: { ne: '', en: '' }, prescription: { ne: '', en: '' } },
        blocks: [
          {
            block_name: 'Block 1',
            area_ha: 10,
            inputs: { block_name: 'Block 1', source: 'raster', band: { code: 2, level: 'moderate', label_ne: 'मध्यम', label_en: 'Moderate', min_deg: 19, max_deg: 31 }, mean_altitude_m: 900, slope_band_area_pct: {}, prof_component: 0.5, gs_ge40_m3_per_ha: 200, std_crown_density_pct: 60, decid_if: 'D', si_a_years: 25, gs_years: 25, min_gs_m3_per_ha: 40 },
            proposed_type_no: 1,
            confidence: 0.9,
            needs_review: false,
            reasons_ne: 'r1',
            reasons_en: 'r1',
            override_type_no: null,
            override_crown_density_pct: null,
            override_origin: null,
            wc_accept: false,
            effective_type_no: 1,
            prescription: null,
            orientation: 'E',
            working_circle_proposal: { target: 'wc1', justification_ne: '', justification_en: '' },
            felling_series_id: 1,
          },
        ],
      },
      user: {
        version: 1,
        params_hash: 'h-base',
        input_token: 'tok|user',
        generated_at: '2026-09-14T00:01:00Z',
        source: 'mixed',
        zone_by_block: { 'Block 1': { sfm_zone: 'outer', inner_terai: false, dom_phys: null, slope_band: 3, slope_band_area_pct: {}, mean_altitude_m: 900 } },
        felling_series: [],
        forest_summary: { dominant_type_no: 1, type_area_breakdown: { '1': 5 }, production_area_ha: 5, protection_area_ha: 5, total_annual_harvest_m3: 100, sampling_plan: [] },
        narration: { methodology: { ne: '', en: '' }, findings: { ne: '', en: '' }, prescription: { ne: '', en: '' } },
        blocks: [],
      },
      blocks: [
        {
          block_name: 'Block 1',
          slope_band: { before: 2, after: 3 },
          slope_source: 'workspace',
          orientation_source: 'raster',
          area_source: 'shared',
        },
      ],
      forest: {
        production_area_ha: { before: 10, after: 5 },
        protection_area_ha: { before: 0, after: 5 },
        total_annual_harvest_m3: { before: 200, after: 100 },
        felling_series: [{ type_no: 1, branch: 'a', annual_harvest_m3: { before: 200, after: 100 } }],
        sampling: [{ block_name: 'Block 1', stratum: { before: 'production', after: 'protection' }, intensity_pct: { before: 1, after: 0.5 } }],
      },
      identical: false,
    })
  }),
]

// The workflow header shows how many forum questions each step has; in tests the forum is empty.
const forumHandlers = [
  http.get('/api/forum/steps', () => HttpResponse.json({})),
]

export const handlers = [
  ...authHandlers,
  ...forumHandlers,
]

export const server = setupServer(...handlers)
