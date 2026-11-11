/**
 * contextComponents — the single context -> component resolver for the tabbed
 * calculation shell. WORKSPACE_FLOW_NAV_PLAN §8.0, phase P2a.
 *
 * Why this exists
 * ---------------
 * The four groups were not only nav groupings. Each had a container component
 * that was a per-group `===` switch statement:
 *
 *   ForestDataTab       5 contexts
 *   SamplingModelTab    4 contexts
 *   DataMapsTab         9 contexts
 *   ReportsOutputsTab   3 contexts
 *
 * The target structure in plan §4 moves those 21 contexts into 4 new groups that
 * do not line up with the old ones — 3 of the 4 old groups are split across new
 * groups. So the containers cannot be kept: a context belongs to exactly one
 * group now, and the group is no longer what decides which component renders.
 *
 * This module inverts the ownership. The **context id** decides; the group is
 * only a heading in the rail.
 *
 * Three things this file preserves deliberately
 * ----------------------------------------------
 * 1. **Lazy per context.** Each container was code-split (`XxxTabLazy`, Phase 5).
 *    Eagerly importing the leaves here would put the whole workspace in the main
 *    bundle and lose the skeleton, so every leaf stays behind `React.lazy`.
 * 2. **Exact prop passing.** The containers passed each leaf only what that leaf
 *    accepts — `UserGroupMapTab` got `forestBoundary`, `MapsTab` got
 *    `forestName`, `AnalysisTab` got `calculation` but not `permissions`. Those
 *    differences are load-bearing, so they are transcribed rather than
 *    normalised behind one `{...props}`.
 * 3. **Removals are unreachable, not just hidden.** The six retired contexts have
 *    no entry here at all, and `resolveSurface` rewrites every URL that named
 *    them. There is no path — not even a stale bookmark — that reaches a
 *    removed surface.
 */
import React, { lazy } from 'react';
import type { Calculation } from '../../types';
import { findContext } from './calcContexts';
import { useT } from '../../i18n/hooks';
import ContextTabHost, { type ContextTabGroup } from './ContextTabHost';
/**
 * The props every context panel can be given. This is exactly what the four
 * containers received from the shell (`sharedProps` in `CalculationDetailTabbed`
 * plus `calculationId`).
 *
 * `onContextChange` is absent because all four containers discarded it — they
 * destructured it as `_onContextChange` so it would not leak into `{...props}`,
 * documented in each as "navigation flows through the shell's ActivityRail". It
 * was never used and is dropped rather than carried forward.
 */
export interface ContextPanelProps {
  calculationId: string;
  calculation?: Calculation | null;
  permissions: any;
  structureLocked: boolean;
  mapLifecycleStatus: string;
  /**
   * Re-read the server-side workflow readiness.
   *
   * Readiness is fetched once when the calculation detail page mounts, and a
   * `needsStepData` pane is locked from it. So a step the user has just
   * *completed in this session* stayed locked until a manual reload: upload a
   * field inventory, and its own Results tab is the one thing that will not
   * open, with nothing on screen to suggest a reload would fix it. Anything
   * that writes a step's data calls this when the write succeeds.
   */
  onStepDataChanged?: () => void;
}

export type ContextRenderer = (props: ContextPanelProps) => React.ReactElement | null;

// ── leaves, code-split exactly as the containers were ─────────────────────
const WorkspaceTab = lazy(() =>
  import('../../components/WorkspaceTab').then((m) => ({ default: m.WorkspaceTab })),
);
type WorkspaceContext = import('../../components/WorkspaceTab').WorkspaceContext;
const AnalysisTab = lazy(() => import('./AnalysisTab'));
const SubAreaTablesTab = lazy(() => import('./SubAreaTablesTab'));
const SamplingTab = lazy(() =>
  import('../../components/SamplingTab').then((m) => ({ default: m.SamplingTab })),
);
const TreeModelPanel = lazy(() => import('./contexts/TreeModelPanel'));
const TreeMappingTab = lazy(() =>
  import('../../components/TreeMappingTab').then((m) => ({ default: m.TreeMappingTab })),
);
const FieldbookTab = lazy(() =>
  import('../../components/FieldbookTab').then((m) => ({ default: m.FieldbookTab })),
);
const OperationalPlanPage = lazy(() => import('../../pages/OperationalPlanPage'));
// Default export, unlike its siblings — noted so the next reader does not
// "fix" it into a named import that does not exist.
const YearlyStepPage = lazy(() => import('../../components/YearlyActivities/YearlyStepPage'));
const FieldInventoryTab = lazy(() =>
  import('../../components/FieldInventoryTab').then((m) => ({ default: m.FieldInventoryTab })),
);
// The provider is lazy for the same reason the panes are: it is only ever needed
// by the tabbed Field Inventory group.
const FieldInventoryDataProvider = lazy(() =>
  import('../../components/fieldInventory/useFieldInventoryData').then((m) => ({
    default: m.FieldInventoryDataProvider,
  })),
);
const ForestMetadataPanel = lazy(() =>
  import('../../components/fieldInventory/ForestMetadataPanel').then((m) => ({
    default: m.ForestMetadataPanel,
  })),
);
const BiodiversityTab = lazy(() => import('../../components/BiodiversityTab'));
const UserGroupMapTab = lazy(() =>
  import('../../components/UserGroupMapTab').then((m) => ({ default: m.UserGroupMapTab })),
);
const HazardErosionTab = lazy(() => import('./HazardErosionTab'));
const NtfpInventoryTab = lazy(() => import('../ntfp/NtfpInventoryTab'));
const SustainableFmTab = lazy(() => import('./SustainableFmTab'));
const CBATab = lazy(() => import('./CBATab'));
const IssueSubmitPage = lazy(() => import('./contexts/IssueSubmitPage'));
const DetailedDescriptionTab = lazy(() =>
  import('../../components/DetailDescription/DetailedDescriptionTab'),
);

