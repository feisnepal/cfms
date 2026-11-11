import { useEffect, useState } from 'react';
import { forumApi, ForumStepCount } from './forumApi';

const TTL_MS = 5 * 60_000;
let cache: { at: number; counts: Record<string, ForumStepCount> } | null = null;
let inflight: Promise<Record<string, ForumStepCount>> | null = null;

function load(): Promise<Record<string, ForumStepCount>> {
  if (cache && Date.now() - cache.at < TTL_MS) return Promise.resolve(cache.counts);
  if (!inflight) {
    inflight = forumApi.steps()
      .then((counts) => {
        cache = { at: Date.now(), counts };
        return counts;
      })
      .finally(() => {
        inflight = null;
      });
  }
  return inflight;
}

/** Questions per workflow step, fetched once and kept for five minutes (the workflow header asks on every step change). Empty until it arrives, and when the forum cannot be reached. */
export function useStepCounts(): Record<string, ForumStepCount> {
  const [counts, setCounts] = useState<Record<string, ForumStepCount>>(cache?.counts ?? {});
  useEffect(() => {
    let alive = true;
    load().then((c) => alive && setCounts(c)).catch(() => undefined); // the count is a nicety: a forum that cannot be reached just shows no number
    return () => {
      alive = false;
    };
  }, []);
  return counts;
}

/** Forget the cached counts (after a question is asked, so the number is right on the next look). */
export function resetStepCounts(): void {
  cache = null;
}
