/**
 * draftAutosave — pure localStorage helpers for the digitize draft autosave
 * gap (Phase 5). Kept free of React/store so the logic is unit-testable.
 *
 * Storage shape:
 *   calc_draft_<calculationId>      -> JSON of `digitizeDraftFeatures` record
 *   calc_draft_ts_<calculationId>   -> epoch ms of last write
 */
export const DRAFT_STORAGE_PREFIX = 'calc_draft_';
export const DRAFT_TS_SUFFIX = '_ts';
export const DRAFT_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000; // 7 days

export const draftDataKey = (calculationId: string) => `${DRAFT_STORAGE_PREFIX}${calculationId}`;
export const draftTsKey = (calculationId: string) =>
  `${draftDataKey(calculationId)}${DRAFT_TS_SUFFIX}`;

export interface DraftSnapshot {
  /** layerId -> digitize features still in the draft buffer */
  features: Record<number, GeoJSON.Feature[]>;
  timestamp: number;
}

/**
 * Read the saved snapshot for a calculation, or null when none/freshness
 * expired. Pure — caller passes a `storage` (defaults to window.localStorage).
 */
export function loadDraftSnapshot(
  calculationId: string,
  storage: Storage = window.localStorage,
): DraftSnapshot | null {
  const tsRaw = storage.getItem(draftTsKey(calculationId));
  if (!tsRaw) return null;

  const timestamp = parseInt(tsRaw, 10);
  if (Number.isNaN(timestamp)) return null;
  if (Date.now() - timestamp > DRAFT_MAX_AGE_MS) return null;

  const raw = storage.getItem(draftDataKey(calculationId));
  if (!raw) return null;

  try {
    const features = JSON.parse(raw) as Record<number, GeoJSON.Feature[]>;
    return { features, timestamp };
  } catch {
    return null;
  }
}

/**
 * Persist the draft buffer. Returns the timestamp written, or null if the
 * draft was empty (nothing saved).
 */
export function saveDraftSnapshot(
  calculationId: string,
  features: Record<number, GeoJSON.Feature[]>,
  storage: Storage = window.localStorage,
  now: number = Date.now(),
): number | null {
  const nonEmpty = Object.values(features).some((arr) => arr && arr.length > 0);
  if (!nonEmpty) return null;

  storage.setItem(draftDataKey(calculationId), JSON.stringify(features));
  storage.setItem(draftTsKey(calculationId), String(now));
  return now;
}

/** True when a saved snapshot exists and is within the 7-day freshness window. */
export function hasFreshDraft(
  calculationId: string,
  storage: Storage = window.localStorage,
): boolean {
  return loadDraftSnapshot(calculationId, storage) !== null;
}

/** Remove the draft snapshot for a calculation (after finalize/flush). */
export function clearDraftSnapshot(
  calculationId: string,
  storage: Storage = window.localStorage,
): void {
  storage.removeItem(draftDataKey(calculationId));
  storage.removeItem(draftTsKey(calculationId));
}
