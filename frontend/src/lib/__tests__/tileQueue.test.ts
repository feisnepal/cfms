/**
 * U06 — tileQueue concurrency and cancellation tests.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { TileFetchQueue } from '../tileQueue';

describe('TileFetchQueue', () => {
  let queue: TileFetchQueue;

  beforeEach(() => {
    queue = new TileFetchQueue(2); // small for testing
  });

  it('runs fetches up to maxConcurrent', async () => {
    const results: number[] = [];
    const running: number[] = [];

    const fetch = vi.fn().mockImplementation(async (n: number) => {
      running.push(n);
      expect(running.length).toBeLessThanOrEqual(2);
      await new Promise((r) => setTimeout(r, 10));
      running.pop();
      return n * 2;
    });

    const p1 = queue.enqueue('a', () => fetch(1), new AbortController());
    const p2 = queue.enqueue('b', () => fetch(2), new AbortController());
    const p3 = queue.enqueue('c', () => fetch(3), new AbortController());

    const [r1, r2, r3] = await Promise.all([p1, p2, p3]);
    expect(r1).toBe(2);
    expect(r2).toBe(4);
    expect(r3).toBe(6);
    expect(fetch).toHaveBeenCalledTimes(3);
  });

  it('drains queue as slots free', async () => {
    const order: string[] = [];
    const fetch = vi.fn().mockImplementation(async (id: string) => {
      order.push(id);
      await new Promise((r) => setTimeout(r, 5));
      return id;
    });

    queue.enqueue('1', () => fetch('1'), new AbortController());
    queue.enqueue('2', () => fetch('2'), new AbortController());
    queue.enqueue('3', () => fetch('3'), new AbortController());

    await Promise.all([
      queue.enqueue('4', () => fetch('4'), new AbortController()),
      queue.enqueue('5', () => fetch('5'), new AbortController()),
    ]);

    expect(order.length).toBe(5);
  });

  it('cancelPending clears pending queue', async () => {
    const c1 = new AbortController();
    const c2 = new AbortController();
    const c3 = new AbortController();
    const fetch = vi.fn().mockImplementation(async () => {
      await new Promise((r) => setTimeout(r, 1000)); // never resolves in test
      return 'done';
    });

    // With maxConcurrent=2, first two run immediately (running), third waits (pending)
    const p1 = queue.enqueue('a', () => fetch(), c1);
    const p2 = queue.enqueue('b', () => fetch(), c2);
    const p3 = queue.enqueue('c', () => fetch(), c3);

    expect(queue.runningCount).toBe(2);
    expect(queue.pendingCount).toBe(1);

    queue.cancelPending();

    // Only pending items get aborted
    expect(queue.pendingCount).toBe(0);
    expect(c1.signal.aborted).toBe(false); // was running
    expect(c2.signal.aborted).toBe(false); // was running
    expect(c3.signal.aborted).toBe(true);  // was pending

    // Await the rejected promise to avoid unhandled rejection
    await expect(p3).rejects.toThrow('Tile fetch cancelled');
  });

  it('cancelKey removes specific item', async () => {
    const c1 = new AbortController();
    const c2 = new AbortController();
    const fetch = vi.fn().mockResolvedValue('ok');

    // With maxConcurrent=2, both start immediately (running, not pending)
    queue.enqueue('a', () => fetch(), c1);
    const p2 = queue.enqueue('b', () => fetch(), c2);

    expect(queue.runningCount).toBe(2);
    expect(queue.pendingCount).toBe(0);

    queue.cancelKey('a');

    // 'a' was running, cancelKey doesn't affect running - only pending
    expect(queue.pendingCount).toBe(0);
    await expect(p2).resolves.toBe('ok');
  });

  it('runningCount tracks in-flight fetches', async () => {
    let resolve: (v: string) => void;
    const fetch = vi.fn().mockImplementation(async () => {
      await new Promise((r) => { resolve = r; });
      return 'done';
    });

    queue.enqueue('a', () => fetch(), new AbortController());
    expect(queue.runningCount).toBe(1);
    expect(queue.pendingCount).toBe(0);

    resolve!('done');
    // Wait for the finally block to decrement runningCount
    await new Promise((r) => setTimeout(r, 10));
    expect(queue.runningCount).toBe(0);
  });
});