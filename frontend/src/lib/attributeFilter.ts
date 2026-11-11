/**
 * One-row attribute filter for the workspace table (WORKSPACE_LAYER_STYLING_PLAN.md
 * P4.6). `field · op · value` — narrows the table, and optionally the map when
 * "show only matches" is on (`store.tableFilter`).
 */
import type { GeoJSON } from 'geojson';

export type FilterOp = 'eq' | 'ne' | 'contains' | 'gt' | 'lt' | 'gte' | 'lte';

export interface AttributeFilter {
  layerId: string;
  field: string;
  op: FilterOp;
  value: string;
}

export const FILTER_OPS: Array<{ op: FilterOp; symbol: string }> = [
  { op: 'eq', symbol: '=' },
  { op: 'ne', symbol: '≠' },
  { op: 'contains', symbol: '⊃' },
  { op: 'gt', symbol: '>' },
  { op: 'lt', symbol: '<' },
  { op: 'gte', symbol: '≥' },
  { op: 'lte', symbol: '≤' },
];

/** Does one feature satisfy `field op value`? A blank field or value passes everything. */
export function matchFeature(
  feature: GeoJSON.Feature,
  field: string,
  op: FilterOp,
  value: string,
): boolean {
  if (!field || value === '') return true;
  const raw = feature.properties?.[field];
  if (op === 'eq' || op === 'ne') {
    const eq = String(raw ?? '').toLowerCase() === value.toLowerCase();
    return op === 'eq' ? eq : !eq;
  }
  if (op === 'contains') {
    return String(raw ?? '').toLowerCase().includes(value.toLowerCase());
  }
  const a = typeof raw === 'number' ? raw : Number(raw);
  const b = Number(value);
  if (!Number.isFinite(a) || !Number.isFinite(b)) return false;
  switch (op) {
    case 'gt': return a > b;
    case 'lt': return a < b;
    case 'gte': return a >= b;
    case 'lte': return a <= b;
    default: return true;
  }
}

/** Apply an active map-side filter to one layer's features (no-op for other layers). */
export function filterForMap(
  features: GeoJSON.Feature[] | null | undefined,
  filter: AttributeFilter | null,
  layerId: string,
): GeoJSON.Feature[] | null {
  if (!features) return null;
  if (!filter || filter.layerId !== layerId) return features;
  return features.filter((f) => matchFeature(f, filter.field, filter.op, filter.value));
}

/** Drop features the user has hidden from the map via the ⋮ row menu (P5.1). */
export function dropHiddenFeatures(
  features: GeoJSON.Feature[] | null | undefined,
  hiddenIds: string[] | undefined,
): GeoJSON.Feature[] | null {
  if (!features) return null;
  if (!hiddenIds || hiddenIds.length === 0) return features;
  const hidden = new Set(hiddenIds);
  return features.filter(
    (f) => !hidden.has(String(f.properties?.id ?? f.properties?.featureId ?? (f as { id?: unknown }).id ?? '')),
  );
}

export interface ValueSuggestion { value: string; count: number }

/**
 * Distinct values of `field` for the filter's value box, most frequent first, narrowed by
 * what the user has typed. Numeric-comparison ops get none (typing a number is easier than
 * picking one). Capped so a field with thousands of distinct values stays cheap.
 */
export function suggestFilterValues(
  features: GeoJSON.Feature[],
  field: string,
  op: FilterOp,
  typed: string,
  limit = 50,
): ValueSuggestion[] {
  if (!field || op === 'gt' || op === 'lt' || op === 'gte' || op === 'lte') return [];
  const counts = new Map<string, number>();
  for (const f of features) {
    const raw = f.properties?.[field];
    if (raw == null || typeof raw === 'object') continue;
    const v = String(raw).trim();
    if (v === '' || v === '-') continue;
    counts.set(v, (counts.get(v) ?? 0) + 1);
  }
  const q = typed.toLowerCase();
  return [...counts.entries()]
    .filter(([v]) => !q || v.toLowerCase().includes(q))
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, limit)
    .map(([value, count]) => ({ value, count }));
}