// Deliberately NOT imported, and unreachable by any URL (D3/D4/D6/D9):
//   MapsTab             — `maps`; the Map workspace owns map preparation
//   TotalInventoryTab   — `totalinventory`; the Field Inventory Results tab
//   ReportTab           — `reports`; the Forest Metadata tab + readiness strip
//   YearlyActivitiesTab — `yearlyactivities`; the Operational Plan's 2nd tab
// The three files still exist and are deleted in P5, once the tabs that replace
// them render the same thing. See WORKSPACE_FLOW_NAV_PLAN §8.7.

/**
 * Workspace contexts and the `WorkspaceTab` prop each one needs.
 *
 * `boundary`, `blocks` and `subcompartments` are NOT in `GROUP_CONTEXTS` — they
 * are legacy context ids that survive because `parseSurfaceId` passes
 * unrecognised contexts through (`calcSurface.ts:26-42`) and `MAP_CONTEXT_IDS`
 * still lists them. They are mapped here for the same reason: a bookmark with
 * `?surface=forest-data/blocks` must still render the map. Plan §6.2 turns the
 * open passthrough into an explicit allowlist in P2b; until then these three keep
 * working exactly as they do today.
 *
 * Transcribed from `ForestDataTab.CONTEXT_MAP`.
 */
const WORKSPACE_CONTEXTS: Record<string, WorkspaceContext> = {
  unified: 'unified',
  boundary: 'boundary_edit',
  blocks: 'block_naming',
  subcompartments: 'sub_compartments',
  // Not a nav context — the older name for the same view, reachable only through
  // `LEGACY_PASSTHROUGH_ALLOWLIST`. It used to render a BLANK panel: it is in
  // neither `GROUP_CONTEXTS` nor the old `ForestDataTab.CONTEXT_MAP`, whose key
  // is `blocks` with the *value* `block_naming`. `tabbed-detail.spec.ts` only
  // ever asserted the URL survived, never that anything rendered, so the blank
  // went unnoticed. Mapping it here is a fix, and it is the only behaviour
  // change in P2b beyond the regrouping.
  block_naming: 'block_naming',
};

const workspaceRenderer =
  (workspaceContext: WorkspaceContext): ContextRenderer =>
  function WorkspacePanel({ calculationId }: ContextPanelProps) {
    return <WorkspaceTab calculationId={calculationId} context={workspaceContext} />;
  };

/**
 * Pane bodies for the contexts that have inner tabs (plan §8.4, phase P5).
 *
 * Kept separate from `CONTEXT_COMPONENTS` rather than nested inside it, so
 * "which contexts are tabbed" is one readable list instead of a union type, and
 * so an un-tabbed context keeps exactly the code path it had in P2a — no
 * behaviour change for the 11 contexts that are not tabbed.
 *
 * A context id present in BOTH maps is a mistake and is rejected by
 * `contextResolver.test.tsx`; the shell would otherwise have two answers.
 */
