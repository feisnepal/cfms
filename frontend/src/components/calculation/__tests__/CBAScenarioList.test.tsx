import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import CBAScenarioList from '../CBAScenarioList';
import * as api from '../../../services/api';
import type { CbaScenarioListItem } from '../../../services/api';

vi.mock('../../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../../services/api')>();
  return {
    ...actual,
    cbaApi: {
      ...actual.cbaApi,
      createScenario: vi.fn(),
      setBase: vi.fn(),
      clone: vi.fn(),
      autoPopulate: vi.fn(),
      deleteScenario: vi.fn(),
    },
  };
});

const cba = api.cbaApi as unknown as Record<string, ReturnType<typeof vi.fn>>;

const mk = (over: Partial<CbaScenarioListItem>): CbaScenarioListItem => ({
  id: 'a',
  name: 'Base Scenario',
  is_base_scenario: true,
  status: 'draft',
  discount_rate: '10.00',
  cost_count: 3,
  benefit_count: 2,
  has_result: true,
  npv: '1245000.00',
  irr: '0.1854',
  benefit_cost_ratio: '2.4500',
  payback_period_years: '4.50',
  created_at: '2026-09-08T00:00:00Z',
  ...over,
});

const SCENARIOS = [
  mk({ id: 'a', name: 'Base Scenario', is_base_scenario: true }),
  mk({
    id: 'b',
    name: 'High Harvest',
    is_base_scenario: false,
    has_result: false,
    npv: null,
    irr: null,
    benefit_cost_ratio: null,
    payback_period_years: null,
  }),
];

const setup = (over: Partial<React.ComponentProps<typeof CBAScenarioList>> = {}) => {
  const onSelect = vi.fn();
  const onChanged = vi.fn();
  render(
    <CBAScenarioList
      calculationId="c1"
      scenarios={SCENARIOS}
      selectedId="a"
      onSelect={onSelect}
      onChanged={onChanged}
      {...over}
    />,
  );
  return { onSelect, onChanged };
};

beforeEach(() => vi.clearAllMocks());

describe('CBAScenarioList', () => {
  it('renders a card per scenario with formatted metrics', () => {
    setup();
    expect(screen.getByText('Base Scenario')).toBeTruthy();
    expect(screen.getByText('High Harvest')).toBeTruthy();
    expect(screen.getByText('₹12,45,000')).toBeTruthy(); // NPV, en-IN grouping
    expect(screen.getByText('18.5%')).toBeTruthy(); // IRR fraction -> %
    expect(screen.getByText('2.45')).toBeTruthy(); // B/C
  });

  it('"New scenario" creates and selects the new one', async () => {
    cba.createScenario.mockResolvedValue({ id: 'new' });
    const { onSelect, onChanged } = setup();
    fireEvent.click(screen.getByText('New scenario'));
    await waitFor(() => expect(cba.createScenario).toHaveBeenCalled());
    await waitFor(() => expect(onSelect).toHaveBeenCalledWith('new'));
    expect(onChanged).toHaveBeenCalled();
  });

  it('Set-as-base is disabled on the base card and fires for the others', async () => {
    cba.setBase.mockResolvedValue([]);
    const { onChanged } = setup();
    const setBaseBtns = screen
      .getAllByRole('button')
      .filter((b) => b.getAttribute('title') === 'Set as base scenario');
    // one per scenario; the base one is disabled
    expect(setBaseBtns).toHaveLength(2);
    expect(setBaseBtns.some((b) => (b as HTMLButtonElement).disabled)).toBe(true);
    const enabled = setBaseBtns.find((b) => !(b as HTMLButtonElement).disabled)!;
    fireEvent.click(enabled);
    await waitFor(() => expect(cba.setBase).toHaveBeenCalledWith('c1', 'b'));
    expect(onChanged).toHaveBeenCalled();
  });

  it('Auto-populate calls the API for that scenario', async () => {
    cba.autoPopulate.mockResolvedValue({
      updated: { costs: 0, benefits: 0 },
      inserted: { costs: 2, benefits: 1 },
      deleted: { costs: 0, benefits: 0 },
      message: 'done',
    });
    setup();
    const btn = screen
      .getAllByRole('button')
      .find((b) => b.getAttribute('title') === 'Auto-populate from system data')!;
    fireEvent.click(btn);
    await waitFor(() => expect(cba.autoPopulate).toHaveBeenCalledWith('a'));
  });

  it('Clone duplicates and selects the copy', async () => {
    cba.clone.mockResolvedValue({ id: 'copy' });
    const { onSelect } = setup();
    const btn = screen
      .getAllByRole('button')
      .find((b) => b.getAttribute('title') === 'Clone scenario')!;
    fireEvent.click(btn);
    await waitFor(() => expect(cba.clone).toHaveBeenCalledWith('c1', 'a'));
    await waitFor(() => expect(onSelect).toHaveBeenCalledWith('copy'));
  });
});
