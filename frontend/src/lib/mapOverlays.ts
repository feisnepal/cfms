/**
 * Map overlay visibility reducer — U06.
 * Given store state, returns which built-in overlay layers are currently active.
 */

import { OverlayKind, OverlayFetchState } from '../store/workspaceStore';
import { tileXY } from './webmercator';

export interface TileKey {
  z: number;
  x: number;
  y: number;
}

export interface VisibleOverlays {
  treeClusters: boolean;
  sampling: boolean;
}

export interface TreeClusterTileRequest {
  calcId: string;
  geometryVersion: number;
  tile: TileKey;
}

export interface TreeClusterTileResponse {
  features: GeoJSON.Feature[];
  hasMore: boolean;
}

export type FetchStateMap = Record<string, OverlayFetchState>;

/** Build a unique key for a tile request (matches backend cache key shape). */
export function tileRequestKey(calcId: string, geometryVersion: number, tile: TileKey): string {
  return `${calcId}:${geometryVersion}:${tile.z}:${tile.x}:${tile.y}`;
}

/**
 * Determine which overlay layers are visible given current map state.
 * Tree clusters are the only cluster overlay in U06; sampling is separate.
 */
export function getVisibleOverlays(
  selectedLayerIds: string[],
  visibleBuiltins: OverlayKind[],
  mapZoom: number
): VisibleOverlays {
  const showTreeClusters = visibleBuiltins.includes('tree_clusters');
  const showSampling = visibleBuiltins.includes('sampling');

  return {
    treeClusters: showTreeClusters && mapZoom >= 0, // always if layer visible
    sampling: showSampling,
  };
}

/**
 * Compute the set of tile keys intersecting the current viewport.
 * Returns tiles for zoom z that cover the map bounds.
 */
export function getViewportTiles(
  bounds: [[number, number], [number, number]], // [[w, s], [e, n]] in 4326
  z: number
): TileKey[] {
  const [[w, s], [e, n]] = bounds;
  const [minX, minY] = tileXY(w, n, z); // top-left
  const [maxX, maxY] = tileXY(e, s, z); // bottom-right

  const tiles: TileKey[] = [];
  for (let x = minX; x <= maxX; x++) {
    for (let y = minY; y <= maxY; y++) {
      tiles.push({ z, x, y });
    }
  }
  return tiles;
}

/** Maximum concurrent in-flight tile requests (U06 spec). */
export const MAX_CONCURRENT_TILES = 4;