/**
 * Turns the server's plan-health CODES into words (YEARLY_ACTIVITIES_WORKSPACE_PLAN §4.5–4.6).
 *
 * The server never sends a sentence: it sends `{code, params, action}`. Every sentence lives in the
 * `yearlyPlan.*` catalogue (en.json / ne.json), so the wording is edited in one place — the Translation
 * page — and the same words appear on the map, the legacy page and the Plan check.
 */
import type { TFunction } from 'i18next';
import type { PlanHealthIssue, YearlyPlanHealth } from '../../services/api';
import { formatNumber } from '../../i18n/numberFormat';

export type PlanAction =
  | 'add_first_activity'
  | 'show_on_map'
  | 'enter_numbers'
  | 'choose_years'
  | 'plan_year'
  | 'check_amount'
  | 'confirm'
  | 'create_plan'
  | 'update_cba';

export interface StepView {
  /** catalogue key under `yearlyPlan.next.` */
  key: string;
  text: string;
  button: string;
  action: PlanAction;
  /** the plan line the step is about; null for plan-level steps */
  activityId: string | null;
  /** the user can also say "these numbers are right" instead of changing them */
  confirmable: boolean;
}

/** The catalogue key of a code; a placeholder line is worded by what is still a starting value. */
export function stepKey(code: string, params: Record<string, unknown> = {}): string {
  if (code === 'PLACEHOLDER_NUMBERS') {
    const fields = Array.isArray(params.fields) ? (params.fields as string[]) : [];
    const q = fields.includes('quantity');
    const b = fields.includes('budget');
    return q && b ? 'PLACEHOLDER_both' : q ? 'PLACEHOLDER_quantity' : 'PLACEHOLDER_budget';
  }
  return code;
}

const CONFIRMABLE = new Set(['PLACEHOLDER_NUMBERS', 'UNUSUAL_AMOUNT', 'NO_BUDGET_ANY_YEAR']);

function interpolation(
  params: Record<string, unknown>,
  activity: string | null | undefined,
  summary?: YearlyPlanHealth['summary'],
): Record<string, unknown> {
  const years = Array.isArray(params.years) ? (params.years as number[]).map((y) => formatNumber(y)).join(', ') : '';
  const amount = typeof params.yearly_budget === 'number' ? formatNumber(Math.round(params.yearly_budget)) : '';
  return {
    activity: activity ?? '',
    years,
    amount,
    activities: summary ? formatNumber(summary.total) : '',
    total: summary ? formatNumber(Math.round(summary.total_budget ?? 0)) : '',
  };
}

/** Words for one code (used for the Next-step card and for each checklist row). */
export function describeCode(
  code: string,
  params: Record<string, unknown>,
  action: string,
  activityId: string | null,
  activity: string | null | undefined,
  t: TFunction,
  summary?: YearlyPlanHealth['summary'],
): StepView {
  const key = stepKey(code, params);
  const values = interpolation(params, activity, summary);
  return {
    key,
    text: t(`yearlyPlan.next.${key}.text`, values) as string,
    button: t(`yearlyPlan.next.${key}.button`) as string,
    action: action as PlanAction,
    activityId,
    confirmable: CONFIRMABLE.has(code),
  };
}

/** The one Next-step the server chose. */
export function describeNextStep(health: YearlyPlanHealth, t: TFunction): StepView {
  const step = health.next_step;
  return describeCode(step.code, step.params ?? {}, step.action, step.activity_id, step.activity, t, health.summary);
}

/** The first issue of a checklist row, worded. */
export function describeIssue(
  issue: PlanHealthIssue,
  activityId: string,
  activity: string | null,
  t: TFunction,
): StepView {
  return describeCode(issue.code, issue.params ?? {}, issue.action, activityId, activity, t);
}
