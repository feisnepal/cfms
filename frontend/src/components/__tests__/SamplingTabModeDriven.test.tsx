import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, fireEvent, screen, waitFor } from '@testing-library/react';
import { SamplingTab } from '../SamplingTab';

// English translation map for test mock - keys match i18n keys used in component
const enTranslations: Record<string, string> = {
  'sampling.createNewDesign': '+ Create New Sampling Design',
  'sampling.createDesign': 'Create Design',
  'sampling.intensityCompartmentMode': 'Sampling Intensity (Compartment mode)',
  'sampling.intensityProductiveForest': 'Sampling Intensity for Productive Forest',
  'sampling.plotSizeProductiveForest': 'Plot Size (Productive Forest)',
  'sampling.modeBannerCompartment': 'Mode: Compartment - random',
  'sampling.modeBannerGuideline': 'Mode: Guideline-2061',
  'sampling.sampleProtectedZones0_1': 'Sample protected zones at 0.1% intensity',
  'sampling.guidelineConfig': 'Guideline-2061 Configuration',
  'sampling.guidelineNoteBody': 'Guideline-2061 Department of Forest standard systematic sampling',
  'sampling.typeLabel': 'Sampling Type',
  'sampling.methodSystematic': 'Systematic',
  'sampling.methodRandom': 'Random',
  'sampling.intensityRandomFallback': 'Sampling Intensity (Random fallback)',
  'sampling.minDistanceBetweenPoints': 'Minimum Distance Between Points (m)',
  'sampling.modeBannerBlockRandom': 'intensity-based Random fallback selected',
  'sampling.areaBasisFull': 'Area Basis Full',
  'sampling.areaFiltersTitle': 'Sampling Area Filters',
  'sampling.lowTreeCoverage': 'Low Tree-Cover Coverage',
  'sampling.lowTreeCoverageBody': 'less than 20% of total area in 1 of 1 block',
  'sampling.designCreatedSuccess': 'Sampling Design Created Successfully',
  'sampling.previewSamplePlots': 'Preview Sample Plots',
  'sampling.samplePlotPreview': 'Sample Plot Preview',
  'sampling.createDesignConfirm': 'Create sampling design with current settings?',
  'sampling.stratumCardTitle': 'SFM stratum sampling',
  'sampling.stratumCardHint': 'Per-unit floors govern',
  'sampling.stratumTableBlock': 'Block',
  'sampling.stratumTableStratum': 'Stratum',
  'sampling.stratumTableFloor': 'Floor %',
  'sampling.stratumTablePlotSize': 'Plot Size',
  'sampling.stratumBelowFloor': 'Below the floor',
  'sampling.stratumFloorViolationBanner': 'Fix the stratum floor violations above',
  'sampling.stratumLabelProduction': 'Production',
  'sampling.stratumLabelConservation': 'Conservation',
  'sampling.intensityPct': 'Intensity %',
  'common.cancel': 'Cancel',
  'common.create': 'Create',
};

vi.mock('../../services/api', () => ({
  samplingApi: {
    list: vi.fn(),
    getPoints: vi.fn(),
    previewAccessibleForest: vi.fn(),
    create: vi.fn(),
    delete: vi.fn(),
    getProtectedZones: vi.fn(),
    preview: vi.fn(),
    unitPlan: vi.fn(),
    suggestedCounts: vi.fn(),
  },
  forestApi: {
    getCalculation: vi.fn(),
    setUnitOrientation: vi.fn(),
  },
  compartmentApi: {
    getAvailableBlocks: vi.fn(),
  },
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => enTranslations[k] || k }),
}));

vi.mock('../SamplingMapView', () => ({
  SamplingMapView: () => <div data-testid="sampling-map-view" />,
}));

vi.mock('../AccessibleForestPreview', () => ({
  AccessibleForestPreview: () => <div data-testid="accessible-preview" />,
}));

import { samplingApi, forestApi, compartmentApi } from '../../services/api';

// Loosely-typed view of a vi.fn() mock — keeps arrange/assert free of `as any`.
type MockView = {
  mockResolvedValue: (v: unknown) => void;
  mock: { calls: Array<[unknown, Record<string, unknown>]> };
};
const mv = (fn: unknown) => fn as unknown as MockView;

