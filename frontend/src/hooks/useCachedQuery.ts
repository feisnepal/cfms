/**
 * useCachedQuery — stale-while-revalidate data hook (Cache Plan Phase 6/7).
 *
 * Wraps @tanstack/react-query: on success, persists the result into the
 * IndexedDB browserCache (per calcId + category). On next mount, serves the
 * cached value instantly while React Query revalidates in the background.
 */
import { useQuery, type UseQueryOptions } from '@tanstack/react-query';
import { browserCache } from '../services/browserCache';

export type CacheCategory = 'maps' | 'charts' | 'analysis';

interface CachedQueryArgs<T> {
  queryKey: (string | number)[];
  queryFn: () => Promise<T>;
  calcId: string;
  category: CacheCategory;
  cacheKey: string;
  options?: Omit<UseQueryOptions<T, Error, T>, 'queryKey' | 'queryFn'>;
}

export function useCachedQuery<T>({
  queryKey,
  queryFn,
  calcId,
  category,
  cacheKey,
  options,
}: CachedQueryArgs<T>) {
  const setter =
    category === 'maps'
      ? browserCache.setMap
      : category === 'charts'
        ? browserCache.setChart
        : browserCache.setAnalysis;

  return useQuery<T, Error>({
    queryKey,
    queryFn: async () => {
      const fresh = await queryFn();
      await setter(calcId, cacheKey, fresh as unknown);
      return fresh;
    },
    ...(options ?? {}),
  });
}

export { browserCache };
