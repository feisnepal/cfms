/**
 * Client-side IndexedDB cache (Cache Plan Phase 6).
 *
 * Three object stores: maps, charts, analysis — each with a TTL and a max
 * size budget. Used by the React Query layer (useCachedQuery) so that
 * map tiles, chart data and analysis responses survive reloads and tabs,
 * serving instantly (<50ms) on repeat visits.
 *
 * Falls back to a no-op in-memory map if IndexedDB is unavailable
 * (e.g. private mode), so callers never have to branch.
 */

const DB_NAME = 'cf_cache';
const DB_VERSION = 2;
const STORES = ['maps', 'charts', 'analysis', 'digitizeDrafts'] as const;
export type StoreName = (typeof STORES)[number];

const STORE_TTL: Record<StoreName, number> = {
  maps: 30 * 24 * 60 * 60 * 1000, // 30 days
  charts: 30 * 24 * 60 * 60 * 1000, // 30 days
  analysis: 14 * 24 * 60 * 60 * 1000, // 14 days
  digitizeDrafts: 30 * 24 * 60 * 60 * 1000, // 30 days — surviving drafts after crash/close
};

const STORE_MAX_SIZE: Record<StoreName, number> = {
  maps: 200 * 1024 * 1024, // 200 MB
  charts: 50 * 1024 * 1024, // 50 MB
  analysis: 100 * 1024 * 1024, // 100 MB
  digitizeDrafts: 50 * 1024 * 1024, // 50 MB (Gap 9.1 cap)
};

interface CacheRecord {
  key: string;
  calcId: string;
  value: unknown;
  size: number;
  createdAt: number;
  expiresAt: number;
}

let dbPromise: Promise<IDBDatabase> | null = null;
const memoryFallback = new Map<string, CacheRecord>();
let usingMemory = false;

function openDB(): Promise<IDBDatabase> {
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve, reject) => {
    if (typeof indexedDB === 'undefined') {
      usingMemory = true;
      reject(new Error('indexedDB unavailable'));
      return;
    }
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      for (const store of STORES) {
        if (!db.objectStoreNames.contains(store)) {
          db.createObjectStore(store, { keyPath: 'key' });
        }
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => {
      usingMemory = true;
      reject(req.error);
    };
  });
  return dbPromise;
}

function approxSize(value: unknown): number {
  try {
    return new Blob([JSON.stringify(value)]).size;
  } catch {
    return JSON.stringify(value).length;
  }
}

async function dbPut(store: StoreName, calcId: string, key: string, value: unknown) {
  const now = Date.now();
  const record: CacheRecord = {
    key,
    calcId,
    value,
    size: approxSize(value),
    createdAt: now,
    expiresAt: now + STORE_TTL[store],
  };
  try {
    const db = await openDB();
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(store, 'readwrite');
      tx.objectStore(store).put(record);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
    await enforceSizeLimit(store);
  } catch {
    memoryFallback.set(`${store}:${key}`, record);
  }
}

async function dbGet(store: StoreName, key: string): Promise<unknown | null> {
  try {
    const db = await openDB();
    const rec = await new Promise<CacheRecord | undefined>((resolve, reject) => {
      const tx = db.transaction(store, 'readonly');
      const req = tx.objectStore(store).get(key);
      req.onsuccess = () => resolve(req.result as CacheRecord | undefined);
      req.onerror = () => reject(req.error);
    });
    if (!rec) return null;
    if (rec.expiresAt < Date.now()) {
      await dbDelete(store, key);
      return null;
    }
    return rec.value;
  } catch {
    const rec = memoryFallback.get(`${store}:${key}`);
    if (rec && rec.expiresAt >= Date.now()) return rec.value;
    return null;
  }
}

async function dbDelete(store: StoreName, key: string) {
  try {
    const db = await openDB();
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(store, 'readwrite');
      tx.objectStore(store).delete(key);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  } catch {
    memoryFallback.delete(`${store}:${key}`);
  }
}

