/**
 * calcContexts — the single registry of every group → context pair in the
 * tabbed calculation shell, and the workflow metadata that drives the guided
 * stepper. WORKSPACE_FLOW_NAV_PLAN §4-§5 (phase P2b).
 *
 * Two changes from the pre-P2b shape, and both are deliberate.
 *
 * 1. **The groups are now the workflow's phases, not topics.** The order is the
 *    order the work is actually done: map → sample → inventory → analyse →
 *    plan → submit. `step` is global and drives `Step N of M` (M = SPINE_LENGTH, from the registry).
 *
 * 2. **Every entry declares its page type.** `PageType` exists because the
 *    owner's classification axis is *who does the work*, not subject matter:
 *    Biodiversity sounds like analysis but is the most input-heavy page in the
 *    system, while the Analysis page sounds like data but the user does nothing
 *    but press Run. Classifying by topic put those two side by side as
 *    indistinguishable peers, which is what this replaces.
 */
import type { LucideIcon } from 'lucide-react';
import {
  Map as MapIcon,
  Users,
  BookOpen,
  Ruler,
  ListTree,
  Leaf,
  MapPin,
  TreePine,
  Sprout,
  FilePen,
  Table2,
  BarChart3,
  ShieldAlert,
  Trees,
  Coins,
  ClipboardList,
  CalendarDays,
  Send,
  FileText,
} from 'lucide-react';
import type { TabId } from '../../pages/calculationTabConfig';

/**
 * How a page is used. Drives the page shell, not just a badge colour.
 *
 * - `input` — the user types or uploads. Form first, results secondary.
 * - `run`   — the user sets parameters or clicks Run; the system computes and
 *             the result is final. Parameter panel + prominent Run + progress.
 * - `view`  — nothing to do. Pure derived tables, no primary action.
 * - `trial` — user-triggered, result disposable. Run + countdown + an explicit
 *             `expired` state once the window closes. There is no escape hatch
 *             (plan §5.1).
 */
export type PageType = 'input' | 'run' | 'view' | 'trial';

/**
 * One tab of a context page.
 *
 * `labelKey`, never a literal. The registry originally held raw English
 * (`tabs: ['Upload Data', ...]`), which cannot work in a Nepali-first app: the
 * labels would stay English in both bundles and `keySync` would have nothing to
 * compare. Ids are stable so tests and future deep links can target a pane
 * without depending on a translated string.
 */
export interface ContextTabSpec {
  /** stable pane id, unique within its context */
  id: string;
  /** i18n key for the visible tab label */
  labelKey: string;
  /**
   * This pane shows derived values, so it has nothing to show until the step
   * itself has data. The host disables it (with a reason) while the step is not
   * done.
   *
   * The check is the step's own server-side readiness, the same signal the rail
   * and the stepper already use, so "Results" cannot disagree with the tick mark
   * next to the step. A *derived* pane is the one place a lock is honest: there
   * is literally nothing behind it. The entering pane stays open and usable, and
   * the step itself is still reachable — sequence, never enforce.
   */
  needsStepData?: boolean;
}

export interface CtxItem {
  /** context id — matches `?surface=<group>/<id>` and the resolver in
   *  `contextComponents.tsx`. Unique across ALL groups; asserted by
   *  `contextResolver.test.tsx`. */
  id: string;
  /** i18n key for the visible label */
  labelKey: string;
  /** icon for the compact rail + the command palette */
  icon: LucideIcon;
  /** Page type. Selects the page shell. */
  type: PageType;
  /** 1-based position in the guided spine. Absent = outside the spine. */
  step?: number;
  /** Context ids that should be complete before this one is meaningful. Flags
   *  only — the system sequences, it never enforces. */
  needs?: string[];
  /** The page's own tabs, in order, when it has more than one. Rendered by
   *  `ContextTabHost`; the pane bodies live in `CONTEXT_TABS`. */
  tabs?: ContextTabSpec[];
  /** Optional page. Rendered in an "Optional" band, never a `needs` target. */
  optional?: boolean;
  /**
   * How much the USER has to do here (owner, 2026-10-11): a step is `required` only when the user must upload, edit or set a
   * parameter; one the system fills in by itself is `optional`; `review` is filled by the system and only needs the user's
   * adjustment (cost-benefit). Only for spine steps. It never blocks anything: it decides what Next walks through first and what
   * the progress count measures.
   */
  need?: 'required' | 'optional' | 'review';
  /** A step whose form must be filled in completely: shown RED in the strip and the rail until the server reports it done. */
  strict?: boolean;
}

