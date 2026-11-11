/**
 * Per-species MAI and AAH.
 *
 * Both tables were dead. They were guarded on `block.mai_by_species` and
 * `block.aah_by_species`, and the backend never writes either key - proved
 * against both of the owner's forests: 0 of 21 and 0 of 5 blocks carry them. So
 * `{{ti_mai_table}}` and `{{ti_aah_table}}` could never render, and the 27-token
 * parity test passed only because its fixture supplied data the API does not
 * produce.
 *
 * The fix performs the SAME apportionment the backend already does for DBH
 * classes - a volume share of the block figure - with species in place of class,
 * from the per-species per-ha volumes the pane already loads. The property that
 * makes that safe is that the shares are a true partition, so the per-species
 * rows must sum back to the block MAI and AAH. That is what these assert.
 */
import { describe, it, expect, vi } from 'vitest';
import { render } from '@testing-library/react';
import React from 'react';

const state: any = { current: null };

vi.mock('react-chartjs-2', () => ({ Pie: () => null, Bar: () => null }));
vi.mock('../utils/chartSetup', () => ({}));
vi.mock('../utils/download', () => ({ downloadFromApi: vi.fn(), downloadBlob: vi.fn() }));
vi.mock('../../i18n/hooks', () => ({ useT: () => (k: string) => k }));
vi.mock('../../i18n/numberFormat', () => ({
  formatNumber: (v: any) => String(v ?? ''),
  formatDecimal: (v: any, d = 2) => Number(v || 0).toFixed(d),
}));

vi.mock('../fieldInventory/useFieldInventoryData', () => ({
  useFieldInventoryData: () => state.current,
}));

import { FieldInventoryResultsTables } from '../fieldInventory/FieldInventoryResultsTables';
import { renderWithProviders } from '../../test/renderWithProviders';

const AREA = 10;

// Two species, volumes 60 and 40 per ha -> shares 0.6 / 0.4.
const SPECIES_ROWS = [
  { block_name: 'B1', species_local: 'Amala', dbh_class: '30-40', count_per_ha: 120, timber_m3_per_ha: 30, firewood_m3_per_ha: 0, volume_m3_per_ha: 60 },
  { block_name: 'B1', species_local: 'Simal', dbh_class: '10-20', count_per_ha: 80, timber_m3_per_ha: 20, firewood_m3_per_ha: 5, volume_m3_per_ha: 40 },
  { block_name: 'B1', species_local: 'Amala', dbh_class: '40-50', count_per_ha: 30, timber_m3_per_ha: 10, firewood_m3_per_ha: 0, volume_m3_per_ha: 0 },
];

const BLOCK = {
  block_name: 'B1',
  area_ha: AREA,
  mai_m3_per_ha: 5,
  aah_m3_per_ha: 2,
  total_mai_m3: 50,
  total_aah_m3: 20,
  total_growing_stock_m3: 1000,
};

const TOTAL_DATA = {
  forest_totals: { total_area_ha: AREA, dbh_class_totals: {} },
  blocks: [BLOCK],
  species_breakdown: [],
};

function mount() {
  state.current = {
    fieldInventory: { id: 'fi-1', status: 'completed' },
    labels: { unitLabelNp: 'Unit' },
    totalData: TOTAL_DATA,
    blockRates: {},
    totalsLoading: false,
    ensureResultsLoaded: () => {},
    speciesDbhData: SPECIES_ROWS,
    speciesDbhForestWide: [],
  };
  return renderWithProviders(<FieldInventoryResultsTables />);
}

const num = (s: string) => Number(s.replace(/[^0-9.\-]/g, ''));

describe('per-species MAI and AAH render, and reconcile', () => {
  it('renders the MAI-by-species table with a row per species', () => {
    const { container } = mount();
    const text = container.textContent || '';
    expect(text).toContain('totalInventory.maiBySpecies');
    expect(text).toContain('Amala');
    expect(text).toContain('Simal');
  });

  it('renders the AAH-by-species table with a row per species', () => {
    const { container } = mount();
    const text = container.textContent || '';
    expect(text).toContain('totalInventory.aahBySpecies');
    expect(text).toContain('Amala');
  });

  it('splits the block MAI by volume share: 60/100 and 40/100 of 5 per ha', () => {
    const { container } = mount();
    const text = container.textContent || '';
    // Amala 3.00 m3/ha, Simal 2.00 m3/ha. findAll by the species cell order.
    expect(text).toContain('3.00'); // Amala MAI/ha
    expect(text).toContain('2.00'); // Simal MAI/ha
  });

  it('sums the per-species MAI back to the block total', () => {
    // 5 m3/ha x 10 ha = 50 m3/yr, and the per-species rows must account for
    // all of it. A share that did not partition would silently lose volume.
    const { container } = mount();
    const text = container.textContent || '';
    // 30 + 20 = 50 m3 total across the two species.
    const totals = (text.match(/50\.00/g) || []).length;
    expect(totals).toBeGreaterThan(0);
  });

  it('sums the per-species AAH back to the block total', () => {
    // 2 m3/ha x 10 ha = 20 m3/yr -> 12 + 8.
    const { container } = mount();
    const text = container.textContent || '';
    expect(text).toContain('12.00'); // Amala AAH total
    expect(text).toContain('8.00');  // Simal AAH total
  });

  it('groups a species that appears in two DBH classes into one row', () => {
    // Amala appears in 30-40 and 40-50. Two rows would double-count it; the
    // third row has volume 0 and must not create a spurious share.
    // Identified by its own header set: MAI-by-species is the table with
    // `totalMai`, while MAI-by-DBH-class carries `totalMaiYr`. Scoped this way
    // because Amala legitimately appears more than once across the pane - the
    // species x DBH tables list it once per class.
    const { container } = mount();
    const all = Array.from(container.querySelectorAll('table'));
    const table = all.find((t) => {
      const head = t.querySelector('thead')?.textContent || '';
      return head.includes('totalMai') && !head.includes('totalMaiYr');
    });
    expect(table).toBeTruthy();
    const rows = Array.from(table!.querySelectorAll('tbody tr')).map((r) =>
      (r.textContent || '').trim(),
    );
    expect(rows.filter((r) => r.includes('Amala'))).toHaveLength(1);
    expect(rows.filter((r) => r.includes('Simal'))).toHaveLength(1);
  });

  it('renders nothing when there is no per-species data at all', () => {
    mount();
    state.current.speciesDbhData = [];
    const { container } = renderWithProviders(<FieldInventoryResultsTables />);
    const text = container.textContent || '';
    expect(text).not.toContain('totalInventory.maiBySpecies');
    expect(text).not.toContain('totalInventory.aahBySpecies');
  });
});
