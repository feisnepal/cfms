/**
 * Tile fetch queue with concurrency limit and cancellation — U06.
 *
 * - MAX_CONCURRENT_TILES = 4 in-flight requests
 * - Enqueues excess tiles; drains as slots free
 * - AbortController integration for viewport/zoom changes
 */

export interface QueuedTile {
  key: string;
  fetch: () => Promise<any>;
  abort: AbortController;
  resolve: (value: any) => void;
  reject: (reason: any) => void;
}

export class TileFetchQueue {
  private queue: QueuedTile[] = [];
  private running = 0;
  private readonly maxConcurrent: number;

  constructor(maxConcurrent = 4) {
    this.maxConcurrent = maxConcurrent;
  }

  /**
   * Enqueue a tile fetch. Returns a promise that resolves when the fetch completes.
   * If maxConcurrent is reached, the fetch waits in queue.
   */
  enqueue(key: string, fetch: () => Promise<any>, abort: AbortController): Promise<any> {
    return new Promise((resolve, reject) => {
      this.queue.push({ key, fetch, abort, resolve, reject });
      this.drain();
    });
  }

  /** Cancel all pending (queued but not running) tiles. */
  cancelPending(): void {
    for (const item of this.queue) {
      if (!item.abort.signal.aborted) {
        item.abort.abort();
        item.reject(new Error('Tile fetch cancelled (viewport change)'));
      }
    }
    this.queue = [];
  }

  /** Cancel a specific tile by key. */
  cancelKey(key: string): void {
    const idx = this.queue.findIndex((t) => t.key === key);
    if (idx >= 0) {
      const item = this.queue[idx];
      if (!item.abort.signal.aborted) {
        item.abort.abort();
        item.reject(new Error('Tile fetch cancelled'));
      }
      this.queue.splice(idx, 1);
    }
  }

  /** Get count of pending (queued) tiles. */
  get pendingCount(): number {
    return this.queue.length;
  }

  /** Get count of currently running fetches. */
  get runningCount(): number {
    return this.running;
  }

  private drain(): void {
    while (this.running < this.maxConcurrent && this.queue.length > 0) {
      const item = this.queue.shift()!;
      if (item.abort.signal.aborted) continue;

      this.running++;
      item.fetch()
        .then((val) => {
          item.resolve(val);
        })
        .catch((err) => {
          if (err.name !== 'AbortError') {
            item.reject(err);
          }
        })
        .finally(() => {
          this.running--;
          this.drain();
        });
    }
  }
}

/** Singleton instance for the map session. */
export const tileFetchQueue = new TileFetchQueue(4);