/**
 * MapComposition — persisted, renderer-agnostic print/preview layout config (U04).
 * Contract per Map Unification plan A.1. A composition is a pure config; the
 * renderer is bound at the map-state-slot (U03) or the server snapshot pipeline.
 */

import type { FeatureCollection } from 'geojson';

export type CompPurpose = 'op' | 'field' | 'user-group';

export interface CompositionLayer {
  id: string;
  type: 'vector' | 'raster';
  source: FeatureCollection | { tileUrl: string; minZoom: number; maxZoom: number };
  style?: Record<string, any>;
  visible?: boolean;
}

export interface MapComposition {
  id: string;                                     // uuid, stable
  name: string;                                   // "Overview Map" | "Block Detail" | ...
  center: [number, number];                       // [lat, lng]
  zoom: number;
  layers: CompositionLayer[];                     // detailed layer definitions for renderer
  visibleLayerIds: string[];                      // layerRegistry ids + 'tree_clusters'|'sampling' (for simple use cases)
  printOptions: { scaleBar: boolean; legend: boolean; inset: boolean; northArrow: boolean };
  baseMap?: string;                               // basemap option id
  purpose: CompPurpose;
  version: number;                                // bumped on every save (config CRUD)
}

export function defaultComposition(): MapComposition {
  return {
    id: crypto.randomUUID(),
    name: 'Overview Map',
    center: [28.3949, 84.124],
    zoom: 12,
    layers: [
      {
        id: 'boundary',
        type: 'vector',
        source: { type: 'FeatureCollection', features: [] },
        visible: true,
      },
      {
        id: 'blocks',
        type: 'vector',
        source: { type: 'FeatureCollection', features: [] },
        visible: true,
      },
    ],
    visibleLayerIds: ['boundary', 'blocks'],
    printOptions: { scaleBar: true, legend: true, inset: false, northArrow: true },
    purpose: 'op',
    version: 1,
  };
}