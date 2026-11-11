import type { Feature } from 'geojson';

/** Best-effort stable id of an imported-layer feature (featureId > id). */
export function featureIdOf(f: Feature): string {
  const p = (f as { properties?: Record<string, unknown> }).properties ?? {};
  return String(p.featureId ?? p.id ?? (f as { id?: unknown }).id ?? '');
}

/**
 * Mirror a backend merge-features response back into the client-side imported
 * feature cache: drop the source ids consumed by the merge and append the
 * merged feature. Returns the SAME array reference when nothing changes so
 * callers can skip redundant state writes.
 */
export function applyImportedMerge(cur: Feature[], sourceIds: string[], merged: unknown): Feature[] {
  const m = merged as { geometry?: unknown } | null | undefined;
  if (!m?.geometry) return cur;
  const next = cur.filter((f) => !sourceIds.includes(featureIdOf(f)));
  return [...next, merged as Feature];
}