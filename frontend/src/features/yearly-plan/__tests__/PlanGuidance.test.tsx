import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { message } from 'antd';
import en from '../../../i18n/locales/en.json';
import type { YearlyPlanHealth } from '../../../services/api';

// the real English catalogue behind a minimal `t`
vi.mock('react-i18next', () => {
  const lookup = (key: string): unknown =>
    key.split('.').reduce<unknown>((node, part) => (node as Record<string, unknown> | undefined)?.[part], en);
  const t = (key: string, values: Record<string, unknown> = {}): string => {
    let node = lookup(key);
    if (node === undefined && typeof values.count === 'number') {
      node = lookup(`${key}_${values.count === 1 ? 'one' : 'other'}`);
    }
    if (typeof node !== 'string') return key;
    return node.replace(/\{\{\s*(\w+)\s*\}\}/g, (_m, name) => String(values[name] ?? ''));
  };
  return { useTranslation: () => ({ t, i18n: { language: 'en' } }) };
});
vi.mock('../../../i18n/numberFormat', () => ({
  formatNumber: (n: number) => n.toLocaleString('en'),
  formatDecimal: (n: number) => String(n),
}));
vi.mock('../../../services/api', () => ({
  yearlyPlanApi: { getHealth: vi.fn(), confirmLine: vi.fn() },
}));

import { yearlyPlanApi } from '../../../services/api';
import { PlanGuidance } from '../PlanGuidance';

const api = yearlyPlanApi as unknown as { getHealth: ReturnType<typeof vi.fn>; confirmLine: ReturnType<typeof vi.fn> };

const item = (id: string, activity: string, state: string, issues: unknown[]) => ({
  activity_id: id,
  potential_activity_id: 1,
  activity,
  state,
  issues,
});

const HEALTH: YearlyPlanHealth = {
  summary: { ready: 1, needs_attention: 2, total: 3, total_budget: 250000 },
  next_step: { code: 'NO_LOCATION', activity_id: 'L1', activity: 'Nursery', params: {}, action: 'show_on_map' },
  items: [
    item('L1', 'Nursery', 'needs_location', [
      { code: 'NO_LOCATION', severity: 'todo', params: {}, action: 'show_on_map' },
    ]),
    item('L2', 'Trail', 'needs_numbers', [
      { code: 'PLACEHOLDER_NUMBERS', severity: 'todo', params: { fields: ['budget'] }, action: 'enter_numbers' },
    ]),
    item('L3', 'Training', 'ready', []),
  ] as YearlyPlanHealth['items'],
  plan_issues: [],
};

beforeEach(() => {
  vi.clearAllMocks();
  api.getHealth.mockResolvedValue(HEALTH);
  api.confirmLine.mockResolvedValue({});
  vi.spyOn(message, 'success').mockImplementation((() => undefined) as never);
  vi.spyOn(message, 'error').mockImplementation((() => undefined) as never);
});

