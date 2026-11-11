/**
 * The yearly-activities page after P5 of the yearly-activities plan: the plan is the shared PlanHome (it opens on
 * "Your plan"), there is no "Save All", and the totals and the operational-plan preview are read from the same plan
 * the table shows — a year at 0 and 0 counts as nothing planned.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import YearlyActivitiesPage from '../YearlyActivitiesPage';
import { yearlyPlanApi, type YearlyPlanLine } from '../../../services/api';

const navigate = vi.fn();
vi.mock('react-router-dom', () => ({ useNavigate: () => navigate }));
vi.mock('react-chartjs-2', () => ({ Bar: () => <div data-testid="bar-chart" />, Pie: () => <div data-testid="pie-chart" /> }));
vi.mock('../../../utils/chartSetup', () => ({}));
vi.mock('../../calculation/HazardVarChip', () => ({ useCanDesignTemplates: () => false }));
vi.mock('../../DetailDescription/CopyTag', () => ({ default: () => null }));
vi.mock('../../../features/yearly-plan/PlanExportMenu', () => ({ PlanExportMenu: () => null }));
vi.mock('../../../features/yearly-plan/LocationChooserModal', () => ({
  LocationChooserModal: ({ line }: { line: { id: string } | null }) => (line ? <div data-testid="chooser">{line.id}</div> : null),
}));
vi.mock('../../../features/yearly-plan/PlanHome', () => ({
  PlanHome: (props: {
    addSignal?: number;
    onEditOnMap?: () => void;
    onOpenDetails?: (line: { id: string }) => void;
  }) => (
    <div data-testid="plan-home" data-add-signal={props.addSignal}>
      <button onClick={props.onEditOnMap}>edit-on-map</button>
      <button onClick={() => props.onOpenDetails?.({ id: 'L1' })}>open-location</button>
    </div>
  ),
}));
vi.mock('../../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../../services/api')>();
  return { ...actual, yearlyPlanApi: { getPlan: vi.fn(), getHealth: vi.fn(), confirmLine: vi.fn() } };
});

const plan = yearlyPlanApi as unknown as Record<'getPlan' | 'getHealth', ReturnType<typeof vi.fn>>;

const cells = (f: (year: number) => [number, number]) =>
  Array.from({ length: 10 }, (_, i) => {
    const [quantity, budget] = f(i + 1);
    return { year: i + 1, quantity, budget, planned: quantity > 0 || budget > 0, has_row: true };
  });

const line = (over: Partial<YearlyPlanLine>): YearlyPlanLine =>
  ({
    id: 'L1',
    potential_activity_id: 1,
    activity: 'Nursery',
    program: 'Forest',
    unit: 'no.',
    requires_map: true,
    default_quantity: 1,
    default_yearly_budget: 5000,
    years: cells(() => [1, 5000]),
    planned_years: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
    total_budget: 50000,
    version: 1,
    reviewed_at: null,
    placeholder_fields: [],
    feature_count: 2,
    location_mode: 'places',
    assign_to_all_blocks: false,
    status: 'proposed',
    notes: null,
    ...over,
  }) as YearlyPlanLine;

const HEALTH = {
  summary: { ready: 0, needs_attention: 0, total: 0, total_budget: 0 },
  next_step: { code: 'EMPTY_PLAN', activity_id: null, params: {}, action: 'add_first_activity' },
  items: [],
  plan_issues: [],
};
const SLOW = { timeout: 8000 };

beforeEach(() => {
  vi.clearAllMocks();
  plan.getPlan.mockResolvedValue({ total_budget: 0, lines: [] });
  plan.getHealth.mockResolvedValue(HEALTH);
});

describe('the yearly-activities page', () => {
  it('opens on the shared plan panel and has no "Save All"', async () => {
    render(<YearlyActivitiesPage calculationId="c1" forestName="छिमेकी" area={12.5} />);
    expect(await screen.findByTestId('plan-home', {}, SLOW)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /save all/i })).toBeNull();
    expect(screen.getByText(/छिमेकी/)).toBeInTheDocument();
  });

  it('shows the totals of the plan: activities, the budget in NPR, and the places', async () => {
    plan.getPlan.mockResolvedValue({
      total_budget: 0,
      lines: [line({ total_budget: 50000, feature_count: 2 }), line({ id: 'L2', total_budget: 30000, feature_count: 0, requires_map: false })],
    });
    render(<YearlyActivitiesPage calculationId="c1" />);
    await waitFor(() => expect(screen.getByTestId('stat-activities').textContent).toContain('2'), SLOW);
    expect(screen.getByTestId('stat-budget').textContent).toContain('80,000');
    expect(screen.getByTestId('stat-places').textContent).toContain('2');
  });

  it('previews the operational plan from the same numbers: a year at 0 and 0 counts nothing', async () => {
    plan.getPlan.mockResolvedValue({
      total_budget: 0,
      lines: [
        // planned in years 1-2 only; the other years are 0 and 0
        line({ years: cells((y) => (y <= 2 ? [3, 7000] : [0, 0])), total_budget: 14000, planned_years: [1, 2] }),
        // year 1 funded with no output; year 2 output with no cost
        line({ id: 'L2', activity: 'Trail', program: 'Roads', years: cells((y) => (y === 1 ? [0, 500] : y === 2 ? [4, 0] : [0, 0])), total_budget: 500, planned_years: [1, 2] }),
      ],
    });
    render(<YearlyActivitiesPage calculationId="c1" />);
    expect(await screen.findByTestId('bar-chart', {}, SLOW)).toBeInTheDocument();
    expect(screen.getByTestId('pie-chart')).toBeInTheDocument();
    const rows = Array.from(document.querySelectorAll('.op-preview-card tbody tr')).map((tr) => Array.from(tr.querySelectorAll('td')).map((td) => td.textContent));
    // year: activities planned, total quantity, total budget
    expect(rows[0]).toEqual(['1', '2', '3', '7,500']);
    expect(rows[1]).toEqual(['2', '2', '7', '7,000']);
    expect(rows[2]).toEqual(['3', '0', '0', '0']); // nothing planned
    expect(rows).toHaveLength(10);
  });

  it('shows no preview while the plan is empty', async () => {
    render(<YearlyActivitiesPage calculationId="c1" />);
    await screen.findByTestId('plan-home', {}, SLOW);
    expect(screen.queryByTestId('bar-chart')).toBeNull();
  });

  it('"Add your first activity" asks the plan panel to open its questions', async () => {
    render(<YearlyActivitiesPage calculationId="c1" />);
    fireEvent.click(await screen.findByRole('button', { name: 'Add your first activity' }, SLOW));
    await waitFor(() => expect(screen.getByTestId('plan-home')).toHaveAttribute('data-add-signal', '1'));
  });

  it('"Edit on map" opens the map workspace, and a row’s location link opens the chooser for that line', async () => {
    render(<YearlyActivitiesPage calculationId="c1" />);
    fireEvent.click(await screen.findByText('edit-on-map', {}, SLOW));
    expect(navigate).toHaveBeenCalledWith('/calculations/c1?surface=base/unified');
    fireEvent.click(screen.getByText('open-location'));
    expect(within(screen.getByTestId('chooser')).getByText('L1')).toBeInTheDocument();
  });

  it('re-reads the plan when the user comes back to the window (it is edited from two screens)', async () => {
    render(<YearlyActivitiesPage calculationId="c1" />);
    await waitFor(() => expect(plan.getPlan).toHaveBeenCalledTimes(1), SLOW);
    window.dispatchEvent(new Event('focus'));
    await waitFor(() => expect(plan.getPlan).toHaveBeenCalledTimes(2), SLOW);
  });

  it('Close is offered only when the host gave a way to close', async () => {
    const onClose = vi.fn();
    const { rerender } = render(<YearlyActivitiesPage calculationId="c1" onClose={onClose} />);
    fireEvent.click(await screen.findByRole('button', { name: /close/i }, SLOW));
    expect(onClose).toHaveBeenCalledTimes(1);
    rerender(<YearlyActivitiesPage calculationId="c1" />);
    expect(screen.queryByRole('button', { name: /close/i })).toBeNull();
  });
});
