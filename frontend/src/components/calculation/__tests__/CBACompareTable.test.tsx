import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import CBACompareTable from '../CBACompareTable';
import * as api from '../../../services/api';
import type { CbaCompareItem, CbaScenarioListItem } from '../../../services/api';

vi.mock('../../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../../services/api')>();
  return { ...actual, cbaApi: { ...actual.cbaApi, compare: vi.fn(), setBase: vi.fn() } };
});

const cba = api.cbaApi as unknown as Record<string, ReturnType<typeof vi.fn>>;

const listRow = (id: string, base: boolean): CbaScenarioListItem => ({
  id,
  name: id,
  is_base_scenario: base,
  status: 'draft',
  discount_rate: '10.00',
  cost_count: 0,
  benefit_count: 0,
  has_result: true,
  npv: null,
  irr: null,
  benefit_cost_ratio: null,
  payback_period_years: null,
  created_at: '2026-09-08T00:00:00Z',
});

const cmp = (id: string, over: Partial<CbaCompareItem> = {}): CbaCompareItem => ({
  cba_id: id,
  name: id,
  npv: '1245000.00',
  irr: '0.1854',
  benefit_cost_ratio: '2.4500',
  payback_period_years: '4.50',
  total_cost: '800000',
  total_benefit: '2045000',
  cost_count: 5,
  benefit_count: 3,
  ...over,
});

beforeEach(() => vi.clearAllMocks());

describe('CBACompareTable', () => {
  it('renders a row per scenario and marks the base', async () => {
    cba.compare.mockResolvedValue([cmp('Base'), cmp('High', { npv: '1520000.00' })]);
    render(
      <CBACompareTable
        calculationId="c1"
        scenarios={[listRow('Base', true), listRow('High', false)]}
        onChanged={vi.fn()}
      />,
    );
    await waitFor(() => expect(cba.compare).toHaveBeenCalledWith('c1', ['Base', 'High']));
    expect(screen.getAllByText('₹12,45,000').length).toBeGreaterThan(0); // Base NPV
    expect(screen.getAllByText('₹15,20,000').length).toBeGreaterThan(0); // High NPV
    expect(screen.getAllByText('18.5%').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Base').length).toBeGreaterThan(0); // base tag
  });

  it('renders nothing with fewer than two scenarios', async () => {
    cba.compare.mockResolvedValue([cmp('Base')]);
    const { container } = render(
      <CBACompareTable
        calculationId="c1"
        scenarios={[listRow('Base', true)]}
        onChanged={vi.fn()}
      />,
    );
    await waitFor(() => expect(cba.compare).toHaveBeenCalled());
    expect(container.querySelector('table')).toBeNull();
  });

  it('"Set as base" calls the API on a non-base row', async () => {
    cba.compare.mockResolvedValue([cmp('Base'), cmp('High')]);
    cba.setBase.mockResolvedValue([]);
    const onChanged = vi.fn();
    render(
      <CBACompareTable
        calculationId="c1"
        scenarios={[listRow('Base', true), listRow('High', false)]}
        onChanged={onChanged}
      />,
    );
    await waitFor(() => screen.getByText('Set as base'));
    fireEvent.click(screen.getByText('Set as base'));
    await waitFor(() => expect(cba.setBase).toHaveBeenCalledWith('c1', 'High'));
    expect(onChanged).toHaveBeenCalled();
  });
});
