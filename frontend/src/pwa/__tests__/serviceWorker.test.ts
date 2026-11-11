import { describe, it, expect, vi, beforeEach } from 'vitest';
// the worker is a plain file in public/: it is loaded as text and run against a fake worker scope, the way a browser would run it
import swSource from '../../../public/sw.js?raw';

const ORIGIN = 'https://app.test';
const abs = (k: string | Request) => new URL(typeof k === 'string' ? k : k.url, ORIGIN).href;

/** A Cache that keeps answers by address, in the order they were put. */
function fakeCache() {
  const m = new Map<string, Response>();
  return {
    m,
    match: async (k: string | Request) => m.get(abs(k))?.clone(),
    put: async (k: string | Request, r: Response) => { m.delete(abs(k)); m.set(abs(k), r); },
    delete: async (k: string | Request) => m.delete(abs(k)),
    keys: async () => Array.from(m.keys()).map((u) => new Request(u)),
  };
}

function load(fetchImpl: (req: Request | string) => Promise<Response>) {
  const store = new Map<string, ReturnType<typeof fakeCache>>();
  const caches = {
    open: async (n: string) => { if (!store.has(n)) store.set(n, fakeCache()); return store.get(n)!; },
    keys: async () => Array.from(store.keys()),
    delete: async (n: string) => store.delete(n),
  };
  const listeners: Record<string, (e: any) => void> = {};
  const self: any = { location: { origin: ORIGIN }, addEventListener: (t: string, fn: (e: any) => void) => { listeners[t] = fn; }, skipWaiting: vi.fn(), clients: { claim: vi.fn() } };
  const fetchMock = vi.fn(fetchImpl);
  new Function('self', 'caches', 'fetch', swSource)(self, caches, fetchMock);
  const sw = self.__cfSw;
  const ask = (url: string, init: { method?: string; mode?: string; headers?: Record<string, string> } = {}) => {
    const request = new Request(url.startsWith('http') ? url : ORIGIN + url, { method: init.method ?? 'GET', headers: init.headers });
    if (init.mode) Object.defineProperty(request, 'mode', { value: init.mode });
    return sw.route({ request }) as Promise<Response> | null;
  };
  return { sw, store, listeners, fetchMock, ask, self };
}

const json = (body: unknown, extra: Record<string, string> = {}) => new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json', ...extra } });
const html = (body = '<html></html>') => new Response(body, { status: 200, headers: { 'content-type': 'text/html' } });
const offline = () => Promise.reject(new TypeError('Failed to fetch'));

beforeEach(() => { vi.useRealTimers(); });

describe('which API answers are kept', () => {
  const { sw } = load(offline);
  const u = (p: string) => new URL(ORIGIN + p);
  it('keeps the forest\'s data and nothing personal or short-lived', () => {
    expect(sw.cacheableApi(u('/api/calculations/c1/ntfp/design'))).toBe(true);
    expect(sw.cacheableApi(u('/api/auth/me'))).toBe(true);
    expect(sw.cacheableApi(u('/api/translations/overlay'))).toBe(true);
    for (const p of ['/api/household/calculations/c1/households', '/api/admin/users', '/api/calculations/c1/tile-token', '/api/auth/password/reset',
      '/api/calculations/c1/export/docx', '/api/calculations/c1/download', '/api/auth/phone/verify']) expect(sw.cacheableApi(u(p)), p).toBe(false);
    expect(sw.cacheableApi(u('/assets/x.js'))).toBe(false);
  });
});

describe('what the worker handles at all', () => {
  it('leaves every write, every other site and itself to the network', () => {
    const { ask } = load(offline);
    expect(ask('/api/calculations/c1/ntfp/plots/1/observations', { method: 'PUT' })).toBeNull();
    expect(ask('/api/calculations/c1/ntfp/plots/1/photos', { method: 'POST' })).toBeNull();
    expect(ask('https://example.org/x.js')).toBeNull();
    expect(ask('/sw.js')).toBeNull();
    expect(ask('/api/household/calculations/c1/households')).toBeNull();
    expect(ask('/something.json')).toBeNull();
  });
  it('takes the page, the built files, the logo, the API reads and the two tile servers', () => {
    const { ask } = load(offline);
    expect(ask('/calculations/c1', { mode: 'navigate' })).not.toBeNull();
    expect(ask('/assets/index-abc.js')).not.toBeNull();
    expect(ask('/cfms-logo.png')).not.toBeNull();
    expect(ask('/api/calculations/c1')).not.toBeNull();
    expect(ask('https://api.other.test/api/calculations/c1')).not.toBeNull();        // the API may live on another address: decided by the path
    expect(ask('https://a.tile.openstreetmap.org/8/1/2.png')).not.toBeNull();
    expect(ask('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/8/1/2')).not.toBeNull();
    expect(ask('https://server.arcgisonline.com/ArcGIS/rest/services/x/MapServer/query')).toBeNull();
  });
});

