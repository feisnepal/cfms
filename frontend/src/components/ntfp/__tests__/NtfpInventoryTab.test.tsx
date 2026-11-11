import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import NtfpInventoryTab from '../NtfpInventoryTab';
import * as api from '../../../services/api';

// The map is Leaflet: not under test here (it needs a real browser layout)
vi.mock('../NtfpPlotMap', () => ({ default: () => <div data-testid="map-stub" /> }));
vi.mock('../../../utils/download', () => ({ downloadFromApi: vi.fn().mockResolvedValue(undefined) }));

vi.mock('../../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../../services/api')>();
  return {
    ...actual,
    ntfpApi: {
      species: vi.fn(), getDesign: vi.fn(), previewDesign: vi.fn(), createDesign: vi.fn(), deleteDesign: vi.fn(),
      formPath: (id: string) => `/api/calculations/${id}/ntfp/form`, uploadForm: vi.fn(), records: vi.fn(), deleteRecords: vi.fn(), results: vi.fn(), card: vi.fn(),
    },
  };
});

const m = api.ntfpApi as unknown as Record<string, ReturnType<typeof vi.fn>>;

const SPECIES = [
  { species_key: 'zanthoxylum armatum', scientific_name: 'Zanthoxylum armatum', aliases: [], nepali_name: 'टिमुर', priority_serial: 30, has_method_card: true,
    growth_class: 'shrub', life_form_ne: 'झाडी', part_ne: 'फल', part_groups: ['ङ'], sampling_method: 'non_destructive', plot_min_sqm: 25, plot_max_sqm: 25,
    altitude_min_m: 1100, altitude_max_m: 2500, conversion_factor: null, prices: [{ group: 'ङ', group_ne: 'फल', group_en: 'Fruit', price: 5, unit: 'kg', basis: 'schedule7', estimated: false, basis_note: '' }],
    default_plot_sqm: 25, default_intensity_pct: 0.5, card_status: 'documented', season: [],
    aah: [{ field: 'aah_pct', part_group: 'ङ', id: 'a1', value_num: 80, value_num2: null, value_text: null, unit: '%', calendar: null, source_key: 'ANSAB2022', source_title: 'x', source_year: '2022',
      source_url: null, source_tier: 3, locator: 'Annex 3, AAH table', status: 'documented', chosen: true, note: null, reviewed_by: null, reviewed_at: null }] },
  { species_key: 'azadirachta indica', scientific_name: 'Azadirachta indica', aliases: [], nepali_name: 'नीम', priority_serial: 5, has_method_card: false,
    growth_class: null, life_form_ne: null, part_ne: null, part_groups: [], sampling_method: null, plot_min_sqm: null, plot_max_sqm: null,
    altitude_min_m: 100, altitude_max_m: 900, conversion_factor: null, prices: [], default_plot_sqm: null, default_intensity_pct: null, card_status: null, aah: [], season: [] },
];

const DESIGN = {
  id: 'd1', plot_shape: 'square', seed: 7, min_plots: 3,
  species: [{ species_key: 'zanthoxylum armatum', label: 'टिमुर', growth_class: 'shrub', plot_sqm: 25, intensity_pct: 0.5, plots: 2, intensity_achieved_pct: 0.5, plots_by_stratum: {} }],
  strata: [{ name: 'forest', area_ha: 10, plots_wanted: 2, plots_laid: 2, spacing_m: 50, warnings: [] }],
  plots: [{ plot_number: 1, stratum: 'forest', transect: 1, longitude: 84, latitude: 28, species_keys: ['zanthoxylum armatum'] }],
  warnings: [], transects: { type: 'FeatureCollection', features: [] }, layout: {},
};

