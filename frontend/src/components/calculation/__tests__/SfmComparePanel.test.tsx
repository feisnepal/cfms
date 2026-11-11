import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import SfmComparePanel from '../SfmComparePanel';
import type { SfmCompareResponse } from '../../../services/api';

vi.mock('../../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../../services/api')>();
  return { ...actual };
});

const compare: SfmCompareResponse = {
  baseline: {
    version: 1,
    params_hash: 'h',
    input_token: 'tok',
    generated_at: '2026-09-14T00:00:00Z',
    source: 'raster',
    zone_by_block: {},
    felling_series: [],
    forest_summary: {
      dominant_type_no: 1,
      type_area_breakdown: {},
      production_area_ha: 0,
      protection_area_ha: 0,
      total_annual_harvest_m3: 0,
      sampling_plan: [],
    },
    narration: { methodology: { ne: '', en: '' }, findings: { ne: '', en: '' }, prescription: { ne: '', en: '' } },
    blocks: [],
  },
  user: {
    version: 1,
    params_hash: 'h',
    input_token: 'tok|user',
    generated_at: '2026-09-14T00:01:00Z',
    source: 'mixed',
    zone_by_block: {},
    felling_series: [],
    forest_summary: {
      dominant_type_no: 1,
      type_area_breakdown: {},
      production_area_ha: 0,
      protection_area_ha: 0,
      total_annual_harvest_m3: 0,
      sampling_plan: [],
    },
    narration: { methodology: { ne: '', en: '' }, findings: { ne: '', en: '' }, prescription: { ne: '', en: '' } },
    blocks: [],
  },
  blocks: [
    {
      block_name: 'Block 1',
      slope_band: { before: 2, after: 3 },
      slope_source: 'workspace',
      orientation: { before: 'E', after: 'N' },
      orientation_source: 'workspace',
      type_no: { before: 1, after: 2 },
      prescription: { before: 'Shelterwood', after: 'Selection' },
      working_circle: { before: 'Circle A', after: 'Circle B' },
      stratum: {
        before: { stratum: 'production', intensity_pct: 1.0 },
        after: { stratum: 'protection', intensity_pct: 0.5 },
      },
      area_source: 'shared',
    },
  ],
  forest: {
    production_area_ha: { before: 10, after: 5 },
    protection_area_ha: { before: 0, after: 5 },
    total_annual_harvest_m3: { before: 200, after: 100 },
    felling_series: [
      { type_no: 1, branch: 'a', annual_harvest_m3: { before: 200, after: 100 } },
    ],
    sampling: [
      {
        block_name: 'Block 1',
        stratum: { before: 'production', after: 'protection' },
        intensity_pct: { before: 1.0, after: 0.5 },
      },
    ],
  },
  identical: false,
};

const identical: SfmCompareResponse = {
  ...compare,
  identical: true,
  blocks: [],
  forest: {
    production_area_ha: undefined,
    protection_area_ha: undefined,
    total_annual_harvest_m3: undefined,
    felling_series: [],
    sampling: [],
  },
};

describe('SfmComparePanel', () => {
  it('shows divergence table with before → after values and source tags', () => {
    render(<SfmComparePanel compare={compare} />);
    // block row present
    expect(screen.getAllByText('Block 1').length).toBeGreaterThan(0);
    // slope band 2 → 3
    // type numbers used to print as "2.0" (a one-decimal number format); they are now the "Type N" tag
    expect(screen.getAllByText('Type 2').length).toBeGreaterThan(0);
    expect(screen.getAllByText('3.0').length).toBeGreaterThan(0);
    // orientation E → N
    expect(screen.getByText('E')).toBeTruthy();
    expect(screen.getByText('N')).toBeTruthy();
    // type 1 → 2 (type_no after collides with slope before) — check presence
    expect(screen.getAllByText('Type 1').length).toBeGreaterThan(0);
    // prescription
    expect(screen.getByText('Shelterwood')).toBeTruthy();
    expect(screen.getByText('Selection')).toBeTruthy();
    // working circle
    expect(screen.getByText('Circle A')).toBeTruthy();
    expect(screen.getByText('Circle B')).toBeTruthy();
    // source tags (workspace + shared area)
    expect(screen.getAllByText('Workspace').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Shared area').length).toBeGreaterThan(0);
  });

  it('renders forest-level roll-up deltas (production, protection, harvest)', () => {
    render(<SfmComparePanel compare={compare} />);
    expect(screen.getAllByText(/10\.0 ha/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/5\.0 ha/).length).toBeGreaterThan(0);
    expect(screen.getByText('200.0 m³/yr')).toBeTruthy();
    expect(screen.getByText('100.0 m³/yr')).toBeTruthy();
  });

  it('renders felling-series deltas', () => {
    render(<SfmComparePanel compare={compare} />);
    expect(screen.getAllByText('Type 1').length).toBeGreaterThan(0);
    expect(screen.getAllByText('a').length).toBeGreaterThan(0);
  });

  it('renders sampling intensity deltas', () => {
    render(<SfmComparePanel compare={compare} />);
    expect(screen.getByText('1.00%')).toBeTruthy();
    expect(screen.getByText('0.50%')).toBeTruthy();
  });

  it('shows empty state when identical', () => {
    render(<SfmComparePanel compare={identical} />);
    expect(screen.getByText(/No differences/)).toBeTruthy();
  });
});