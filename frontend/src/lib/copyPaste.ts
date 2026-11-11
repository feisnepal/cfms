/**
 * copyPaste.ts — Feature copy & paste clipboard utilities (Task 3.5.1).
 *
 * Clones geometry and properties (stripping featureId and geo_* fields so they
 * get re-derived on persistence), and applies purpose-appropriate defaults.
 */
import type { GeoJSON, Feature } from 'geojson';
import { defaultPropertiesForPurpose } from './defaultProperties';

export function copyFeature(feature: Feature): Feature {
  return JSON.parse(JSON.stringify(feature)) as Feature;
}

export function pasteFeature(feature: Feature, purpose: string, offsetLatLng?: { lat: number; lng: number }): Feature {
  const cloned = copyFeature(feature);
  const props = (cloned.properties || {}) as Record<string, unknown>;

  // Strip featureId and server/client internal geo_* fields so they recompute fresh
  delete props.featureId;
  delete props.id;
  delete props._vectorClock;
  for (const k of Object.keys(props)) {
    if (k.startsWith('geo_')) delete props[k];
  }

  // Apply purpose defaults
  const defaults = defaultPropertiesForPurpose(purpose);
  cloned.properties = { ...defaults, ...props };

  // Apply offset if geometry is Point
  if (cloned.geometry && cloned.geometry.type === 'Point' && offsetLatLng) {
    const coords = (cloned.geometry as any).coordinates;
    coords[0] += 0.0005; // slight lng offset
    coords[1] += 0.0005; // slight lat offset
  } else if (cloned.geometry && cloned.geometry.type === 'LineString') {
    (cloned.geometry as any).coordinates = (cloned.geometry as any).coordinates.map(([lng, lat]: [number, number]) => [
      lng + 0.0005,
      lat + 0.0005,
    ]);
  } else if (cloned.geometry && cloned.geometry.type === 'Polygon') {
    (cloned.geometry as any).coordinates = (cloned.geometry as any).coordinates.map((ring: number[][]) =>
      ring.map(([lng, lat]) => [lng + 0.0005, lat + 0.0005])
    );
  }

  return cloned;
}
