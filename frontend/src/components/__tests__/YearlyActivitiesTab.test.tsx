/**
 * The Reports-tab yearly-activities screen after P5 of the yearly-activities plan: the plan is the shared PlanHome
 * (it opens on "Your plan"), the guidance card sits above it, and what stays here is where an activity applies
 * (blocks / sub-areas), the map view and the summary. There is no "Save All" and no table of its own.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { message } from 'antd';
import YearlyActivitiesTab from '../YearlyActivitiesTab';
import { yearlyActivitiesApi, yearlyPlanApi } from '../../services/api';

const navigate = vi.fn();
vi.mock('react-router-dom', () => ({ useNavigate: () => navigate }));
vi.mock('../YearlyActivities/ActivityMapView', () => ({ default: () => null }));
vi.mock('../../hooks/useDimensionLabels', () => ({
  useDimensionLabels: () => ({ unitLabel: 'Block', unitLabelNp: 'ब्लक', unitLabelLower: 'block' }),
}));
vi.mock('../YearlyActivities/BlockSubAreaSelector', () => ({
  default: ({ selectedAllBlocks }: { selectedAllBlocks: boolean }) => <div data-testid="selector">{String(selectedAllBlocks)}</div>,
}));
// the panel has its own tests: here it is a stub that shows what the screen hands it
vi.mock('../../features/yearly-plan/PlanHome', () => ({
  PlanHome: (props: {
    addSignal?: number;
    onEditOnMap?: () => void;
    onOpenDetails?: (line: { id: string }) => void;
    onPlanChanged?: () => void;
  }) => (
    <div data-testid="plan-home" data-add-signal={props.addSignal}>
      <button onClick={props.onEditOnMap}>edit-on-map</button>
      <button onClick={() => props.onOpenDetails?.({ id: 'L1' })}>open-location</button>
      <button onClick={props.onPlanChanged}>plan-changed</button>
    </div>
  ),
}));
vi.mock('../../features/yearly-plan/PlanExportMenu', () => ({ PlanExportMenu: () => null }));

vi.mock('../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../services/api')>();
  return {
    ...actual,
    yearlyPlanApi: { getHealth: vi.fn(), confirmLine: vi.fn(), getUnits: vi.fn() },
    yearlyActivitiesApi: {
      getSummary: vi.fn(),
      getSpatialAssignments: vi.fn(),
      createSpatialAssignment: vi.fn(),
      deleteSpatialAssignment: vi.fn(),
      updateProposedActivity: vi.fn(),
    },
  };
});

const acts = yearlyActivitiesApi as unknown as Record<string, ReturnType<typeof vi.fn>>;
const plan = yearlyPlanApi as unknown as Record<string, ReturnType<typeof vi.fn>>;

const health = (code: string, action: string, extra: Record<string, unknown> = {}) => ({
  summary: { ready: 0, needs_attention: 1, total: 1, total_budget: 5000 },
  next_step: { code, activity_id: extra.activity_id ?? null, activity: 'Nursery', params: {}, action },
  items: [],
  plan_issues: [],
});

const SLOW = { timeout: 8000 };

beforeEach(() => {
  vi.clearAllMocks();
  acts.getSummary.mockResolvedValue(null);
  acts.getSpatialAssignments.mockResolvedValue([]);
  plan.getUnits.mockResolvedValue([]);
  acts.createSpatialAssignment.mockResolvedValue({});
  acts.deleteSpatialAssignment.mockResolvedValue({});
  acts.updateProposedActivity.mockResolvedValue({});
  plan.getHealth.mockResolvedValue(health('EMPTY_PLAN', 'add_first_activity'));
  vi.spyOn(message, 'error').mockImplementation((() => undefined) as never);
  vi.spyOn(message, 'success').mockImplementation((() => undefined) as never);
});

describe('Reports-tab yearly activities — the plan comes first', () => {
  it('opens on the shared plan panel, with no "Save All" and no table of its own', async () => {
    render(<YearlyActivitiesTab calculationId="c1" />);
    expect(await screen.findByTestId('plan-home', {}, SLOW)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /save all/i })).toBeNull();
  });

  it('the guidance card says what to do next, in plain words', async () => {
    plan.getHealth.mockResolvedValue(health('NO_LOCATION', 'show_on_map', { activity_id: 'L1' }));
    render(<YearlyActivitiesTab calculationId="c1" />);
    const card = await screen.findByTestId('next-step-card', {}, SLOW);
    expect(card.textContent).toContain('“Nursery” has no place on the map yet');
  });

  it('"Add your first activity" opens the add-activity questions in the plan panel', async () => {
    render(<YearlyActivitiesTab calculationId="c1" />);
    fireEvent.click(await screen.findByRole('button', { name: 'Add your first activity' }, SLOW));
    await waitFor(() => expect(screen.getByTestId('plan-home')).toHaveAttribute('data-add-signal', '1'));
  });

  it('a failed load is reported in plain words, never with the server text', async () => {
    acts.getSummary.mockRejectedValue(Object.assign(new Error('relation "x" does not exist'), { response: { status: 500 } }));
    acts.getSummary.mockImplementation(() => Promise.reject(new Error('relation "x" does not exist')));
    render(<YearlyActivitiesTab calculationId="c1" />);
    await screen.findByTestId('plan-home', {}, SLOW);
    for (const call of (message.error as unknown as { mock: { calls: unknown[][] } }).mock.calls) {
      expect(String(call[0])).not.toContain('relation');
    }
  });

  it('"Edit on map" opens the map workspace of this forest', async () => {
    render(<YearlyActivitiesTab calculationId="c1" />);
    fireEvent.click(await screen.findByText('edit-on-map', {}, SLOW));
    expect(navigate).toHaveBeenCalledWith('/calculations/c1?surface=base/unified');
  });
});

describe('Reports-tab yearly activities — where an activity applies', () => {
  it('a row’s "Location and drawing" link opens the shared chooser for that line', async () => {
    acts.getSpatialAssignments.mockResolvedValue([{ id: 'S1', block_id: 'B1', assignment_type: 'block' }]);
    render(<YearlyActivitiesTab calculationId="c1" />);
    fireEvent.click(await screen.findByText('open-location', {}, SLOW));
    expect(await screen.findByTestId('selector', {}, SLOW)).toHaveTextContent('false'); // not "all blocks"
    expect(acts.getSpatialAssignments).toHaveBeenCalledWith('L1');
  });

  it('saving the location re-reads the plan (the summary is asked again)', async () => {
    render(<YearlyActivitiesTab calculationId="c1" />);
    fireEvent.click(await screen.findByText('open-location', {}, SLOW));
    await screen.findByTestId('selector', {}, SLOW);
    const before = acts.getSummary.mock.calls.length;
    fireEvent.click(screen.getByRole('button', { name: /save/i }));
    await waitFor(() => expect(acts.getSummary.mock.calls.length).toBeGreaterThan(before), SLOW);
    expect(message.success).toHaveBeenCalled();
  });
});