describe('SamplingTab — mode-driven method (Phase C)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (samplingApi.list as any).mockResolvedValue([]);
    // no polygons by default: the per-polygon table stays out of the way of the tests that are not about it
    (samplingApi.unitPlan as any).mockResolvedValue({ state: 'no_units', design_id: null, field_data_exists: false, units: [] });
    (samplingApi.suggestedCounts as any).mockRejectedValue(new Error('no suggestions'));
    (samplingApi.getPoints as any).mockResolvedValue({ points: [] });
    (samplingApi.getProtectedZones as any).mockResolvedValue({ has_protected: false });
    (forestApi.getCalculation as any).mockResolvedValue({
      id: 'calc-1',
      name: 'Test Forest',
      result_data: {},
    });
  });

  async function openForm() {
    render(<SamplingTab calculationId="calc-1" />);
    const createBtn = await screen.findByText('+ Create New Sampling Design');
    fireEvent.click(createBtn);
    await screen.findByText('Create Design');
  }

  it('compartment + systematic → Guideline-2061 config, no compartment-intensity control (C.1 / P5)', async () => {
    mv(compartmentApi.getAvailableBlocks).mockResolvedValue([
      { block_name: 'Comp 1', has_compartments: true },
    ]);
    await openForm();

    // Guideline-2061 config panel is now the systematic path for compartment forests too
    expect(screen.getAllByText(enTranslations['sampling.guidelineConfig'])).toHaveLength(1);
    expect(screen.getByText(enTranslations['sampling.intensityProductiveForest'])).toBeTruthy();
    expect(screen.getByText(enTranslations['sampling.plotSizeProductiveForest'])).toBeTruthy();
    // The compartment percentage-intensity control is not shown in systematic mode
    expect(screen.queryByText(enTranslations['sampling.intensityCompartmentMode'])).toBeNull();
    // Banner explains the active path
    expect(screen.getByText(enTranslations['sampling.modeBannerGuideline'])).toBeTruthy();
  });

  it('compartment + systematic → submits guideline_2061 without intensity payload (C.2 / P5)', async () => {
    mv(compartmentApi.getAvailableBlocks).mockResolvedValue([
      { block_name: 'Comp 1', has_compartments: true },
    ]);
    await openForm();

    fireEvent.click(screen.getByText(enTranslations['sampling.createDesignConfirm']));

    await waitFor(() => expect(samplingApi.create).toHaveBeenCalledTimes(1));
    const [[, params]] = mv(samplingApi.create).mock.calls;
    expect(params.sampling_method).toBe('guideline_2061');
    expect(params.sampling_type).toBeUndefined();
    expect(params.sampling_intensity_percent).toBeUndefined();
    // SS-1.5: the production-stratum floor (कार्यविधि §16) is 2.0%, so that
    // is now the dropdown's default, not the old pre-enforcement 0.5%.
    expect(params.productive_intensity).toBe('2.0');
  });

  it('compartment + systematic → protected-zone 0.1% toggle is reachable (C.3 / P5)', async () => {
    mv(compartmentApi.getAvailableBlocks).mockResolvedValue([
      { block_name: 'Comp 1', has_compartments: true },
    ]);
    mv(samplingApi.getProtectedZones).mockResolvedValue({
      has_protected: true,
      protected_zone_count: 1,
      protected_area_hectares: 4.2,
    });
    await openForm();

    const toggle = await screen.findByText(enTranslations['sampling.sampleProtectedZones0_1']);
    expect(toggle).toBeTruthy();

    fireEvent.click(screen.getByText(enTranslations['sampling.createDesignConfirm']));
    await waitFor(() => expect(samplingApi.create).toHaveBeenCalledTimes(1));
    const [[, params]] = mv(samplingApi.create).mock.calls;
    expect(params.sampling_method).toBe('guideline_2061');
    expect(params.sample_protected_zone).toBe(false);
  });

  const unit = (over: Record<string, unknown>) => ({
    unit_id: 'u', name: 'Comp-1', area_ha: 10, slope_band: 1, stratum: 'production', stratum_source: 'default',
    management_orientation: null, floor_pct: 2.0, plot_size_sqm: 500, sampled_plots: 0, ...over,
  });
  const UNIT_PLAN_FIXTURE = {
    state: 'ready', design_id: null, field_data_exists: false,
    units: [
      unit({ unit_id: 'u1', name: 'Comp-1' }),
      unit({ unit_id: 'u2', name: 'Comp-2', stratum: 'conservation', stratum_source: 'user', floor_pct: 1.0 }),
    ],
  };
  const withPlan = (plan: unknown = UNIT_PLAN_FIXTURE) => {
    mv(compartmentApi.getAvailableBlocks).mockResolvedValue([{ block_name: 'Comp 1', has_compartments: true }]);
    mv(samplingApi.unitPlan).mockResolvedValue(plan);
  };

  it('asks the server for the per-polygon plan - no SFM classification is needed for the table', async () => {
    withPlan();
    await openForm();
    await waitFor(() => expect(samplingApi.unitPlan).toHaveBeenCalledWith('calc-1'));
    expect(await screen.findByTestId('sampling-unit-table')).toBeTruthy();
  });

  it('compartment + systematic → the polygon table is shown, and with nothing ticked the payload carries every polygon at its minimum (SS-1.5)', async () => {
    withPlan();
    await openForm();
    expect(await screen.findByTestId('sampling-unit-table')).toBeTruthy();
    expect(screen.getByTestId('unit-selection-note').textContent).toBe('sampling.unitTable.allUnticked');

    fireEvent.click(screen.getByText(enTranslations['sampling.createDesignConfirm']));
    await waitFor(() => expect(samplingApi.create).toHaveBeenCalledTimes(1));
    const [[, params]] = mv(samplingApi.create).mock.calls;
    expect(params.per_block_intensity).toEqual({ 'Comp-1': 2.0, 'Comp-2': 1.0 });
  });

  it('ticking a polygon samples ONLY that polygon: the others are sent as 0 % (excluded)', async () => {
    withPlan();
    await openForm();
    fireEvent.click(await screen.findByTestId('unit-tick-Comp-2'));
    expect(screen.getByTestId('unit-selection-note').textContent).toBe('sampling.unitTable.onlyTicked');

    fireEvent.click(screen.getByText(enTranslations['sampling.createDesignConfirm']));
    await waitFor(() => expect(samplingApi.create).toHaveBeenCalledTimes(1));
    const [[, params]] = mv(samplingApi.create).mock.calls;
    expect(params.per_block_intensity).toEqual({ 'Comp-1': 0, 'Comp-2': 1.0 });
  });

  it('compartment + systematic → per-unit intensity pre-filled at the minimum, freely raisable', async () => {
    withPlan();
    await openForm();

    // (the test's t() mock ignores interpolation args, so the aria-label key itself is the shared accessible name for every row)
    const intensityInputs = await screen.findAllByLabelText('sampling.stratumTableIntensityFor');
    expect(intensityInputs).toHaveLength(2);
    const values = intensityInputs.map((el) => (el as HTMLInputElement).value);
    expect(values).toEqual(expect.arrayContaining(['2', '1']));

    // Raising Comp-1 above its production minimum (2.0%) is allowed (users may exceed a floor, never fall below it).
    const comp1Input = intensityInputs.find((el) => (el as HTMLInputElement).value === '2')!;
    fireEvent.change(comp1Input, { target: { value: '2.5' } });

    fireEvent.click(screen.getByText(enTranslations['sampling.createDesignConfirm']));
    await waitFor(() => expect(samplingApi.create).toHaveBeenCalledTimes(1));
    const [[, params]] = mv(samplingApi.create).mock.calls;
    expect(params.per_block_intensity).toEqual({ 'Comp-1': 2.5, 'Comp-2': 1.0 });
  });

  it('compartment + systematic → typing below a unit\'s minimum blocks Create/Preview (D2)', async () => {
    withPlan();
    await openForm();

    const intensityInputs = await screen.findAllByLabelText('sampling.stratumTableIntensityFor');
    // Comp-1 is production stratum, floor 2.0% — drop it to 1.5%.
    const comp1Input = intensityInputs.find((el) => (el as HTMLInputElement).value === '2')!;
    fireEvent.change(comp1Input, { target: { value: '1.5' } });

    expect(await screen.findByText(enTranslations['sampling.stratumFloorViolationBanner'])).toBeTruthy();
    expect(screen.getByText(enTranslations['sampling.createDesignConfirm'])).toBeDisabled();

    fireEvent.click(screen.getByText(enTranslations['sampling.createDesignConfirm']));
    expect(samplingApi.create).not.toHaveBeenCalled();
  });

  it('a violation on a polygon that is NOT going to be sampled does not block the design', async () => {
    withPlan();
    await openForm();
    const inputs = await screen.findAllByLabelText('sampling.stratumTableIntensityFor');
    fireEvent.change(inputs.find((el) => (el as HTMLInputElement).value === '2')!, { target: { value: '1.5' } }); // Comp-1 below its minimum
    fireEvent.click(screen.getByTestId('unit-tick-Comp-2')); // ...but only Comp-2 is to be sampled
    expect(screen.queryByText(enTranslations['sampling.stratumFloorViolationBanner'])).toBeNull();
    expect(screen.getByText(enTranslations['sampling.createDesignConfirm'])).not.toBeDisabled();
  });

  it('changing a polygon\'s stratum saves it as the unit\'s orientation, then re-reads the plan', async () => {
    withPlan();
    mv(forestApi.setUnitOrientation).mockResolvedValue({});
    await openForm();
    const select = await screen.findByTestId('unit-stratum-Comp-1');
    fireEvent.change(select, { target: { value: 'conservation' } });
    await waitFor(() => expect(forestApi.setUnitOrientation).toHaveBeenCalledWith('calc-1', 'u1', 'Conservation'));
    await waitFor(() => expect((samplingApi.unitPlan as any).mock.calls.length).toBeGreaterThan(1));
  });

  it('a forest with no polygons shows no table (backward compatible)', async () => {
    withPlan({ state: 'no_units', design_id: null, field_data_exists: false, units: [] });
    await openForm();
    expect(screen.queryByTestId('sampling-unit-table')).toBeNull();
  });

