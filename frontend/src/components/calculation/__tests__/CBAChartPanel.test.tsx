import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import CBAChartPanel from '../CBAChartPanel';
import * as api from '../../../services/api';
import type { CbaExportData } from '../../../services/api';

vi.mock('react-chartjs-2', () => ({
  Bar: () => <div data-testid="bar-chart" />,
  Line: () => <div data-testid="line-chart" />,
  Pie: () => <div data-testid="pie-chart" />,
}));

vi.mock('../../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../../services/api')>();
  return { ...actual, cbaApi: { ...actual.cbaApi, exportData: vi.fn() } };
});

const exp = api.cbaApi.exportData as unknown as ReturnType<typeof vi.fn>;

const data = (over: Partial<CbaExportData> = {}): CbaExportData => ({
  base_npv: '1000',
  base_irr: 18.5,
  base_bc_ratio: '2.0',
  base_payback: '4.0',
  summary_table: [],
  cash_flow_table: [
    { year: 1, cost: 500, benefit: 800, net: 300 },
    { year: 2, cost: 400, benefit: 900, net: 500 },
  ],
  cost_breakdown: [{ label: 'Harvest', amount: 900, percent: 100 }],
  benefit_breakdown: [
    { label: 'timber', amount: 1200, percent: 70 },
    { label: 'fuelwood', amount: 500, percent: 30 },
  ],
  ...over,
});

beforeEach(() => exp.mockReset());

describe('CBAChartPanel', () => {
  it('renders the bar, line and two pies from export-data', async () => {
    exp.mockResolvedValue(data());
    render(<CBAChartPanel cbaId="s1" />);
    await waitFor(() => expect(screen.getByTestId('bar-chart')).toBeTruthy());
    expect(screen.getByTestId('line-chart')).toBeTruthy();
    expect(screen.getAllByTestId('pie-chart')).toHaveLength(2);
  });

  it('shows the "compute first" empty state when there is no cash flow', async () => {
    exp.mockResolvedValue(data({ cash_flow_table: [] }));
    render(<CBAChartPanel cbaId="s1" />);
    await waitFor(() =>
      expect(screen.getByText('Compute the scenario to see the charts.')).toBeTruthy(),
    );
  });
});