export const CONTEXT_TABS: Record<string, ContextTabGroup> = {
  // P5d. Field Inventory is the one step whose panes genuinely share state: the
  // upload, the summary and the results are three views of a single record, and
  // `FieldInventoryTab` held 20 useState hooks. So the provider is not optional
  // here — without it, switching panes would refetch and lose the multiplier
  // edits and the half-chosen file.
  fieldinventory: {
    // A provider, not a bare wrapper: the group slot only guarantees *where*
    // state can live, and this is what actually holds it.
    // `onStepDataChanged` MUST be forwarded: processing the inventory is what makes this step complete, and the provider calls
    // it so the shell re-reads readiness and unlocks the Results tab. Dropping it (as this wrapper once did) left the tab locked
    // until a manual reload.
    provider: ({ calculationId, onStepDataChanged, children }) => (
      <FieldInventoryDataProvider calculationId={calculationId} onStepDataChanged={onStepDataChanged}>
        {children}
      </FieldInventoryDataProvider>
    ),
    panes: {
      data: {
        id: 'data',
        labelKey: 'workflow.tab.uploadData',
        render: (p) => <FieldInventoryTab calculationId={p.calculationId} view="data" />,
      },
      results: {
        id: 'results',
        labelKey: 'workflow.tab.results',
        render: (p) => <FieldInventoryTab calculationId={p.calculationId} view="results" />,
      },
    },
  },

  // Plan 8.4 — "Biodiversity, Tree Inventory: Results tab added (D4)". D4 is
  // that the results are the *same* data in a second state, so each pane is the
  // same component with a different `view`. The host mounts one pane at a time,
  // so there is never a second copy of the data in flight.
  //
  // Results carries `needsStepData`, so it stays disabled until the step reports
  // data of its own. That is the one honest lock in the app: a Results tab with
  // nothing behind it is a dead end, and the step is still fully reachable via
  // the pane that does the entering.
  treemapping: {
    panes: {
      data: {
        id: 'data',
        labelKey: 'workflow.tab.data',
        render: (p) => <TreeMappingTab calculationId={p.calculationId} view="data" onChanged={() => p.onStepDataChanged?.()} />,
      },
      results: {
        id: 'results',
        labelKey: 'workflow.tab.results',
        render: (p) => <TreeMappingTab calculationId={p.calculationId} view="results" onChanged={() => p.onStepDataChanged?.()} />,
      },
    },
  },
  biodiversity: {
    panes: {
      data: {
        id: 'data',
        labelKey: 'workflow.tab.data',
        render: (p) => <BiodiversityTab calculationId={p.calculationId} view="data" onStepDataChanged={p.onStepDataChanged} />,
      },
      results: {
        id: 'results',
        labelKey: 'workflow.tab.results',
        render: (p) => <BiodiversityTab calculationId={p.calculationId} view="results" onStepDataChanged={p.onStepDataChanged} />,
      },
    },
  },
};

/**
 * Every context id the shell can render, and the node it renders.
 *
 * Keys are context ids alone, not `group/context`. Ids are globally unique
 * across the four groups today and stay unique under the P2b grouping, which
 * `contextResolver.test.ts` asserts — if a future group reuses an id, the test
 * fails rather than one entry silently shadowing another.
 */
export const CONTEXT_COMPONENTS: Record<string, ContextRenderer> = {
  ...Object.fromEntries(
    Object.entries(WORKSPACE_CONTEXTS).map(([id, workspaceContext]) => [
      id,
      workspaceRenderer(workspaceContext),
    ]),
  ),

  // --- forest-data ---
  analysis: ({ calculationId, calculation }) => (
    <AnalysisTab calculationId={calculationId} calculation={calculation} />
  ),
  areadetail: ({ calculationId, calculation }) => (
    <SubAreaTablesTab calculationId={calculationId} calculation={calculation} />
  ),

  // --- sampling-model (all four contexts now live in `field`) ---
  sampling: ({ calculationId }) => <SamplingTab calculationId={calculationId} />,
  treemodel: ({ calculationId, calculation }) => (
    <TreeModelPanel calculationId={calculationId} calculation={calculation} />
  ),
  fieldbook: ({ calculationId }) => <FieldbookTab calculationId={calculationId} />,

  // --- field inventory / biodiversity / tree inventory ---
  // `fieldinventory` is deliberately absent: it is a tabbed group in
  // CONTEXT_TABS, and it needs its provider, which the flat map has nowhere to
  // put. `renderContext` prefers the tabbed map, and a test asserts the two
  // never overlap.

  // Forest Metadata is its own step (owner, 2026-10-11); it used to be a pane of the field-inventory step. It reads the forest metadata
  // record, not the field inventory, so it needs no provider and sits in the flat map.
  forestmetadata: ({ calculationId }) => <ForestMetadataPanel calculationId={calculationId} />,

  // --- data collection / user group ---
  usergroup: ({ calculationId, calculation }) => (
    <UserGroupMapTab
      calculationId={calculationId}
      forestBoundary={calculation?.geometry}
      forestName={calculation?.forest_name || undefined}
    />
  ),

  // --- analysis ---
  // `DetailedDescriptionTab` declares only `{ calculation, fieldInventoryBreakdown?,
  // biodiversityData? }`. The old container spread `{...props}` into it, handing it
  // permissions and structureLocked at runtime which it ignored; a spread is not
  // excess-property checked, so that type-checked while doing nothing.
  detaildescription: ({ calculation }) => <DetailedDescriptionTab calculation={calculation} />,
  hazarderosion: ({ calculationId }) => <HazardErosionTab calculationId={calculationId} />,
  // Advanced (owner, 2026-10-22): the optional NTFP inventory page.
  ntfp: ({ calculationId, calculation }) => <NtfpInventoryTab calculationId={calculationId} calculation={calculation} />,
  sustainablefm: ({ calculationId }) => <SustainableFmTab calculationId={calculationId} />,
  cba: ({ calculationId }) => <CBATab calculationId={calculationId} />,

  // --- plan ---
  yearly: ({ calculationId }) => <YearlyStepPage calculationId={calculationId} />,
  mgmtplan: ({ calculationId }) => <OperationalPlanPage calculationId={calculationId} />,
  issuesubmit: ({ calculationId }) => <IssueSubmitPage calculationId={calculationId} />,
};

