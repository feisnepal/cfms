/**
 * CalculationDetailTabbed — NEW tabbedrock-20230531\v * Tabbed container for calculation detail page (Phase 4, extended Phase 12+).
 * Route: `/calculations/:id/tabbed` with query params:
 *   - `?surface=<group>/<context>` (canonical)
 *   - `?tab=&context=` (legacy pair, still read for old bookmarks)
 *
 * Groups are the phases of the work (WORKSPACE_FLOW_NAV_PLAN §4), and each
 * group's contexts resolve through `components/calculation/contextComponents.tsx`
 * — the four per-group container components were dissolved in P2a, because the
 * target grouping splits three of the four old groups.
 *
 * Legacy group ids (`forest-data`, `sampling-model`, `data-maps`,
 * `reports-outputs`) still resolve, through `LEGACY_SURFACE_ALIASES` in
 * `lib/calcSurface.ts` — in both the `?surface=` and the `?tab=&context=` form.
 *
 * Phase 3 wiring: usePermissionGate, useTabChangeInterceptor +
 * shouldAllowTabChange, useTabFocusManagement, useTabKeyboardShortcuts,
 * CalculationHeader, NetworkStatusBanner, TabErrorBoundary.
 *
 * Tier 2 W1e: navigation is the single merged `ActivityRail` (group tablist +
 * nested contexts) — the old horizontal `CalculationTabs` bar and the four
 * per-group `GroupSubNav` rails are gone.
 *
 * CRITICAL: CSS `display` toggle (not conditional render) so the map stays
 * mounted and zoom/pan/draft survive tab switches.
 */
import React, { Suspense, useCallback, useEffect, useMemo, useState, Profiler } from 'react';
import { useT } from '../i18n/hooks';
import { Navigate, useParams, useSearchParams, useLocation, useNavigate } from 'react-router-dom';
import { Modal } from 'antd';

import { useCalculationContext, NetworkStatusBanner } from '../hooks/useCalculationContext';
import { usePermissionGate } from '../hooks/usePermissionGate';
import { useTabSwitchTiming } from '../hooks/usePerformance';
import { onRenderCallback, shouldTrackRenders } from '../lib/performance';
import type { FrontendRole } from '../lib/roleMapping';
import {
  useTabChangeInterceptor,
  shouldAllowTabChange,
} from '../hooks/useTabChangeInterceptor';
import { useTabFocusManagement, useTabKeyboardShortcuts } from '../hooks/useFocusManagement';
import { useAuth } from '../contexts/AuthContext';
import { useWorkspaceStore } from '../store/workspaceStore';
import {
  TABS,
  tabRequiresEdit,
  resolveActiveTab,
  computeDisabledTabs,
  type TabId,
} from './calculationTabConfig';
import { CalculationHeader } from '../components/CalculationHeader';
import { StructureStaleBanner } from '../components/calculation/StructureStaleBanner';
import { TemplateStoreBanner } from '../components/calculation/TemplateStoreBanner';
import { TabErrorBoundary } from '../components/TabErrorBoundary';
import { ShortcutsHelpModal } from '../components/ShortcutsHelpModal';
import { CalcCommandPalette } from '../components/calculation/CalcCommandPalette';
import { ReanalyzeModal } from '../components/calculation/ReanalyzeModal';
import { isMapContext } from '../components/calculation/calcContexts';
import { ActivityRail } from '../components/calculation/ActivityRail';
import { toSurfaceId, resolveSurface, surfaceFromLegacyParams } from '../lib/calcSurface';
import { parseFeatureParam, toFeatureParam } from '../lib/dockSurface';
import { useCalcChromeStore } from '../store/calcChromeStore';
import { ChevronDown } from 'lucide-react';

// Context -> component resolution. The four per-group container components were
// dissolved in WORKSPACE_FLOW_NAV_PLAN P2a: the target grouping splits 3 of the
// 4 old groups, so a group-keyed container can no longer decide what renders.
import { renderContext } from '../components/calculation/contextComponents';
import PanelSkeleton, { GROUP_SKELETON_LABEL } from '../components/calculation/PanelSkeleton';
import WorkflowStepper from '../components/calculation/WorkflowStepper';
import { useWorkflowReadiness } from '../hooks/useWorkflowReadiness';
import { useExportReady } from '../hooks/useExportReady';
import { onDataImported } from '../lib/uploadEvents';

const TABS_CONST = TABS as readonly TabId[];