async function dbClearStore(store: StoreName, calcId?: string) {
  try {
    const db = await openDB();
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(store, 'readwrite');
      const os = tx.objectStore(store);
      if (calcId) {
        const idx = os.index('calcId');
        const range = IDBKeyRange.only(calcId);
        idx.openCursor(range).onsuccess = (e) => {
          const cursor = (e.target as IDBRequest<IDBCursorWithValue>).result;
          if (cursor) {
            cursor.delete();
            cursor.continue();
          }
        };
      } else {
        os.clear();
      }
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  } catch {
    for (const k of [...memoryFallback.keys()]) {
      if (k.startsWith(`${store}:`) && (!calcId || memoryFallback.get(k)?.calcId === calcId)) {
        memoryFallback.delete(k);
      }
    }
  }
}

async function dbStoreSize(store: StoreName): Promise<number> {
  try {
    const db = await openDB();
    return await new Promise<number>((resolve, reject) => {
      const tx = db.transaction(store, 'readonly');
      const req = tx.objectStore(store).count();
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  } catch {
    let n = 0;
    for (const k of memoryFallback.keys()) if (k.startsWith(`${store}:`)) n++;
    return n;
  }
}

async function enforceSizeLimit(store: StoreName) {
  // Best-effort: if over budget, drop oldest expired/oldest records.
  const max = STORE_MAX_SIZE[store];
  try {
    const db = await openDB();
    const records = await new Promise<CacheRecord[]>((resolve, reject) => {
      const tx = db.transaction(store, 'readonly');
      const req = tx.objectStore(store).getAll();
      req.onsuccess = () => resolve(req.result as CacheRecord[]);
      req.onerror = () => reject(req.error);
    });
    let total = records.reduce((s, r) => s + r.size, 0);
    if (total <= max) return;
    const sorted = records.sort((a, b) => a.createdAt - b.createdAt);
    for (const rec of sorted) {
      if (total <= max) break;
      await dbDelete(store, rec.key);
      total -= rec.size;
    }
  } catch {
    /* memory fallback: ignore size enforcement */
  }
}

export const browserCache = {
  getMap: (calcId: string, key: string) => dbGet('maps', `${calcId}:${key}`),
  setMap: (calcId: string, key: string, v: unknown) => dbPut('maps', calcId, `${calcId}:${key}`, v),
  clearMaps: (calcId?: string) => dbClearStore('maps', calcId),

  getChart: (calcId: string, key: string) => dbGet('charts', `${calcId}:${key}`),
  setChart: (calcId: string, key: string, v: unknown) => dbPut('charts', calcId, `${calcId}:${key}`, v),
  clearCharts: (calcId?: string) => dbClearStore('charts', calcId),

  getAnalysis: (calcId: string, key: string) => dbGet('analysis', `${calcId}:${key}`),
  setAnalysis: (calcId: string, key: string, v: unknown) => dbPut('analysis', calcId, `${calcId}:${key}`, v),
  clearAnalysis: (calcId?: string) => dbClearStore('analysis', calcId),

  getDigitizeDraft: (calcId: string, layerId: number) => dbGet('digitizeDrafts', `${calcId}:${layerId}`),
  setDigitizeDraft: (calcId: string, layerId: number, v: unknown) => dbPut('digitizeDrafts', calcId, `${calcId}:${layerId}`, v),
  clearDigitizeDraft: (calcId?: string) => dbClearStore('digitizeDrafts', calcId),

  clearAll: async (calcId?: string) => {
    await Promise.all([
      dbClearStore('maps', calcId),
      dbClearStore('charts', calcId),
      dbClearStore('analysis', calcId),
      dbClearStore('digitizeDrafts', calcId),
    ]);
  },

  getStats: async () => ({
    maps: await dbStoreSize('maps'),
    charts: await dbStoreSize('charts'),
    analysis: await dbStoreSize('analysis'),
    backend: usingMemory ? 'memory' : 'indexeddb',
  }),

  cleanup: async () => {
    for (const store of STORES) await enforceSizeLimit(store);
  },
};
