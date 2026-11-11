import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { message } from 'antd';
import en from '../../../i18n/locales/en.json';

vi.mock('react-i18next', () => {
  const lookup = (key: string): unknown =>
    key.split('.').reduce<unknown>((node, part) => (node as Record<string, unknown> | undefined)?.[part], en);
  const t = (key: string): string => (typeof lookup(key) === 'string' ? (lookup(key) as string) : key);
  return { useTranslation: () => ({ t, i18n: { language: 'en' } }) };
});

vi.mock('../../../services/api', () => ({
  yearlyPlanApi: { getCbaPlanDrift: vi.fn(), getHealth: vi.fn() },
  cbaApi: { autoPopulate: vi.fn() },
}));

import { cbaApi, yearlyPlanApi } from '../../../services/api';
import { CbaPlanDriftBanner } from '../CbaPlanDriftBanner';

const drift = yearlyPlanApi.getCbaPlanDrift as unknown as ReturnType<typeof vi.fn>;
const health = yearlyPlanApi.getHealth as unknown as ReturnType<typeof vi.fn>;
const populate = cbaApi.autoPopulate as unknown as ReturnType<typeof vi.fn>;

const HEALTH = (items: unknown[]) => ({
  summary: { ready: 0, needs_attention: items.length, total: items.length, total_budget: 0 },
  next_step: { code: 'ALL_READY', activity_id: null, params: {}, action: 'create_plan' },
  items,
  plan_issues: [],
});
const placeholderItem = {
  activity_id: 'L1', potential_activity_id: 1, activity: 'A', state: 'needs_numbers',
  issues: [{ code: 'PLACEHOLDER_NUMBERS', severity: 'todo', params: {}, action: 'enter_numbers' }],
};

beforeEach(() => {
  vi.clearAllMocks();
  drift.mockResolvedValue({ out_of_date: false, added: [], removed: [], changed: [] });
  health.mockResolvedValue(HEALTH([]));
  populate.mockResolvedValue({ message: 'ok', warnings: [] });
  vi.spyOn(message, 'success').mockImplementation((() => undefined) as never);
  vi.spyOn(message, 'warning').mockImplementation((() => undefined) as never);
  vi.spyOn(message, 'error').mockImplementation((() => undefined) as never);
});

describe('CbaPlanDriftBanner', () => {
  it('shows nothing when the analysis matches the plan and there are no starting numbers', async () => {
    render(<CbaPlanDriftBanner calculationId="c1" baseScenarioId="s1" onUpdated={() => {}} />);
    await waitFor(() => expect(drift).toHaveBeenCalled());
    expect(screen.queryByTestId('cba-plan-banner')).toBeNull();
  });

  it('says the plan changed and offers to update — and updates only when asked', async () => {
    drift.mockResolvedValue({ out_of_date: true, added: [], removed: [], changed: ['activity:1:1-3'] });
    const updated = vi.fn();
    render(<CbaPlanDriftBanner calculationId="c1" baseScenarioId="s1" onUpdated={updated} />);

    const banner = await screen.findByTestId('cba-plan-banner');
    expect(banner.textContent).toContain('The yearly plan changed after this analysis was last updated.');
    expect(populate).not.toHaveBeenCalled(); // never on its own

    fireEvent.click(screen.getByRole('button', { name: 'Update from plan' }));
    await waitFor(() => expect(populate).toHaveBeenCalledWith('s1'));
    await waitFor(() => expect(updated).toHaveBeenCalled());
    expect(message.success).toHaveBeenCalledWith('Updated from the yearly plan.');
  });

  it('shows the re-populate warnings (a locked row that may now be counted twice)', async () => {
    drift.mockResolvedValue({ out_of_date: true, added: ['x'], removed: [], changed: [] });
    populate.mockResolvedValue({ message: 'ok', warnings: ["'Nursery': a manual cost row with the same name exists"] });
    render(<CbaPlanDriftBanner calculationId="c1" baseScenarioId="s1" onUpdated={() => {}} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Update from plan' }));
    await waitFor(() => expect(message.warning).toHaveBeenCalled());
    expect(String((message.warning as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0])).toContain('Nursery');
  });

  it('says so when the costs still include the starting numbers', async () => {
    health.mockResolvedValue(HEALTH([placeholderItem]));
    render(<CbaPlanDriftBanner calculationId="c1" baseScenarioId="s1" onUpdated={() => {}} />);
    const banner = await screen.findByTestId('cba-plan-banner');
    expect(banner.textContent).toContain('still have starting numbers');
    expect(screen.queryByRole('button', { name: 'Update from plan' })).toBeNull(); // nothing to update
  });

  it('a failing drift check never breaks the tab', async () => {
    drift.mockRejectedValue(new Error('500'));
    render(<CbaPlanDriftBanner calculationId="c1" baseScenarioId="s1" onUpdated={() => {}} />);
    await waitFor(() => expect(drift).toHaveBeenCalled());
    expect(screen.queryByTestId('cba-plan-banner')).toBeNull();
  });

  it('a failed update is reported in plain words, never with the server text', async () => {
    drift.mockResolvedValue({ out_of_date: true, added: ['x'], removed: [], changed: [] });
    populate.mockRejectedValue({ response: { status: 500, data: { detail: 'Traceback…' } } });
    render(<CbaPlanDriftBanner calculationId="c1" baseScenarioId="s1" onUpdated={() => {}} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Update from plan' }));
    await waitFor(() => expect(message.error).toHaveBeenCalled());
    const shown = String((message.error as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0]);
    expect(shown).toContain('Your data is safe');
    expect(shown).not.toContain('Traceback');
  });
});
