import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import * as api from '../api';
import { _resetForTests, discard, enqueue, flushOutbox, isNetworkFailure, listOutbox, persistent, retry } from '../ntfpOutbox';

vi.mock('../api', async (orig) => {
  const actual = await orig<typeof import('../api')>();
  return { ...actual, ntfpApi: { ...actual.ntfpApi, savePlot: vi.fn(), checkPresence: vi.fn(), uploadPhoto: vi.fn() } };
});
const m = api.ntfpApi as unknown as Record<'savePlot' | 'checkPresence' | 'uploadPhoto', ReturnType<typeof vi.fn>>;

const entry = (n: number) => ({ species_key: 'x', count_total: n, weights: [] });
const plot = (n: number, count = 1) => ({ calcId: 'c1', kind: 'plot' as const, plotNumber: n, entries: [entry(count)] });
const refused = (code: string, message: string, findings?: unknown[]) => ({ response: { status: 422, data: { detail: { code, message, findings } } } });
const noSignal = () => ({ message: 'Network Error' });          // axios gives no response when the phone has no signal

beforeEach(() => {
  _resetForTests();
  (['savePlot', 'checkPresence', 'uploadPhoto'] as const).forEach((k) => m[k].mockReset());
  Object.defineProperty(navigator, 'onLine', { configurable: true, value: true });
});
afterEach(() => { Object.defineProperty(navigator, 'onLine', { configurable: true, value: true }); });

describe('what counts as "no signal"', () => {
  it('is no response, a timeout, a busy server or an expired sign-in; not an answer about the data', () => {
    expect(isNetworkFailure({ message: 'Network Error' })).toBe(true);
    for (const s of [401, 408, 429, 502, 503, 504]) expect(isNetworkFailure({ response: { status: s } })).toBe(true);
    for (const s of [400, 403, 404, 409, 413, 415, 422]) expect(isNetworkFailure({ response: { status: s } })).toBe(false);
  });
});

describe('the queue', () => {
  it('lists a forest\'s items oldest first and keeps forests apart', async () => {
    await enqueue(plot(1));
    await enqueue({ ...plot(2), calcId: 'c2' });
    await enqueue(plot(3));
    expect((await listOutbox('c1')).map((i) => i.plotNumber)).toEqual([1, 3]);
    expect((await listOutbox('c2')).map((i) => i.plotNumber)).toEqual([2]);
    expect(persistent()).toBe(false);          // jsdom has no IndexedDB: the memory fallback says so
  });

  it('keeps only the newest save of a plot, but never merges photos', async () => {
    await enqueue(plot(1, 5));
    const last = await enqueue(plot(1, 9));
    expect((await listOutbox('c1')).map((i) => i.id)).toEqual([last.id]);
    const photo = { calcId: 'c1', kind: 'photo' as const, plotNumber: 1, blob: new Blob(['a']), fileName: 'a.jpg' };
    await enqueue(photo);
    await enqueue(photo);
    expect((await listOutbox('c1')).filter((i) => i.kind === 'photo')).toHaveLength(2);
  });

  it('lets the person discard an item', async () => {
    const i = await enqueue(plot(1));
    await discard(i.id);
    expect(await listOutbox('c1')).toEqual([]);
  });
});

