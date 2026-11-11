/**
 * Sub-areas must be tied to the yearly plan (owner rule 2026-10-08): the guided "What will you do here?" step, the list of
 * what still needs a plan, "decide later", and the choice when a planned sub-area is deleted.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import en from '../../../i18n/locales/en.json';
import ne from '../../../i18n/locales/ne.json';

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
vi.mock('../../../services/api', () => ({
  subAreaPlanApi: { status: vi.fn(), plan: vi.fn(), planSuggested: vi.fn() },
}));

import { subAreaPlanApi } from '../../../services/api';
import { SubAreaPlanDialog } from '../SubAreaPlanDialog';
import { planLinesDetail, PLAN_LINES_CODE } from '../../../lib/planLinesChoice';

const api = subAreaPlanApi as unknown as Record<'status' | 'plan' | 'planSuggested', ReturnType<typeof vi.fn>>;

const PLANTATION = { id: 4, activity: 'Plantation', program: 'P', unit: 'ha', map_kind: 'plantation' };
const status = (items: unknown[]) => ({ sub_areas: items, needs_plan: items.length });
const item = (over: Record<string, unknown> = {}) => ({
  id: 'SA1', name: 'North plot', category: 'plantation', area_ha: 2.5, state: 'needs_plan', unit_id: 'U1', line_ids: [],
  suggestions: [PLANTATION], ...over,
});

beforeEach(() => {
  vi.clearAllMocks();
});

describe('SubAreaPlanDialog', () => {
  it('asks "What will you do here?" for a just-drawn sub-area, pre-selects the suggestion and ties it to the plan', async () => {
    api.status.mockResolvedValue(status([item()]));
    api.plan.mockResolvedValue({ lines: [] });
    const onChanged = vi.fn();
    render(<SubAreaPlanDialog open calculationId="C1" focusId="SA1" onClose={vi.fn()} onChanged={onChanged} />);
    expect(await screen.findByText('What will you do here?')).toBeTruthy();
    fireEvent.click(await screen.findByTestId('sub-area-plan-save-SA1'));
    await waitFor(() => expect(api.plan).toHaveBeenCalledWith('C1', 'SA1', [4]));
    expect(onChanged).toHaveBeenCalled();
  });

  it('"Decide later" only closes: nothing is created', async () => {
    api.status.mockResolvedValue(status([item()]));
    const onClose = vi.fn();
    render(<SubAreaPlanDialog open calculationId="C1" focusId="SA1" onClose={onClose} onChanged={vi.fn()} />);
    fireEvent.click(await screen.findByTestId('sub-area-plan-later'));
    expect(onClose).toHaveBeenCalled();
    expect(api.plan).not.toHaveBeenCalled();
  });

  it('closes by itself when the drawn sub-area needs no plan (private land)', async () => {
    api.status.mockResolvedValue({ sub_areas: [item({ state: 'exempt' })], needs_plan: 0 });
    const onClose = vi.fn();
    render(<SubAreaPlanDialog open calculationId="C1" focusId="SA1" onClose={onClose} onChanged={vi.fn()} />);
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it('says so when a category has no suggestion, and when the sub-area lies in no unit', async () => {
    api.status.mockResolvedValue(status([
      item({ id: 'A', name: 'Odd', suggestions: [] }),
      item({ id: 'B', name: 'Far', state: 'no_unit', suggestions: [] }),
    ]));
    render(<SubAreaPlanDialog open calculationId="C1" onClose={vi.fn()} onChanged={vi.fn()} />);
    expect(await screen.findByText(en.subAreaPlan.noSuggestion)).toBeTruthy();
    expect(screen.getByText(en.subAreaPlan.noUnit)).toBeTruthy();
  });

  it('plans everything that has a suggestion in one click', async () => {
    api.status.mockResolvedValue(status([item({ id: 'A' }), item({ id: 'B' })]));
    api.planSuggested.mockResolvedValue({ planned: [{ id: 'A', name: 'x', activity: 'Plantation' }], skipped: [] });
    render(<SubAreaPlanDialog open calculationId="C1" onClose={vi.fn()} onChanged={vi.fn()} />);
    fireEvent.click(await screen.findByTestId('sub-area-plan-all'));
    await waitFor(() => expect(api.planSuggested).toHaveBeenCalledWith('C1'));
  });

  it('shows the all-clear when nothing is left', async () => {
    api.status.mockResolvedValue({ sub_areas: [], needs_plan: 0 });
    render(<SubAreaPlanDialog open calculationId="C1" onClose={vi.fn()} onChanged={vi.fn()} />);
    expect(await screen.findByText(en.subAreaPlan.allPlanned)).toBeTruthy();
  });
});

describe('planLinesDetail', () => {
  it('recognises the server\'s "choose what happens to the plan lines" answer, axios or fetch shaped', () => {
    const detail = { code: PLAN_LINES_CODE, count: 2, names: 'Plantation' };
    expect(planLinesDetail({ response: { status: 409, data: { detail } } })).toEqual(detail);
    expect(planLinesDetail(detail)).toEqual(detail);
    expect(planLinesDetail({ response: { status: 409, data: { detail: { code: 'other' } } } })).toBeNull();
    expect(planLinesDetail(undefined)).toBeNull();
  });
});

describe('catalogue', () => {
  it('has the same subAreaPlan keys in English and Nepali', () => {
    expect(Object.keys(ne.subAreaPlan).sort()).toEqual(Object.keys(en.subAreaPlan).sort());
  });
});
