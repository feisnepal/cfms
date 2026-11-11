import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import NtfpHarvestPanel from '../NtfpHarvestPanel';
import * as api from '../../../services/api';

vi.mock('../../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../../services/api')>();
  return { ...actual, ntfpHarvestApi: { get: vi.fn(), save: vi.fn(), toYearlyPlan: vi.fn() } };
});

const m = api.ntfpHarvestApi as unknown as Record<string, ReturnType<typeof vi.fn>>;

const ROW = {
  species_key: 'zanthoxylum armatum', nepali_name: 'टिमुर', scientific_name: 'Zanthoxylum armatum', part_group: 'ङ',
  stock_fresh_kg: 1000, stock_dry_kg: 400, yield_precision_pct: 20,
  price: { npr_per_unit: 5, unit: 'kg', basis: 'schedule7', estimated: false, note: 'Schedule-7 ङ 1' },
  plan: null, value_npr_per_year: null,
  aah: { pct_min: 80, pct_max: 80, source_key: 'ANSAB2022', source_title: 'Toolkit on Sustainable Harvesting', locator: 'Annex 3, AAH table', status: 'documented', note: null },
};
const EMPTY_PLAN = { rows: [ROW], totals: { rows_planned: 0, kg_per_year: 0, value_npr_per_year: 0 } };
const PLANNED = {
  rows: [{ ...ROW, plan: { annual_quantity: 40, unit: 'kg', weight_basis: 'dry', price_override: null, notes: null }, value_npr_per_year: 200 }],
  totals: { rows_planned: 1, kg_per_year: 40, value_npr_per_year: 200 },
};

beforeEach(() => {
  Object.values(m).forEach((f) => f.mockReset());
  m.get.mockResolvedValue(EMPTY_PLAN);
});

const renderPanel = () => render(<NtfpHarvestPanel calculationId="c1" refreshKey={0} />);
const quantity = () => screen.getByLabelText('Harvest a year') as HTMLInputElement;
const saveButton = () => screen.getByRole('button', { name: 'Save harvest plan' });
const yearlyButton = () => screen.getByRole('button', { name: /Add the collection to the yearly plan/ });

describe('NtfpHarvestPanel', () => {
  it('lists the surveyed parts with stock and rate, and nothing is planned yet', async () => {
    renderPanel();
    expect(await screen.findByText('टिमुर')).toBeInTheDocument();
    expect(screen.getByText(/dry: 400 kg/i)).toBeInTheDocument();
    expect(screen.getByText('Rs 5/kg')).toBeInTheDocument();
    expect(saveButton()).toBeDisabled();
    expect(yearlyButton()).toBeDisabled();
  });

  it('shows the annual allowable harvest with its source and fills the quantity from it on request', async () => {
    renderPanel();
    await screen.findByText('टिमुर');
    expect(screen.getByText(/80 %/)).toBeInTheDocument();
    expect(screen.getByText('ANSAB2022, Annex 3, AAH table')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Use the allowable harvest' }));
    await waitFor(() => expect(quantity().value).toBe('320'));             // 80 % of the 400 kg dry stock
    expect(saveButton()).not.toBeDisabled();                                // the owner still saves it: nothing is filled in silently
  });

  it('says plainly when the sources read give no allowable harvest for a part', async () => {
    m.get.mockResolvedValue({ ...EMPTY_PLAN, rows: [{ ...ROW, aah: null }] });
    renderPanel();
    await screen.findByText('टिमुर');
    expect(screen.getByText('No figure in the sources read')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Use the allowable harvest' })).not.toBeInTheDocument();
  });

  it('fills the quantity from a share of the stock', async () => {
    renderPanel();
    await screen.findByText('टिमुर');
    fireEvent.change(screen.getByLabelText('Share of stock a year'), { target: { value: '10' } });
    await waitFor(() => expect(quantity().value).toBe('40'));       // 10 % of the 400 kg dry stock
    expect(saveButton()).not.toBeDisabled();
  });

  it('refuses a quantity above the whole stock before it is sent', async () => {
    renderPanel();
    await screen.findByText('टिमुर');
    fireEvent.change(quantity(), { target: { value: '500' } });
    expect(await screen.findByText('More than the stock')).toBeInTheDocument();
    expect(saveButton()).toBeDisabled();
  });

  it('saves only the planned rows and shows the saved totals', async () => {
    m.save.mockResolvedValue(PLANNED);
    renderPanel();
    await screen.findByText('टिमुर');
    fireEvent.change(quantity(), { target: { value: '40' } });
    fireEvent.click(saveButton());
    await waitFor(() => expect(m.save).toHaveBeenCalledWith('c1', [
      { species_key: 'zanthoxylum armatum', part_group: 'ङ', annual_quantity: 40, unit: 'kg', weight_basis: 'dry', price_override: null },
    ]));
    expect(await screen.findByText(/40 kg a year, worth Rs 200 a year/)).toBeInTheDocument();
    expect(yearlyButton()).not.toBeDisabled();
  });

  it('adds the collection line to the yearly plan and says when one already exists', async () => {
    m.get.mockResolvedValue(PLANNED);
    m.toYearlyPlan.mockResolvedValueOnce({ created: true, line_id: 'l1', quantity: 40, kg_planned: 40, activity: 'x' })
      .mockResolvedValueOnce({ created: false, line_id: 'l1', quantity: 25, kg_planned: 40, activity: 'x' });
    renderPanel();
    await screen.findByText('टिमुर');
    fireEvent.click(yearlyButton());
    expect(await screen.findByText(/now has an NTFP collection line of 40 kg a year/)).toBeInTheDocument();
    await waitFor(() => expect(yearlyButton()).toBeEnabled());      // the first call has finished
    fireEvent.click(yearlyButton());
    expect(await screen.findByText(/already has an NTFP collection line \(25 kg a year\)/)).toBeInTheDocument();
  });

  it('shows the server refusal as a translated message', async () => {
    m.save.mockRejectedValue({ response: { data: { detail: { code: 'harvest.exceeds_stock', message: 'x' } } } });
    renderPanel();
    await screen.findByText('टिमुर');
    fireEvent.change(quantity(), { target: { value: '40' } });
    fireEvent.click(saveButton());
    expect(await screen.findByText('A planned quantity is more than the whole standing stock.')).toBeInTheDocument();
  });

  it('explains an empty survey and a forest with no design', async () => {
    m.get.mockResolvedValueOnce({ rows: [], totals: { rows_planned: 0, kg_per_year: 0, value_npr_per_year: 0 } });
    const first = renderPanel();
    expect(await screen.findByText(/Nothing to plan yet/)).toBeInTheDocument();
    first.unmount();
    m.get.mockRejectedValueOnce({ response: { data: { detail: { code: 'no_design' } } } });
    renderPanel();
    expect(await screen.findByText('Lay out the sample plots first.')).toBeInTheDocument();
  });
});
