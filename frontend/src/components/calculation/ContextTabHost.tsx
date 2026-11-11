/**
 * ContextTabHost — the inner tab bar of a page that has more than one view.
 * WORKSPACE_FLOW_NAV_PLAN §8.4, phase P5a.
 *
 * A step in the spine is a *page*, but four of them are really two or three
 * views of the same subject: Field Inventory is Upload Data / Forest Metadata /
 * Results, the Operational Plan is Plan / Yearly Activities. Before this, each
 * of those was its own nav item, which inflated the rail with things that are
 * not steps in the work. Here they become tabs *inside* one step, so the spine
 * stays one entry per step and the step still has one name.
 *
 * Three decisions that are load-bearing:
 *
 * 1. **Labels come from the registry, via i18n keys.** `CtxItem.tabs` is
 *    `{ id, labelKey }[]`; this component never sees a literal. That is why the
 *    registry changed shape in P5a — it used to hold `'Upload Data'` and friends,
 *    which would have stayed English in a Nepali-first app.
 * 2. **Only the active pane is mounted.** `destroyInactiveTabPane` is set, so a
 *    pane is torn down when the user leaves it. That matters because the pane
 *    bodies fetch on mount: without it a three-tab page would fire three
 *    requests and hold three copies of the data. The cost is that pane-local
 *    state does not survive a tab switch — acceptable for a *view*, and the
 *    reason P5d gives Field Inventory a shared data hook rather than relying on
 *    two mounts of one component to stay in sync.
 * 3. **Nothing here enforces anything.** A pane can be marked unavailable
 *    (`locked` in `CONTEXT_TABS`) and it renders disabled with the reason
 *    attached. That is a *result* tab with no data behind it, not a gate on the
 *    work: the step itself stays reachable, and the sibling pane that does the
 *    entering is right there. This mirrors the rail's rule — sequence, never
 *    enforce — at one remove.
 */
import React, { Suspense } from 'react';
import { Empty } from 'antd';
import { useT } from '../../i18n/hooks';
import PanelSkeleton from './PanelSkeleton';
import type { ContextTabSpec } from './calcContexts';
import type { ContextPanelProps, ContextRenderer } from './contextComponents';

export interface ContextTabDefinition extends ContextTabSpec {
  render: ContextRenderer;
  /**
   * When true the pane is disabled and shows `workflow.tabs.resultsLocked`
   * instead of its body. Used for a Results pane with no data behind it.
   */
  locked?: boolean;
}

export interface ContextTabGroup {
  /**
   * Optional component rendered *above* the tab bar and the panes, once per
   * context, surviving every pane switch.
   *
   * This exists because the host mounts one pane at a time — which is what
   * keeps two panes from holding two copies of the same data — and therefore
   * any state that must outlive a pane switch cannot live in a pane. A form the
   * user has half filled, or a set of multipliers, has to be held up here or it
   * is destroyed the moment they look at another tab.
   *
   * It is a plain wrapper (`({children}) => <div/>`), not a context provider by
   * itself: the provider is the caller's business, so the mechanism does not
   * decide what shared state means. It is handed the `calculationId` and nothing
   * else, because that is the one thing a shared-state holder has to know about
   * to load anything.
   */
  provider?: React.ComponentType<{
    calculationId: string;
    /**
     * Passed through to the provider so a write inside a pane can re-read the
     * shell's workflow readiness. See `ContextPanelProps.onStepDataChanged`.
     */
    onStepDataChanged?: () => void;
    children?: React.ReactNode;
  }>;
  panes: Record<string, ContextTabDefinition>;
}

export interface ContextTabHostProps extends ContextPanelProps {
  tabs: readonly ContextTabSpec[];
  panes: Record<string, ContextTabDefinition>;
  /** Accessible name for the tab bar, e.g. the step's own label. */
  label?: string;
  /**
   * Whether the owning step has data, from the server-side readiness the rail
   * and stepper already use. Gates only panes the registry marked
   * `needsStepData`; omit it and nothing locks.
   */
  stepDone?: boolean;
}

