import { createContext, useContext, ReactNode } from 'react';
import type { Map as LeafletMap, LatLngBoundsExpression, LatLngExpression, PointExpression, LatLngBounds } from 'leaflet';

/**
 * MapApi — minimal imperative surface published by the single MapContainer.
 * Consumers (MapPreview, MapWorkspace) use this instead of calling useMap().
 * Published via MapApiContext.Provider from MapCanvas/MapController.
 */
export interface MapApi {
  /** Center the map at [lat, lng] with given zoom. */
  setView: (center: LatLngExpression, zoom: number) => void;
  /** Fit the map to bounds. */
  fitBounds: (bounds: LatLngBoundsExpression, options?: { padding?: PointExpression; maxZoom?: number }) => void;
  /** Get current map bounds. */
  getBounds: () => LatLngBounds;
  /** Add a layer to the map. */
  addLayer: (layer: any) => void;
  /** Remove a layer from the map. */
  removeLayer: (layer: any) => void;
  /** Invalidate map size (call after container visibility/size change). */
  invalidateSize: () => void;
  /** Pan to a center. */
  panTo: (center: LatLngExpression, options?: { animate?: boolean; duration?: number }) => void;
  /** Get current zoom. */
  getZoom: () => number;
  /** Get current center. */
  getCenter: () => [number, number];
}

/** Context with null fallback — consumers must check before use. */
export const MapApiContext = createContext<MapApi | null>(null);

/** Hook to access the shared map API. Throws if used outside provider. */
export function useMapApi(): MapApi {
  const ctx = useContext(MapApiContext);
  if (!ctx) {
    throw new Error('useMapApi() must be used within a MapApiContext.Provider (wrap with MapCanvas)');
  }
  return ctx;
}

/** Provider component for the shell to wrap around MapCanvas. */
interface MapApiProviderProps {
  children: ReactNode;
  /** The map API instance from MapController, or null when unmounted. */
  value: MapApi | null;
}

export function MapApiProvider({ children, value }: MapApiProviderProps) {
  return <MapApiContext.Provider value={value}>{children}</MapApiContext.Provider>;
}