it('block mode → Guideline-2061 without intensity payload (C.1/C.2)', async () => {
    (compartmentApi.getAvailableBlocks as any).mockResolvedValue([
      { block_name: 'Block 1', has_compartments: false },
    ]);
    await openForm();

    expect(screen.getAllByText(enTranslations['sampling.guidelineConfig'])).toHaveLength(1);
    expect(screen.queryByText(enTranslations['sampling.intensityCompartmentMode'])).toBeNull();
    expect(screen.getByText(enTranslations['sampling.guidelineNoteBody'])).toBeTruthy();

    fireEvent.click(screen.getByText(enTranslations['sampling.createDesignConfirm']));

    await waitFor(() => expect(samplingApi.create).toHaveBeenCalledTimes(1));
    const [[, params]] = (samplingApi.create as any).mock.calls;
    expect(params.sampling_method).toBe('guideline_2061');
    expect(params.sampling_intensity_percent).toBeUndefined();
    expect(params.sampling_type).toBeUndefined();
  });
});

describe('SamplingTab — sampling type selector (Phase E)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (samplingApi.list as any).mockResolvedValue([]);
    // no polygons by default: the per-polygon table stays out of the way of the tests that are not about it
    (samplingApi.unitPlan as any).mockResolvedValue({ state: 'no_units', design_id: null, field_data_exists: false, units: [] });
    (samplingApi.suggestedCounts as any).mockRejectedValue(new Error('no suggestions'));
    (samplingApi.getPoints as any).mockResolvedValue({ points: [] });
    (samplingApi.getProtectedZones as any).mockResolvedValue({ has_protected: false });
    (forestApi.getCalculation as any).mockResolvedValue({
      id: 'calc-1',
      name: 'Test Forest',
      result_data: {},
    });
  });

  async function openForm() {
    render(<SamplingTab calculationId="calc-1" />);
    const createBtn = await screen.findByText('+ Create New Sampling Design');
    fireEvent.click(createBtn);
    await screen.findByText('Create Design');
  }

  it('type selector is shown in both modes (E.1)', async () => {
    (compartmentApi.getAvailableBlocks as any).mockResolvedValue([
      { block_name: 'Block 1', has_compartments: false },
    ]);
    await openForm();
    expect(screen.getByText('Sampling Type')).toBeTruthy();
    expect(screen.getAllByText('Systematic').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Random').length).toBeGreaterThan(0);
  });

  it('compartment + Random → min-distance revealed; manual+random+2.0 payload (E.2)', async () => {
    (compartmentApi.getAvailableBlocks as any).mockResolvedValue([
      { block_name: 'Comp 1', has_compartments: true },
    ]);
    await openForm();

    // systematic is the default → Guideline-2061; switching to Random reveals the
    // compartment percentage-intensity + min-distance controls
    fireEvent.click(screen.getByText(enTranslations['sampling.methodRandom']));
    await screen.findByDisplayValue('2');
    await screen.findByText(enTranslations['sampling.minDistanceBetweenPoints']);
    expect(screen.getByDisplayValue('30')).toBeTruthy();

    fireEvent.click(screen.getByText(enTranslations['sampling.createDesignConfirm']));
    await waitFor(() => expect(samplingApi.create).toHaveBeenCalledTimes(1));
    const [[, params]] = (samplingApi.create as any).mock.calls;
    expect(params.sampling_method).toBe('manual');
    expect(params.sampling_type).toBe('random');
    expect(params.sampling_intensity_percent).toBe(2);
    expect(params.min_distance_meters).toBe(30);
  });

  it('block + Random → intensity fallback with 0.5% default + min distance; manual+random payload (E.3)', async () => {
    (compartmentApi.getAvailableBlocks as any).mockResolvedValue([
      { block_name: 'Block 1', has_compartments: false },
    ]);
    await openForm();

    fireEvent.click(screen.getByText(enTranslations['sampling.methodRandom']));
    await screen.findByText(enTranslations['sampling.intensityRandomFallback']);
    expect(screen.getByDisplayValue('0.5')).toBeTruthy();
    expect(screen.getByText(enTranslations['sampling.minDistanceBetweenPoints'])).toBeTruthy();
    expect(screen.getByText(enTranslations['sampling.modeBannerBlockRandom'])).toBeTruthy();
    expect(screen.queryByText(enTranslations['sampling.guidelineConfig'])).toBeNull();

    fireEvent.click(screen.getByText(enTranslations['sampling.createDesignConfirm']));
    await waitFor(() => expect(samplingApi.create).toHaveBeenCalledTimes(1));
    const [[, params]] = (samplingApi.create as any).mock.calls;
    expect(params.sampling_method).toBe('manual');
    expect(params.sampling_type).toBe('random');
    expect(params.sampling_intensity_percent).toBe(0.5);
    expect(params.min_distance_meters).toBe(30);
  });
});