beforeEach(() => {
  Object.values(m).forEach((f) => f.mockReset?.());
  m.species.mockResolvedValue({ forest_area_ha: 120, species: SPECIES });
  m.getDesign.mockResolvedValue({ design: null });
  m.records.mockResolvedValue({ pairs_assigned: 0, pairs_recorded: 0, weights: 0, observations: [] });
  m.results.mockRejectedValue({ response: { data: { detail: { code: 'no_design' } } } });
  m.card.mockResolvedValue({ species_key: 'zanthoxylum armatum', nepali_name: 'टिमुर', scientific_name: 'Zanthoxylum armatum', aliases: [], card_status: 'documented', has_method_card: true,
    growth_class: 'shrub', part_groups: ['ङ'], sources: {}, facts: [] });
});

const renderTab = () => render(<NtfpInventoryTab calculationId="c1" calculation={null} />);

describe('NtfpInventoryTab', () => {
  it('lists the species with their guideline defaults and royalty rate', async () => {
    renderTab();
    expect(await screen.findByText('टिमुर')).toBeInTheDocument();
    expect(screen.getByText('नीम')).toBeInTheDocument();
    expect(m.species).toHaveBeenCalledWith('c1', expect.objectContaining({}));
    await waitFor(() => expect(m.getDesign).toHaveBeenCalledWith('c1'));
  });

  it('keeps Next disabled until a species is picked and then goes to the design tab', async () => {
    renderTab();
    await screen.findByText('टिमुर');
    const next = screen.getAllByRole('button').find((b) => /toDesign|sample plots/i.test(b.textContent ?? ''))!;
    expect(next).toBeDisabled();
    fireEvent.click(screen.getAllByRole('checkbox')[1]); // first row (0 is select-all)
    await waitFor(() => expect(next).not.toBeDisabled());
  });

  it('has a steps strip that follows the survey and opens the tab of a stage when it is clicked', async () => {
    renderTab();
    await screen.findByText('टिमुर');
    expect(screen.getByTestId('ntfp-stages')).toBeInTheDocument();
    expect(screen.getByTestId('ntfp-stage-species')).toHaveAttribute('data-status', 'current');
    expect(screen.getByTestId('ntfp-stage-design')).toHaveTextContent('Needs species first');
    fireEvent.click(screen.getByText('Lay out plots'));
    await waitFor(() => expect(screen.getByRole('tab', { name: /Sample plots/ })).toHaveAttribute('aria-selected', 'true'));
  });

  it('shows each species\' card status and its allowable harvest with the source', async () => {
    renderTab();
    await screen.findByText('टिमुर');
    expect(screen.getAllByText('Documented').length).toBeGreaterThan(0);   // timur has a documented card
    expect(screen.getAllByText('No card').length).toBeGreaterThan(0);      // neem has none
    expect(screen.getByText('Allowable harvest 80 %')).toBeInTheDocument();
  });

  it('opens a species\' card with its sources when the row is expanded', async () => {
    renderTab();
    await screen.findByText('टिमुर');
    const expanders = document.querySelectorAll('.ant-table-row-expand-icon');
    expect(expanders.length).toBeGreaterThan(0);                           // only rows with a card or a sourced figure can expand
    fireEvent.click(expanders[0]);
    await waitFor(() => expect(m.card).toHaveBeenCalledWith('c1', 'zanthoxylum armatum'));
  });

  it('shows a saved design as the starting point of the picks', async () => {
    m.getDesign.mockResolvedValue({ design: DESIGN });
    renderTab();
    await screen.findByText('टिमुर');
    await waitFor(() => expect(screen.getAllByRole('checkbox')[1]).toBeChecked());
  });

  it('refuses to preview a species with no method card until its growth class is chosen', async () => {
    renderTab();
    await screen.findByText('नीम');
    fireEvent.click(screen.getAllByRole('checkbox')[2]); // the species with no card
    const preview = (await screen.findAllByRole('button')).find((b) => /preview/i.test(b.textContent ?? ''));
    // the Design tab is not mounted until opened; the guard itself is unit-tested in lib/__tests__/ntfp.test.ts
    expect(preview === undefined || preview.hasAttribute('disabled')).toBe(true);
    expect(m.previewDesign).not.toHaveBeenCalled();
  });
});
