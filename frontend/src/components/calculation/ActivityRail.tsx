/**
 * ActivityRail — the tabbed calc shell's navigation surface.
 *
 * WORKSPACE_FLOW_NAV_PLAN §8.2. The four groups are the **phases of the work**
 * and the contexts under them are **numbered steps**, so the rail reads as a field
 * checklist rather than a list of topics. Each step carries a type badge
 * (Input / Run / View / Trial) and, where applicable, a flag.
 *
 * A vertical **tablist**: each group header is a real `role="tab"` that selects
 * the group (URL `?surface=` syncs via the shell); the active group's steps list
 * under it; a non-active group can be *peeked* (chevron) without navigating.
 * Reuses `calcRailStore` for the shared collapse state + width + drag-resize.
 *
 * Two modes, toggled by the header button: `expanded` shows icon + label and
 * `compact` shows icon only. Collapsing and restoring are always symmetric —
 * there is no third "hidden" state to get trapped in.
 *
 * The readiness strip at the top and the flag chips on each step **report**.
 * Nothing here disables a step for an unmet prerequisite: `disabledTabs` carries
 * only the *role* gate (a read-only user cannot write), and conflating that with
 * workflow progress is how a "sequence, don't enforce" rule turns into a lock.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ChevronDown,
  ChevronRight,
  PanelLeftClose,
  PanelLeftOpen,
  Grid3x3,
  TreePine,
  Database,
  FileText,
  Check,
  AlertTriangle,
  type LucideIcon,
} from 'lucide-react';
import { useT } from '../../i18n/hooks';
import { TABS, TAB_CONFIG, type TabId } from '../../pages/calculationTabConfig';
import { GROUP_CONTEXTS } from './calcContexts';
import { OFF_SPINE, TYPE_BADGE } from './workflowSteps';
import { RAIL_WIDTH, useCalcRailStore } from '../../store/calcRailStore';
import type { StaleFlag } from '../../hooks/useWorkflowReadiness';

const GROUP_ICON: Record<TabId, LucideIcon> = {
  base: Grid3x3,
  field: TreePine,
  analysis: Database,
  plan: FileText,
};

interface ActivityRailProps {
  activeTab: TabId;
  activeContext: string;
  /** select a group — same contract as the old tab bar's onChange */
  onSelectGroup: (tab: TabId) => void;
  /** group + context in one call; runs the shell's unsaved-changes guard */
  onNavigate: (tab: TabId, ctx: string) => void;
  /** role gate only (edit-required groups while locked) — never workflow state */
  disabledTabs?: readonly string[];
  /** completion per context id, from the server */
  isDone?: (id: string) => boolean;
  stale?: readonly StaleFlag[];
  doneCount?: number;
  totalCount?: number;
  loading?: boolean;
  /** open the Template Store for this forest (always offered; highlighted once every required step is done) */
  onOpenStore?: () => void;
  /** the export gate says this forest can be exported: the store button turns into a call to action */
  storeReady?: boolean;
}