describe('SamplingTab — area basis (Phase D)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (samplingApi.list as any).mockResolvedValue([]);
    // no polygons by default: the per-polygon table stays out of the way of the tests that are not about it
    (samplingApi.unitPlan as any).mockResolvedValue({ state: 'no_units', design_id: null, field_data_exists: false, units: [] });
    (samplingApi.suggestedCounts as any).mockRejectedValue(new Error('no suggestions'));
    (samplingApi.getPoints as any).mockResolvedValue({ points: [] });
    (samplingApi.getProtectedZones as any).mockResolvedValue({ has_protected: false });
    (forestApi.getCalculation as any).mockResolvedValue({
      id: 'calc-1',
      name: 'Test Forest',
      result_data: {},
    });
  });

async function openForm() {
    render(<SamplingTab calculationId="calc-1" />);
    const createBtn = await screen.findByText(enTranslations['sampling.createNewDesign']);
    fireEvent.click(createBtn);
    await screen.findByText(enTranslations['sampling.createDesignConfirm']);
  }

  it('default basis = Tree Cover → filter_tree_cover=true in payload (D.1)', async () => {
    (compartmentApi.getAvailableBlocks as any).mockResolvedValue([
      { block_name: 'Block 1', has_compartments: false },
    ]);
    await openForm();

    fireEvent.click(screen.getByText(enTranslations['sampling.createDesignConfirm']));
    await waitFor(() => expect(samplingApi.create).toHaveBeenCalledTimes(1));
    const [[, params]] = (samplingApi.create as any).mock.calls;
    expect(params.filter_tree_cover).toBe(true);
  });

  it('Full Block Area basis → filter_tree_cover=false in payload (D.1)', async () => {
    (compartmentApi.getAvailableBlocks as any).mockResolvedValue([
      { block_name: 'Block 1', has_compartments: false },
    ]);
    await openForm();

    fireEvent.click(screen.getByText(/Area Basis Full/));
    fireEvent.click(screen.getByText(enTranslations['sampling.createDesignConfirm']));
    await waitFor(() => expect(samplingApi.create).toHaveBeenCalledTimes(1));
    const [[, params]] = (samplingApi.create as any).mock.calls;
    expect(params.filter_tree_cover).toBe(false);
  });

  it('low-coverage warning shown for tree-cover basis (D.2)', async () => {
    (compartmentApi.getAvailableBlocks as any).mockResolvedValue([
      { block_name: 'Block 1', has_compartments: false },
    ]);
    (samplingApi.list as any).mockResolvedValue([
      {
        id: 'd1',
        created_at: new Date().toISOString(),
        sampling_type: 'systematic',
        total_points: 4,
        default_parameters: { filter_tree_cover: true, area_basis: 'tree_cover' },
        result_data: {
          total_points: 4,
          total_blocks: 1,
          requested_intensity_percent: 0.5,
          sampling_percentage: 0.5,
          blocks_info: [
            { block_name: 'Block 1', block_area_hectares: 10, accessible_forest_area_ha: 1 },
          ],
        },
      },
    ]);

    render(<SamplingTab calculationId="calc-1" />);
    expect(await screen.findByText(/Low Tree-Cover Coverage/)).toBeTruthy();
    expect(screen.getByText(/less than 20% of total area in 1 of 1/)).toBeTruthy();
  });

  it('no low-coverage warning for Full Area basis (D.2)', async () => {
    (compartmentApi.getAvailableBlocks as any).mockResolvedValue([
      { block_name: 'Block 1', has_compartments: false },
    ]);
    (samplingApi.list as any).mockResolvedValue([
      {
        id: 'd1',
        created_at: new Date().toISOString(),
        sampling_type: 'systematic',
        total_points: 4,
        default_parameters: { filter_tree_cover: false, area_basis: 'full_area' },
        result_data: {
          total_points: 4,
          total_blocks: 1,
          requested_intensity_percent: 0.5,
          sampling_percentage: 0.5,
          blocks_info: [
            { block_name: 'Block 1', block_area_hectares: 10, accessible_forest_area_ha: 10 },
          ],
        },
      },
    ]);

    render(<SamplingTab calculationId="calc-1" />);
    await screen.findByText(/Sampling Design Created Successfully/);
    expect(screen.queryByText(/Low Tree-Cover Coverage/)).toBeNull();
  });

  it('fully-treed unit with raster overcount (accessible > block area) does NOT warn (D.2 clamp)', async () => {
    (compartmentApi.getAvailableBlocks as any).mockResolvedValue([
      { block_name: 'Block 1', has_compartments: false },
    ]);
    (samplingApi.list as any).mockResolvedValue([
      {
        id: 'd1',
        created_at: new Date().toISOString(),
        sampling_type: 'systematic',
        total_points: 4,
        default_parameters: { filter_tree_cover: true, area_basis: 'tree_cover' },
        result_data: {
          total_points: 4,
          total_blocks: 1,
          requested_intensity_percent: 0.5,
          sampling_percentage: 0.5,
          blocks_info: [
            { block_name: 'C4', block_area_hectares: 31.88, accessible_forest_area_ha: 36.13 },
          ],
        },
      },
    ]);

    render(<SamplingTab calculationId="calc-1" />);
    await screen.findByText(/Sampling Design Created Successfully/);
    expect(screen.queryByText(/Low Tree-Cover Coverage/)).toBeNull();
  });

  it('Per Unit Summary table shows a Stratum column populated from block.stratum', async () => {
    (compartmentApi.getAvailableBlocks as any).mockResolvedValue([
      { block_name: 'Block 1', has_compartments: false },
      { block_name: 'Block 2', has_compartments: false },
    ]);
    (samplingApi.list as any).mockResolvedValue([
      {
        id: 'd1',
        created_at: new Date().toISOString(),
        sampling_type: 'systematic',
        total_points: 12,
        default_parameters: { filter_tree_cover: false, area_basis: 'full_area' },
        result_data: {
          total_points: 12,
          total_blocks: 2,
          requested_intensity_percent: 2.0,
          sampling_percentage: 2.0,
          blocks_info: [
            { block_name: 'Block 1', block_area_hectares: 10, accessible_forest_area_ha: 10, stratum: 'production' },
            { block_name: 'Block 2', block_area_hectares: 5, accessible_forest_area_ha: 5, stratum: 'protection' },
          ],
        },
      },
    ]);

    render(<SamplingTab calculationId="calc-1" />);
    await screen.findByText(/Sampling Design Created Successfully/);

    // sampling.stratumTableStratum is mocked to "Stratum" -- reused as the
    // Per Unit Summary column header (SFM_STRATUM_SAMPLING_PLAN SS-1.x, part B).
    expect(screen.getAllByText('Stratum').length).toBeGreaterThan(0);
    expect(screen.getAllByText(enTranslations['sampling.stratumLabelProduction']).length).toBeGreaterThan(0);
  });
});
