import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import CBALineItemEditor from '../CBALineItemEditor';
import * as api from '../../../services/api';
import type { CbaCostItem, CbaBenefitItem } from '../../../services/api';

vi.mock('../../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../../services/api')>();
  return {
    ...actual,
    cbaApi: {
      ...actual.cbaApi,
      createCost: vi.fn(),
      updateCost: vi.fn(),
      deleteCost: vi.fn(),
      createBenefit: vi.fn(),
      updateBenefit: vi.fn(),
      deleteBenefit: vi.fn(),
    },
  };
});

const cba = api.cbaApi as unknown as Record<string, ReturnType<typeof vi.fn>>;

const cost = (over: Partial<CbaCostItem> = {}): CbaCostItem => ({
  id: 'k1',
  cba_id: 's1',
  category: 'Harvest',
  description: 'Felling',
  year_from: 1,
  year_to: 10,
  amount_per_year: '20000',
  is_recurring: false,
  total_amount: '200000',
  source_link: 'activity:abc',
  notes: null,
  display_order: 0,
  created_at: '2026-09-08T00:00:00Z',
  updated_at: '2026-09-08T00:00:00Z',
  ...over,
});

const benefit = (over: Partial<CbaBenefitItem> = {}): CbaBenefitItem => ({
  ...(cost() as unknown as CbaBenefitItem),
  id: 'b1',
  source: 'timber',
  quantity: '50',
  unit_price: '8000',
  source_link: null,
  ...over,
});

beforeEach(() => vi.clearAllMocks());

describe('CBALineItemEditor', () => {
  it('renders a row per item with an Auto / Manual badge', () => {
    render(
      <CBALineItemEditor
        cbaId="s1"
        kind="cost"
        items={[cost(), cost({ id: 'k2', source_link: null, category: 'Manual cost' })]}
        onChanged={vi.fn()}
      />,
    );
    // antd Table with scroll.x renders a measure row → use getAllBy
    expect(screen.getAllByText('Auto').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Manual').length).toBeGreaterThan(0);
    expect(screen.getAllByDisplayValue('Felling').length).toBeGreaterThan(0);
  });

  it('Add row creates a cost item', async () => {
    cba.createCost.mockResolvedValue({});
    const onChanged = vi.fn();
    render(
      <CBALineItemEditor cbaId="s1" kind="cost" items={[]} onChanged={onChanged} />,
    );
    fireEvent.click(screen.getByText('Add row'));
    await waitFor(() => expect(cba.createCost).toHaveBeenCalledWith('s1', expect.any(Object)));
    expect(onChanged).toHaveBeenCalled();
  });

  it('editing a number cell saves on blur', async () => {
    cba.updateCost.mockResolvedValue({});
    render(
      <CBALineItemEditor cbaId="s1" kind="cost" items={[cost()]} onChanged={vi.fn()} />,
    );
    const apy = screen.getAllByDisplayValue('20000')[0];
    fireEvent.change(apy, { target: { value: '30000' } });
    fireEvent.blur(apy);
    await waitFor(() =>
      expect(cba.updateCost).toHaveBeenCalledWith('s1', 'k1', { amount_per_year: 30000 }),
    );
  });

  it('rejects an inverted year range without calling the API', async () => {
    cba.updateCost.mockResolvedValue({});
    const onChanged = vi.fn();
    render(
      <CBALineItemEditor
        cbaId="s1"
        kind="cost"
        items={[cost({ year_from: 1, year_to: 10 })]}
        onChanged={onChanged}
      />,
    );
    const yf = screen.getAllByDisplayValue('1')[0];
    fireEvent.change(yf, { target: { value: '12' } }); // 12 > year_to 10
    fireEvent.blur(yf);
    await waitFor(() =>
      expect(screen.getByText(/Year range is invalid/i)).toBeTruthy(),
    );
    expect(cba.updateCost).not.toHaveBeenCalled();
  });

  it('the lock button converts an auto row to manual', async () => {
    cba.updateCost.mockResolvedValue({});
    render(
      <CBALineItemEditor cbaId="s1" kind="cost" items={[cost()]} onChanged={vi.fn()} />,
    );
    fireEvent.click(screen.getAllByTitle(/Lock the value/i)[0]);
    await waitFor(() =>
      expect(cba.updateCost).toHaveBeenCalledWith('s1', 'k1', { source_link: null }),
    );
  });

  it('delete goes through the Popconfirm', async () => {
    cba.deleteCost.mockResolvedValue(undefined);
    render(
      <CBALineItemEditor cbaId="s1" kind="cost" items={[cost()]} onChanged={vi.fn()} />,
    );
    const row = screen.getAllByDisplayValue('Felling')[0].closest('tr')!;
    const btns = within(row).getAllByRole('button');
    fireEvent.click(btns[btns.length - 1]); // trailing delete
    fireEvent.click(await screen.findByText('OK'));
    await waitFor(() => expect(cba.deleteCost).toHaveBeenCalledWith('s1', 'k1'));
  });

  it('the benefit kind shows quantity and unit price columns and saves them', async () => {
    cba.updateBenefit.mockResolvedValue({});
    render(
      <CBALineItemEditor
        cbaId="s1"
        kind="benefit"
        items={[benefit()]}
        onChanged={vi.fn()}
      />,
    );
    expect(screen.getAllByText('Quantity').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Unit price').length).toBeGreaterThan(0);
    // the "Source" column (benefit-only) is editable
    const src = screen.getAllByDisplayValue('timber')[0];
    fireEvent.change(src, { target: { value: 'fuelwood' } });
    fireEvent.blur(src);
    await waitFor(() =>
      expect(cba.updateBenefit).toHaveBeenCalledWith('s1', 'b1', { source: 'fuelwood' }),
    );
  });
});