describe('PlanGuidance', () => {
  it('shows the progress, the ONE next step in plain words, and what else needs attention', async () => {
    render(<PlanGuidance calculationId="c1" onOpenActivity={() => {}} />);

    expect((await screen.findByTestId('plan-progress')).textContent).toBe('Activities ready: 1 of 3');
    const card = screen.getByTestId('next-step-card');
    expect(card.textContent).toContain('“Nursery” has no place on the map yet');
    expect(card.textContent).toContain('Show on map');
    const rows = screen.getAllByTestId('plan-checklist-row');
    expect(rows).toHaveLength(2); // the ready activity is not listed
    expect(rows[1].textContent).toContain('The budget for “Trail” is still the starting value');
  });

  it('the card\'s button opens that activity with the action to take', async () => {
    const open = vi.fn();
    render(<PlanGuidance calculationId="c1" onOpenActivity={open} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Show on map' }));
    expect(open).toHaveBeenCalledWith('L1', 'show_on_map');
  });

  it('a checklist row opens its activity', async () => {
    const open = vi.fn();
    render(<PlanGuidance calculationId="c1" onOpenActivity={open} />);
    await screen.findByTestId('plan-checklist');
    fireEvent.click(screen.getAllByRole('button', { name: 'Open' })[1]);
    expect(open).toHaveBeenCalledWith('L2', 'open');
  });

  it('offers "these numbers are right" next to a starting-value warning, and Confirm saves it', async () => {
    api.getHealth.mockResolvedValue({
      ...HEALTH,
      next_step: { code: 'PLACEHOLDER_NUMBERS', activity_id: 'L2', activity: 'Trail', params: { fields: ['quantity', 'budget'] }, action: 'enter_numbers' },
    });
    const changed = vi.fn();
    render(<PlanGuidance calculationId="c1" onOpenActivity={() => {}} onPlanChanged={changed} />);

    fireEvent.click(await screen.findByRole('button', { name: 'These numbers are right' }));

    await waitFor(() => expect(api.confirmLine).toHaveBeenCalledWith('c1', 'L2'));
    await waitFor(() => expect(changed).toHaveBeenCalled());
    expect(message.success).toHaveBeenCalledWith('Confirmed.');
    expect(api.getHealth).toHaveBeenCalledTimes(2); // re-read after the change
  });

  it('never offers Confirm on a step that only needs a place', async () => {
    render(<PlanGuidance calculationId="c1" onOpenActivity={() => {}} />);
    await screen.findByTestId('next-step-card');
    expect(screen.queryByRole('button', { name: 'These numbers are right' })).toBeNull();
  });

  it('an empty plan asks for the first activity', async () => {
    api.getHealth.mockResolvedValue({
      summary: { ready: 0, needs_attention: 0, total: 0, total_budget: 0 },
      next_step: { code: 'EMPTY_PLAN', activity_id: null, params: {}, action: 'add_first_activity' },
      items: [],
      plan_issues: [],
    });
    const addFirst = vi.fn();
    render(<PlanGuidance calculationId="c1" onOpenActivity={() => {}} onAddFirst={addFirst} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Add your first activity' }));
    expect(addFirst).toHaveBeenCalled();
    expect(screen.queryByTestId('plan-progress')).toBeNull();
  });

  it('when everything is ready it says so, with the total, and offers the plan', async () => {
    api.getHealth.mockResolvedValue({
      summary: { ready: 2, needs_attention: 0, total: 2, total_budget: 1250000 },
      next_step: { code: 'ALL_READY', activity_id: null, params: {}, action: 'create_plan' },
      items: [item('L1', 'A', 'ready', []), item('L2', 'B', 'ready', [])],
      plan_issues: [],
    });
    const create = vi.fn();
    render(<PlanGuidance calculationId="c1" onOpenActivity={() => {}} onCreatePlan={create} />);
    const card = await screen.findByTestId('next-step-card');
    expect(card.textContent).toContain('Your yearly plan is ready: 2 activities, NPR 1,250,000 over 10 years.');
    fireEvent.click(screen.getByRole('button', { name: 'Create the plan' }));
    expect(create).toHaveBeenCalled();
  });

  it('says so, in plain words, when the plan could not be loaded — never a raw error', async () => {
    api.getHealth.mockRejectedValue({ response: { status: 500, data: { detail: 'Traceback (most recent call last)' } } });
    render(<PlanGuidance calculationId="c1" onOpenActivity={() => {}} />);
    const box = await screen.findByTestId('plan-guidance-error');
    expect(box.textContent).toContain('Could not load your plan');
    expect(box.textContent).not.toContain('Traceback');
  });

  it('re-reads the plan when the window regains focus (the map may have changed it)', async () => {
    render(<PlanGuidance calculationId="c1" onOpenActivity={() => {}} />);
    await screen.findByTestId('next-step-card');
    expect(api.getHealth).toHaveBeenCalledTimes(1);
    window.dispatchEvent(new Event('focus'));
    await waitFor(() => expect(api.getHealth).toHaveBeenCalledTimes(2));
  });

  it('re-reads the plan when the host bumps refreshKey after saving', async () => {
    const { rerender } = render(<PlanGuidance calculationId="c1" refreshKey={0} onOpenActivity={() => {}} />);
    await screen.findByTestId('next-step-card');
    rerender(<PlanGuidance calculationId="c1" refreshKey={1} onOpenActivity={() => {}} />);
    await waitFor(() => expect(api.getHealth).toHaveBeenCalledTimes(2));
  });
});