describe('API answers: the newest when there is a signal, the last seen when there is none', () => {
  it('keeps what it got and serves it when the network fails', async () => {
    let up = true;
    const { ask } = load(() => (up ? Promise.resolve(json({ n: 1 })) : offline()));
    expect(await (await ask('/api/calculations/c1/ntfp/design'))!.json()).toEqual({ n: 1 });
    up = false;
    const kept = await ask('/api/calculations/c1/ntfp/design');
    expect(await kept!.json()).toEqual({ n: 1 });
    expect(Number(kept!.headers.get('x-sw-cached-at'))).toBeGreaterThan(0);
  });

  it('serves the kept answer even when the sign-in header differs, and when the server sent Vary', async () => {
    let up = true;
    const { ask } = load(() => (up ? Promise.resolve(json({ ok: true }, { vary: 'Origin, Accept-Encoding' })) : offline()));
    await ask('/api/calculations/c1/ntfp/design?x=1', { headers: { Authorization: 'Bearer a' } });
    up = false;
    const kept = await ask('/api/calculations/c1/ntfp/design?x=1', { headers: { Authorization: 'Bearer b' } });
    expect(await kept!.json()).toEqual({ ok: true });
  });

  it('answers with an error (the page sees a network failure) when nothing was kept', async () => {
    const { ask } = load(offline);
    expect((await ask('/api/calculations/c1/ntfp/design'))!.type).toBe('error');
  });

  it('does not trust an answer older than two weeks', async () => {
    let up = true;
    const { ask, store } = load(() => (up ? Promise.resolve(json({ n: 1 })) : offline()));
    await ask('/api/calculations/c1/x');
    const cache = store.get('cf-api-v1')!;
    const [key] = Array.from(cache.m.keys());
    const old = new Response('{"n":1}', { status: 200, headers: { 'content-type': 'application/json', 'x-sw-cached-at': String(Date.now() - 15 * 24 * 3600 * 1000) } });
    cache.m.set(key, old);
    up = false;
    expect((await ask('/api/calculations/c1/x'))!.type).toBe('error');
  });

  it('keeps only JSON and the plot photos, and nothing marked no-store or failed', async () => {
    const answers: Record<string, Response> = {
      '/api/a': json({ a: 1 }),
      '/api/b': new Response('x', { status: 200, headers: { 'content-type': 'text/plain' } }),
      '/api/c': json({ c: 1 }, { 'cache-control': 'no-store' }),
      '/api/d': new Response('{}', { status: 500, headers: { 'content-type': 'application/json' } }),
      '/api/calculations/c1/ntfp/photos/p1': new Response('img', { status: 200, headers: { 'content-type': 'image/jpeg', 'content-length': '3' } }),
      '/api/calculations/c1/other/image': new Response('img', { status: 200, headers: { 'content-type': 'image/jpeg', 'content-length': '3' } }),
    };
    const { ask, store } = load((r) => Promise.resolve(answers[new URL(typeof r === 'string' ? r : r.url).pathname].clone()));
    for (const p of Object.keys(answers)) await ask(p);
    const kept = Array.from(store.get('cf-api-v1')!.m.keys()).map((k) => new URL(k).pathname);
    expect(kept.sort()).toEqual(['/api/a', '/api/calculations/c1/ntfp/photos/p1']);
  });

  it('waits only a while for a slow network, then falls back to the kept answer', async () => {
    vi.useFakeTimers();
    let slow = false;
    const { ask } = load(() => (slow ? new Promise<Response>(() => undefined) : Promise.resolve(json({ n: 1 }))));
    await ask('/api/calculations/c1/x');
    slow = true;
    const pending = ask('/api/calculations/c1/x')!;
    await vi.advanceTimersByTimeAsync(8100);
    expect(await (await pending).json()).toEqual({ n: 1 });
  });

  it('keeps at most 400 answers, forgetting the oldest', async () => {
    const { ask, store } = load(() => Promise.resolve(json({ ok: 1 })));
    for (let i = 0; i < 405; i += 1) await ask(`/api/calculations/c1/item${i}`);
    const keys = Array.from(store.get('cf-api-v1')!.m.keys());
    expect(keys).toHaveLength(400);
    expect(keys[0]).toContain('/item5');
  });
});

