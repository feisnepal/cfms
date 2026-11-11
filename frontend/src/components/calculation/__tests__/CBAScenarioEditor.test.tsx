import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import CBAScenarioEditor from '../CBAScenarioEditor';
import * as api from '../../../services/api';
import type { CbaScenario } from '../../../services/api';

vi.mock('../../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../../services/api')>();
  return {
    ...actual,
    cbaApi: { ...actual.cbaApi, updateScenario: vi.fn(), compute: vi.fn() },
  };
});

const cba = api.cbaApi as unknown as Record<string, ReturnType<typeof vi.fn>>;

const scenario = (over: Partial<CbaScenario> = {}): CbaScenario => ({
  id: 's1',
  calculation_id: 'c1',
  name: 'Base Scenario',
  description: null,
  discount_rate: '10.00',
  time_horizon_years: 10,
  irr_start_year: 1,
  currency: 'NPR',
  default_rates: {},
  is_base_scenario: true,
  status: 'draft',
  cost_items: [],
  benefit_items: [],
  result: null,
  created_at: '2026-09-08T00:00:00Z',
  updated_at: '2026-09-08T00:00:00Z',
  ...over,
});

beforeEach(() => vi.clearAllMocks());

describe('CBAScenarioEditor', () => {
  it('seeds the fields and keeps Save disabled until a field changes', () => {
    render(
      <CBAScenarioEditor calculationId="c1" scenario={scenario()} onChanged={vi.fn()} />,
    );
    expect((screen.getByDisplayValue('Base Scenario') as HTMLInputElement).value).toBe(
      'Base Scenario',
    );
    expect(screen.getByText('Save').closest('button')).toBeDisabled();
  });

  it('saves the edited parameters', async () => {
    cba.updateScenario.mockResolvedValue(scenario());
    const onChanged = vi.fn();
    render(
      <CBAScenarioEditor calculationId="c1" scenario={scenario()} onChanged={onChanged} />,
    );
    fireEvent.change(screen.getByDisplayValue('Base Scenario'), {
      target: { value: 'Renamed' },
    });
    await waitFor(() => expect(screen.getByText('Save').closest('button')).not.toBeDisabled());
    fireEvent.click(screen.getByText('Save'));
    await waitFor(() =>
      expect(cba.updateScenario).toHaveBeenCalledWith(
        'c1',
        's1',
        expect.objectContaining({ name: 'Renamed' }),
      ),
    );
    expect(onChanged).toHaveBeenCalled();
  });

  it('Compute calls the API and refreshes', async () => {
    cba.compute.mockResolvedValue({});
    const onChanged = vi.fn();
    render(
      <CBAScenarioEditor calculationId="c1" scenario={scenario()} onChanged={onChanged} />,
    );
    fireEvent.click(screen.getByText('Compute'));
    await waitFor(() => expect(cba.compute).toHaveBeenCalledWith('s1'));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it('shows the result panel with N/A IRR and the viability verdict', () => {
    render(
      <CBAScenarioEditor
        calculationId="c1"
        scenario={scenario({
          result: {
            npv: '26569513.34',
            irr: null,
            benefit_cost_ratio: '61.0565',
            payback_period_years: '0.00',
            total_cost_pv: '442408.83',
            total_benefit_pv: '27011922.17',
            cash_flow_data: [],
            computed_at: '2026-09-08T00:00:00Z',
          },
        })}
        onChanged={vi.fn()}
      />,
    );
    expect(screen.getByText('₹2,65,69,513')).toBeTruthy(); // NPV en-IN
    expect(screen.getByText('N/A')).toBeTruthy(); // IRR undefined
    expect(screen.getByText('61.06')).toBeTruthy(); // B/C
    expect(
      screen.getByText(/financially viable/i),
    ).toBeTruthy();
  });
});
