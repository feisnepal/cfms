/**
 * The structure of the yearly plan in its table (owner, 2026-10-15): the table ends with an empty row where the next
 * activity is picked, and a row can be removed. Both only when the catalogue is given and the plan is editable.
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
vi.mock('../../../i18n/numberFormat', () => ({
  formatNumber: (n: number) => String(n),
  formatDecimal: (n: number) => String(n),
  parseLocaleNumber: (s: string) => (String(s).trim() === '' ? NaN : Number(String(s).replace(/,/g, ''))),
}));
vi.mock('../../../services/api', () => ({
  yearlyPlanApi: { getPlan: vi.fn(), updateLine: vi.fn(), confirmLine: vi.fn(), addLine: vi.fn() },
  yearlyActivitiesApi: { deleteProposedActivity: vi.fn() },
}));

import { yearlyActivitiesApi, yearlyPlanApi, type YearlyPlanLine } from '../../../services/api';
import { PlanTable } from '../PlanTable';

const plan = yearlyPlanApi as unknown as Record<'getPlan' | 'addLine', ReturnType<typeof vi.fn>>;
const del = yearlyActivitiesApi.deleteProposedActivity as unknown as ReturnType<typeof vi.fn>;

const matrix = Array.from({ length: 10 }, (_, i) => ({ year: i + 1, quantity: 1, budget: 100, planned: true, has_row: true }));
const line = (over: Partial<YearlyPlanLine> = {}): YearlyPlanLine => ({
  id: 'L',
  potential_activity_id: 1,
  activity: 'Main nursery',
  program: 'Forest development',
  unit: 'no.',
  requires_map: false,
  default_quantity: 1,
  default_yearly_budget: 100,
  years: matrix,
  planned_years: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
  total_budget: 1000,
  version: 1,
  reviewed_at: null,
  placeholder_fields: [],
  feature_count: 0,
  location_mode: 'not_applicable',
  assign_to_all_blocks: false,
  status: 'planned',
  notes: null,
  ...over,
});

const catalogue = [
  { id: 1, activity: 'Main nursery', unit: 'no.' },
  { id: 2, activity: 'Fire line construction', unit: 'km' },
];

beforeEach(() => {
  vi.clearAllMocks();
  plan.getPlan.mockResolvedValue({ total_budget: 0, lines: [line()] });
  plan.addLine.mockResolvedValue({ plan_line: line({ id: 'M', potential_activity_id: 2 }), created_plan_line: true, unit: 'km' });
  del.mockResolvedValue(undefined);
});

describe('the empty last row', () => {
  it('is there when the catalogue is given, and offers only activities not in the plan', async () => {
    render(<PlanTable calculationId="c1" activities={catalogue} />);
    await screen.findByText('Main nursery');
    fireEvent.mouseDown(screen.getByRole('combobox'));
    expect(await screen.findByText('Fire line construction (km)')).toBeInTheDocument();
    expect(screen.queryByText('Main nursery (no.)')).not.toBeInTheDocument(); // already a row
  });

  it('picking an activity adds it to the plan for year 1 and re-reads the plan', async () => {
    const onPlanChanged = vi.fn();
    render(<PlanTable calculationId="c1" activities={catalogue} onPlanChanged={onPlanChanged} />);
    await screen.findByText('Main nursery');
    fireEvent.mouseDown(screen.getByRole('combobox'));
    fireEvent.click(await screen.findByText('Fire line construction (km)'));
    await waitFor(() => expect(plan.addLine).toHaveBeenCalledWith('c1', { potential_activity_id: 2, years: [1] }));
    await waitFor(() => expect(plan.getPlan).toHaveBeenCalledTimes(2));
    expect(onPlanChanged).toHaveBeenCalled();
  });

  it('is absent without the catalogue and for a read-only plan', async () => {
    const { unmount } = render(<PlanTable calculationId="c1" />);
    await screen.findByText('Main nursery');
    expect(screen.queryByTestId('plan-inline-add')).not.toBeInTheDocument();
    unmount();
    render(<PlanTable calculationId="c1" activities={catalogue} readOnly />);
    await screen.findByText('Main nursery');
    expect(screen.queryByTestId('plan-inline-add')).not.toBeInTheDocument();
    expect(screen.queryByTestId('remove-line-L')).not.toBeInTheDocument();
  });
});

describe('removing a row', () => {
  it('asks first, then removes the line and re-reads the plan', async () => {
    render(<PlanTable calculationId="c1" activities={catalogue} />);
    await screen.findByText('Main nursery');
    fireEvent.click(screen.getByTestId('remove-line-L'));
    expect(del).not.toHaveBeenCalled(); // the confirmation comes first
    fireEvent.click(await screen.findByText('Remove'));
    await waitFor(() => expect(del).toHaveBeenCalledWith('L'));
    await waitFor(() => expect(plan.getPlan).toHaveBeenCalledTimes(2));
  });
});