/**
 * The layout class each group's panel wrapper carries, transcribed from the four
 * dissolved containers. Load-bearing, not decorative — see the comment at
 * `panelFor` and `index.css:3167`.
 */
/**
 * The layout class each group's panel wrapper carries.
 *
 * Renamed to match the new groups. These classes are load-bearing, not
 * decorative — see `index.css` and the note at `panelFor`: they carry the
 * Leaflet map's height chain, and the map is a descendant.
 */
const GROUP_PANEL_CLASS: Record<TabId, string> = {
  base: 'panel-base',
  field: 'panel-field',
  analysis: 'panel-analysis',
  plan: 'panel-plan',
};

/**
 * Default context per group — the first spine step in that phase, so landing on
 * a bare `?surface=<group>` puts the user at the start of that phase's work.
 */
const getDefaultContext = (tab: TabId): string => {
  switch (tab) {
    case 'base':
      return 'unified';
    case 'field':
      return 'fieldbook';
    case 'analysis':
      return 'detaildescription';
    // Not the first step of the phase: all four panels stay mounted (hidden), so a default of `yearly` would load the whole yearly
    // planner in the background of every forest. The Operational Plan page was this panel's default before step 13 existed.
    case 'plan':
      return 'mgmtplan';
  }
};

export const CalculationDetailTabbed: React.FC = () => {
  const t = useT();
  const { id } = useParams<{ id: string }>();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const { user } = useAuth();
  const dirty = useWorkspaceStore((s) => s.dirty);

  const { calculation, permissions, mapLifecycleStatus, structureLocked, isLoading, error, refetchMeta } =
    useCalculationContext(id);

  const { can, isLocked } = usePermissionGate({
    backendRole: user?.role ?? 'user',
    frontendRoles: permissions as FrontendRole[],
    mapLifecycleStatus,
    structureLocked,
  });

  // Per-step completion + staleness for the strip, the step badges and the
  // stepper. Reports only — no surface here blocks on it, and a failed read
  // leaves the workspace fully usable.
  const readiness = useWorkflowReadiness(id);
  const navigate = useNavigate();
  const exportReady = useExportReady(id, readiness.readiness);
  // "Add data" imports from outside the tab that owns the data: re-read the step status so what it completed (Results ...) unlocks.
  useEffect(() => onDataImported(() => readiness.refresh()), [readiness.refresh]);

  // Navigation is synced to the URL with history.replace.
  // `?surface=<group>/<context>` is the canonical param. `?tab=&context=` is
  // still read (old bookmarks, redirect wrappers) and is *composed* into the
  // same `group/context` string, so both shapes run through one resolver
  // (plan §6.1). `resolveSurface` never returns an unrenderable surface: an
  // unknown group/context falls back to the Map and is logged, rather than
  // rendering a blank panel as the old unvalidated parse did.
  const requestedSurface =
    searchParams.get('surface') ??
    surfaceFromLegacyParams(searchParams.get('tab'), searchParams.get('context'));
  const { tab: activeTab, ctx: contextParam } = resolveSurface(requestedSurface, (bad) => {
    if (import.meta.env.DEV) {
      console.warn(`[calcSurface] unrecognised surface "${bad}" — falling back to the Map`);
    }
  });

  // W1f: `?surface=` and `?feature=` are two independent params on the same
  // URL — write one, and the other (if present) must survive untouched.
  // `setSearchParams({...})` REPLACES the whole query string, so every write
  // goes through this merge instead of a raw call.
  const setUrlParams = useCallback(
    (patch: { surface?: string; feature?: string | null }, replace = true) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        if (patch.surface !== undefined) next.set('surface', patch.surface);
        if ('feature' in patch) {
          if (patch.feature) next.set('feature', patch.feature);
          else next.delete('feature');
        }
        return next;
      }, { replace });
    },
    [setSearchParams],
  );

  /** Write a (group, context) to the URL as the canonical `?surface=`. */
  const writeNav = useCallback(
    (tab: TabId, ctx: string, replace = true) => {
      setUrlParams({ surface: toSurfaceId(tab, ctx) }, replace);
    },
    [setUrlParams],
  );

  // Canonicalise the URL to `?surface=<resolved>`. The resolved surface is
  // authoritative, so a legacy alias (`forest-data/unified`) and a failed lookup
  // (garbage) are both rewritten to what actually rendered — otherwise the
  // address bar keeps showing a surface the app is no longer on, and the next
  // bookmark records the stale id.
  //
  // Deliberately declarative and idempotent rather than one-shot behind a ref:
  // sibling effects (e.g. the `?feature=` sync below) re-commit the query string
  // they were rendered with, so a one-shot write can be clobbered back to the
  // alias. Re-asserting whenever the URL drifts converges on the resolved id
  // instead of leaving a writer race to decide the final address bar.
  useEffect(() => {
    const resolved = toSurfaceId(activeTab, contextParam);
    if (searchParams.get('surface') !== resolved) {
      setUrlParams({ surface: resolved }, true);
    }
  }, [activeTab, contextParam, searchParams, setUrlParams]);

  // W1f — `?feature=<layerId>:<featureId>` deep-links the one selected
  // feature (workspaceStore.selection), independent of which group/context is
  // active. Seed the store from an incoming link exactly once per mount...
  const selectionLayerId = useWorkspaceStore((s) => s.selection.layerId);
  const selectionFeatureIds = useWorkspaceStore((s) => s.selection.featureIds);
  const selectFeatures = useWorkspaceStore((s) => s.selectFeatures);
  const featureSeeded = React.useRef(false);
  useEffect(() => {
    if (featureSeeded.current) return;
    featureSeeded.current = true;
    const ref = parseFeatureParam(searchParams.get('feature'));
    if (ref) selectFeatures(ref.layerId, [ref.featureId], 'replace');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ...then keep the URL in sync with the store from then on. Only a single
  // selected feature is deep-linkable (a dock panel, once one exists, shows
  // one feature at a time); 0 or many clears the param.
  const featureParam = useMemo(
    () => (selectionLayerId && selectionFeatureIds.length === 1
      ? toFeatureParam({ layerId: selectionLayerId, featureId: selectionFeatureIds[0] })
      : null),
    [selectionLayerId, selectionFeatureIds],
  );
  useEffect(() => {
    // Only write when the URL is actually out of step. `setUrlParams` re-commits
    // the whole query string it was rendered with, so an unconditional write on
    // every mount re-applies a stale `surface` and undoes canonicalisation.
    // Compare null-to-null: `get()` yields null when absent, not ''.
    const current = searchParams.get('feature');
    const desired = featureParam ?? null;
    if (current === desired) return;
    setUrlParams({ feature: featureParam });
  }, [featureParam, searchParams, setUrlParams]);

  // Per-tab context memory so the shared ?context= URL param never leaks a
  // foreign tab's default into hidden tabs (which would unmount WorkspaceTab /
  // destroy the Leaflet map). Each tab keeps its own last-known context.
  const [tabContexts, setTabContexts] = useState<Partial<Record<TabId, string>>>({});

  // Remember the active tab's context (incl. from deep links) so it survives
  // tab switches even when the URL ?context= is dropped.
  useEffect(() => {
    if (!tabContexts[activeTab] || tabContexts[activeTab] !== contextParam) {
      setTabContexts((prev) => ({ ...prev, [activeTab]: contextParam }));
    }
  }, [activeTab, contextParam]);

  const chromeCollapsed = useCalcChromeStore((s) => s.headerCollapsed);
  const toggleChrome = useCalcChromeStore((s) => s.toggleHeader);

// Context handed to a tab: hidden tabs use their own stored context (never the
// active tab's), the active tab gets the URL-driven one.
  const contextForTab = useCallback(
    (tab: TabId): string => {
      if (tab === activeTab) return contextParam || tabContexts[tab] || getDefaultContext(tab);
      return tabContexts[tab] || getDefaultContext(tab);
    },
    [activeTab, contextParam],
  );

  const setActiveTab = useCallback(
    (tab: TabId) => {
      writeNav(tab, tabContexts[tab] ?? getDefaultContext(tab));
    },
    [writeNav, tabContexts],
  );

  // Unsaved-changes confirmation state (in-page tab switch ONLY).
  const [pendingTab, setPendingTab] = useState<TabId | null>(null);
  const [pendingContext, setPendingContext] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [reanalyzeOpen, setReanalyzeOpen] = useState(false);

  const handleTabChange = useCallback(
    (tab: TabId) => {
      if (shouldAllowTabChange(dirty)) {
        setActiveTab(tab);
      } else {
        setPendingTab(tab);
        setPendingContext(null);
        setConfirmOpen(true);
      }
    },
    [dirty, setActiveTab],
  );

  // A6 command palette: jump straight to a group + context. Same-group jumps
  // skip the guard (like a context switch); cross-group jumps honour it.
  const navigateToSurface = useCallback(
    (tab: TabId, ctx: string) => {
      const apply = () => {
        setTabContexts((prev) => ({ ...prev, [tab]: ctx }));
        writeNav(tab, ctx);
      };
      if (tab === activeTab || shouldAllowTabChange(dirty)) {
        apply();
      } else {
        setPendingTab(tab);
        setPendingContext(ctx);
        setConfirmOpen(true);
      }
    },
    [activeTab, dirty, writeNav],
  );

  const confirmSwitch = useCallback(() => {
    setConfirmOpen(false);
    if (pendingTab) {
      if (pendingContext) {
        setTabContexts((prev) => ({ ...prev, [pendingTab]: pendingContext }));
        writeNav(pendingTab, pendingContext);
      } else {
        setActiveTab(pendingTab);
      }
    }
    setPendingTab(null);
    setPendingContext(null);
  }, [pendingTab, pendingContext, setActiveTab, writeNav]);

  const cancelSwitch = useCallback(() => {
    setConfirmOpen(false);
    setPendingTab(null);
    setPendingContext(null);
  }, []);

  // Route-level navigation guard (browser back/forward leaving the page).
  useTabChangeInterceptor({
    hasUnsavedChanges: dirty,
    onConfirm: () => setConfirmOpen(true),
  });

  // Focus + keyboard shortcuts on the panel.
  const panelRef = useTabFocusManagement(activeTab);
  useTabKeyboardShortcuts([...TABS_CONST], activeTab, handleTabChange, true);

  // Phase 8 — measure tab switch duration (Sentry breadcrumb/message + GA4).
  useTabSwitchTiming(activeTab);

  // Shell-level focus toggle: `F` hides all chrome (body.focus-mode) from any
  // tab, not only from inside WorkspaceHeader. Guarded so it never fires while
  // typing or with a modifier held.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'f' && e.key !== 'F') return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      if ((e.target as HTMLElement | null)?.isContentEditable) return;
      useWorkspaceStore.getState().toggleFocusMode();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const renderProfiler = shouldTrackRenders();

  // Disabled groups: edit-required groups while locked + no edit capability.
  // A *role* gate, distinct from the `needs` flags in `calcContexts`, which are
  // advisory and never lock anything.
  const disabledKeys = useMemo(
    () => computeDisabledTabs(tabRequiresEdit(), can.isTabDisabled),
    [can.isTabDisabled],
  );

  if (isLoading) {
    return (
      <div className="calculation-detail calculation-detail--loading" role="status" aria-live="polite">
        <div className="skeleton skeleton--header" />
        <div className="skeleton skeleton--tabs" />
        <div className="skeleton skeleton--content" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="calculation-detail calculation-detail--error" role="alert">
        <h2>{t('calc.detail.loadFailed')}</h2>
        <p>{error.message}</p>
        {/* eslint-disable-next-line no-alert */}
        <button onClick={() => window.location.reload()}>{t('common.retry')}</button>
      </div>
    );
  }

  if (!calculation) {
    return (
      <div className="calculation-detail calculation-detail--empty" role="alert">
        <h2>{t('calc.detail.notFound')}</h2>
        <p>{t('calc.detail.notFoundHint')}</p>
      </div>
    );
  }

  const forestName = calculation?.forest_name || calculation?.block_name || undefined;

  // The four tab panels. CSS `display` toggle (not conditional render) keeps the
  // Leaflet map mounted across tab switches — a conditional render destroys it.
  //
  // P2a: each panel asks `renderContext` which component its context maps to,
  // instead of a per-group container doing its own `===` switch. The group is
  // now only a heading in the rail — the context id decides what renders.
  //
  // The wrapper markup the containers used to provide is reproduced here, and
  // it is NOT cosmetic: `index.css:3167-3176` gives these classes
  // `height:100%; width:100%; display:flex; flex-direction:column`, and
  // `:3566-3574` makes them 100vh/100vw in focus mode. The Leaflet map is a
  // descendant, so dropping the wrapper breaks the map's height chain. The
  // four `data-testid`s stay too — 26 e2e assertions select on them.
  const panelFor = (tab: TabId) => (
    <div style={{ display: activeTab === tab ? 'block' : 'none' }} data-testid={`tab-${tab}`}>
      <TabErrorBoundary tab={tab} calculationId={id}>
        <Suspense fallback={<PanelSkeleton label={t(GROUP_SKELETON_LABEL[tab])} />}>
          <div className={`${GROUP_PANEL_CLASS[tab]} min-h-full`}>
            <div className="flex-1 min-w-0">
              {renderContext(
                contextForTab(tab),
                {
                  calculationId: id!,
                  calculation,
                  permissions,
                  structureLocked,
                  mapLifecycleStatus,
                  // Readiness is read once on mount, so a step completed in this
                  // session would keep its `needsStepData` panes locked until a
                  // manual reload — upload a field inventory and its own Results
                  // tab is the one thing that will not open.
                  onStepDataChanged: readiness.refresh,
                },
                // The step's own server-side readiness, so a `needsStepData` pane
                // (Field Inventory's Results) locks off exactly the same signal
                // the rail and the stepper tick off. Omitting it would leave
                // those panes permanently unlocked.
                readiness.isDone(contextForTab(tab)),
              )}
            </div>
          </div>
        </Suspense>
      </TabErrorBoundary>
    </div>
  );

  const panels = (
    <div
      ref={panelRef}
      className="tab-panels"
      role="tabpanel"
      aria-labelledby={`tab-${activeTab}`}
      tabIndex={-1}
    >
      {/* CRITICAL: CSS display toggle, NOT conditional render */}
      {TABS_CONST.map(panelFor)}
    </div>
  );

  const page = (
    <div className="calculation-detail">
      <NetworkStatusBanner isError={!!error} />

      {chromeCollapsed ? (
        <button
          type="button"
          className="calc-chrome-strip"
          onClick={toggleChrome}
          aria-label={t('calc.chrome.expand')}
          title={t('calc.chrome.expand')}
        >
          <ChevronDown size={14} aria-hidden="true" />
          <span>{forestName || t('calc.untitledCalculation')}</span>
        </button>
      ) : (
        <CalculationHeader
          calculation={calculation}
          can={can}
          isLocked={isLocked}
          lifecycleStatus={mapLifecycleStatus}
          onReanalyze={() => setReanalyzeOpen(true)}
          onShowShortcuts={() => setHelpOpen(true)}
          onToggleChrome={toggleChrome}
          // On a map surface WorkspaceHeader already shows the name + status —
          // don't stack a second identity line above it.
          titleHidden={isMapContext(contextParam)}
        />
      )}

      <StructureStaleBanner
        resultData={calculation?.result_data as Record<string, unknown> | null | undefined}
        calculationId={id}
      />

      <TemplateStoreBanner calculationId={id} ready={exportReady} loading={readiness.loading} />

      <div className="calc-body">
        <ActivityRail
          activeTab={activeTab}
          activeContext={contextParam}
          onSelectGroup={handleTabChange}
          onNavigate={navigateToSurface}
          disabledTabs={disabledKeys}
          isDone={readiness.isDone}
          stale={readiness.stale}
          doneCount={readiness.doneCount}
          totalCount={readiness.totalCount}
          loading={readiness.loading}
          onOpenStore={() => navigate(`/templates?calculation_id=${id}`)}
          storeReady={exportReady}
        />
        {/* The stepper is chrome above the panels, not a container swap: the
            panels stay mounted and display-toggled so the Leaflet map survives a
            step change. It drives WHICH step is active; the panels follow. */}
        <div className="flex-1 min-w-0 flex flex-col">
          <WorkflowStepper
            activeContext={contextParam}
            onNavigate={navigateToSurface}
            isDone={readiness.isDone}
            stale={readiness.stale}
            loading={readiness.loading}
          />
          {panels}
        </div>
      </div>

      <Modal
        open={confirmOpen}
        title={t('calc.detail.unsavedTitle')}
        onOk={confirmSwitch}
        onCancel={cancelSwitch}
        okText={t('calc.detail.discardLeave')}
        cancelText={t('calc.detail.stay')}
      >
        <p>
          {t('calc.detail.unsavedBody')}
        </p>
      </Modal>

      <ShortcutsHelpModal open={helpOpen} onClose={() => setHelpOpen(false)} />
      <CalcCommandPalette onNavigate={navigateToSurface} />
      {id && (
        <ReanalyzeModal
          open={reanalyzeOpen}
          calculationId={id}
          onClose={() => setReanalyzeOpen(false)}
          onDone={refetchMeta}
        />
      )}
    </div>
  );

  return renderProfiler ? (
    <Profiler id="CalculationDetailTabbed" onRender={onRenderCallback}>
      {page}
    </Profiler>
  ) : (
    page
  );
};

export default CalculationDetailTabbed;