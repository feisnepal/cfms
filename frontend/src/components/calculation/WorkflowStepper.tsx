/**
 * WorkflowStepper — the primary working surface. WORKSPACE_FLOW_NAV_PLAN §8.1.
 *
 * The owner's requirement, verbatim: *"user should get page easy in a ordered
 * form or in sequence. System should not enforce user navigating the page hither
 * and thither."* This component is the answer — one step at a time, in the order
 * the work is done, so nothing has to be hunted for.
 *
 * It is a **header, not a container swap.** The four group panels below stay
 * mounted and CSS-display-toggled, because the Leaflet map is a descendant and
 * unmounting it destroys the map the user was working on (see
 * `CalculationDetailTabbed.panelFor`). So the stepper drives *which step is
 * active*; the panels follow. One page is visible at a time either way.
 *
 * Three rules this component must not break:
 *
 * 1. **Nothing is ever locked.** An unmet `needs` renders a flag and a sentence
 *     explaining what is missing. The step stays clickable, `Next` still works,
 *     and there is no "you must complete step 3 first" anywhere in this file.
 * 2. **`Next` prefers input steps.** See `nextStep` in `workflowSteps.ts` — a
 *     crew that only enters data is walked through the seven Input steps without
 *     passing through Run and View steps they do not need.
 * 3. **Progress is reported separately from navigation.** `Skip for now` advances
 *     without marking anything done. Readiness comes from the server, not from
 *     where the user has been, so skipping cannot fake progress.
 */
import React from 'react';
import { ChevronLeft, ChevronRight, Check } from 'lucide-react';
import { useT } from '../../i18n/hooks';
import { SPINE, SPINE_LENGTH, TYPE_BADGE, nextStep, prevStep, type SpineStep } from './workflowSteps';
import type { StaleFlag } from '../../hooks/useWorkflowReadiness';
import StepForumLinks from '../../features/forum/StepForumLinks';

interface Props {
  /** The context id currently shown. */
  activeContext: string;
  onNavigate: (tab: SpineStep['tab'], ctx: string) => void;
  /** Completion per context id, from the server. */
  isDone: (id: string) => boolean;
  stale?: readonly StaleFlag[];
  loading?: boolean;
}

