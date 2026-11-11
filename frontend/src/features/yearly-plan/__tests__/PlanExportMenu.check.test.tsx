/**
 * Exporting the yearly plan with the plan check in front of it (P6, D24): unfinished activities are listed once, the
 * person may go on anyway, and a clean plan exports at once.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { message } from 'antd';
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
vi.mock('../../../utils/download', () => ({ downloadFromApi: vi.fn(), downloadBlob: vi.fn() }));
vi.mock('../../../config/featureFlags', () => ({ isYearlyPlanGuidanceEnabled: () => true }));
vi.mock('../../../services/api', () => ({ yearlyPlanApi: { getHealth: vi.fn() } }));

import { downloadFromApi } from '../../../utils/download';
import { yearlyPlanApi } from '../../../services/api';
import { PlanExportMenu } from '../PlanExportMenu';

const download = downloadFromApi as unknown as ReturnType<typeof vi.fn>;
const getHealth = (yearlyPlanApi as unknown as { getHealth: ReturnType<typeof vi.fn> }).getHealth;

const UNFINISHED = {
  summary: { ready: 0, needs_attention: 1, total: 1, total_budget: 5000 },
  next_step: { code: 'PLACEHOLDER_NUMBERS', activity_id: 'L1', params: {}, action: 'edit_numbers' },
  items: [
    {
      activity_id: 'L1',
      potential_activity_id: 1,
      activity: 'Nursery',
      state: 'needs_numbers',
      issues: [{ code: 'PLACEHOLDER_NUMBERS', severity: 'todo', params: { fields: ['quantity', 'budget'] }, action: 'edit_numbers' }],
    },
  ],
  plan_issues: [],
};
const CLEAN = { ...UNFINISHED, items: [{ ...UNFINISHED.items[0], state: 'ready', issues: [] }] };

async function chooseYearlyPlan() {
  fireEvent.mouseEnter(screen.getByTestId('plan-export'));
  fireEvent.click(screen.getByTestId('plan-export'));
  fireEvent.click(await screen.findByText('Yearly plan (CSV)'));
}

beforeEach(() => {
  vi.clearAllMocks();
  download.mockResolvedValue(undefined);
  vi.spyOn(message, 'success').mockImplementation((() => undefined) as never);
  vi.spyOn(message, 'error').mockImplementation((() => undefined) as never);
});

describe('the export menu with the plan check', () => {
  it('a plan with unfinished activities is listed first, and nothing is exported yet', async () => {
    getHealth.mockResolvedValue(UNFINISHED);
    render(<PlanExportMenu calculationId="c1" />);
    await chooseYearlyPlan();
    expect(await screen.findByTestId('plan-check')).toBeInTheDocument();
    expect(screen.getByText('Before we export the plan: 1 to check')).toBeInTheDocument();
    expect(download).not.toHaveBeenCalled();
  });

  it('"Export anyway" makes the file — the check never blocks', async () => {
    getHealth.mockResolvedValue(UNFINISHED);
    render(<PlanExportMenu calculationId="c1" />);
    await chooseYearlyPlan();
    fireEvent.click(await screen.findByTestId('plan-check-continue'));
    await waitFor(() => expect(download).toHaveBeenCalledTimes(1));
    expect(String(download.mock.calls[0][0])).toContain('/yearly-plan/export');
  });

  it('a row\'s Open button tells the host which activity to show, and exports nothing', async () => {
    getHealth.mockResolvedValue(UNFINISHED);
    const onFixIssue = vi.fn();
    render(<PlanExportMenu calculationId="c1" onFixIssue={onFixIssue} />);
    await chooseYearlyPlan();
    fireEvent.click(await screen.findByTestId('plan-check-fix'));
    expect(onFixIssue).toHaveBeenCalledWith('L1');
    expect(download).not.toHaveBeenCalled();
  });

  it('a plan with nothing to check exports at once', async () => {
    getHealth.mockResolvedValue(CLEAN);
    render(<PlanExportMenu calculationId="c1" />);
    await chooseYearlyPlan();
    await waitFor(() => expect(download).toHaveBeenCalledTimes(1));
    expect(screen.queryByTestId('plan-check')).toBeNull();
  });
});