describe('the page', () => {
  it('is served from the kept copy for any address when there is no signal', async () => {
    let up = true;
    const { ask } = load(() => (up ? Promise.resolve(html('<html>shell</html>')) : offline()));
    await ask('/calculations/c1', { mode: 'navigate' });
    up = false;
    const res = await ask('/calculations/other/path?surface=field/ntfp', { mode: 'navigate' });
    expect(await res!.text()).toContain('shell');
  });
  it('does not keep an error page as the page', async () => {
    const { ask, store } = load(() => Promise.resolve(new Response('bad gateway', { status: 502, headers: { 'content-type': 'text/html' } })));
    await ask('/', { mode: 'navigate' });
    expect(store.get('cf-shell-v1')?.m.size ?? 0).toBe(0);
  });
  it('answers with an error when it was never kept', async () => {
    const { ask } = load(offline);
    expect((await ask('/', { mode: 'navigate' }))!.type).toBe('error');
  });
});

describe('built files and tiles', () => {
  it('keeps a built file and does not ask the network for it again', async () => {
    const { ask, fetchMock } = load(() => Promise.resolve(new Response('js', { status: 200, headers: { 'content-type': 'text/javascript' } })));
    await ask('/assets/index-abc.js');
    await ask('/assets/index-abc.js');
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
  it('asks for a tile with CORS (an opaque one would count as megabytes), keeps it and serves it offline', async () => {
    let up = true;
    const modes: string[] = [];
    const { ask } = load((r) => { modes.push((r as Request).mode); return up ? Promise.resolve(new Response('png', { status: 200 })) : offline(); });
    await ask('https://a.tile.openstreetmap.org/8/1/2.png');
    expect(modes).toEqual(['cors']);
    up = false;
    expect(await (await ask('https://a.tile.openstreetmap.org/8/1/2.png'))!.text()).toBe('png');
    expect((await ask('https://a.tile.openstreetmap.org/8/9/9.png'))!.type).toBe('error');    // a tile never looked at is simply missing
  });
});

describe('install, activate and messages', () => {
  it('keeps the page and the files it names at install, so the first visit is already enough', async () => {
    const { listeners, store, self } = load((r) => {
      const u = typeof r === 'string' ? r : r.url;
      return Promise.resolve(u.endsWith('/') || u === '/' ? html('<script src="/assets/index-1.js"></script><link href="/assets/index-1.css">') : new Response('file', { status: 200 }));
    });
    let waited: Promise<unknown> = Promise.resolve();
    listeners.install({ waitUntil: (p: Promise<unknown>) => { waited = p; } });
    await waited;
    expect(store.get('cf-shell-v1')!.m.size).toBe(1);
    expect(Array.from(store.get('cf-assets-v1')!.m.keys()).map((k) => new URL(k).pathname).sort()).toEqual(['/assets/index-1.css', '/assets/index-1.js']);
    expect(self.skipWaiting).toHaveBeenCalled();
  });
  it('still installs when the network fails (nothing is kept, the page works as before)', async () => {
    const { listeners, self } = load(offline);
    let waited: Promise<unknown> = Promise.resolve();
    listeners.install({ waitUntil: (p: Promise<unknown>) => { waited = p; } });
    await expect(waited).resolves.toBeUndefined();
    expect(self.skipWaiting).toHaveBeenCalled();
  });
  it('forgets the caches of older versions at activate and takes control', async () => {
    const { listeners, store, self } = load(offline);
    store.set('cf-assets-v0', fakeCache());
    store.set('cf-api-v1', fakeCache());
    let waited: Promise<unknown> = Promise.resolve();
    listeners.activate({ waitUntil: (p: Promise<unknown>) => { waited = p; } });
    await waited;
    expect(Array.from(store.keys())).toEqual(['cf-api-v1']);
    expect(self.clients.claim).toHaveBeenCalled();
  });
  it('forgets every kept API answer on request (somebody signs in or out), and only those', async () => {
    const { listeners, store, ask } = load(() => Promise.resolve(json({ a: 1 })));
    await ask('/api/calculations/c1/x');
    store.set('cf-assets-v1', fakeCache());
    let waited: Promise<unknown> = Promise.resolve();
    listeners.message({ data: { type: 'CLEAR_API' }, waitUntil: (p: Promise<unknown>) => { waited = p; } });
    await waited;
    expect(store.has('cf-api-v1')).toBe(false);
    expect(store.has('cf-assets-v1')).toBe(true);
  });
  it('keeps the built files the page already loaded when asked, and nothing else', async () => {
    const { listeners, store, fetchMock } = load(() => Promise.resolve(new Response('f', { status: 200 })));
    let waited: Promise<unknown> = Promise.resolve();
    listeners.message({ data: { type: 'WARM', urls: ['/assets/a.js', '/api/secret', 'https://evil.test/assets/x.js', '/assets/b.js'] }, waitUntil: (p: Promise<unknown>) => { waited = p; } });
    await waited;
    expect(Array.from(store.get('cf-assets-v1')!.m.keys()).map((k) => new URL(k).pathname).sort()).toEqual(['/assets/a.js', '/assets/b.js']);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
