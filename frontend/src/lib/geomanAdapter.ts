/**
 * geomanAdapter.ts — Pinned Geoman event adapter (Gap 4.1).
 *
 * Encapsulates Leaflet Geoman event names and helper wrappers so version
 * upgrades or breaking changes are isolated in one file.
 */
import type L from 'leaflet';

export interface GeomanCreateEvent {
  layer: L.Layer;
  shape: string;
  latlngs?: L.LatLng | L.LatLng[] | L.LatLng[][];
}

export interface GeomanEditEvent {
  layer: L.Layer;
  shape: string;
}

export interface GeomanRemoveEvent {
  layer: L.Layer;
  shape: string;
}
