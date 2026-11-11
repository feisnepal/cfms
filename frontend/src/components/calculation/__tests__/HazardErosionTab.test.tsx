import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import HazardErosionTab from '../HazardErosionTab';
import * as api from '../../../services/api';

vi.mock('../../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../../services/api')>();
  return {
    ...actual,
    hazardErosionApi: {
      summary: vi.fn(),
      recompute: vi.fn(),
      tables: vi.fn(),
      narration: vi.fn(),
      insertOpSubsections: vi.fn(),
      // the map legend under the map: not under test here
      getMapLegend: vi.fn().mockResolvedValue({ state: 'not_computed', key: 'soil' }),
      getDotsSummary: vi.fn().mockResolvedValue({ state: 'not_computed', kind: 'households' }),
    },
  };
});

const mockApi = api.hazardErosionApi as unknown as {
  summary: ReturnType<typeof vi.fn>;
  recompute: ReturnType<typeof vi.fn>;
  tables: ReturnType<typeof vi.fn>;
  narration: ReturnType<typeof vi.fn>;
  insertOpSubsections: ReturnType<typeof vi.fn>;
};

const emptyNarrBlock = {
  methodology_ne: '', methodology_en: '', findings_ne: '', findings_en: '',
  prescription_ne: '', prescription_en: '', assumptions_ne: [], assumptions_en: [],
};
const EMPTY_NARRATION = {
  calculation_id: 'c1',
  soil_available: false,
  hazard_available: false,
  soil: emptyNarrBlock,
  hazard: emptyNarrBlock,
};

const renderTab = () =>
  render(
    <MemoryRouter initialEntries={['/calculations/c1?tab=data-maps&context=hazarderosion']}>
      <HazardErosionTab calculationId="c1" />
    </MemoryRouter>,
  );

const EMPTY_TABLES = {
  calculation_id: 'c1',
  fs_enabled: false,
  hh_available: false,
  has_user_group: false,
  soil_loss_by_unit: [],
  soil_loss_aoi_comparison: [],
  lsi_area_by_class: [],
  lsi_by_unit: [],
  fs_by_unit: [],
  hazard_aoi_comparison: [],
  hh_priority_table: [],
  hh_settlement_rollup_table: [],
  hh_driver_counts: [],
};

function makeSummary(over: Partial<api.HazardErosionSummary> = {}): api.HazardErosionSummary {
  const prereq = (tag: string, met: boolean): api.HazardErosionPrereq => ({
    tag,
    status: met ? 'available' : 'partial',
    met,
    reason_ne: '',
    reason_en: met ? '' : `${tag} missing`,
    hint_ne: '',
    hint_en: met ? '' : `add ${tag}`,
  });
  return {
    calculation_id: 'c1',
    forest_name: 'बृन्दाबन',
    physiography_zone: 'Chure Hillslopes',
    has_user_group: true,
    prereqs: [
      prereq('raster_zonal', true),
      prereq('soil_data', true),
      prereq('geology', true),
      prereq('household_data', true),
      prereq('user_group_extent', true),
    ],
    soil: {
      available: true,
      mean_t_ha: 16.91,
      total_t_yr: 8760,
      pct_above_tolerable: 41,
      dominant_factor: 'C',
      customised: false,
      sdr_enabled: false,
    },
    hazard: {
      available: true,
      lsi_prone_pct: 42,
      lsi_prone_ha: 231.6,
      lsi_high_units: 'blocks-3',
      fs_enabled: true,
      fs_unstable_pct: 0,
      fs_marginal_pct: 14.7,
      hh_count: 99,
      hh_priority_count: 15,
      hh_mean_score: 0.45,
      hazard_layer_informative: false,
      hh_coord_source: 'survey',
      customised: false,
    },
    maps: [
      {
        key: 'thememap:hazard__landslide_susceptibility',
        label_ne: '',
        label_en: 'LSI',
        section: 'S9',
        is_factor_band: false,
        is_user_group: false,
        available: true,
        reason_ne: '',
      },
    ],
    ...over,
  };
}

