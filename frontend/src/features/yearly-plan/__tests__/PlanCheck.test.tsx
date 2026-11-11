/**
 * The plan check before the plan document is created or a file is exported (YEARLY_ACTIVITIES plan §4.3, P6, D24):
 * it lists what still needs attention, links to the fixes, and NEVER blocks — the person decides.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import en from '../../../i18n/locales/en.json';

vi.mock('react-i18next', () => {
  const lookup = (key: string): unknown =>
    key.split('.').reduce<unknown>((node, part) => (node as Record<string, unknown> | undefined)?.[part], en);
  const t = (key: string, values: Record<string, unknown> = {}): string => {
    const node = lookup(key);
    if (typeof node !== 'string') return key;
    return node.replace(/\{\{\s*(\w+)\s*\}\}/g, (_m, name) => String(values[name] ?? ''));
  };
  return { useTranslation: () => ({ t, i18n: { language: 'en' } }) };
});
vi.mock('../../../i18n/numberFormat', () => ({ formatNumber: (n: number) => String(n), formatDecimal: (n: number) => String(n) }));
const flag = vi.hoisted(() => ({ on: true }));
vi.mock('../../../config/featureFlags', () => ({ isYearlyPlanGuidanceEnabled: () => flag.on }));
vi.mock('../../../services/api', () => ({ yearlyPlanApi: { getHealth: vi.fn() } }));

import { yearlyPlanApi, type YearlyPlanHealth } from '../../../services/api';
import { planCheckRows, usePlanCheck } from '../PlanCheck';

const getHealth = (yearlyPlanApi as unknown as { getHealth: ReturnType<typeof vi.fn> }).getHealth;
const t = ((key: string, values: Record<string, unknown> = {}) => {
  const node = key.split('.').reduce<unknown>((n, p) => (n as Record<string, unknown> | undefined)?.[p], en);
  return typeof node === 'string' ? node.replace(/\{\{\s*(\w+)\s*\}\}/g, (_m, name) => String(values[name] ?? '')) : key;
}) as never;

const item = (over: Record<string, unknown>) => ({
  activity_id: 'L1',
  potential_activity_id: 1,
  activity: 'Nursery',
  state: 'needs_numbers',
  issues: [{ code: 'PLACEHOLDER_NUMBERS', severity: 'todo', params: { fields: ['quantity', 'budget'] }, action: 'edit_numbers' }],
  ...over,
});

const health = (over: Partial<YearlyPlanHealth> = {}): YearlyPlanHealth => ({
  summary: { ready: 0, needs_attention: 1, total: 1, total_budget: 5000 },
  next_step: { code: 'ALL_READY', activity_id: null, params: {}, action: 'create_plan' },
  items: [item({}) as never],
  plan_issues: [],
  ...over,
});

describe('planCheckRows', () => {
  it('lists each activity that still needs something, in the same words as the checklist', () => {
    const rows = planCheckRows(health({ items: [item({}) as never, item({ activity_id: 'L2', activity: 'Trail', state: 'ready', issues: [] }) as never] }), t);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ activityId: 'L1', activity: 'Nursery', state: 'needs_numbers' });
    expect(rows[0].text).toContain('still the starting values');
  });

  it('an empty plan is one row, and an out-of-date cost-benefit analysis is one more', () => {
    expect(planCheckRows(health({ items: [] }), t).map((r) => r.key)).toEqual(['empty']);
    const rows = planCheckRows(health({ items: [], plan_issues: [{ code: 'CBA_OUT_OF_DATE', severity: 'info', params: {}, action: 'update_cba' }] }), t);
    expect(rows.map((r) => r.key)).toEqual(['empty', 'cba']);
    expect(rows[1].text).toContain('cost-benefit analysis was last updated before');
    expect(rows[1].activityId).toBeNull(); // about the whole plan: nothing to open
  });

  it('a plan with nothing to check has no rows', () => {
    expect(planCheckRows(health({ items: [item({ state: 'ready', issues: [] }) as never] }), t)).toEqual([]);
  });
});

function Host({ proceed, action = 'create', onFix }: { proceed: () => void; action?: 'create' | 'export'; onFix?: (calc: string, id: string) => void }) {
  const check = usePlanCheck({ onFix });
  return (
    <>
      <button onClick={() => void check.guard('c1', proceed, action)}>go</button>
      {check.dialog}
    </>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  flag.on = true;
  getHealth.mockResolvedValue(health());
});

describe('usePlanCheck', () => {
  it('goes straight on when there is nothing to check', async () => {
    getHealth.mockResolvedValue(health({ items: [item({ state: 'ready', issues: [] }) as never] }));
    const proceed = vi.fn();
    render(<Host proceed={proceed} />);
    fireEvent.click(screen.getByText('go'));
    await waitFor(() => expect(proceed).toHaveBeenCalledTimes(1));
    expect(screen.queryByTestId('plan-check')).toBeNull();
  });

  it('otherwise lists what needs attention and does nothing until the person chooses', async () => {
    const proceed = vi.fn();
    render(<Host proceed={proceed} />);
    fireEvent.click(screen.getByText('go'));
    expect(await screen.findByTestId('plan-check')).toBeInTheDocument();
    expect(screen.getByText('Before we create your plan: 1 to check')).toBeInTheDocument();
    expect(screen.getByText('Nursery')).toBeInTheDocument();
    expect(proceed).not.toHaveBeenCalled();
  });

  it('it never blocks: "Create the plan anyway" goes on without any fix', async () => {
    const proceed = vi.fn();
    render(<Host proceed={proceed} />);
    fireEvent.click(screen.getByText('go'));
    fireEvent.click(await screen.findByTestId('plan-check-continue'));
    await waitFor(() => expect(proceed).toHaveBeenCalledTimes(1));
  });

  it('"Go back and fix" closes it and does not go on', async () => {
    const proceed = vi.fn();
    render(<Host proceed={proceed} />);
    fireEvent.click(screen.getByText('go'));
    fireEvent.click(await screen.findByTestId('plan-check-back'));
    await new Promise((r) => setTimeout(r, 50));
    expect(proceed).not.toHaveBeenCalled();
  });

  it('a row\'s Open button takes the person to that activity (and does not go on)', async () => {
    const proceed = vi.fn();
    const onFix = vi.fn();
    render(<Host proceed={proceed} onFix={onFix} />);
    fireEvent.click(screen.getByText('go'));
    fireEvent.click(await screen.findByTestId('plan-check-fix'));
    expect(onFix).toHaveBeenCalledWith('c1', 'L1');
    expect(proceed).not.toHaveBeenCalled();
  });

  it('an export says so in its title and on its button', async () => {
    render(<Host proceed={vi.fn()} action="export" />);
    fireEvent.click(screen.getByText('go'));
    expect(await screen.findByText('Before we export the plan: 1 to check')).toBeInTheDocument();
    expect(screen.getByTestId('plan-check-continue').textContent).toBe('Export anyway');
  });

  it('a check that cannot run never stands in the way', async () => {
    getHealth.mockRejectedValue(new Error('offline'));
    const proceed = vi.fn();
    render(<Host proceed={proceed} />);
    fireEvent.click(screen.getByText('go'));
    await waitFor(() => expect(proceed).toHaveBeenCalledTimes(1));
  });

  it('with the guidance switched off there is no check at all', async () => {
    flag.on = false;
    const proceed = vi.fn();
    render(<Host proceed={proceed} />);
    fireEvent.click(screen.getByText('go'));
    await waitFor(() => expect(proceed).toHaveBeenCalledTimes(1));
    expect(getHealth).not.toHaveBeenCalled();
  });
});
