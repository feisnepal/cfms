import { useEffect, useRef } from 'react';
import { useMap, Pane, GeoJSON, TileLayer, LayersControl } from 'react-leaflet';
import type { Feature, FeatureCollection } from 'geojson';
import type { LatLngBounds, PointExpression } from 'leaflet';
import type { MapApi } from './MapApiContext';
import { useWorkspaceStore } from '../store/workspaceStore';

const { BaseLayer } = LayersControl;

/**
 * MapController — lives INSIDE MapContainer, lifts the real Leaflet map
 * out via callback ref (not useImperativeHandle). Also renders the active
 * MapComposition in a dedicated print pane.
 */
interface MapControllerProps {
  /** Called with the built MapApi when map is ready; called with null on cleanup. */
  onReady: (api: MapApi | null) => void;
}

export function MapController({ onReady }: MapControllerProps) {
  const map = useMap();
  const store = useWorkspaceStore();
  const apiRef = useRef<MapApi | null>(null);

  // Build the imperative MapApi from the Leaflet map
  const buildApi = (): MapApi => ({
    setView: (center, zoom) => map.setView(center, zoom),
    fitBounds: (bounds, options) => map.fitBounds(bounds, options as any),
    getBounds: () => map.getBounds(),
    addLayer: (layer) => layer.addTo(map),
    removeLayer: (layer) => map.removeLayer(layer),
    invalidateSize: () => map.invalidateSize(),
    panTo: (center, options) => map.panTo(center, options),
    getZoom: () => map.getZoom(),
    getCenter: () => {
      const c = map.getCenter();
      return [c.lat, c.lng];
    },
  });

  // Publish the API via callback ref (triggers parent state update)
  useEffect(() => {
    const api = buildApi();
    apiRef.current = api;
    onReady(api);
    return () => onReady(null);
  }, [map, onReady]);

  // Invalidate size when store's map visibility changes (handles display:none→block)
  useEffect(() => {
    if (store.mapVisible) {
      map.invalidateSize();
    }
  }, [map, store.mapVisible]);

  // Render the active MapComposition in the print pane (read-only, pointerEvents: none)
  // This runs on every composition change via store subscription in render
  const activeCompositionId = store.activeCompositionId;
  const compositions = store.mapCompositions;

  if (!activeCompositionId) return null;

  const composition = compositions.find(c => c.id === activeCompositionId);
  if (!composition) return null;

  return (
    <Pane name="print" style={{ pointerEvents: 'none' }}>
      {/* Base layers for the composition (same as workspace base map) */}
      <LayersControl position="topright">
        <BaseLayer name="Street Map" checked>
          <TileLayer
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            maxZoom={19}
            attribution='&copy; OpenStreetMap contributors'
          />
        </BaseLayer>
        <BaseLayer name="Satellite Imagery">
          <TileLayer
            url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
            maxZoom={19}
            attribution='&copy; Esri'
          />
        </BaseLayer>
        <BaseLayer name="Topographic Map">
          <TileLayer
            url="https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png"
            maxZoom={17}
            attribution='&copy; OpenTopoMap'
          />
        </BaseLayer>
      </LayersControl>

      {/* Composition layers */}
      {composition.layers.map((layer, idx) => (
        <CompositionLayer key={`${layer.id}-${idx}`} layer={layer} />
      ))}

      {/* Center on composition view */}
      {composition.center && (
        <MapViewSetter
          center={composition.center}
          zoom={composition.zoom ?? 8}
        />
      )}
    </Pane>
  );
}

/** Renders a single composition layer (vector or raster). */
interface CompositionLayerProps {
  layer: {
    id: string;
    type: 'vector' | 'raster';
    source: FeatureCollection | { tileUrl: string; minZoom: number; maxZoom: number };
    style?: Record<string, any>;
    visible?: boolean;
  };
}

function CompositionLayer({ layer }: CompositionLayerProps) {
  if (layer.visible === false) return null;

  if (layer.type === 'raster') {
    const { tileUrl, minZoom = 5, maxZoom = 18 } = layer.source as { tileUrl: string; minZoom?: number; maxZoom?: number };
    return <TileLayer url={tileUrl} minZoom={minZoom} maxZoom={maxZoom} />;
  }

  // Vector layer (GeoJSON)
  return (
    <GeoJSON
      data={layer.source as FeatureCollection}
      style={layer.style as any}
    />
  );
}

/** Imperative setView/panTo when composition view changes. */
function MapViewSetter({ center, zoom }: { center: [number, number]; zoom: number }) {
  const map = useMap();
  useEffect(() => {
    map.setView(center, zoom, { animate: true, duration: 1 });
  }, [map, center, zoom]);
  return null;
}