export const ContextTabHost: React.FC<ContextTabHostProps> = ({
  tabs,
  panes,
  label,
  stepDone,
  ...panelProps
}) => {
  const t = useT();

  const isLocked = (tab: ContextTabSpec): boolean =>
    panes[tab.id]?.locked === true || (tab.needsStepData === true && stepDone === false);

  // Default to the first pane the registry declares that is not locked, so a
  // page whose Results tab has nothing behind it still opens on the pane the
  // user can actually use. Keyed on the tab signature so a context swap resets
  // it: the outer component is reused across steps.
  // `?pane=<id>` (the export checklist's shortcuts) opens that pane when it exists and is not locked.
  const wantedPane = typeof window !== 'undefined' ? new URLSearchParams(window.location.search).get('pane') : null;
  const requested = wantedPane ? tabs.find((tab) => tab.id === wantedPane && !isLocked(tab))?.id : undefined;
  const firstOpen = requested ?? tabs.find((tab) => !isLocked(tab))?.id ?? tabs[0]?.id;
  const [activeId, setActiveId] = React.useState<string | undefined>(firstOpen);
  const signature = tabs.map((tab) => tab.id).join('|');

  React.useEffect(() => {
    setActiveId(firstOpen);
  }, [signature, firstOpen]);

  if (tabs.length === 0) return null;

  // A pane id with no body is a registry/resolver disagreement. The resolver
  // test asserts the two agree; rendering nothing beats throwing mid-panel.
  const active = activeId ? panes[activeId] : undefined;
  if (!active) return <Empty description={t('workflow.tabs.missingPane')} />;

  // The selected pane can become locked underneath the user (its data was
  // removed while they were on another tab). Fall back rather than render a
  // disabled pane's contents.
  const activeLocked = activeId ? isLocked(tabs.find((x) => x.id === activeId)!) : false;

  const index = Math.max(
    0,
    tabs.findIndex((tab) => tab.id === active.id),
  );

  return (
    <div className="flex flex-col h-full min-h-0" data-testid="context-tabs">
      <div role="tablist" aria-label={label} className="flex gap-1 border-b border-gray-200 px-3">
        {tabs.map((tab) => {
          const pane = panes[tab.id];
          const disabled = isLocked(tab);
          return (
            <button
              key={tab.id}
              type="button"
              role="tab"
              id={`context-tab-${tab.id}`}
              aria-selected={tab.id === active.id}
              aria-controls={`context-tabpanel-${tab.id}`}
              disabled={disabled}
              title={disabled ? t('workflow.tabs.resultsLocked') : undefined}
              onClick={() => setActiveId(tab.id)}
              className={[
                'px-3 py-2 text-sm border-b-2 -mb-px transition-colors',
                tab.id === active.id
                  ? 'border-green-600 text-green-700 font-medium'
                  : 'border-transparent text-gray-600 hover:text-gray-900',
                disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer',
              ].join(' ')}
            >
              {t(tab.labelKey)}
            </button>
          );
        })}
      </div>

      <div
        role="tabpanel"
        id={`context-tabpanel-${active.id}`}
        aria-labelledby={`context-tab-${active.id}`}
        data-testid="context-tabpanel"
        className="flex-1 min-h-0 overflow-auto"
      >
        {/*
          The pane bodies are `React.lazy`, and the only Suspense boundary in the
          shell wraps the WHOLE panel (`CalculationDetailTabbed.tsx:408`). Without
          a boundary here, clicking a lazy pane suspends up to that one, the tab bar
          is unmounted along with it, and the host remounts with its default tab —
          so the click appears to do nothing and the selection snaps back. Caught by
          a live probe, not by the unit tests: those render plain components, which
          never suspend. Keep this boundary.
        */}
        <Suspense fallback={<PanelSkeleton label={t(active.labelKey)} />}>
          {activeLocked ? (
            <div className="p-6 text-sm text-gray-600" data-testid="context-tabpanel-locked">
              {t('workflow.tabs.resultsLocked')}
            </div>
          ) : (
            active.render(panelProps)
          )}
        </Suspense>
      </div>
    </div>
  );
};

export default ContextTabHost;