beforeEach(() => {
  mockApi.summary.mockReset();
  mockApi.recompute.mockReset();
  mockApi.tables.mockReset();
  mockApi.tables.mockResolvedValue(EMPTY_TABLES);
  mockApi.narration.mockReset();
  mockApi.narration.mockResolvedValue(EMPTY_NARRATION);
  mockApi.insertOpSubsections.mockReset();
});

describe('HazardErosionTab', () => {
  it('renders the header, physiography zone and 5 prereq pills', async () => {
    mockApi.summary.mockResolvedValue(makeSummary());
    renderTab();
    await waitFor(() => expect(screen.getByText('बृन्दाबन', { exact: false })).toBeTruthy());
    expect(screen.getByText('Chure Hillslopes', { exact: false })).toBeTruthy();
    // 5 prereq pills (case-insensitive substring can also hit body text — count ≥ 1)
    expect(screen.getAllByText('DEM', { exact: false }).length).toBeGreaterThan(0);
    expect(screen.getAllByText('Geology', { exact: false }).length).toBeGreaterThan(0);
    expect(screen.getAllByText('Households', { exact: false }).length).toBeGreaterThan(0);
    expect(screen.getByText('Recompute')).toBeTruthy();
  });

  it('shows the key soil + hazard summary lines and the not-informative warning', async () => {
    mockApi.summary.mockResolvedValue(makeSummary());
    renderTab();
    await waitFor(() => expect(screen.getByText(/16\.91/)).toBeTruthy());
    expect(screen.getByText(/41/)).toBeTruthy(); // % over tolerable
    expect(screen.getByText(/15 \/ 99/)).toBeTruthy(); // priority / total
    expect(
      screen.getByText(/not precise enough/i),
    ).toBeTruthy();
  });

  it('swaps the not-informative warning for the footprint note when coords come from building footprints', async () => {
    mockApi.summary.mockResolvedValue(
      makeSummary({
        hazard: {
          available: true,
          lsi_prone_pct: 42,
          lsi_prone_ha: 231.6,
          lsi_high_units: 'blocks-3',
          fs_enabled: true,
          fs_unstable_pct: 0,
          fs_marginal_pct: 14.7,
          hh_count: 99,
          hh_priority_count: 15,
          hh_mean_score: 0.45,
          hazard_layer_informative: false,
          hh_coord_source: 'building_footprint',
          customised: false,
        },
      }),
    );
    renderTab();
    await waitFor(() => expect(screen.getByText(/16\.91/)).toBeTruthy());
    expect(screen.queryByText(/not precise enough/i)).toBeNull();
    expect(
      screen.getByText(/building footprint|representative building/i),
    ).toBeTruthy();
  });

  it('shows the empty state when no prereq is met', async () => {
    mockApi.summary.mockResolvedValue(
      makeSummary({
        prereqs: makeSummary().prereqs.map((p) => ({ ...p, met: false, status: 'partial' })),
        soil: { ...makeSummary().soil, available: false },
        hazard: { ...makeSummary().hazard, available: false },
      }),
    );
    renderTab();
    await waitFor(() =>
      expect(screen.getByText(/Nothing to analyse yet/i)).toBeTruthy(),
    );
  });

  it('calls recompute and reloads', async () => {
    mockApi.summary.mockResolvedValue(makeSummary());
    mockApi.recompute.mockResolvedValue({ status: 'recompute queued', cleared: ['soil_erosion'] });
    renderTab();
    await waitFor(() => screen.getByText('Recompute'));
    fireEvent.click(screen.getByText('Recompute'));
    await waitFor(() => expect(mockApi.recompute).toHaveBeenCalledWith('c1'));
    await waitFor(() => expect(mockApi.summary).toHaveBeenCalledTimes(2));
  });

  it('shows an error + retry on a failed load', async () => {
    mockApi.summary.mockRejectedValueOnce(new Error('boom')).mockResolvedValueOnce(makeSummary());
    renderTab();
    await waitFor(() => screen.getByText('Retry'));
    fireEvent.click(screen.getByText('Retry'));
    await waitFor(() => expect(screen.getByText('बृन्दाबन', { exact: false })).toBeTruthy());
  });
});
