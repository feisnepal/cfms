/**
 * usePrefetchOnHover / usePrefetchOnVisible — prefetch triggers for the map
 * chunk (Phase 7, from `Tab_setup/CalculationListItem-Preload.tsx`).
 */
import { useEffect, useRef } from 'react';
import { preloadMapChunk, preloadMapChunkDebounced } from '../lib/mapPreload';

/**
 * Calls `onPrefetch` when the bound element is hovered or touched.
 * Returns a ref to attach to the element.
 */
export const usePrefetchOnHover = (
  onPrefetch: () => void,
  { debounce = 0 }: { debounce?: number } = {},
) => {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const trigger = debounce > 0
      ? () => {
          // debounced preload keeps its own timer internally
          if (debounce > 0) preloadMapChunkDebounced(debounce);
          else onPrefetch();
        }
      : onPrefetch;

    const mouseEnter = () => trigger();
    const touchStart = () => trigger();

    el.addEventListener('mouseenter', mouseEnter);
    el.addEventListener('touchstart', touchStart, { passive: true });
    return () => {
      el.removeEventListener('mouseenter', mouseEnter);
      el.removeEventListener('touchstart', touchStart);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onPrefetch, debounce]);

  return ref;
};

/** Prefetch when the element scrolls within `rootMargin` of the viewport. */
export const usePrefetchOnVisible = (
  onPrefetch: () => void,
  { rootMargin = '200px' }: { rootMargin?: string } = {},
) => {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === 'undefined') return;

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            onPrefetch();
            observer.unobserve(el);
          }
        });
      },
      { rootMargin },
    );

    observer.observe(el);
    return () => observer.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onPrefetch, rootMargin]);

  return ref;
};

/** Convenience: preloads the map chunk on hover (used by list items). */
export const usePrefetchMapOnHover = () => usePrefetchOnHover(preloadMapChunk);