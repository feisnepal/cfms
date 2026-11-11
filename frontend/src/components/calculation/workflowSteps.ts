/**
 * workflowSteps — the ordered spine, and the rules for walking it.
 * WORKSPACE_FLOW_NAV_PLAN §4/§5.
 *
 * Pure, so the stepper and the rail cannot disagree about what "the next step"
 * is — which is the failure mode when two components each compute it.
 *
 * The rule that matters most, and the one most likely to be "optimised" away by
 * someone later: **`next` prefers REQUIRED steps** (`need: 'required'`, owner 2026-10-11): the steps where the user must upload,
 * edit or set a parameter. A crew is walked through those and never has to hunt through the steps the system fills in by itself.
 * Optional and review steps are still one `Next` away and always reachable — this is an ordering preference, never a filter,
 * because hiding part of the flow is enforcement by omission.
 */
import { TABS, type TabId } from '../../pages/calculationTabConfig';
import { GROUP_CONTEXTS, isSpineItem, type CtxItem, type PageType } from './calcContexts';

export interface SpineStep {
  tab: TabId;
  id: string;
  step: number;
  item: CtxItem;
}

/** Every numbered step, in workflow order. Computed once — the registry is static. */
export const SPINE: readonly SpineStep[] = TABS.flatMap((tab) =>
  GROUP_CONTEXTS[tab]
    .filter(isSpineItem)
    .map((item) => ({ tab, id: item.id, step: item.step!, item })),
).sort((a, b) => a.step - b.step);

/** Contexts with no step — the Optional band. */
export const OFF_SPINE: readonly { tab: TabId; item: CtxItem }[] = TABS.flatMap((tab) =>
  GROUP_CONTEXTS[tab]
    .filter((c) => !isSpineItem(c))
    .map((item) => ({ tab, item })),
);

export const SPINE_LENGTH = SPINE.length;

/** The steps the user must act on; progress is counted over these, not over the steps the system completes by itself. */
export const REQUIRED_STEPS: readonly SpineStep[] = SPINE.filter((s) => s.item.need === 'required');

export function stepAt(step: number): SpineStep | undefined {
  return SPINE.find((s) => s.step === step);
}

export function stepById(id: string): SpineStep | undefined {
  return SPINE.find((s) => s.id === id);
}

/** Where a context id sits, spine or not. Used to resolve a URL onto the flow. */
export function locate(id: string): { tab: TabId; step?: number; item?: CtxItem } | null {
  const spine = stepById(id);
  if (spine) return { tab: spine.tab, step: spine.step, item: spine.item };
  const off = OFF_SPINE.find((o) => o.item.id === id);
  return off ? { tab: off.tab, item: off.item } : null;
}

/**
 * The step `Next` should land on.
 *
 * Three fallbacks, in order, so it always moves:
 *  1. the next **incomplete required** step — the crew-entering-data case;
 *  2. the next **incomplete** step of any type — so a crew that must run an
 *     analysis is not stranded;
 *  3. the next step at all — so a forest with everything done still moves
 *     forward instead of dead-ending on the last step.
 *
 * Wraps to step 1, because a loop that stops at the end is a dead end (D7: the
 * plan feeds the next cycle).
 */
export function nextStep(
  fromStep: number,
  isDone: (id: string) => boolean,
  onlyInput = true,
): SpineStep {
  const ordered = [
    ...SPINE.filter((s) => s.step > fromStep),
    ...SPINE.filter((s) => s.step <= fromStep),
  ];
  const acceptable = (s: SpineStep) => !onlyInput || s.item.need === 'required';
  const next =
    ordered.find((s) => acceptable(s) && !isDone(s.id)) ??
    ordered.find((s) => acceptable(s)) ??
    ordered[0];
  // `ordered` is non-empty because SPINE is, but assert rather than lie if a
  // future registry ends up empty — an empty rail should not crash the shell.
  if (!next) throw new Error('workflowSteps: SPINE is empty');
  return next;
}

/** `Back` — the previous step, stopping at 1. */
export function prevStep(fromStep: number): SpineStep | undefined {
  return SPINE.filter((s) => s.step < fromStep).pop();
}

/**
 * Badge presentation per page type.
 *
 * `input` is filled and `view` is hollow on purpose: the same shape language the
 * mock used, and it survives being read at a glance or by a screen reader, where
 * a four-way colour code would not.
 */
export const TYPE_BADGE: Record<PageType, { glyph: string; labelKey: string; className: string }> = {
  input: { glyph: '■', labelKey: 'workflow.type.input', className: 'text-green-700' },
  run: { glyph: '▶', labelKey: 'workflow.type.run', className: 'text-blue-700' },
  view: { glyph: '□', labelKey: 'workflow.type.view', className: 'text-gray-500' },
  trial: { glyph: '1h', labelKey: 'workflow.type.trial', className: 'text-amber-700' },
};
