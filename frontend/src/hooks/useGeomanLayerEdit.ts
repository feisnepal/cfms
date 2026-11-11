import { useEffect, useRef, useCallback } from 'react';
import type L from 'leaflet';
import type { GeoJSON } from 'geojson';

interface GeomanVertexEvent {
  layer: L.Layer;
  latlng: L.LatLng;
  index?: number;
  ring?: number;
  type?: string;
}

interface UseGeomanLayerEditProps {
  map: L.Map | null;
  enabled: boolean;
  layerId: string;
  featureId: string;
  onVertexDrag?: (event: GeomanVertexEvent) => void;
  onVertexAdd?: (event: GeomanVertexEvent) => void;
  onVertexDelete?: (event: GeomanVertexEvent) => void;
  isTouchDevice?: boolean;
}

export function useGeomanLayerEdit({
  map,
  enabled,
  layerId,
  featureId,
  onVertexDrag,
  onVertexAdd,
  onVertexDelete,
  isTouchDevice,
}: UseGeomanLayerEditProps) {
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;

  const handleDrag = useCallback((e: any) => {
    if (!enabledRef.current) return;
    const event: GeomanVertexEvent = {
      layer: e.layer,
      latlng: e.latlng,
      index: e.index,
      ring: e.ring,
    };
    onVertexDrag?.(event);
  }, [onVertexDrag]);

  const handleAdd = useCallback((e: any) => {
    if (!enabledRef.current) return;
    const event: GeomanVertexEvent = {
      layer: e.layer,
      latlng: e.latlng,
      index: e.index,
      ring: e.ring,
    };
    onVertexAdd?.(event);
  }, [onVertexAdd]);

  const handleDelete = useCallback((e: any) => {
    if (!enabledRef.current) return;
    const event: GeomanVertexEvent = {
      layer: e.layer,
      latlng: e.latlng,
      index: e.index,
      ring: e.ring,
    };
    onVertexDelete?.(event);
  }, [onVertexDelete]);

  useEffect(() => {
    if (!map || !enabled) return;

    if (isTouchDevice) {
      map.doubleClickZoom.disable();
    }

    map.on('pm:vertexdrag', handleDrag);
    map.on('pm:vertexadded', handleAdd);
    map.on('pm:vertexremoved', handleDelete);

    return () => {
      map.off('pm:vertexdrag', handleDrag);
      map.off('pm:vertexadded', handleAdd);
      map.off('pm:vertexremoved', handleDelete);
      if (isTouchDevice) {
        map.doubleClickZoom.enable();
      }
    };
  }, [map, enabled, isTouchDevice, handleDrag, handleAdd, handleDelete]);

  return { featureId, layerId };
}

export default useGeomanLayerEdit;
