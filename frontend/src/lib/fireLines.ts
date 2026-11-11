/** Fire lines (FIRELINE_RIVERBANK_PLAN.md, FL-5): the pure logic behind the tick-list and the draw editor.
 *  Widths are metres PER SIDE, like the backend (`FIRE_LINE_SIDE_M`); the backend is the authority, these are the defaults
 *  and the same limits so the form can say "no" before the server does. */
import type { FireLineRow, FireLineSummary, FireLineTotals } from '../services/api';

export const DEFAULT_SIDE_M = 1.5;
export const MIN_SIDE_M = 0.1;
export const MAX_SIDE_M = 50;

export type Group = 'boundary' | 'road' | 'river';
export const GROUPS: Group[] = ['boundary', 'road', 'river'];

/** The two kinds share the panel, the editor and the helpers; only the groups, the default width and the words differ. */
export type StripKind = 'fire_line' | 'river_bank';
export const KIND_GROUPS: Record<StripKind, Group[]> = { fire_line: ['boundary', 'road'], river_bank: ['river'] };
/** Metres PER SIDE; mirrors the backend constants (`FIRE_LINE_SIDE_M`, `RIVER_BANK_SIDE_M`). */
export const KIND_DEFAULT_SIDE: Record<StripKind, number> = { fire_line: DEFAULT_SIDE_M, river_bank: 20 };

export function segmentCount(line: { coordinates: unknown[] } | null | undefined): number {
  return Math.max(0, (line?.coordinates?.length ?? 0) - 1);
}

export function defaultWidths(segments: number, side: number = DEFAULT_SIDE_M): number[] {
  return Array.from({ length: segments }, () => side);
}

export function validWidth(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v) && v >= MIN_SIDE_M && v <= MAX_SIDE_M;
}

export function allWidthsValid(widths: unknown[]): boolean {
  return widths.length > 0 && widths.every(validWidth);
}

/** Rows whose name contains `text` (case-insensitive); an empty filter keeps everything. */
export function filterRows(rows: FireLineRow[], text: string): FireLineRow[] {
  const q = text.trim().toLowerCase();
  return q ? rows.filter((r) => r.name.toLowerCase().includes(q)) : rows;
}

/** The rows in walking order: start at the north-west end, then always take the line whose end lies nearest the end we are at
 *  (a line that touches the last one is at distance 0), so each row joins the one above it. Rows with no line go last. */
export function chainOrder(rows: FireLineRow[]): FireLineRow[] {
  type Ends = { row: FireLineRow; a: [number, number]; b: [number, number] };
  const ends: Ends[] = [];
  const loose: FireLineRow[] = [];
  for (const row of rows) {
    const c = (row.centerline as { coordinates?: number[][] } | null | undefined)?.coordinates;
    if (c && c.length >= 2) ends.push({ row, a: [c[0][0], c[0][1]], b: [c[c.length - 1][0], c[c.length - 1][1]] });
    else loose.push(row);
  }
  if (!ends.length) return rows;
  const dist = (p: [number, number], q: [number, number]) => Math.hypot(p[0] - q[0], p[1] - q[1]);
  const startAt = (e: Ends): [number, number] => (e.a[1] - e.a[0] >= e.b[1] - e.b[0] ? e.a : e.b); // most north-west of its two ends
  ends.sort((p, q) => { const s = startAt(p), t = startAt(q); return (t[1] - t[0]) - (s[1] - s[0]); });
  const out: FireLineRow[] = [];
  const left = ends.slice();
  const first = left.shift() as Ends;
  out.push(first.row);
  let tail = startAt(first) === first.a ? first.b : first.a;
  while (left.length) {
    let best = 0, bestD = Infinity, bestFar = left[0].b;
    left.forEach((e, i) => {
      const da = dist(tail, e.a), db = dist(tail, e.b);
      const d = Math.min(da, db);
      if (d < bestD) { best = i; bestD = d; bestFar = da <= db ? e.b : e.a; }
    });
    const [next] = left.splice(best, 1);
    out.push(next.row);
    tail = bestFar;
  }
  return [...out, ...loose];
}

/** One row of the tick-list: every piece of one unit pair (`e-g`, `e-g ·2`, `e-g (3)`...) is a single entry; roads and rivers stay one each. */
export interface PairGroup { key: string; name: string; rows: FireLineRow[]; length_m: number; area_ha: number }

/** Group the rows (already in walking order) by unit pair, keeping the order of each pair's first piece. Only boundary rows group:
 *  their `unit_key` is `<pair>||<line>[~<piece>]`, and the pair part is built from sorted unit numbers, so `e-g` and `g-e` are one key. */