export const GROUP_CONTEXTS: Record<TabId, CtxItem[]> = {
  // ── BASE — free order, but the Map gates everything (plan §4.1) ──────────
  base: [
    {
      id: 'unified',
      labelKey: 'workspace.sidebar.map',
      icon: MapIcon,
      type: 'input',
      step: 1,
      need: 'required',
    },
    {
      id: 'usergroup',
      labelKey: 'workspace.sidebar.userGroupMap',
      icon: Users,
      type: 'input',
      step: 2,
      need: 'required',
      // Parallel with the boundary, not downstream of it — but the map is what
      // the user-group geometry is drawn on, so it is still a real dependency.
      needs: ['unified'],
    },
  ],

  // ── FIELD WORK — the ordered chain (plan §4.2) ──────────────────────────
  field: [
    {
      id: 'fieldbook',
      labelKey: 'workspace.sidebar.fieldbook',
      icon: BookOpen,
      type: 'run',
      step: 3,
      need: 'required',
      needs: ['unified'],
    },
    {
      id: 'sampling',
      labelKey: 'navigation.sampling',
      icon: Ruler,
      // Configured, then *generated* — the design is produced by `sampling.py`,
      // not typed. So `run`, not a compound type.
      type: 'run',
      step: 4,
      need: 'required',
      needs: ['unified'],
    },
    {
      id: 'fieldinventory',
      labelKey: 'inventory.title',
      icon: ListTree,
      type: 'input',
      step: 5,
      need: 'required',
      needs: ['sampling'],
      // (D5) Forest Metadata is collected during the field-inventory visit, and
      // (D4) the inventory results are the same data in a second state.
      //
      // Metadata is the odd one out: it is not a view of the field inventory but
      // a record of the forest itself, and the DOCX cover page reads it. It is
      // still a pane of this step rather than a step of its own, because D5 puts
      // it in the field inventory visit. No `needsStepData`: it is editable
      // before any inventory exists, which is the whole point of collecting it on
      // the way in rather than afterwards.
      tabs: [
        { id: 'data', labelKey: 'workflow.tab.uploadData' },
        { id: 'results', labelKey: 'workflow.tab.results', needsStepData: true },
      ],
    },
    {
      // Its own step (owner, 2026-10-11): it is a record of the forest itself (names, code, financial year), the DOCX cover page
      // reads it, and the user has to fill it in. It used to be a third pane of the field-inventory step.
      id: 'forestmetadata',
      labelKey: 'workspace.sidebar.forestMetadata',
      icon: FileText,
      type: 'input',
      step: 6,
      need: 'required',
      strict: true,
    },
    {
    id: 'biodiversity',
    labelKey: 'workspace.sidebar.biodiversity',
    icon: Leaf,
    type: 'input',
    step: 7,
      need: 'required',
    needs: ['fieldinventory'],
    // Plan 8.4 / D4. `results` is the OP document variables derived from the
    // species recorded on `data`; it has nothing to show without them, so it
    // locks off this step's own readiness rather than opening empty.
    tabs: [
      { id: 'data', labelKey: 'workflow.tab.data' },
      { id: 'results', labelKey: 'workflow.tab.results', needsStepData: true },
    ],
      // Data / Results land with P5c.
    },
    {
    id: 'treemapping',
    labelKey: 'workspace.sidebar.treeMapping',
    icon: MapPin,
    type: 'input',
    step: 8,
      need: 'optional',
    needs: ['fieldinventory'],
    // Plan 8.4 / D4. `data` is the file and the rows it brought; `results` is
    // the totals, charts, tables and analysis computed from those rows.
    tabs: [
      { id: 'data', labelKey: 'workflow.tab.data' },
      { id: 'results', labelKey: 'workflow.tab.results', needsStepData: true },
    ],
      // Data / Results land with P5c.
    },
    {
      // An optional numbered step (owner, 2026-10-22): the NTFP resource inventory (government guideline 2069). It sits in the spine so a field team sees it
      // in the order the work is done, but it is `optional`: the plan can be finished without it and no export gate asks for it. It reads the forest's boundary
      // and units, hence `unified`. Its results reach the plan as table 39 / section ntfp_inventory. (It was in the Optional band until 2026-10-22; the steps after it moved up by one.)
      id: 'ntfp',
      labelKey: 'workspace.sidebar.ntfpInventory',
      icon: Sprout,
      type: 'run',
      step: 9,
      need: 'optional',
      needs: ['unified'],
    },
    {
      // The only Trial page. Optional, so it carries no `step` and no entry may
      // name it in `needs` (D13).
      id: 'treemodel',
      labelKey: 'workspace.sidebar.treeModel',
      icon: TreePine,
      type: 'trial',
      needs: ['fieldinventory'],
      optional: true,
    },
  ],

  // ── ANALYSIS — free order, flagged not blocked (plan §4.3) ──────────────
  analysis: [
    {
      id: 'detaildescription',
      labelKey: 'workspace.sidebar.detailDescription',
      icon: FilePen,
      // Autogenerated, no manual input (D14).
      type: 'view',
      step: 10,
      need: 'optional',
    },
    {
      id: 'areadetail',
      labelKey: 'workspace.sidebar.areaDetail',
      icon: Table2,
      type: 'view',
      step: 11,
      need: 'optional',
      needs: ['unified'],
    },
    {
      // Advanced (owner, 2026-10-17): the plan builds this by itself from the map's analysis, so the page is for correcting
      // values and looking at the charts. Off the numbered steps, in the Optional band; no entry may name it in `needs`.
      id: 'analysis',
      labelKey: 'workspace.sidebar.analysis',
      icon: BarChart3,
      type: 'run',
      optional: true,
      needs: ['unified'],
    },
    {
      // Advanced (owner, 2026-10-17): the plan computes the landslide and soil-loss figures with default settings; this page
      // is for tuning them and looking at the maps.
      id: 'hazarderosion',
      labelKey: 'workspace.sidebar.hazardErosion',
      icon: ShieldAlert,
      type: 'run',
      optional: true,
      needs: ['unified', 'fieldinventory'],
    },
    {
      id: 'sustainablefm',
      labelKey: 'workspace.sidebar.sustainableFm',
      icon: Trees,
      type: 'run',
      step: 12,
      need: 'optional',
      needs: ['treemapping'],
    },
    {
      id: 'cba',
      labelKey: 'workspace.sidebar.cba',
      icon: Coins,
      // Reads inventory + analysis, NOT the plan: the plan document *consumes*
      // CBA's output, so the dependency runs that way round.
      type: 'run',
      step: 13,
      need: 'review',
      needs: ['fieldinventory'],
    },
  ],

  // ── PLAN & SUBMISSION — desktop work, terminal deliverable (D7/D8) ──────
  plan: [
    {
      // Its own step (owner, 2026-10-15). It used to be the Operational Plan's second tab (D9). It is done only when the owner
      // presses Done on its page, because the list is long and is not finished in one sitting; a later change reopens it.
      id: 'yearly',
      labelKey: 'workspace.sidebar.yearlyActivities',
      icon: CalendarDays,
      type: 'input',
      step: 14,
      need: 'required',
    },
    {
      id: 'mgmtplan',
      labelKey: 'navigation.operationalPlan',
      icon: ClipboardList,
      type: 'input',
      step: 15,
      need: 'required',
    },
    {
      id: 'issuesubmit',
      labelKey: 'workspace.sidebar.issueSubmit',
      icon: Send,
      type: 'run',
      step: 16,
      need: 'required',
      needs: ['mgmtplan'],
    },
  ],
};

