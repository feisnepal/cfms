/**
 * What the ActivityPicker knows about the master list beyond text search (§4.11): which programme /
 * unit / map symbol an activity belongs to, the filter chips and how they combine, the browse tree, and
 * the "recently used" list kept in this browser only.
 *
 * Pure functions (plus a guarded localStorage) so they are unit-tested without rendering anything.
 */
import { ACTIVITY_KINDS } from '../../lib/activityKinds';
import {
  normalizeActivityText,
  type CatalogueActivity,
  type SearchHit,
} from '../../lib/activitySearch';

// ------------------------------------------------------------------------------- programmes

/** Programme → the slug of its plain-language note (`yearlyPlan.find.programme.<slug>`). First match wins. */
const PROGRAMME_RULES: Array<[string, string]> = [
  ['वन विकासका', 'development'],
  ['वन संरक्षण', 'protection'],
  ['सम्वर्दन', 'silviculture'],
  ['सदुपयोग', 'utilisation'],
  ['सक्तिकरण', 'capacity'],
  ['गरिवी', 'poverty'],
  ['उद्यम', 'enterprise'],
  ['पर्यापर्यटन', 'ecotourism'],
  ['जलवायु', 'climate'],
  ['संस्थागत', 'institutional'],
  ['कार्यालय भवन', 'office'],
  ['सामुदायिक विकास', 'community'],
  ['प्रसासनिक', 'admin'],
].map(([needle, slug]) => [normalizeActivityText(needle), slug] as [string, string]);

/** The slug of a programme's note, or null for a programme without one (an unknown or admin-added group). */
export function programmeSlug(programme: string): string | null {
  const n = normalizeActivityText(programme);
  if (!n) return null;
  for (const [needle, slug] of PROGRAMME_RULES) if (n.includes(needle)) return slug;
  return null;
}

// ------------------------------------------------------------------------------------ units

const UNIT_SLUGS: Record<string, string> = Object.fromEntries(
  (
    [
      ['हेक्टर', 'hectare'],
      ['कि.मि.', 'kilometre'],
      ['वटा', 'piece'],
      ['पटक', 'time'],
      ['जना', 'person'],
      ['स्थान', 'place'],
      ['आ.अ.', 'asneeded'],
      ['भारी', 'load'],
      ['क्यु.फि.', 'cubicfeet'],
      ['के.जी.', 'kilogram'],
      ['चट्टा', 'stack'],
      ['दिवस', 'day'],
      ['किसिम', 'kind'],
    ] as Array<[string, string]>
  ).map(([unit, slug]) => [normalizeActivityText(unit).replace(/ /g, ''), slug]),
);

/** The slug of a unit's wording (`yearlyPlan.find.unit.<slug>`), or null for a unit without one. */
export function unitSlug(unit: string): string | null {
  return UNIT_SLUGS[normalizeActivityText(unit).replace(/ /g, '')] ?? null;
}

// ------------------------------------------------------------------------------------- map

export type MapPhrase = 'area' | 'line' | 'point' | 'generic' | 'none';

/** How an activity can be shown on the map: by its symbol's geometry, generically, or not at all. */
export function mapPhrase(a: Pick<CatalogueActivity, 'requiresMap' | 'mapKind'> & { mapGeom?: CatalogueActivity['mapGeom'] }): MapPhrase {
  if (!a.requiresMap) return 'none';
  const geom = a.mapGeom ?? (a.mapKind ? ACTIVITY_KINDS[a.mapKind]?.geom : undefined);
  if (geom === 'polygon') return 'area';
  if (geom === 'line') return 'line';
  if (geom === 'point') return 'point';
  return 'generic';
}

// ---------------------------------------------------------------------------------- filters

export type MapFilter = 'any' | 'map' | 'nomap';
export type PlanFilter = 'any' | 'in' | 'not';

export interface PickerFilters {
  map: MapFilter;
  /** Map symbols (`map_kind`); empty = any. */
  kinds: string[];
  /** Units; empty = any. */
  units: string[];
  plan: PlanFilter;
  recentOnly: boolean;
}

export const NO_FILTERS: PickerFilters = { map: 'any', kinds: [], units: [], plan: 'any', recentOnly: false };

