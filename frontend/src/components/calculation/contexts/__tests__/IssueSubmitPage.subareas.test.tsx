/** Step 15 says why the plan cannot be issued while a sub-area has no plan, and offers to plan it (owner rule 2026-10-08). */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import en from '../../../../i18n/locales/en.json';

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
vi.mock('../../../../services/api', () => ({
  operationalPlanApi: { getByCalculation: vi.fn(), exportDocx: vi.fn(), getExportRequirements: vi.fn() },
  subAreaPlanApi: { status: vi.fn(), plan: vi.fn(), planSuggested: vi.fn() },
  yearlyPlanApi: { getStatus: vi.fn(async () => ({ done: true, done_at: null, done_by: null, reopened_reason: null })), setDone: vi.fn() },
}));

import { operationalPlanApi, subAreaPlanApi } from '../../../../services/api';
import IssueSubmitPage from '../IssueSubmitPage';

const plan = operationalPlanApi as unknown as Record<string, ReturnType<typeof vi.fn>>;
const sub = subAreaPlanApi as unknown as Record<string, ReturnType<typeof vi.fn>>;

beforeEach(() => {
  vi.clearAllMocks();
  plan.getByCalculation.mockResolvedValue({ id: 'P1' });
  plan.getExportRequirements.mockResolvedValue({ ready: true, items: [] });
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ total: 1, resolved: 1, ready: true, unverified: 0, missing: [], unmet_maps: [], submissions: [] }) })));
});

describe('IssueSubmitPage - sub-areas', () => {
  it('lists the unplanned sub-areas, offers to plan them and keeps the export button off', async () => {
    sub.status.mockResolvedValue({
      needs_plan: 2,
      sub_areas: [
        { id: 'A', name: 'North plot', state: 'needs_plan', category: 'plantation', area_ha: 1, unit_id: 'U', line_ids: [] },
        { id: 'B', name: 'Mine', state: 'exempt', category: 'private_land', area_ha: 1, unit_id: 'U', line_ids: [] },
        { id: 'C', name: 'Far away', state: 'no_unit', category: 'plantation', area_ha: 1, unit_id: null, line_ids: [] },
      ],
    });
    render(<IssueSubmitPage calculationId="C1" />);
    const alert = await screen.findByTestId('issue-sub-areas-unplanned');
    expect(alert.textContent).toContain('2 sub-area(s) are not tied to the yearly plan');
    expect(alert.textContent).toContain('North plot');
    expect(alert.textContent).toContain('Far away');
    expect(alert.textContent).not.toContain('Mine');
    expect(screen.getByTestId('issue-plan-sub-areas')).toBeTruthy();
    const exportBtn = screen.getByRole('button', { name: en.operationalPlan.page.exportDocx });
    expect((exportBtn as HTMLButtonElement).disabled).toBe(true);
  });

  it('shows nothing extra when every sub-area is planned', async () => {
    sub.status.mockResolvedValue({ needs_plan: 0, sub_areas: [{ id: 'A', name: 'x', state: 'planned', category: 'plantation', area_ha: 1, unit_id: 'U', line_ids: ['L'] }] });
    render(<IssueSubmitPage calculationId="C1" />);
    await waitFor(() => expect(sub.status).toHaveBeenCalled());
    expect(screen.queryByTestId('issue-sub-areas-unplanned')).toBeNull();
  });

  it('shows the mandatory-steps checklist and keeps the export button off until every step is done', async () => {
    sub.status.mockResolvedValue({ needs_plan: 0, sub_areas: [] });
    plan.getExportRequirements.mockResolvedValue({
      ready: false,
      items: [
        { key: 'raster', done: true, label_en: 'Analysis run on every unit', label_ne: 'x', hint_en: '', hint_ne: '', detail: {} },
        { key: 'cba', done: false, label_en: 'Cost-benefit analysis calculated', label_ne: 'x', hint_en: 'Open Cost-Benefit and calculate the base scenario.', hint_ne: 'x', detail: {} },
      ],
    });
    render(<IssueSubmitPage calculationId="C1" />);
    const list = await screen.findByTestId('export-requirements');
    expect(list.textContent).toContain('1 of 2 required steps are complete');
    expect(list.textContent).toContain('Cost-benefit analysis calculated');
    expect(list.textContent).toContain('Open Cost-Benefit and calculate the base scenario.');
    const exportBtn = screen.getByRole('button', { name: en.operationalPlan.page.exportDocx });
    expect((exportBtn as HTMLButtonElement).disabled).toBe(true);
  });
});