describe('sending', () => {
  it('sends in order, with each item\'s id as its idempotency key, and empties the queue', async () => {
    m.savePlot.mockResolvedValue({ ok: true });
    m.checkPresence.mockResolvedValue({});
    m.uploadPhoto.mockResolvedValue({});
    const a = await enqueue(plot(1));
    const b = await enqueue({ calcId: 'c1', kind: 'presence', plotNumber: 1, position: { latitude: 28, longitude: 84, accuracy_m: 5 } });
    const c = await enqueue({ calcId: 'c1', kind: 'photo', plotNumber: 1, blob: new Blob(['a']), fileName: 'a.jpg', position: { latitude: 28, longitude: 84, accuracy_m: 5 } });
    const r = await flushOutbox('c1');
    expect(r).toEqual({ sent: 3, rejected: 0, waiting: 0, offline: false });
    expect(m.savePlot).toHaveBeenCalledWith('c1', 1, a.entries, { idempotencyKey: a.id });
    expect(m.checkPresence).toHaveBeenCalledWith('c1', 1, b.position, { idempotencyKey: b.id });
    expect(m.uploadPhoto.mock.calls[0][5]).toEqual({ idempotencyKey: c.id });
    expect(await listOutbox('c1')).toEqual([]);
  });

  it('stops at the first failure for want of a signal and keeps everything for later', async () => {
    m.savePlot.mockRejectedValue(noSignal());
    const a = await enqueue(plot(1));
    await enqueue(plot(2));
    const r = await flushOutbox('c1');
    expect(r).toMatchObject({ sent: 0, rejected: 0, waiting: 2, offline: true });
    expect(m.savePlot).toHaveBeenCalledTimes(1);                       // the second would fail the same way
    const items = await listOutbox('c1');
    expect(items.map((i) => i.state)).toEqual(['waiting', 'waiting']);
    expect(items.find((i) => i.id === a.id)!.attempts).toBe(1);
    m.savePlot.mockResolvedValue({ ok: true });
    expect(await flushOutbox('c1')).toMatchObject({ sent: 2, waiting: 0 });   // the same items go when the signal is back
  });

  it('does not even try while the phone says it is offline', async () => {
    Object.defineProperty(navigator, 'onLine', { configurable: true, value: false });
    await enqueue(plot(1));
    expect(await flushOutbox('c1')).toMatchObject({ sent: 0, waiting: 1, offline: true });
    expect(m.savePlot).not.toHaveBeenCalled();
  });

  it('keeps an item the server refused, with the reason and the findings, and goes on with the next', async () => {
    m.savePlot
      .mockRejectedValueOnce(refused('plot.invalid', 'Nothing was saved: check the entries.', [{ severity: 'error', code: 'count.parts_exceed_total', message: 'too many', species_key: 'x' }]))
      .mockResolvedValueOnce({ ok: true });
    const bad = await enqueue(plot(1));
    await enqueue(plot(2));
    const r = await flushOutbox('c1');
    expect(r).toMatchObject({ sent: 1, rejected: 1, waiting: 0 });
    const [kept] = await listOutbox('c1');
    expect(kept).toMatchObject({ id: bad.id, state: 'rejected', error: 'Nothing was saved: check the entries.' });
    expect(kept.findings?.[0].species_key).toBe('x');
    expect(await flushOutbox('c1')).toMatchObject({ sent: 0 });        // a refused item is not sent again by itself
    expect(m.savePlot).toHaveBeenCalledTimes(2);
  });

  it('puts a refused item back to waiting when the person asks, and sends it', async () => {
    m.savePlot.mockRejectedValueOnce(refused('mode_conflict', 'The records were uploaded.')).mockResolvedValueOnce({ ok: true });
    await enqueue(plot(1));
    await flushOutbox('c1');
    const [kept] = await listOutbox('c1');
    expect(kept.state).toBe('rejected');
    await retry(kept);
    expect((await listOutbox('c1'))[0]).toMatchObject({ state: 'waiting', error: undefined });
    expect(await flushOutbox('c1')).toMatchObject({ sent: 1 });
  });

  it('is one flush at a time', async () => {
    let release: (v: unknown) => void = () => {};
    m.savePlot.mockReturnValue(new Promise((res) => { release = res; }));
    await enqueue(plot(1));
    const first = flushOutbox('c1');
    const second = await flushOutbox('c1');
    expect(second.sent).toBe(0);
    release({ ok: true });
    expect((await first).sent).toBe(1);
    expect(m.savePlot).toHaveBeenCalledTimes(1);
  });
});