export function ActivityRail({
  activeTab,
  activeContext,
  onSelectGroup,
  onNavigate,
  disabledTabs = [],
  isDone = () => false,
  stale = [],
  doneCount = 0,
  totalCount = 0,
  loading = false,
  onOpenStore,
  storeReady = false,
}: ActivityRailProps) {
  const t = useT();
  const mode = useCalcRailStore((s) => s.mode);
  const width = useCalcRailStore((s) => s.width);
  const toggleMode = useCalcRailStore((s) => s.toggleMode);
  const setWidth = useCalcRailStore((s) => s.setWidth);

  const compact = mode === 'compact';
  const [showOptional, setShowOptional] = useState(false);

  /** Non-active groups the user has expanded to *peek* at (no navigation). */
  const [peek, setPeek] = useState<Partial<Record<TabId, boolean>>>({});
  useEffect(() => {
    // a group stops being "peeked" once it becomes active (its contexts show anyway)
    setPeek((p) => (p[activeTab] ? { ...p, [activeTab]: false } : p));
  }, [activeTab]);
  const contextsShown = (g: TabId) => g === activeTab || !!peek[g];

  const staleSteps = new Set(stale.map((s) => s.step));

  // Drag-resize handle.
  const drag = useRef<{ x: number; w: number } | null>(null);
  const onMove = useCallback(
    (e: PointerEvent) => {
      if (drag.current) setWidth(drag.current.w + (e.clientX - drag.current.x));
    },
    [setWidth],
  );
  const endDrag = useCallback(() => {
    drag.current = null;
    window.removeEventListener('pointermove', onMove);
    window.removeEventListener('pointerup', endDrag);
    document.body.style.removeProperty('cursor');
    document.body.style.removeProperty('user-select');
  }, [onMove]);
  const startDrag = useCallback(
    (e: React.PointerEvent) => {
      e.preventDefault();
      drag.current = { x: e.clientX, w: width };
      window.addEventListener('pointermove', onMove);
      window.addEventListener('pointerup', endDrag);
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
    },
    [width, onMove, endDrag],
  );
  useEffect(() => endDrag, [endDrag]);

  return (
    <nav
      className="calc-activity-rail flex-shrink-0 h-full border-r border-gray-200 bg-gray-50/60 flex flex-col relative"
      style={{ width: compact ? RAIL_WIDTH.COMPACT : width }}
      aria-label={t('calc.subnav.label')}
      data-testid="workflow-rail"
    >
      <div className={`flex ${compact ? 'flex-col items-center' : 'justify-end'} gap-0.5 px-1 py-1`}>
        <button
          type="button"
          onClick={toggleMode}
          className="p-1 text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded"
          aria-label={compact ? t('calc.subnav.show') : t('calc.subnav.collapse')}
          title={compact ? t('calc.subnav.show') : t('calc.subnav.collapse')}
        >
          {compact ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
        </button>
      </div>

      {/* Readiness strip. Reports progress; it never gates anything. Hidden in
          compact mode, where there is no room for a sentence. */}
      {!compact && (
        <div className="px-2.5 py-2 border-b border-gray-200" data-testid="workflow-readiness">
          {loading ? (
            <span className="text-[11px] text-gray-400">{t('workflow.strip.checking')}</span>
          ) : totalCount > 0 ? (
            <>
              <div className="text-[11px] text-gray-600">
                {t('workflow.strip.progress', { done: doneCount, total: totalCount })}
              </div>
              <div className="mt-1 h-1 rounded-full bg-gray-200 overflow-hidden">
                <div
                  className="h-full bg-green-500 transition-all"
                  style={{ width: `${totalCount ? (doneCount / totalCount) * 100 : 0}%` }}
                />
              </div>
            </>
          ) : null}
          {onOpenStore && (
            <button
              type="button"
              onClick={onOpenStore}
              data-testid="rail-template-store"
              className={`mt-2 w-full flex items-center gap-1.5 rounded px-2 py-1 text-left text-[11px] font-medium ${
                storeReady
                  ? 'bg-green-600 text-white hover:bg-green-700'
                  : 'border border-gray-300 text-gray-600 hover:bg-gray-100'
              }`}
            >
              <FileText size={12} />
              <span className="flex-1 truncate">
                {storeReady
                  ? t('workflow.store.railReady')
                  : t('workflow.store.rail')}
              </span>
            </button>
          )}
        </div>
      )}

      <div className="flex-1 min-h-0 flex flex-col overflow-y-auto" role="tablist" aria-orientation="vertical">
        {TABS.map((group, groupIndex) => {
          const GroupIcon = GROUP_ICON[group];
          const groupLabel = t(TAB_CONFIG[group].labelKey);
          const disabled = disabledTabs.includes(group);
          const isActiveGroup = group === activeTab;
          const showContexts = contextsShown(group);
          return (
            <section
              key={group}
              className={groupIndex > 0 ? 'border-t border-gray-200' : ''}
            >
              {/* ── GROUP HEADER: uppercase, tracked, muted; green + accent bar when active ── */}
              <div
                className={`flex items-stretch ${
                  isActiveGroup ? 'bg-green-50 border-l-4 border-green-600' : 'border-l-4 border-transparent'
                }`}
              >
                <button
                  type="button"
                  role="tab"
                  aria-selected={isActiveGroup}
                  disabled={disabled}
                  onClick={() => onSelectGroup(group)}
                  aria-label={compact ? groupLabel : undefined}
                  title={compact ? groupLabel : undefined}
                  className={`flex-1 flex items-center font-semibold uppercase tracking-wide transition-colors disabled:opacity-40 ${
                    compact
                      ? 'justify-center px-0 py-2.5'
                      : 'gap-2 px-2.5 py-2 text-left text-[11px]'
                  } ${
                    isActiveGroup
                      ? 'text-green-800'
                      : 'text-gray-500 hover:bg-gray-100 hover:text-gray-700'
                  }`}
                >
                  <span
                    className={`flex items-center justify-center flex-shrink-0 rounded ${
                      compact ? 'p-1.5' : ''
                    } ${
                      compact && isActiveGroup
                        ? 'bg-green-100 text-green-700'
                        : compact
                          ? 'bg-gray-200/70 text-gray-600'
                          : ''
                    }`}
                  >
                    <GroupIcon size={compact ? 16 : 14} />
                  </span>
                  {!compact && <span className="flex-1 truncate">{groupLabel}</span>}
                </button>
                {!compact && !isActiveGroup && !disabled && (
                  <button
                    type="button"
                    onClick={() => setPeek((p) => ({ ...p, [group]: !p[group] }))}
                    aria-expanded={showContexts}
                    aria-label={t('calc.rail.peek', { group: groupLabel })}
                    title={t('calc.rail.peek', { group: groupLabel })}
                    className="px-2 text-gray-400 hover:text-gray-700 hover:bg-gray-100"
                  >
                    {showContexts ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                  </button>
                )}
              </div>

              {/* ── STEPS: numbered, badged, flagged. Indented behind a guide rule. ── */}
              {showContexts && (
                <div className={compact ? '' : 'ml-[17px] border-l border-gray-200'}>
                  {/* Optional pages are NOT listed here — they have their own band
                      at the foot of the rail. Listing them in both places would
                      show the Trial page twice and make "where do I click this"
                      a question the nav should never raise. */}
                  {GROUP_CONTEXTS[group]
                    .filter((it) => !it.optional)
                    .map((it) => {
                    const active = isActiveGroup && it.id === activeContext;
                    const Icon = it.icon;
                    const label = t(it.labelKey);
                    const badge = TYPE_BADGE[it.type];
                    const done = isDone(it.id);
                    const isStale = staleSteps.has(it.id);
                    const incomplete = !!it.strict && !done; // a strict form that is not complete yet: red
                    // One composed accessible name for both modes, so a screen
                    // reader hears the same thing expanded or collapsed. The
                    // glyphs and ticks inside are decoration; their meaning is
                    // carried here rather than by whatever the icons happen to be.
                    const a11y = [
                      it.step ? `${it.step}.` : '',
                      label,
                      done ? t('workflow.rail.done') : '',
                      isStale ? t('workflow.rail.stale') : '',
                      incomplete ? t('workflow.stepper.incomplete') : '',
                    ]
                      .filter(Boolean)
                      .join(' ');
                    return (
                      <button
                        key={it.id}
                        type="button"
                        // Role gate only. An unmet `needs` never lands here as a
                        // disabled button — it gets a flag chip instead.
                        disabled={disabled}
                        onClick={() => onNavigate(group, it.id)}
                        aria-current={active ? 'page' : undefined}
                        aria-label={a11y}
                        title={a11y}
                        className={`w-full flex items-center gap-2 text-[13px] normal-case transition-colors disabled:opacity-40 ${
                          compact ? 'justify-center px-0 py-2' : 'text-left pl-2.5 pr-3 py-1.5'
                        } ${
                          active
                            ? 'bg-green-100 text-green-800 font-medium border-r-2 border-green-500 -mr-px'
                            : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
                        }`}
                      >
                        <Icon size={15} className="flex-shrink-0" aria-hidden="true" />
                        {!compact && (
                          <>
                            <span
                              className="tabular-nums text-[11px] text-gray-400 w-4 flex-shrink-0"
                              aria-hidden="true"
                            >
                              {it.step ?? '·'}
                            </span>
                            <span className={`flex-1 truncate${incomplete ? ' text-red-700 font-semibold' : ''}`}>{label}</span>
                            <span
                              className={`text-[10px] font-mono flex-shrink-0 ${badge.className}`}
                              title={t(badge.labelKey)}
                              aria-hidden="true"
                            >
                              {badge.glyph}
                            </span>
                            {done && (
                              <Check
                                size={12}
                                className="text-green-600 flex-shrink-0"
                                aria-hidden="true"
                              />
                            )}
                            {incomplete && (
                              <AlertTriangle
                                size={12}
                                className="text-red-600 flex-shrink-0"
                                data-testid={`rail-incomplete-${it.id}`}
                                aria-hidden="true"
                              />
                            )}
                            {isStale && (
                              <AlertTriangle
                                size={12}
                                className="text-amber-600 flex-shrink-0"
                                aria-hidden="true"
                              />
                            )}
                          </>
                        )}
                      </button>
                    );
                  })}
                </div>
              )}
            </section>
          );
        })}
      </div>

      {/* ── OPTIONAL BAND ──────────────────────────────────────────────────
          The one thing the toggle reveals. It is *not* a "needs my input"
          filter: analysis steps are spine items and are always listed, because
          hiding part of the flow is enforcement by omission. The Trial page is
          optional, so it is the only thing that earns a band of its own. */}
      {!compact && OFF_SPINE.length > 0 && (
        <div className="border-t border-gray-200 px-1 py-1.5">
          <button
            type="button"
            onClick={() => setShowOptional((v) => !v)}
            aria-expanded={showOptional}
            className="w-full flex items-center gap-1.5 px-1.5 py-1 text-[11px] uppercase tracking-wide text-gray-400 hover:text-gray-600"
          >
            {showOptional ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            {t('workflow.rail.optional', { count: OFF_SPINE.length })}
          </button>
          {showOptional &&
            OFF_SPINE.map(({ tab, item }) => {
              const Icon = item.icon;
              const badge = TYPE_BADGE[item.type];
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => onNavigate(tab, item.id)}
                  aria-current={activeContext === item.id ? 'page' : undefined}
                  className={`w-full flex items-center gap-2 pl-5 pr-2 py-1.5 text-[13px] text-left ${
                    activeContext === item.id
                      ? 'bg-green-100 text-green-800 font-medium'
                      : 'text-gray-600 hover:bg-gray-100'
                  }`}
                >
                  <Icon size={14} className="flex-shrink-0" />
                  <span className="flex-1 truncate">{t(item.labelKey)}</span>
                  <span className={`text-[10px] font-mono ${badge.className}`} title={t(badge.labelKey)}>
                    {badge.glyph}
                  </span>
                </button>
              );
            })}
        </div>
      )}

      {!compact && (
        <div
          role="separator"
          aria-orientation="vertical"
          onPointerDown={startDrag}
          className="absolute top-0 right-0 h-full w-1.5 translate-x-1/2 cursor-col-resize hover:bg-green-300/60"
          title={t('calc.subnav.resize')}
        />
      )}
    </nav>
  );
}

export default ActivityRail;
