/**
 * The NTFP outbox: what was typed, measured or photographed at a plot while there was no signal, kept on the phone until it can be sent (owner, 2026-10-22).
 *
 * Only a plot save, a position check or a photo that FAILED for want of a network is queued; online the writes go straight through as before. The queue lives in IndexedDB (a photo is a
 * Blob, which localStorage cannot hold), so it survives a closed tab or a phone that ran out of memory; where IndexedDB is not available it is kept in memory for the life of the page and
 * `persistent()` says so.
 *
 * Every queued item has its own id, sent as the `Idempotency-Key`: a send whose answer was lost in the dark is recognised by the server when it is tried again, so a photo is never kept twice.
 * A flush goes in the order things were done and stops at the first network failure. An item the server REFUSES (a mistake in the entries, the other way of recording already in use) is not
 * retried: it is marked rejected with the reason and kept for the person to see and discard, never dropped silently.
 */
import { ntfpApi, type NtfpFinding, type NtfpSpeciesEntry } from './api';

export type OutboxKind = 'plot' | 'presence' | 'photo';
export type OutboxState = 'waiting' | 'rejected';

export interface OutboxItem {
  id: string;
  calcId: string;
  kind: OutboxKind;
  plotNumber: number;
  createdAt: number;
  state: OutboxState;
  attempts: number;
  /** why the server refused it (state = rejected) */
  error?: string;
  findings?: NtfpFinding[];
  entries?: NtfpSpeciesEntry[];                                       // plot
  position?: { latitude: number; longitude: number; accuracy_m: number | null };   // presence; also kept with a photo
  blob?: Blob;                                                        // photo
  fileName?: string;                                                  // photo
}

const DB_NAME = 'cf_ntfp_outbox';
const STORE = 'queue';

let dbPromise: Promise<IDBDatabase> | null = null;
const memory = new Map<string, OutboxItem>();
let usingMemory = false;
const listeners = new Set<() => void>();

const notify = () => listeners.forEach((fn) => fn());
/** Be told whenever the queue changes (an item added, sent, refused or discarded). Returns the unsubscribe. */
export const subscribe = (fn: () => void): (() => void) => { listeners.add(fn); return () => { listeners.delete(fn); }; };

/** True when the queue survives a closed tab (IndexedDB works); false when it is only kept until the page closes. */
export const persistent = (): boolean => !usingMemory;

const openDB = (): Promise<IDBDatabase> => {
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve, reject) => {
    if (typeof indexedDB === 'undefined') { usingMemory = true; reject(new Error('indexedDB unavailable')); return; }
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => {
      const store = req.result.createObjectStore(STORE, { keyPath: 'id' });
      store.createIndex('calcId', 'calcId');
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => { usingMemory = true; reject(req.error); };
  });
  return dbPromise.catch((err) => { usingMemory = true; dbPromise = null; throw err; });
};

