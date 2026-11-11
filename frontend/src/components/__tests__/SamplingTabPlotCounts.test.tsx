import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, fireEvent, screen, waitFor } from '@testing-library/react';
import { SamplingTab } from '../SamplingTab';

// the test's t() returns the key (or this table's text); interpolation is not applied
const en: Record<string, string> = {
  'sampling.createNewDesign': '+ Create New Sampling Design',
  'sampling.createDesign': 'Create Design',
  'sampling.createDesignConfirm': 'Create sampling design with current settings?',
  'sampling.stratumFloorViolationBanner': 'Fix the stratum floor violations above',
  'sampling.intensityPct': 'Intensity %',
};

vi.mock('../../services/api', () => ({
  samplingApi: {
    list: vi.fn(), getPoints: vi.fn(), previewAccessibleForest: vi.fn(), create: vi.fn(), delete: vi.fn(),
    getProtectedZones: vi.fn(), preview: vi.fn(), unitPlan: vi.fn(), suggestedCounts: vi.fn(),
  },
  forestApi: { getCalculation: vi.fn(), setUnitOrientation: vi.fn() },
  compartmentApi: { getAvailableBlocks: vi.fn() },
}));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k: string) => en[k] || k }) }));
vi.mock('../SamplingMapView', () => ({ SamplingMapView: () => <div /> }));
vi.mock('../AccessibleForestPreview', () => ({ AccessibleForestPreview: () => <div /> }));

import { samplingApi, forestApi, compartmentApi } from '../../services/api';

const api = samplingApi as unknown as Record<string, ReturnType<typeof vi.fn>>;

// Two 10 ha polygons, 500 m2 plots: one plot is 0.5 % of a polygon. Comp-1 production (minimum 2 % = 4 plots), Comp-2 conservation
// (minimum 1 % = 2 plots); both can have at most 10 plots (5 %).
const unit = (over: Record<string, unknown>) => ({
  unit_id: 'u', name: 'Comp-1', area_ha: 10, slope_band: 1, stratum: 'production', stratum_source: 'default', management_orientation: null,
  floor_pct: 2.0, plot_size_sqm: 500, sampled_plots: 0, ...over,
});
const PLAN = {
  state: 'ready', design_id: null, field_data_exists: false,
  units: [unit({ unit_id: 'u1', name: 'Comp-1' }), unit({ unit_id: 'u2', name: 'Comp-2', stratum: 'conservation', floor_pct: 1.0 })],
};
const sug = (over: Record<string, unknown>) => ({
  area_ha: 10, plot_size_sqm: 500, intensity_pct: 2, computed: 4, suggested: 5, raised_to_minimum: true, equivalent_pct: 2.5,
  min_plots_legal: 4, max_plots_legal: 10, ...over,
});
const SUGGESTIONS = {
  minimum_suggested: 5,
  units: { 'Comp-1': sug({}), 'Comp-2': sug({ intensity_pct: 1, computed: 2, min_plots_legal: 2 }) },
};

async function openForm() {
  render(<SamplingTab calculationId="calc-1" />);
  fireEvent.click(await screen.findByText('+ Create New Sampling Design'));
  await screen.findByText('Create Design');
}

// the suggestions arrive a moment after the form opens (they are asked for once the intensities settle)
const suggestionsLoaded = () => waitFor(() => expect(screen.getByTestId('unit-suggested-Comp-1').textContent).toContain('5'));