export function hasActiveFilters(f: PickerFilters): boolean {
  return f.map !== 'any' || f.kinds.length > 0 || f.units.length > 0 || f.plan !== 'any' || f.recentOnly;
}

export interface FilterContext {
  /** Is this master-list activity already a line of the plan? */
  inPlan: (id: number) => boolean;
  recent: number[];
}

/** Every chip narrows; chips of different kinds combine (AND), several values of one kind are alternatives (OR). */
export function filterHits(hits: SearchHit[], f: PickerFilters, ctx: FilterContext): SearchHit[] {
  if (!hasActiveFilters(f)) return hits;
  return hits.filter(({ activity: a }) => {
    if (f.map === 'map' && !a.requiresMap) return false;
    if (f.map === 'nomap' && a.requiresMap) return false;
    if (f.kinds.length > 0 && !(a.mapKind && f.kinds.includes(a.mapKind))) return false;
    if (f.units.length > 0 && !f.units.includes(a.unit)) return false;
    if (f.plan === 'in' && !ctx.inPlan(a.id)) return false;
    if (f.plan === 'not' && ctx.inPlan(a.id)) return false;
    if (f.recentOnly && !ctx.recent.includes(a.id)) return false;
    return true;
  });
}

export interface Counted {
  value: string;
  count: number;
}

/** Counts per value, biggest first, ties by value — for the "measured in" and "map symbol" chips. */
export function countBy(hits: SearchHit[], pick: (a: CatalogueActivity) => string | null): Counted[] {
  const counts = new Map<string, number>();
  hits.forEach(({ activity }) => {
    const v = pick(activity);
    if (v) counts.set(v, (counts.get(v) ?? 0) + 1);
  });
  return [...counts.entries()]
    .map(([value, count]) => ({ value, count }))
    .sort((a, b) => b.count - a.count || a.value.localeCompare(b.value));
}

// ------------------------------------------------------------------------ grouping and tree

export interface ProgrammeGroup {
  programme: string;
  hits: SearchHit[];
}

/** Results grouped by programme: the group with the best hit first, then master-list order. */
export function groupByProgramme(hits: SearchHit[]): ProgrammeGroup[] {
  const groups = new Map<string, ProgrammeGroup & { best: number; order: number }>();
  for (const h of hits) {
    const key = h.activity.programme;
    const g = groups.get(key) ?? { programme: key, hits: [], best: 0, order: h.programmeOrder };
    g.hits.push(h);
    g.best = Math.max(g.best, h.score);
    groups.set(key, g);
  }
  return [...groups.values()]
    .sort((a, b) => b.best - a.best || a.order - b.order)
    .map(({ programme, hits: hs }) => ({ programme, hits: hs }));
}

export interface TreeProject {
  project: string;
  programmes: ProgrammeGroup[];
  total: number;
}

/** project → programme → activity, all in master-list order (the tree is for browsing, so no ranking). */
export function buildBrowseTree(hits: SearchHit[]): TreeProject[] {
  const projects = new Map<string, TreeProject>();
  for (const h of [...hits].sort((a, b) => a.activity.id - b.activity.id)) {
    const p = projects.get(h.activity.project) ?? { project: h.activity.project, programmes: [], total: 0 };
    let g = p.programmes.find((x) => x.programme === h.activity.programme);
    if (!g) {
      g = { programme: h.activity.programme, hits: [] };
      p.programmes.push(g);
    }
    g.hits.push(h);
    p.total += 1;
    projects.set(h.activity.project, p);
  }
  return [...projects.values()];
}

// -------------------------------------------------------------------------- recently used

const RECENT_KEY = 'cfms.yearlyPlan.recentActivities';
const RECENT_MAX = 8;

/** The last activities this browser chose, newest first. Storage may be blocked or empty: never throws. */
export function readRecent(): number[] {
  try {
    const raw = window.localStorage.getItem(RECENT_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.map(Number).filter((n) => Number.isInteger(n)).slice(0, RECENT_MAX) : [];
  } catch {
    return [];
  }
}

/** Remembers a chosen activity and returns the new list (still returns it when storage is unavailable). */
export function rememberRecent(id: number): number[] {
  const next = [id, ...readRecent().filter((x) => x !== id)].slice(0, RECENT_MAX);
  try {
    window.localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    /* storage blocked: the list simply is not kept */
  }
  return next;
}