const tx = async <T,>(mode: IDBTransactionMode, run: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> => {
  const db = await openDB();
  return new Promise<T>((resolve, reject) => {
    const req = run(db.transaction(STORE, mode).objectStore(STORE));
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
};

const putItem = async (item: OutboxItem): Promise<void> => {
  try { await tx('readwrite', (s) => s.put(item)); } catch { memory.set(item.id, item); usingMemory = true; }   // no IndexedDB: kept in memory, and persistent() says so
};
const deleteItem = async (id: string): Promise<void> => {
  memory.delete(id);
  try { await tx('readwrite', (s) => s.delete(id)); } catch { /* nothing stored there to delete when IndexedDB is unavailable */ }
};

/** The queued items of a forest, oldest first. */
export const listOutbox = async (calcId: string): Promise<OutboxItem[]> => {
  let rows: OutboxItem[] = [];
  try { rows = (await tx('readonly', (s) => s.index('calcId').getAll(calcId))) as OutboxItem[]; } catch { /* the in-memory items below are all there is */ }
  const mem = Array.from(memory.values()).filter((i) => i.calcId === calcId && !rows.some((r) => r.id === i.id));
  return [...rows, ...mem].sort((a, b) => a.createdAt - b.createdAt);
};

const newId = (): string => (typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`);

/**
 * Queue something. A newer save of the same plot (or newer position check of it) replaces an older one still waiting: the plot is saved as a whole, so only the last matters.
 * Photos are never merged.
 */
export const enqueue = async (item: Omit<OutboxItem, 'id' | 'createdAt' | 'state' | 'attempts'>): Promise<OutboxItem> => {
  if (item.kind !== 'photo') {
    const older = (await listOutbox(item.calcId)).filter((i) => i.kind === item.kind && i.plotNumber === item.plotNumber && i.state === 'waiting');
    for (const o of older) await deleteItem(o.id);
  }
  const row: OutboxItem = { ...item, id: newId(), createdAt: Date.now(), state: 'waiting', attempts: 0 };
  await putItem(row);
  notify();
  return row;
};

export const discard = async (id: string): Promise<void> => { await deleteItem(id); notify(); };

/** A refused item put back to waiting (after the person fixed what refused it, e.g. deleted the other way's records). */
export const retry = async (item: OutboxItem): Promise<void> => {
  await putItem({ ...item, state: 'waiting', error: undefined, findings: undefined });
  notify();
};

/** The answer was "no signal, or try again": the same request will do later. Everything else the server said is an answer. */
export const isNetworkFailure = (err: any): boolean => {
  const status = err?.response?.status;
  if (!err?.response) return true;                                   // no response at all: offline, a dropped connection, a timeout
  return status === 401 || status === 408 || status === 429 || status === 502 || status === 503 || status === 504;
};

const send = (item: OutboxItem) => {
  const opts = { idempotencyKey: item.id };
  if (item.kind === 'plot') return ntfpApi.savePlot(item.calcId, item.plotNumber, item.entries ?? [], opts);
  if (item.kind === 'presence') return ntfpApi.checkPresence(item.calcId, item.plotNumber, item.position!, opts);
  return ntfpApi.uploadPhoto(item.calcId, item.plotNumber, item.blob!, item.fileName ?? 'photo.jpg', item.position ?? null, opts);
};

let flushing = false;
export const isFlushing = (): boolean => flushing;

export interface FlushResult { sent: number; rejected: number; waiting: number; offline: boolean }

/** Send what is waiting, in order. One flush at a time; stops at the first network failure (the rest would fail the same way). */
export const flushOutbox = async (calcId: string): Promise<FlushResult> => {
  if (flushing) return { sent: 0, rejected: 0, waiting: (await listOutbox(calcId)).filter((i) => i.state === 'waiting').length, offline: false };
  flushing = true;
  let sent = 0, rejected = 0, offline = false;
  try {
    notify();
    for (const item of (await listOutbox(calcId)).filter((i) => i.state === 'waiting')) {
      if (typeof navigator !== 'undefined' && navigator.onLine === false) { offline = true; break; }
      try {
        await send(item);
        await deleteItem(item.id);
        sent += 1;
      } catch (err: any) {
        if (isNetworkFailure(err)) {
          await putItem({ ...item, attempts: item.attempts + 1 });
          offline = true;
          break;
        }
        const detail = err?.response?.data?.detail;
        await putItem({
          ...item, attempts: item.attempts + 1, state: 'rejected',
          error: (typeof detail === 'string' ? detail : detail?.message) || `HTTP ${err?.response?.status}`,
          findings: Array.isArray(detail?.findings) ? detail.findings : undefined,
        });
        rejected += 1;
      }
    }
  } finally {
    flushing = false;
    notify();
  }
  const waiting = (await listOutbox(calcId)).filter((i) => i.state === 'waiting').length;
  return { sent, rejected, waiting, offline };
};

/** For tests: forget everything held in memory and the open database. */
export const _resetForTests = (): void => { memory.clear(); dbPromise = null; usingMemory = false; listeners.clear(); flushing = false; };
