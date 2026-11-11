import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import CBATab from '../CBATab';
import * as api from '../../../services/api';
import type { CbaScenarioListItem } from '../../../services/api';

// the plan-drift banner has its own tests (CbaPlanDriftBanner.test.tsx)
vi.mock('../CbaPlanDriftBanner', () => ({ default: () => null }));

vi.mock('../../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../../services/api')>();
  return {
    ...actual,
    cbaApi: {
      ...actual.cbaApi,
      listScenarios: vi.fn(),
      createScenario: vi.fn(),
      setBase: vi.fn(),
      clone: vi.fn(),
      autoPopulate: vi.fn(),
      deleteScenario: vi.fn(),
    },
  };
});

const cba = api.cbaApi as unknown as Record<string, ReturnType<typeof vi.fn>>;

const row = (over: Partial<CbaScenarioListItem>): CbaScenarioListItem => ({
  id: 'a',
  name: 'Base Scenario',
  is_base_scenario: true,
  status: 'draft',
  discount_rate: '10.00',
  cost_count: 0,
  benefit_count: 0,
  has_result: false,
  npv: null,
  irr: null,
  benefit_cost_ratio: null,
  payback_period_years: null,
  created_at: '2026-09-08T00:00:00Z',
  ...over,
});

beforeEach(() => {
  vi.clearAllMocks();
});

describe('CBATab', () => {
  it('shows the empty state and creates the base scenario', async () => {
    cba.listScenarios.mockResolvedValueOnce([]).mockResolvedValueOnce([row({})]);
    cba.createScenario.mockResolvedValue({ id: 'a' });
    render(<CBATab calculationId="c1" />);

    await waitFor(() => screen.getByText('No scenarios yet'));
    fireEvent.click(screen.getByText('Create base scenario'));
    await waitFor(() => expect(cba.createScenario).toHaveBeenCalledWith('c1', expect.any(Object)));
    await waitFor(() => expect(cba.listScenarios).toHaveBeenCalledTimes(2));
  });

  it('lists scenarios and auto-selects the base', async () => {
    cba.listScenarios.mockResolvedValue([
      row({ id: 'a', name: 'Base Scenario', is_base_scenario: true }),
      row({ id: 'b', name: 'High Harvest', is_base_scenario: false }),
    ]);
    render(<CBATab calculationId="c1" />);
    await waitFor(() => screen.getByText('High Harvest'));
    expect(screen.getByText('Base Scenario')).toBeTruthy();
    expect(screen.getByText('Scenarios')).toBeTruthy();
  });

  it('shows an error + retry when the list fails', async () => {
    cba.listScenarios.mockRejectedValueOnce(new Error('boom')).mockResolvedValueOnce([row({})]);
    render(<CBATab calculationId="c1" />);
    await waitFor(() => screen.getByText('Could not load the cost-benefit scenarios.'));
    fireEvent.click(screen.getByText('Retry'));
    await waitFor(() => screen.getByText('Base Scenario'));
  });
});