const WorkflowStepper: React.FC<Props> = ({ activeContext, onNavigate, isDone, stale = [], loading }) => {
  const t = useT();
  const current = SPINE.find((s) => s.id === activeContext) ?? SPINE[0];

  if (!current) return null;

  const go = (target: SpineStep | undefined) => {
    if (target) onNavigate(target.tab, target.id);
  };

  const back = prevStep(current.step);
  const fwd = nextStep(current.step, isDone);
  const badge = TYPE_BADGE[current.item.type];
  const isStale = stale.some((s) => s.step === current.id);
  const currentStale = stale.find((s) => s.step === current.id);

  // Which of this step's `needs` are unmet, in the user's language.
  const unmet = (current.item.needs ?? []).filter((id) => !isDone(id));

  return (
    <div className="workflow-stepper border-b border-gray-200 bg-white px-3 py-2" data-testid="workflow-stepper">
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => go(back)}
            disabled={!back}
            data-testid="workflow-stepper-back"
            aria-label={t('workflow.stepper.back')}
            title={t('workflow.stepper.back')}
            className="p-1 rounded text-gray-500 hover:bg-gray-100 disabled:opacity-30 disabled:hover:bg-transparent"
          >
            <ChevronLeft size={16} />
          </button>
          <button
            type="button"
            onClick={() => go(fwd)}
            data-testid="workflow-stepper-next"
            aria-label={t('workflow.stepper.next')}
            title={t('workflow.stepper.next')}
            className="p-1 rounded text-gray-500 hover:bg-gray-100"
          >
            <ChevronRight size={16} />
          </button>
        </div>

        <div className="flex items-baseline gap-2 min-w-0">
          <span className="text-xs text-gray-500 tabular-nums whitespace-nowrap">
            {t('workflow.stepper.stepOf', { n: current.step, total: SPINE_LENGTH })}
          </span>
          <span className="font-medium text-sm text-gray-900 truncate">
            {t(current.item.labelKey)}
          </span>
          <span
            className={`text-[10px] font-mono ${badge.className}`}
            title={t(badge.labelKey)}
            aria-label={t(badge.labelKey)}
          >
            {badge.glyph}
          </span>
          {isDone(current.id) && (
            <span
              className="inline-flex items-center gap-0.5 text-[11px] text-green-700"
              title={t('workflow.stepper.done')}
            >
              <Check size={12} aria-hidden="true" />
              {t('workflow.stepper.done')}
            </span>
          )}
          <StepForumLinks stepId={current.id} />
        </div>

        {/* One numbered chip per step (SPINE_LENGTH of them), in the SAME row as Back / Next and the step's name: green = the server says it is done,
            grey = not yet; the current step is darker and underlined. The number is the text; the full "N. name" is the tooltip. */}
        <ol className="flex items-center gap-1 min-w-0" aria-label={t('workflow.stepper.progress')}>
          {SPINE.map((s) => {
            const done = isDone(s.id);
            const isCurrent = s.step === current.step;
            const need = s.item.need ?? 'required';
            const incomplete = !!s.item.strict && !done;
            const text = `${s.step}. ${t(s.item.labelKey)}${need === 'required' ? '' : ` (${t(`workflow.need.${need}`)})`}${incomplete ? ` (${t('workflow.stepper.incomplete')})` : ''}`;
            // Required steps are solid; the ones the system fills in by itself (optional) or only needs adjusting (review) are
            // outlined, so the strip shows at a glance where the user's own work is.
            const outline = need === 'required' ? '' : need === 'review' ? ' border border-amber-500' : ' border border-dashed';
            return (
              <li key={s.id} className="shrink-0">
                <button
                  type="button"
                  onClick={() => go(s)}
                  aria-current={isCurrent ? 'step' : undefined}
                  aria-label={text}
                  title={text}
                  data-done={done ? 'true' : 'false'}
                  className={`min-w-[1.5rem] px-1 rounded-sm text-[11px] leading-4 font-bold text-center tabular-nums hover:underline${outline} ${
                    isCurrent
                      ? `${done ? 'text-green-950 bg-green-300' : incomplete ? 'text-red-950 bg-red-300' : 'text-blue-900 bg-blue-200'} underline decoration-2 underline-offset-2`
                      : incomplete
                        ? 'text-red-900 bg-red-200'
                        : done
                        ? 'text-green-800 bg-green-200'
                        : need === 'required'
                          ? 'text-gray-700 bg-gray-200'
                          : 'text-gray-500 bg-gray-50'
                  }`}
                >
                  {s.step}
                </button>
              </li>
            );
          })}
        </ol>

        <div className="ml-auto flex items-center gap-2">
          <button
            type="button"
            onClick={() => go(fwd)}
            className="text-sm px-3 py-1 rounded bg-green-600 text-white hover:bg-green-700"
          >
            {t('workflow.stepper.next')}
          </button>
          {/* Present so skipping is a first-class choice rather than a trap. It
              changes position only: readiness comes from the server. */}
          <button
            type="button"
            onClick={() => go(fwd)}
            className="text-xs px-2 py-1 rounded text-gray-500 hover:bg-gray-100"
          >
            {t('workflow.stepper.skip')}
          </button>
        </div>
      </div>

      {/* Flags and reasons. Advisory by construction — no control here can block. */}
      {(unmet.length > 0 || isStale || loading) && (
        <div className="mt-1.5 flex items-center gap-2 flex-wrap text-[11px]">
          {loading && <span className="text-gray-400">{t('workflow.stepper.checking')}</span>}
          {isStale && currentStale && (
            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-amber-50 text-amber-800 border border-amber-200">
              {t('workflow.stepper.stale', { version: currentStale.seen })}
            </span>
          )}
          {unmet.map((id) => {
            const dep = SPINE.find((s) => s.id === id);
            return (
              <span
                key={id}
                className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-gray-50 text-gray-600 border border-gray-200"
              >
                {t('workflow.stepper.waitingOn', { step: dep ? t(dep.item.labelKey) : id })}
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default WorkflowStepper;