export function groupByPair(rows: FireLineRow[]): PairGroup[] {
  const out = new Map<string, PairGroup>();
  for (const r of rows) {
    const key = r.group === 'boundary' ? r.unit_key.split('||')[0] : r.unit_key;
    const g = out.get(key) ?? { key, name: r.group === 'boundary' ? r.name.replace(/\s*(·\d+|\(\d+\))$/, '') : r.name, rows: [], length_m: 0, area_ha: 0 };
    g.rows.push(r);
    g.length_m += r.length_m;
    g.area_ha += r.area_ha;
    out.set(key, g);
  }
  return [...out.values()];
}

/** What each row will be once the staged ticks are applied (a row with no staged tick keeps its own). */
export function wanted(row: FireLineRow, staged: Record<string, boolean>): boolean {
  return row.unit_key in staged ? staged[row.unit_key] : row.ticked;
}

/** The changes to send: only rows whose wanted state differs from what is stored. */
export function pendingChanges(rows: FireLineRow[], staged: Record<string, boolean>): Array<{ unit_key: string; included: boolean }> {
  return rows.filter((r) => wanted(r, staged) !== r.ticked).map((r) => ({ unit_key: r.unit_key, included: wanted(r, staged) }));
}

/** Stage a tick for every row in `rows` (select all / none of what the filter shows). Rows already in that state are unstaged. */
export function stageAll(rows: FireLineRow[], staged: Record<string, boolean>, ticked: boolean): Record<string, boolean> {
  const next = { ...staged };
  for (const r of rows) {
    if (r.ticked === ticked) delete next[r.unit_key];
    else next[r.unit_key] = ticked;
  }
  return next;
}

export function toggle(row: FireLineRow, staged: Record<string, boolean>): Record<string, boolean> {
  const next = { ...staged };
  const want = !wanted(row, staged);
  if (want === row.ticked) delete next[row.unit_key];
  else next[row.unit_key] = want;
  return next;
}

/** Totals of what would exist after applying the staged ticks (lengths and areas are the candidates' own). */
export function projectedTotals(rows: FireLineRow[], staged: Record<string, boolean>): Record<Group, FireLineTotals> {
  const out: Record<Group, FireLineTotals> = {
    boundary: { count: 0, km: 0, ha: 0 }, road: { count: 0, km: 0, ha: 0 }, river: { count: 0, km: 0, ha: 0 },
  };
  const counted = new Set<string>(); // a pair counts once, however many of its pieces are wanted
  for (const r of rows) {
    if (!wanted(r, staged)) continue;
    const t = out[r.group];
    const key = r.group === 'boundary' ? r.unit_key.split('||')[0] : r.unit_key;
    if (!counted.has(key)) { counted.add(key); t.count += 1; }
    t.km += (r.length_m || 0) / 1000;
    t.ha += r.area_ha || 0;
  }
  for (const g of GROUPS) {
    out[g].km = Math.round(out[g].km * 1000) / 1000;
    out[g].ha = Math.round(out[g].ha * 10000) / 10000;
  }
  return out;
}

/** The i18n key and parameters that explain a status, or null when there is nothing to say (state "ok"). */
export function statusMessage(status: FireLineSummary['status'] | undefined): { key: string; params: Record<string, unknown> } | null {
  const s = status?.state ?? 'never';
  if (s === 'ok' || s === 'synced' || s === 'unchanged' || s === 'decided') return null;
  const params: Record<string, unknown> = {};
  if (s === 'dirty_units') params.m2 = Math.round(Number(status?.overlap_m2 ?? 0));
  if (s === 'fragmented_edges') {
    params.pieces = status?.pieces ?? 0;
    params.pairs = status?.pairs ?? 0;
  }
  if (s === 'unresolved_edges') {
    params.n = status?.unresolved_legs ?? 0;
    params.total = status?.legs ?? 0;
  }
  return { key: `fireLines.status.${s}`, params };
}

/** The backend's friendly error (`detail.message`) when there is one, else the fallback. */
export function errorMessage(err: unknown, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (detail && typeof detail === 'object' && typeof (detail as { message?: unknown }).message === 'string') {
    return (detail as { message: string }).message;
  }
  return typeof detail === 'string' && detail ? detail : fallback;
}

/** A replay-safe id for one "Create" press (the backend returns the first result for a repeated id). */
export function newClientId(): string {
  const c = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto;
  return c?.randomUUID ? c.randomUUID() : `c-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

export const formatKm = (m: number): string => (m / 1000).toFixed(2);