/** Every step number, ascending, for `Step N of M`. */
export const SPINE_LENGTH: number = Object.values(GROUP_CONTEXTS)
  .flat()
  .filter((c) => c.step !== undefined).length;

export const isSpineItem = (c: CtxItem): boolean => c.step !== undefined;

/** Look up a context by id, wherever it lives. */
export function findContext(id: string): { tab: TabId; item: CtxItem } | null {
  for (const tab of Object.keys(GROUP_CONTEXTS) as TabId[]) {
    const item = GROUP_CONTEXTS[tab].find((c) => c.id === id);
    if (item) return { tab, item };
  }
  return null;
}

/**
 * Context ids that render a full-bleed map. When the active context is one of
 * these and the user hasn't picked a rail mode yet, the rail auto-collapses to
 * the icon strip so the canvas keeps the width.
 *
 * `usergroup` stays even though it is no longer a map *context* surface: the
 * page still renders a map, so removing it would stop the rail auto-collapsing
 * and give that page a wider rail than it needs. The three legacy ids
 * (`boundary`, `blocks`, `subcompartments`) are not in `GROUP_CONTEXTS` at all
 * and stay so `?surface=base/boundary` still renders the workspace.
 */
export const MAP_CONTEXT_IDS: ReadonlySet<string> = new Set([
  'unified',
  'boundary',
  'blocks',
  'subcompartments',
  'usergroup',
]);

export const isMapContext = (id: string): boolean => MAP_CONTEXT_IDS.has(id);
