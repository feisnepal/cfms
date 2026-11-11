/*
 * Offline support for the Community Forest Management System (service worker).
 *
 * Purpose (owner, 2026-10-22): a field team opens the forest's NTFP page while they still have a signal, walks into the forest, and keeps working: the page can be reloaded, the
 * map and the data are the ones last seen, and what they enter goes to the outbox (src/services/ntfpOutbox.ts) until the signal is back. This file only makes the page itself and its
 * reading data available offline; saving is the outbox's job.
 *
 * What is kept, and how:
 *   shell   the page (index.html), network first (a new release is picked up when there is a signal), the kept copy when there is none.
 *   assets  /assets/*: built files named by a hash of their content, so the kept copy is always the right one: cache first.
 *   static  other files of the site (logo, guides): kept copy at once, refreshed in the background.
 *   api     GET /api/* whose path is on the list below: network first (the newest data when there is a signal), the last seen answer when there is none.
 *   tiles   map tiles (OpenStreetMap, ArcGIS imagery) that were looked at: cache first, a limited number.
 * Everything else (every write, every other site, downloads) goes straight to the network, untouched.
 *
 * Privacy: kept API answers belong to whoever was signed in. The page tells this worker to forget them when somebody signs in or out (message CLEAR_API), and household data, admin and
 * account paths are never kept.
 *
 * Only registered in a production build (src/pwa/offline.ts); in development the dev server's changing modules would be fought over by a cache.
 */
const BUILD = '__BUILD_ID__';
const SHELL = 'cf-shell-v1';
const ASSETS = 'cf-assets-v1';
const STATIC = 'cf-static-v1';
const API = 'cf-api-v1';
const TILES = 'cf-tiles-v1';
const KEEP = [SHELL, ASSETS, STATIC, API, TILES];
// a kept answer is matched by its address alone: a `Vary` header from the server (Origin, Accept-Encoding) must not turn a kept copy into a miss offline
const MATCH = { ignoreVary: true };

const MAX_ASSETS = 700;
const MAX_TILES = 600;
const MAX_API = 400;
const API_MAX_AGE_MS = 14 * 24 * 60 * 60 * 1000;
const API_MAX_JSON_BYTES = 12 * 1024 * 1024;
const API_MAX_IMAGE_BYTES = 6 * 1024 * 1024;
const SHELL_WAIT_MS = 3000;
const API_WAIT_MS = 8000;

// Never kept, wherever they appear in the path: personal data, accounts, files made for download.
const API_DENY = /household|admin|password|reset|verify|token|secret|payment|billing|export|download|upload|invitation|otp|phone/i;
const IMAGE_PATH = /\/ntfp\/photos\/[^/]+$/;

const sameSite = (url) => url.origin === self.location.origin;

/** A map tile: the two tile servers the maps use. */
function isTile(url) {
  return /\.tile\.openstreetmap\.org$/.test(url.hostname) || (url.hostname === 'server.arcgisonline.com' && url.pathname.includes('/tile/'));
}

/** Is this GET answer worth keeping for offline use? Decided by the path alone, before any request is made. */
function cacheableApi(url) {
  if (!url.pathname.startsWith('/api/')) return false;
  return !API_DENY.test(url.pathname);
}

/** Wait for the network, but only so long: on a weak signal the kept copy is better than a spinner. Rejects on timeout or failure. */
function fetchWithin(request, ms) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('timeout')), ms);
    fetch(request).then((r) => { clearTimeout(timer); resolve(r); }, (e) => { clearTimeout(timer); reject(e); });
  });
}

async function trim(cacheName, max) {
  const cache = await caches.open(cacheName);
  const keys = await cache.keys();
  for (const k of keys.slice(0, Math.max(0, keys.length - max))) await cache.delete(k);   // the oldest go first
}

async function put(cacheName, request, response, max) {
  try {
    const cache = await caches.open(cacheName);
    await cache.put(request, response);
    await trim(cacheName, max);
  } catch (e) {
    /* a full or unavailable cache must never break the page: the answer is still returned to it */
  }
}

// ── the page ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

async function shellRequest(request) {
  const cache = await caches.open(SHELL);
  try {
    const res = await fetchWithin(request, SHELL_WAIT_MS);
    if (res.ok && (res.headers.get('content-type') || '').includes('text/html')) await cache.put('/index.html', res.clone());
    return res;
  } catch (e) {
    const kept = await cache.match('/index.html', MATCH);
    if (kept) return kept;
    return Response.error();
  }
}

// ── built files ───────────────────────────────────────────────────────────────────────────────────────────────────────────

async function assetRequest(request) {
  const cache = await caches.open(ASSETS);
  const kept = await cache.match(request, MATCH);
  if (kept) return kept;
  try {
    const res = await fetch(request);
    if (res.ok) await put(ASSETS, request, res.clone(), MAX_ASSETS);
    return res;
  } catch (e) {
    return Response.error();
  }
}

