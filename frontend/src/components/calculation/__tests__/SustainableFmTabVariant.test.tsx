/**
 * SustainableFmTab — variant switcher tests (SV-1.8).
 *
 * The Segmented *Guideline (raster)* / *My adjustments (workspace)* control
 * re-fetches all three read endpoints with `?variant=user` and bumps the
 * SfmMapPanel refreshKey so the thematic PNGs re-render for the new variant.
 * Default stays baseline on mount. Uses the real i18n so translated labels are
 * asserted from the en.json bundle (`sfm.variantBaseline` / `sfm.variantUser`).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import en from '../../../i18n/locales/en.json';
import SustainableFmTab from '../SustainableFmTab';
import * as api from '../../../services/api';
import type { SfmNarrationBlock } from '../../../services/api';

vi.mock('../../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../../services/api')>();
  return {
    ...actual,
    sfmApi: {
      ...actual.sfmApi,
      getSummary: vi.fn(),
      getBlocks: vi.fn(),
      getNarration: vi.fn(),
    },
  };
});

vi.mock('../SfmMapPanel', () => ({
  default: (p: { refreshKey?: number }) => (
    <div data-testid="sfm-map-panel" data-refreshkey={String(p.refreshKey ?? 0)} />
  ),
}));
vi.mock('../SfmSlopeHelperPanel', () => ({ default: () => <div /> }));
vi.mock('../SfmParamsPanel', () => ({ default: () => <div /> }));
vi.mock('../SfmBlockTable', () => ({ default: () => <div /> }));
vi.mock('../SfmFellingSeriesStrip', () => ({ default: () => <div /> }));
vi.mock('../SfmPrescriptionCard', () => ({ default: () => <div /> }));
vi.mock('../SfmNarration', () => ({ default: () => <div /> }));
vi.mock('../SfmVarChip', () => ({ SfmVarCopyMenu: () => <div />, SfmVarChip: () => <div /> }));

type MockView = {
  mockResolvedValue: (v: unknown) => void;
  mock: { calls: Array<[string, unknown]> };
};
const mv = (fn: unknown) => fn as unknown as MockView;

const NARRATION: SfmNarrationBlock = {
  methodology: { ne: 'm', en: 'm' },
  findings: { ne: 'f', en: 'f' },
  prescription: { ne: 'p', en: 'p' },
};

const summaryFor = (harvest: number) => ({
  forest_summary: {
    dominant_type_no: 1,
    type_area_breakdown: { '1': 10 },
    production_area_ha: 10,
    protection_area_ha: 2,
    total_annual_harvest_m3: harvest,
    sampling_plan: [],
  },
  felling_series: [],
  source: 'raster',
  generated_at: null,
});

const blocksFor = (source: string) => ({
  blocks: [
    {
      block_name: 'Block 1',
      area_ha: 10,
      inputs: { source },
      proposed_type_no: 1,
      confidence: 1,
      needs_review: false,
      reasons_ne: '',
      reasons_en: '',
      override_type_no: null,
      override_crown_density_pct: null,
      override_origin: null,
      wc_accept: false,
      effective_type_no: 1,
      prescription: null,
      orientation: null,
      working_circle_proposal: null,
      felling_series_id: null,
    },
  ],
  zone_by_block: { 'Block 1': { sfm_zone: 'outer', inner_terai: false, dom_phys: null, slope_band: 2, slope_band_area_pct: {}, mean_altitude_m: 900 } },
  source,
  generated_at: null,
});

describe('SustainableFmTab — variant switcher (SV-1.8)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('defaults to baseline on mount and refetches all three endpoints with variant=user on switch', async () => {
    mv(api.sfmApi.getSummary).mockResolvedValue(summaryFor(100));
    mv(api.sfmApi.getBlocks).mockResolvedValue(blocksFor('raster'));
    mv(api.sfmApi.getNarration).mockResolvedValue(NARRATION);
    render(<SustainableFmTab calculationId="c1" />);

    await waitFor(() => expect(mv(api.sfmApi.getSummary).mock.calls).toHaveLength(1));
    expect(mv(api.sfmApi.getSummary).mock.calls[0][0]).toBe('c1');
    expect(mv(api.sfmApi.getSummary).mock.calls[0][1]).toBe('baseline');
    expect(mv(api.sfmApi.getBlocks).mock.calls[0][1]).toBe('baseline');
    expect(mv(api.sfmApi.getNarration).mock.calls[0][1]).toBe('baseline');
    expect(screen.getByText(/100\.0/)).toBeInTheDocument();

    // My adjustments → all three re-fetch with variant=user
    mv(api.sfmApi.getSummary).mockResolvedValue(summaryFor(250));
    fireEvent.click(screen.getByText(en.sfm.variantUser));

    await waitFor(() =>
      expect(mv(api.sfmApi.getSummary).mock.calls[1]).toEqual(['c1', 'user']),
    );
    expect(mv(api.sfmApi.getBlocks).mock.calls[1]).toEqual(['c1', 'user']);
    expect(mv(api.sfmApi.getNarration).mock.calls[1]).toEqual(['c1', 'user']);
    // panels render the user-variant figures
    expect(await screen.findByText(/250\.0/)).toBeInTheDocument();
    expect(screen.queryByText(/100\.0/)).toBeNull();
  });

  it('bumps the SfmMapPanel refreshKey when the variant changes', async () => {
    mv(api.sfmApi.getSummary).mockResolvedValue(summaryFor(100));
    mv(api.sfmApi.getBlocks).mockResolvedValue(blocksFor('raster'));
    mv(api.sfmApi.getNarration).mockResolvedValue(NARRATION);
    render(<SustainableFmTab calculationId="c1" />);

    await waitFor(() => expect(mv(api.sfmApi.getSummary).mock.calls).toHaveLength(1));
    const panel = screen.getByTestId('sfm-map-panel');
    const before = Number(panel.getAttribute('data-refreshkey'));

    fireEvent.click(screen.getByText(en.sfm.variantUser));
    await waitFor(() =>
      expect(mv(api.sfmApi.getBlocks).mock.calls[1]).toEqual(['c1', 'user']),
    );
    const after = Number(screen.getByTestId('sfm-map-panel').getAttribute('data-refreshkey'));
    expect(after).toBeGreaterThan(before);
  });
});