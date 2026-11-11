import { useQuery } from '@tanstack/react-query';
import api from '../services/api';

/**
 * H2.4 / S1-04 — credential for raster tile URLs.
 *
 * The tile endpoints used to be unauthenticated, so `<TileLayer url=...>` just
 * worked. They are owner-gated now, and Leaflet fetches tiles as `<img>`, which
 * carries no Authorization header and offers no hook to add one.
 *
 * So the map asks the backend for a tile token — short-lived, scoped to one
 * calculation, valid for nothing but tile reads — and appends it to the URL.
 * The session token deliberately stays out of URLs: those end up in browser
 * history, `Referer` headers and proxy logs.
 *
 * Refetches comfortably inside the 30-minute server-side lifetime so a map left
 * open on a desk does not start serving blank tiles.
 */
export function useTileToken(calculationId: string | null | undefined) {
  const { data } = useQuery({
    queryKey: ['tile-token', calculationId],
    queryFn: async () => {
      const response = await api.get(`/api/calculations/${calculationId}/tile-token`);
      return response.data as { token: string; expires_in: number };
    },
    enabled: !!calculationId,
    staleTime: 20 * 60 * 1000,
    refetchInterval: 20 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  return data?.token ?? null;
}

/**
 * Append the tile token to a tile URL template.
 *
 * Returns null while the token is still in flight, which callers use to hold
 * the layer back — mounting a TileLayer without it would fire a screenful of
 * 401s and cache the failures.
 */
export function withTileToken(url: string, token: string | null): string | null {
  if (!token) return null;
  return `${url}${url.includes('?') ? '&' : '?'}tk=${encodeURIComponent(token)}`;
}
