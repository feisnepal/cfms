/**
 * "Data was imported" signal (UPLOAD_EXPERIENCE_PLAN.md, UP-4).
 *
 * "Add data" imports from outside the tab that owns the data, so the tab and the workflow readiness (what unlocks Results) know nothing about
 * it until the page is reloaded. Add data sends this when its run finishes; the pieces that hold imported data listen and reload.
 */
const EVENT = 'forest:data-imported';

export interface DataImportedDetail {
  /** Canonical purpose ids of the files that were handled (households, field_inventory, trees ...). */
  purposes: string[];
}

export function emitDataImported(purposes: string[]): void {
  window.dispatchEvent(new CustomEvent<DataImportedDetail>(EVENT, { detail: { purposes } }));
}

/** Subscribe; returns the unsubscribe function. */
export function onDataImported(cb: (detail: DataImportedDetail) => void): () => void {
  const handler = (e: Event) => cb((e as CustomEvent<DataImportedDetail>).detail ?? { purposes: [] });
  window.addEventListener(EVENT, handler);
  return () => window.removeEventListener(EVENT, handler);
}
