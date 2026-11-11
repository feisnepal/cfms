/**
 * CalculationDetailTabbed — shared pure helpers.
 *
 * 4 groups, named for the phases of the work rather than for topics
 * (WORKSPACE_FLOW_NAV_PLAN §4):
 *
 *   base     -> Map, User Group
 *   field    -> Fieldbook, Sampling, Field Inventory, Biodiversity, Tree Inventory
 *   analysis -> Detail Description, Area Accounting, Analysis, Hazard & Erosion,
 *               SFM, Cost-Benefit
 *   plan     -> Operational Plan, Issue & Submit
 *
 * The order is the order the work is done, which is the point of the change: the
 * rail is now a field checklist rather than an alphabetical topic list.
 */
import type { PermissionGateCan } from '../hooks/usePermissionGate';

export const TABS = ['base', 'field', 'analysis', 'plan'] as const;
export type TabId = (typeof TABS)[number];

export type TabRequiresEdit = Record<TabId, boolean>;

/**
 * Group labels are i18n keys, not display strings. The previous hardcoded
 * English ('Forest Data', 'Data & Maps', …) was rendered raw by `ActivityRail`
 * with no `t()` call, while the Nepali translations already sat unused in the
 * bundles.
 */
export const TAB_CONFIG: Record<
  TabId,
  { labelKey: string; icon: string; requiresEdit: boolean }
> = {
  // `requiresEdit` is a *role* gate, not a workflow gate (plan §5.2): a read-only
  // user can still review the map and every analysis, so `base` and `analysis`
  // are open to them. `field` and `plan` write.
  base: { labelKey: 'workspace.phase.base', icon: 'grid', requiresEdit: false },
  field: { labelKey: 'workspace.phase.field', icon: 'tree', requiresEdit: true },
  analysis: { labelKey: 'workspace.phase.analysis', icon: 'database', requiresEdit: false },
  plan: { labelKey: 'workspace.phase.plan', icon: 'file-text', requiresEdit: true },
};

/** Map group -> requiresEdit, for disabled-group computation. */
export const tabRequiresEdit = (): TabRequiresEdit =>
  Object.fromEntries(TABS.map((t) => [t, TAB_CONFIG[t].requiresEdit])) as TabRequiresEdit;

/** Validate a group id against the known set. */
export const isValidTab = (tab: string | null | undefined): tab is TabId =>
  !!tab && (TABS as readonly string[]).includes(tab);

/** Resolve the active group id, defaulting to 'base'. */
export const resolveActiveTab = (tabParam: string | null | undefined): TabId =>
  isValidTab(tabParam) ? (tabParam as TabId) : 'base';

/**
 * Groups that must be disabled, given the permission gate.
 *
 * This is a *role* gate, not a workflow gate: a read-only user cannot write. It
 * is distinct from the `needs` flags in `calcContexts`, which are advisory and
 * never lock anything (plan §2: the system sequences, it never enforces).
 */
export const computeDisabledTabs = (
  requiresEdit: TabRequiresEdit,
  isTabDisabled: PermissionGateCan['isTabDisabled'],
): TabId[] => TABS.filter((t) => requiresEdit[t] && isTabDisabled(requiresEdit[t]));

/** Whether switching groups is allowed given unsaved changes. */
export const canSwitchTab = (hasUnsavedChanges: boolean): boolean => !hasUnsavedChanges;

/**
 * Keyboard shortcut digit (1-based) for the N-th group. Used by both
 * `useTabKeyboardShortcuts` (Ctrl/Cmd+digit) and the shortcuts help modal so
 * the contract stays in one place. Addresses **groups**, not steps: 15 step
 * shortcuts would collide with 4 group shortcuts, and the stepper has
 * Back/Next (plan §8.8).
 */
export const shortcutKeyForTab = (index: number): string | undefined => {
  const n = index + 1;
  return n >= 1 && n <= TABS.length ? String(n) : undefined;
};