describe('SamplingTab - number of plots per polygon', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.list.mockResolvedValue([]);
    api.getPoints.mockResolvedValue({ points: [] });
    api.getProtectedZones.mockResolvedValue({ has_protected: false });
    api.unitPlan.mockResolvedValue(PLAN);
    api.suggestedCounts.mockResolvedValue(SUGGESTIONS);
    (forestApi.getCalculation as any).mockResolvedValue({ id: 'calc-1', name: 'Test Forest', result_data: {} });
    (compartmentApi.getAvailableBlocks as any).mockResolvedValue([{ block_name: 'Comp 1', has_compartments: true }]);
  });

  it('shows what each intensity amounts to and suggests at least 5, saying so when it raised the number', async () => {
    await openForm();
    await suggestionsLoaded();
    expect(screen.getByTestId('unit-raised-Comp-1').textContent).toContain('sampling.unitTable.raisedToMinimum');
    expect((screen.getByTestId('unit-plots-Comp-1') as HTMLInputElement).value).toBe('5'); // pre-filled with the suggestion
    expect(screen.getByTestId('unit-equivalent-Comp-1')).toBeTruthy();
  });

  it('asks the server for the suggestion with the polygons\' intensities and the engine in use', async () => {
    await openForm();
    await suggestionsLoaded();
    expect(api.suggestedCounts).toHaveBeenCalledWith('calc-1', { 'Comp-1': 2, 'Comp-2': 1 }, 'guideline');
  });

  it('the payload carries exactly the number shown for every polygon, so what is placed is what the user saw', async () => {
    api.create.mockResolvedValue({ sampling_design_id: 'd1', blocks_info: [] });
    await openForm();
    await suggestionsLoaded();
    fireEvent.click(screen.getByText(en['sampling.createDesignConfirm']));
    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1));
    const [[, params]] = api.create.mock.calls;
    expect(params.per_block_plots).toEqual({ 'Comp-1': 5, 'Comp-2': 5 });
  });

  it('the user may increase or decrease the number, fewer than 5 included, and is told it is fewer than usual', async () => {
    api.create.mockResolvedValue({ sampling_design_id: 'd1', blocks_info: [] });
    await openForm();
    await suggestionsLoaded();
    const box = screen.getByTestId('unit-plots-Comp-1') as HTMLInputElement;
    fireEvent.change(box, { target: { value: '4' } }); // the legal minimum for Comp-1, below the usual 5
    expect(screen.getByTestId('unit-plots-fewer-Comp-1').textContent).toContain('fewerThanUsual');
    expect(screen.queryByTestId('unit-plots-problem-Comp-1')).toBeNull();
    expect(screen.getByTestId('unit-equivalent-Comp-1').textContent).toContain('equivalent');
    fireEvent.change(screen.getByTestId('unit-plots-Comp-2'), { target: { value: '9' } }); // more than suggested

    fireEvent.click(screen.getByText(en['sampling.createDesignConfirm']));
    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1));
    expect(api.create.mock.calls[0][1].per_block_plots).toEqual({ 'Comp-1': 4, 'Comp-2': 9 });
  });

  it('shows how far the typed number is from the suggestion, and nothing when it matches', async () => {
    await openForm();
    await suggestionsLoaded();
    expect(screen.queryByTestId('unit-deviation-Comp-1')).toBeNull(); // the suggestion itself
    fireEvent.change(screen.getByTestId('unit-plots-Comp-1'), { target: { value: '8' } });
    expect(screen.getByTestId('unit-deviation-Comp-1').textContent).toContain('deviationMore');
    fireEvent.change(screen.getByTestId('unit-plots-Comp-1'), { target: { value: '4' } });
    expect(screen.getByTestId('unit-deviation-Comp-1').textContent).toContain('deviationFewer');
    fireEvent.click(screen.getByTestId('unit-plots-reset-Comp-1'));
    expect(screen.queryByTestId('unit-deviation-Comp-1')).toBeNull();
  });

  it('a number below the legal minimum is shown in red and blocks the design; above the usual 5 % only warns (owner 2026-10-08)', async () => {
    await openForm();
    await suggestionsLoaded();
    const box = screen.getByTestId('unit-plots-Comp-1') as HTMLInputElement;
    fireEvent.change(box, { target: { value: '3' } }); // 1.5 % < 2 %
    expect(screen.getByTestId('unit-plots-problem-Comp-1').textContent).toContain('plotsTooFew');
    expect(await screen.findByText(en['sampling.stratumFloorViolationBanner'])).toBeTruthy();
    expect(screen.getByText(en['sampling.createDesignConfirm'])).toBeDisabled();

    fireEvent.change(box, { target: { value: '11' } }); // 5.5 % > 5 %: allowed, the user is told
    expect(screen.queryByTestId('unit-plots-problem-Comp-1')).toBeNull();
    expect(screen.getByTestId('unit-plots-above-Comp-1').textContent).toContain('plotsAboveUsual');
    expect(screen.queryByText(en['sampling.stratumFloorViolationBanner'])).toBeNull();
    expect(screen.getByText(en['sampling.createDesignConfirm'])).not.toBeDisabled();

    fireEvent.change(box, { target: { value: '6' } });
    expect(screen.queryByTestId('unit-plots-problem-Comp-1')).toBeNull();
    expect(screen.queryByTestId('unit-plots-above-Comp-1')).toBeNull();
    expect(screen.getByText(en['sampling.createDesignConfirm'])).not.toBeDisabled();
  });

  it('0 plots leaves the polygon out, and it is not held to the minimum', async () => {
    api.create.mockResolvedValue({ sampling_design_id: 'd1', blocks_info: [] });
    await openForm();
    await suggestionsLoaded();
    fireEvent.change(screen.getByTestId('unit-plots-Comp-1'), { target: { value: '0' } });
    expect(screen.queryByTestId('unit-plots-problem-Comp-1')).toBeNull();
    fireEvent.click(screen.getByText(en['sampling.createDesignConfirm']));
    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1));
    expect(api.create.mock.calls[0][1].per_block_plots['Comp-1']).toBe(0);
  });

  it('editing the intensity starts again from it: the typed number is dropped and the suggestion is asked again', async () => {
    await openForm();
    await suggestionsLoaded();
    const box = screen.getByTestId('unit-plots-Comp-1') as HTMLInputElement;
    fireEvent.change(box, { target: { value: '8' } });
    expect(box.value).toBe('8');
    const calls = api.suggestedCounts.mock.calls.length;
    const intensity = screen.getAllByLabelText('sampling.stratumTableIntensityFor')[0];
    fireEvent.change(intensity, { target: { value: '3' } });
    await waitFor(() => expect(api.suggestedCounts.mock.calls.length).toBeGreaterThan(calls));
    expect((screen.getByTestId('unit-plots-Comp-1') as HTMLInputElement).value).toBe('5'); // back to the suggestion
  });

  it('a ticked polygon is the only one with a number; the others are sent as 0', async () => {
    api.create.mockResolvedValue({ sampling_design_id: 'd1', blocks_info: [] });
    await openForm();
    await suggestionsLoaded();
    fireEvent.click(screen.getByTestId('unit-tick-Comp-2'));
    fireEvent.click(screen.getByText(en['sampling.createDesignConfirm']));
    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1));
    expect(api.create.mock.calls[0][1].per_block_plots).toEqual({ 'Comp-1': 0, 'Comp-2': 5 });
  });

  it('without suggestions the form still works from the intensities alone', async () => {
    api.suggestedCounts.mockRejectedValue(new Error('down'));
    api.create.mockResolvedValue({ sampling_design_id: 'd1', blocks_info: [] });
    await openForm();
    await screen.findByTestId('sampling-unit-table');
    await waitFor(() => expect(api.suggestedCounts).toHaveBeenCalled()); // asked, and it failed
    fireEvent.click(screen.getByText(en['sampling.createDesignConfirm']));
    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1));
    expect(api.create.mock.calls[0][1].per_block_plots).toBeUndefined();
    expect(api.create.mock.calls[0][1].per_block_intensity).toEqual({ 'Comp-1': 2, 'Comp-2': 1 });
  });
});
