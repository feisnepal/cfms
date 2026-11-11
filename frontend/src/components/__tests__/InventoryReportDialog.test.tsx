import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const get = vi.fn();
vi.mock('../../services/api', async (orig) => ({ ...(await orig<typeof import('../../services/api')>()), default: { get: (...a: unknown[]) => get(...a) } }));
vi.mock('../../i18n/hooks', () => ({
  useT: () => (key: string, o?: Record<string, unknown>) => (o?.defaultValue as string) ?? key,
}));

import { InventoryReportDialog } from '../InventoryReportDialog';

const row = (over: Record<string, unknown>) => ({
  name: 'x', kind: 'unit', depth: 1, parent: null, area_ha: 10, has_data: true, plots: 3, regeneration_per_ha: 100, sapling_per_ha: 50,
  pole_per_ha: 20, tree_per_ha: 10, growing_stock_m3_per_ha: 50, growing_stock_m3: 500, basal_area_m2_per_ha: 5, mai_m3_per_ha: 1.5, mai_m3: 15,
  aah_m3_per_ha: 0.6, aah_m3: 6, forest_condition: 'Good', regeneration_condition: 'Good', covered_pct: 100, ...over,
});

const REPORT = {
  state: 'ready', leaf_count: 2, has_errors: true,
  rows: [
    row({ name: 'blocks-1', kind: 'rollup', forest_condition: null, plots: 9, growing_stock_m3_per_ha: 18 }),
    row({ name: 'blocks-1-SC1', depth: 2, parent: 'blocks-1' }),
    row({ name: 'blocks-1-SC2', depth: 2, parent: 'blocks-1', has_data: false, plots: 0, growing_stock_m3_per_ha: null, forest_condition: null, covered_pct: 0 }),
  ],
  total: row({ name: 'total', kind: 'total', depth: 0, forest_condition: null }),
  problems: [
    { code: 'PLOT_IN_DIVIDED_UNIT', severity: 'error', unit: 'blocks-1', message: '3 plot(s) are still assigned to blocks-1, which has been divided', count: 3 },
    { code: 'UNIT_WITHOUT_PLOTS', severity: 'warning', unit: 'blocks-1-SC2', message: 'blocks-1-SC2 has no sample plot', count: 0 },
  ],
};

const mount = () =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <InventoryReportDialog calculationId="c1" open onClose={() => {}} />
    </QueryClientProvider>,
  );

describe('Inventory by sub-unit', () => {
  beforeEach(() => get.mockReset());

  it('lists the units, a roll-up for the divided parent and the forest total', async () => {
    get.mockResolvedValue({ data: REPORT });
    mount();
    await waitFor(() => expect(screen.getByTestId('inventory-report')).toBeTruthy());
    const kinds = Array.from(document.querySelectorAll('[data-testid="inventory-report"] tbody tr')).map((tr) => tr.getAttribute('data-kind'));
    expect(kinds).toEqual(['rollup', 'unit', 'unit', 'total']);
    expect(screen.getByText('Forest total')).toBeTruthy();
    expect(get).toHaveBeenCalledWith('/api/calculations/c1/field-inventory-report');
  });

  it('puts the inventory problems above the table, errors and warnings told apart', async () => {
    get.mockResolvedValue({ data: REPORT });
    mount();
    await waitFor(() => expect(screen.getByTestId('inventory-problems')).toBeTruthy());
    const items = Array.from(document.querySelectorAll('[data-testid="inventory-problems"] li'));
    expect(items.map((li) => li.getAttribute('data-severity'))).toEqual(['error', 'warning']);
    expect(items[0].textContent).toContain('which has been divided');
  });

  it('can hide the roll-up rows and show only the undivided units (the forest total stays)', async () => {
    get.mockResolvedValue({ data: REPORT });
    mount();
    await waitFor(() => expect(screen.getByTestId('inventory-report')).toBeTruthy());
    fireEvent.click(screen.getByTestId('inventory-report-rollups'));
    const kinds = Array.from(document.querySelectorAll('[data-testid="inventory-report"] tbody tr')).map((tr) => tr.getAttribute('data-kind'));
    expect(kinds).toEqual(['unit', 'unit', 'total']);
  });

  it('says so when there is no inventory yet, and cannot download', async () => {
    get.mockResolvedValue({ data: { state: 'not_computed', rows: [], total: null, leaf_count: 0, problems: [], has_errors: false } });
    mount();
    await waitFor(() => expect(screen.getByTestId('inventory-report-empty')).toBeTruthy());
    expect((screen.getByTestId('inventory-report-download') as HTMLButtonElement).disabled).toBe(true);
  });

  it('asks the server for the workbook when downloading', async () => {
    get.mockImplementation((url: string, cfg?: { params?: { format?: string } }) =>
      Promise.resolve(cfg?.params?.format === 'xlsx'
        ? { data: new Blob(['x']), headers: { 'content-disposition': 'attachment; filename="a.xlsx"' } }
        : { data: REPORT }));
    (URL as unknown as { createObjectURL: () => string }).createObjectURL = () => 'blob:x';
    (URL as unknown as { revokeObjectURL: () => void }).revokeObjectURL = () => {};
    mount();
    await waitFor(() => expect(screen.getByTestId('inventory-report')).toBeTruthy());
    fireEvent.click(screen.getByTestId('inventory-report-download'));
    await waitFor(() =>
      expect(get).toHaveBeenCalledWith('/api/calculations/c1/field-inventory-report', { params: { format: 'xlsx' }, responseType: 'blob' }));
  });
});
