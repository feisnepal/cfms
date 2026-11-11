/**
 * mapPreload — hover/visibility preloading of the map chunk (Phase 7).
 *
 * Reality-aligned: the map lives in `src/components/WorkspaceTab.tsx`, which
 * `React.lazy`s the real Leaflet `MapWorkspace`. Calling this dynamic import
 * ahead of navigation warms that chunk (Vite emits it as a separate asset).
 * Idempotent + debounced so a burst of hovers fires a single preload.
 */
let preloadPromise: Promise<unknown> | null = null;

/** Imperatively ask the bundler to start loading the map chunk. Idempotent. */
export const preloadMapChunk = (): void => {
  if (!preloadPromise) {
    preloadPromise = import('../components/WorkspaceTab')
      .catch((err: unknown) => {
        // Non-fatal — navigation still works, it just loads on demand then.
        console.error('[mapPreload] failed to preload map chunk', err);
        preloadPromise = null; // allow retry next hover
      });
  }
};

/** Debounced variant: coalesces rapid hover/touch events into one preload. */
let timer: ReturnType<typeof setTimeout> | null = null;
export const preloadMapChunkDebounced = (delay = 200): void => {
  if (timer) clearTimeout(timer);
  timer = setTimeout(() => {
    timer = null;
    preloadMapChunk();
  }, delay);
};