async function staticRequest(request) {
  const cache = await caches.open(STATIC);
  const kept = await cache.match(request, MATCH);
  const refresh = fetch(request).then(async (res) => { if (res.ok) await put(STATIC, request, res.clone(), 100); return res; });
  if (kept) { refresh.catch(() => {}); return kept; }
  try { return await refresh; } catch (e) { return Response.error(); }
}

// ── data ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────

/** The answer with the time it was kept, so an answer too old to trust can be recognised. */
async function stamped(res) {
  const headers = new Headers(res.headers);
  headers.set('x-sw-cached-at', String(Date.now()));
  return new Response(await res.clone().arrayBuffer(), { status: res.status, statusText: res.statusText, headers });
}

function worthKeeping(url, res) {
  if (!res.ok || res.status !== 200) return false;
  if ((res.headers.get('cache-control') || '').includes('no-store')) return false;
  const type = res.headers.get('content-type') || '';
  const size = Number(res.headers.get('content-length') || 0);
  if (type.includes('json')) return size <= API_MAX_JSON_BYTES;
  if (type.startsWith('image/') && IMAGE_PATH.test(url.pathname)) return size <= API_MAX_IMAGE_BYTES;
  return false;
}

async function apiRequest(request) {
  const url = new URL(request.url);
  // the key is the address alone: the sign-in header must not make two entries of one answer
  const key = new Request(url.origin + url.pathname + url.search);
  const cache = await caches.open(API);
  try {
    const res = await fetchWithin(request, API_WAIT_MS);
    if (worthKeeping(url, res)) await put(API, key, await stamped(res), MAX_API);
    return res;
  } catch (e) {
    const kept = await cache.match(key, MATCH);
    if (kept) {
      const at = Number(kept.headers.get('x-sw-cached-at') || 0);
      if (!at || Date.now() - at <= API_MAX_AGE_MS) return kept;
    }
    return Response.error();
  }
}

// ── map tiles ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

async function tileRequest(request) {
  const cache = await caches.open(TILES);
  const kept = await cache.match(request.url, MATCH);
  if (kept) return kept;
  try {
    // a tile image asked for without CORS comes back opaque, and an opaque answer is counted as megabytes by the browser: ask again with CORS (the tile server allows it)
    const res = await fetch(new Request(request.url, { mode: 'cors', credentials: 'omit' }));
    if (res.ok) await put(TILES, request.url, res.clone(), MAX_TILES);
    return res;
  } catch (e) {
    return Response.error();
  }
}

// ── events ────────────────────────────────────────────────────────────────────────────────────────────────────────────────

/** Keep the page and the files it names right away, so the very first visit already works offline once it ends. */
async function precacheShell() {
  const res = await fetch('/', { cache: 'reload' });
  if (!res.ok) return;
  const html = await res.clone().text();
  const shell = await caches.open(SHELL);
  await shell.put('/index.html', res);
  const assets = await caches.open(ASSETS);
  const names = Array.from(new Set(html.match(/\/assets\/[^"'\s)>]+/g) || []));
  await Promise.all(names.map(async (name) => {
    try {
      if (!(await assets.match(name, MATCH))) {
        const r = await fetch(name);
        if (r.ok) await assets.put(name, r);
      }
    } catch (e) {
      /* one file that would not come now will be kept when the page asks for it */
    }
  }));
}

self.addEventListener('install', (event) => {
  event.waitUntil(precacheShell().catch(() => undefined).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    for (const name of await caches.keys()) if (!KEEP.includes(name)) await caches.delete(name);
    await self.clients.claim();
  })());
});

function route(event) {
  const request = event.request;
  if (request.method !== 'GET') return null;
  const url = new URL(request.url);
  if (isTile(url)) return tileRequest(request);
  if (url.pathname.startsWith('/api/')) return cacheableApi(url) ? apiRequest(request) : null;
  if (!sameSite(url) || url.pathname === '/sw.js') return null;
  if (request.mode === 'navigate') return shellRequest(request);
  if (url.pathname.startsWith('/assets/')) return assetRequest(request);
  if (/\.(png|svg|ico|webp|jpg|jpeg|woff2?|pdf|md)$/i.test(url.pathname)) return staticRequest(request);
  return null;
}

self.addEventListener('fetch', (event) => {
  const answer = route(event);
  if (answer) event.respondWith(answer);
});

self.addEventListener('message', (event) => {
  const data = event.data || {};
  if (data.type === 'CLEAR_API') {
    event.waitUntil(caches.delete(API));
  } else if (data.type === 'WARM' && Array.isArray(data.urls)) {
    // the built files the page has loaded before this worker took control: keep them too
    event.waitUntil(Promise.all(data.urls.filter((u) => typeof u === 'string' && u.startsWith('/assets/')).map(async (u) => {
      try {
        const cache = await caches.open(ASSETS);
        if (!(await cache.match(u, MATCH))) {
          const r = await fetch(u);
          if (r.ok) await put(ASSETS, u, r, MAX_ASSETS);
        }
      } catch (e) {
        /* it will be kept when the page asks for it while online */
      }
    })));
  } else if (data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});

// for the tests: the decisions that do not need a browser
self.__cfSw = { BUILD, cacheableApi, worthKeeping, isTile, route, KEEP };
