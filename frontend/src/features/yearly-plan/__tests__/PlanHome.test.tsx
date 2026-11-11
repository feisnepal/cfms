/**
 * The shared yearly-plan panel of the yearly-activities pages (YEARLY_ACTIVITIES plan P5): it opens on "Your plan",
 * the finder is "Browse all activities", adding an activity uses the same questions as the map — but with nothing to
 * draw on, so a place is drawn later on the map ("Edit on map").
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
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
vi.mock('../../../i18n/numberFormat', () => ({
  formatNumber: (n: number) => String(n),
  formatDecimal: (n: number) => String(n),
  parseLocaleNumber: (s: string) => (String(s).trim() === '' ? NaN : Number(String(s).replace(/,/g, ''))),
}));
vi.mock('../../../services/api', () => ({
  yearlyPlanApi: { getPlan: vi.fn(), addLine: vi.fn(), createFeature: vi.fn(), updateLine: vi.fn(), confirmLine: vi.fn() },
  yearlyActivitiesApi: { listPotentialActivities: vi.fn() },
}));

import { yearlyActivitiesApi, yearlyPlanApi, type YearlyPlanLine } from '../../../services/api';
import { PlanHome } from '../PlanHome';

const plan = yearlyPlanApi as unknown as Record<'getPlan' | 'addLine', ReturnType<typeof vi.fn>>;
const acts = yearlyActivitiesApi as unknown as Record<'listPotentialActivities', ReturnType<typeof vi.fn>>;

const NURSERY = { id: 1, activities: 'Nursery building', name_en: 'Nursery building', progarms: 'Forest', unit: 'no.', requires_map: true, map_kind: 'nursery' };
const SCHOLARSHIP = { id: 2, activities: 'Scholarship', name_en: 'Scholarship', progarms: 'Community', unit: 'no.', requires_map: false, map_kind: null };

const line = (over: Partial<YearlyPlanLine> = {}): YearlyPlanLine => ({
  id: 'L1',
  potential_activity_id: 1,
  activity: 'Nursery building',
  program: 'Forest',
  unit: 'no.',
  requires_map: true,
  default_quantity: 1,
  default_yearly_budget: 5000,
  years: Array.from({ length: 10 }, (_, i) => ({ year: i + 1, quantity: 1, budget: 5000, planned: true, has_row: true })),
  planned_years: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
  total_budget: 50000,
  version: 1,
  reviewed_at: null,
  placeholder_fields: ['quantity', 'budget'],
  feature_count: 0,
  location_mode: 'needs_location',
  assign_to_all_blocks: false,
  status: 'proposed',
  notes: null,
  ...over,
});

beforeEach(() => {
  vi.clearAllMocks();
  acts.listPotentialActivities.mockResolvedValue([NURSERY, SCHOLARSHIP]);
  plan.getPlan.mockResolvedValue({ total_budget: 0, lines: [] });
  vi.spyOn(message, 'info').mockImplementation((() => undefined) as never);
  vi.spyOn(message, 'success').mockImplementation((() => undefined) as never);
});

async function openBrowse() {
  fireEvent.click(await screen.findByRole('tab', { name: 'Browse all activities' }));
  await screen.findByTestId('activity-search');
}

const choose = async (id: number, word: string) => {
  // the finder lists rows once something is typed
  fireEvent.change(screen.getByTestId('activity-search'), { target: { value: word } });
  const row = await screen.findByTestId(`activity-row-${id}`);
  fireEvent.click(within(row).getByRole('button', { name: 'Choose' }));
};

describe('PlanHome — the plan comes first', () => {
  it('opens on "Your plan" with the editable table, and the finder is "Browse all activities"', async () => {
    plan.getPlan.mockResolvedValue({ total_budget: 0, lines: [line()] });
    render(<PlanHome calculationId="c1" />);
    expect(await screen.findByTestId('plan-table')).toBeInTheDocument();
    expect(await screen.findByText('Nursery building')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Your plan', selected: true })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Browse all activities', selected: false })).toBeInTheDocument();
    // no "Save All": numbers save where they are typed
    expect(screen.queryByRole('button', { name: /save all/i })).toBeNull();
    expect(screen.getByTestId('default-quantity-L1')).toBeInTheDocument();
  });

  it('has no "Wider view" button — the page already has the width', async () => {
    render(<PlanHome calculationId="c1" />);
    await screen.findByTestId('plan-table');
    expect(screen.queryByTestId('plan-table-expand')).toBeNull();
  });

  it('"Edit on map" is offered and calls the host', async () => {
    const onEditOnMap = vi.fn();
    render(<PlanHome calculationId="c1" onEditOnMap={onEditOnMap} />);
    fireEvent.click(await screen.findByTestId('plan-home-edit-on-map'));
    expect(onEditOnMap).toHaveBeenCalledTimes(1);
  });

  it('a mappable row has a "Location and drawing…" link; a row that needs no map has none', async () => {
    plan.getPlan.mockResolvedValue({
      total_budget: 0,
      lines: [
        line(),
        line({ id: 'L2', potential_activity_id: 2, activity: 'Scholarship', requires_map: false, location_mode: 'not_applicable' }),
      ],
    });
    const onOpenDetails = vi.fn();
    render(<PlanHome calculationId="c1" onOpenDetails={onOpenDetails} />);
    fireEvent.click(await screen.findByTestId('location-details-L1'));
    expect(onOpenDetails.mock.calls[0][0].id).toBe('L1');
    expect(screen.queryByTestId('location-details-L2')).toBeNull();
  });
});

describe('PlanHome — adding an activity', () => {
  it('an activity that needs no map goes years → numbers → save, with no place question, and lands in Your plan', async () => {
    plan.addLine.mockResolvedValue({ plan_line: line({ id: 'N', potential_activity_id: 2 }), created_plan_line: true, unit: 'no.' });
    const onPlanChanged = vi.fn();
    render(<PlanHome calculationId="c1" onPlanChanged={onPlanChanged} />);
    await openBrowse();
    await choose(2, 'scholarship');

    expect(await screen.findByTestId('activity-wizard')).toBeInTheDocument();
    expect(await screen.findByTestId('wizard-when')).toBeInTheDocument();
    expect(screen.queryByTestId('wizard-where')).toBeNull();
    // the questions are embedded (no fold-away button; there is no map to keep free)
    expect(screen.queryByTestId('wizard-min')).toBeNull();

    fireEvent.click(screen.getByTestId('preset-first5'));
    fireEvent.click(screen.getByTestId('wizard-next'));
    fireEvent.change(screen.getByTestId('numbers-quantity'), { target: { value: '2' } });
    fireEvent.change(screen.getByTestId('numbers-budget'), { target: { value: '5000' } });
    fireEvent.click(screen.getByTestId('wizard-next'));
    fireEvent.click(screen.getByTestId('wizard-save'));

    await waitFor(() => expect(plan.addLine).toHaveBeenCalledTimes(1));
    expect(plan.addLine.mock.calls[0][1]).toMatchObject({ potential_activity_id: 2, years: [1, 2, 3, 4, 5], quantity: 2, budget: 5000 });
    await waitFor(() => expect(onPlanChanged).toHaveBeenCalled());
    expect(screen.getByRole('tab', { name: 'Your plan', selected: true })).toBeInTheDocument();
  });

  it('an activity that can be drawn offers "whole forest" and "decide later" — not "Show it on the map" — and says how to draw it', async () => {
    const onEditOnMap = vi.fn();
    render(<PlanHome calculationId="c1" onEditOnMap={onEditOnMap} />);
    await openBrowse();
    await choose(1, 'nursery');

    const where = await screen.findByTestId('wizard-where');
    expect(within(where).queryByTestId('where-map')).toBeNull();
    expect(within(where).getByTestId('where-whole')).toBeInTheDocument();
    expect(within(where).getByTestId('where-later')).toBeInTheDocument();
    expect(screen.getByTestId('wizard-no-draw').textContent).toContain('you can draw the place later');
    fireEvent.click(screen.getByTestId('wizard-edit-on-map'));
    expect(onEditOnMap).toHaveBeenCalledTimes(1);
  });

  it('an activity already in the plan is offered as "Open in plan", which shows its row — it is never added twice', async () => {
    plan.getPlan.mockResolvedValue({ total_budget: 0, lines: [line()] });
    render(<PlanHome calculationId="c1" />);
    await screen.findByText('Nursery building');
    await openBrowse();
    fireEvent.change(screen.getByTestId('activity-search'), { target: { value: 'nursery' } });
    const row = await screen.findByTestId('activity-row-1');
    expect(within(row).queryByRole('button', { name: 'Choose' })).toBeNull();
    fireEvent.click(within(row).getByRole('button', { name: 'Open in plan' }));
    expect(screen.queryByTestId('activity-wizard')).toBeNull();
    expect(screen.getByRole('tab', { name: 'Your plan', selected: true })).toBeInTheDocument();
  });

  it('"Add activity" in the table and the host’s signal both open the questions', async () => {
    const { rerender } = render(<PlanHome calculationId="c1" addSignal={0} />);
    fireEvent.click(await screen.findByTestId('plan-table-add'));
    expect(await screen.findByTestId('activity-wizard')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('wizard-close'));
    await waitFor(() => expect(screen.queryByTestId('activity-wizard')).toBeNull());
    rerender(<PlanHome calculationId="c1" addSignal={1} />);
    expect(await screen.findByTestId('activity-wizard')).toBeInTheDocument();
  });
});
