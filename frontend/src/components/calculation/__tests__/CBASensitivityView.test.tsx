import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import CBASensitivityView from '../CBASensitivityView';
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
  name: 'Base',
  description: null,
  discount_rate: '10.00',
  time_horizon_years: 5,
  irr_start_year: 1,
  currency: 'NPR',
  default_rates: {},
  is_base_scenario: true,
  status: 'draft',
  cost_items: [],
  benefit_items: [],
  result: {
    npv: '150000',
    irr: '0.4',
    benefit_cost_ratio: '2.0',
    payback_period_years: '2.5',
    total_cost_pv: '1',
    total_benefit_pv: '2',
    cash_flow_data: [
      { year: 1, cost: 100000, benefit: 0, net: -100000 },
      { year: 2, cost: 50000, benefit: 80000, net: 30000 },
      { year: 3, cost: 25000, benefit: 100000, net: 75000 },
    ],
    computed_at: '2026-09-08T00:00:00Z',
  },
  created_at: '2026-09-08T00:00:00Z',
  updated_at: '2026-09-08T00:00:00Z',
  ...over,
});

beforeEach(() => vi.clearAllMocks());

describe('CBASensitivityView', () => {
  it('renders sliders and a live NPV / IRR / B-C preview', () => {
    render(
      <CBASensitivityView
        calculationId="c1"
        scenario={scenario()}
        onChanged={vi.fn()}
      />,
    );
    expect(screen.getByText('Sensitivity (what-if)')).toBeTruthy();
    expect(screen.getByText('Benefit level')).toBeTruthy();
    // NPV preview is rendered (a ₹ figure appears in the result box)
    expect(screen.getAllByText(/₹/).length).toBeGreaterThan(0);
  });

  it('renders nothing when the scenario has no result', () => {
    const { container } = render(
      <CBASensitivityView
        calculationId="c1"
        scenario={scenario({ result: null })}
        onChanged={vi.fn()}
      />,
    );
    expect(container.textContent).toBe('');
  });

  it('"Apply discount rate" starts disabled and enables + persists when the rate changes', async () => {
    cba.updateScenario.mockResolvedValue({});
    cba.compute.mockResolvedValue({});
    const onChanged = vi.fn();
    const { rerender } = render(
      <CBASensitivityView
        calculationId="c1"
        scenario={scenario()}
        onChanged={onChanged}
      />,
    );
    const btn = () => screen.getByText('Apply discount rate to scenario').closest('button')!;
    expect(btn()).toBeDisabled();

    // simulate the slider moving via antd's onChange contract: the discount
    // Slider is the only one bound to a value != 0. Fire its aria change.
    const rateSlider = document.querySelectorAll('.ant-slider')[2] as HTMLElement;
    const handle = rateSlider.querySelector('.ant-slider-handle') as HTMLElement;
    fireEvent.mouseDown(handle, { clientX: 300 });
    fireEvent.mouseMove(document, { clientX: 320 });
    fireEvent.mouseUp(document);

    // fall back: if jsdom didn't move it, drive the InputNumber directly
    if (btn().hasAttribute('disabled')) {
      const input = rateSlider.parentElement!.querySelector(
        'input.ant-input-number-input',
      ) as HTMLInputElement;
      fireEvent.change(input, { target: { value: '15' } });
      fireEvent.blur(input);
    }
    await waitFor(() => expect(btn()).not.toBeDisabled());
    fireEvent.click(btn());
    await waitFor(() => expect(cba.updateScenario).toHaveBeenCalled());
    expect(cba.compute).toHaveBeenCalledWith('s1');
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    rerender(<div />);
  });
});
