/**
 * The page's side of offline support: register the service worker (`public/sw.js`), tell it when to forget kept data, and say whether the page is ready to open offline.
 *
 * Production builds only: in development the dev server's constantly changing modules would be fought over by a cache. Nothing here imports the app, so it can be used from anywhere
 * (the API layer clears the kept data when the person signs out).
 */

export type OfflineReadiness = 'ready' | 'pending' | 'unsupported';

const supported = (): boolean => typeof navigator !== 'undefined' && 'serviceWorker' in navigator && Boolean(import.meta.env.PROD);

/** The built files this page has loaded so far (including those loaded before the worker took control): the worker keeps them too. */
export const loadedAssetUrls = (): string[] => {
  if (typeof performance === 'undefined') return [];
  return performance.getEntriesByType('resource').map((e) => {
    try { return new URL(e.name).pathname; } catch { return ''; }
  }).filter((p) => p.startsWith('/assets/'));
};

const post = (message: Record<string, unknown>): void => {
  if (!supported()) return;
  const target = navigator.serviceWorker.controller;
  if (target) { target.postMessage(message); return; }
  void navigator.serviceWorker.ready.then((reg) => reg.active?.postMessage(message)).catch(() => undefined);
};

/** Forget every kept answer of the API: somebody else is signing in, or the person signed out. */
export const clearOfflineApiCache = (): void => post({ type: 'CLEAR_API' });

export const registerOfflineSupport = (): void => {
  if (!supported()) return;
  const start = () => {
    navigator.serviceWorker.register('/sw.js').then(() => navigator.serviceWorker.ready).then((reg) => {
      // the first visit: what was loaded before the worker took control is kept now
      reg.active?.postMessage({ type: 'WARM', urls: loadedAssetUrls() });
    }).catch(() => undefined);   // no worker only means no offline start: the page works as it always did
  };
  if (document.readyState === 'complete') start();
  else window.addEventListener('load', start, { once: true });
};

export const offlineReadiness = (): OfflineReadiness => {
  if (!supported()) return 'unsupported';
  return navigator.serviceWorker.controller ? 'ready' : 'pending';
};

/** Be told when the worker takes control (the page is then kept for offline). Returns the unsubscribe. */
export const onOfflineReadinessChange = (fn: () => void): (() => void) => {
  if (!supported()) return () => undefined;
  navigator.serviceWorker.addEventListener('controllerchange', fn);
  return () => navigator.serviceWorker.removeEventListener('controllerchange', fn);
};