/**
 * Every context id the resolver can render, from either map, sorted.
 *
 * The union, not `Object.keys(CONTEXT_COMPONENTS)`: a tabbed context resolves
 * just as much as a flat one, and callers use this to assert the resolver is
 * total over the registry. Reading only the flat map would have quietly shrunk
 * this by one when `mgmtplan` became tabbed.
 */
export const RESOLVED_CONTEXT_IDS: readonly string[] = [
  ...new Set([...Object.keys(CONTEXT_COMPONENTS), ...Object.keys(CONTEXT_TABS)]),
].sort();

/**
 * Render one context. Returns `null` for an id with no entry.
 *
 * `null` rather than a throw or a fallback. Note what has changed since P2a:
 * `resolveSurface` (`lib/calcSurface.ts`) is now fail-closed, so an id that
 * reaches here unrecognised is one the *allowlist* deliberately preserved, and
 * every id the registry removed is rewritten to its replacement before it gets
 * this far. The removed contexts — `subareas`, `compartments`, `maps`,
 * `totalinventory`, `reports`, `yearlyactivities` — have no entry here at all
 * and are therefore unreachable by any URL.
 */
/**
 * Bridges the registry's tab spec to the host, resolving the step's own label for
 * the tab bar's accessible name.
 *
 * A component rather than inline JSX in `renderContext`, because that is a plain
 * function called during the shell's render — `useT` is a hook and cannot run
 * there.
 */
const TabbedContext: React.FC<{
  item: NonNullable<ReturnType<typeof findContext>>['item'];
  group: ContextTabGroup;
  panelProps: ContextPanelProps;
  /** The step's own server-side readiness, for `needsStepData` panes. */
  stepDone?: boolean;
}> = ({ item, group, panelProps, stepDone }) => {
  const t = useT();
  const host = (
    <ContextTabHost
      {...panelProps}
      tabs={item.tabs ?? []}
      panes={group.panes}
      label={t(item.labelKey)}
      stepDone={stepDone}
    />
  );
  // The provider wraps the host, not the other way round, so its state sits
  // above the pane switch. A provider inside the host would be unmounted with
  // the pane it was meant to outlive.
  //
  // It gets `calculationId` and not the whole of `panelProps`: Field Inventory is
  // the only provider so far, and it loads by calculation id. Passing the id
  // explicitly means a provider that forgets to thread it fails loudly at the
  // type level rather than rendering an empty panel, which is what happened
  // when this was `<Provider>{host}</Provider>`.
  const Provider = group.provider;
  return Provider ? (
    <Provider
      calculationId={panelProps.calculationId}
      onStepDataChanged={panelProps.onStepDataChanged}
    >
      {host}
    </Provider>
  ) : (
    host
  );
};

export function renderContext(
  contextId: string,
  props: ContextPanelProps,
  stepDone?: boolean,
): React.ReactElement | null {
  // A tabbed context wins over the flat map, and the two are asserted mutually
  // exclusive — this ordering is a safety net, not a policy.
  const group = CONTEXT_TABS[contextId];
  if (group) {
    const item = findContext(contextId)?.item;
    // The registry owns the tab order and the labels; the resolver owns the
    // bodies. No `tabs` in the registry means nothing to render a bar for.
    if (item?.tabs?.length) {
      return <TabbedContext item={item} group={group} panelProps={props} stepDone={stepDone} />;
    }
  }
  const renderer = CONTEXT_COMPONENTS[contextId];
  if (!renderer) return null;
  try {
    return renderer(props);
  } catch {
    // A render-time throw in a lazy leaf must not take the shell down; the
    // surrounding TabErrorBoundary is the real guard, this only stops a
    // synchronous failure while building the element.
    return null;
  }
}
