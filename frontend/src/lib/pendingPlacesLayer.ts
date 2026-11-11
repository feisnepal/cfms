import L from 'leaflet';
import { createFreshPointIcon, FRESH_POINT_FILL, FRESH_POINT_RING } from './pointIcons';

/**
 * The places drawn for the add-activity questions but not saved yet, as one Leaflet group: fuchsia = "not saved yet" (the colour
 * of a point being placed). A shape used to leave the map the moment it was finished - a point at its first click - so the user
 * could not see what had been mapped until the questions were saved. Points are numbered in the order they were drawn.
 */
export function buildPendingPlacesLayer(places: ReadonlyArray<{ geometry: GeoJSON.Geometry }>): L.FeatureGroup {
  const group = L.featureGroup();
  const style = { color: FRESH_POINT_RING, weight: 3, dashArray: '6 4', interactive: false } as const;
  const flip = (c: number[]): L.LatLngTuple => [c[1], c[0]];
  places.forEach((place, i) => {
    const g = place.geometry;
    if (g.type === 'Point') {
      L.marker(flip(g.coordinates as number[]), { icon: createFreshPointIcon(i + 1), interactive: false, zIndexOffset: 1500 }).addTo(group);
    } else if (g.type === 'LineString') {
      L.polyline((g.coordinates as number[][]).map(flip), style).addTo(group);
    } else if (g.type === 'Polygon') {
      L.polygon((g.coordinates as number[][][]).map((ring) => ring.map(flip)), { ...style, fillColor: FRESH_POINT_FILL, fillOpacity: 0.25 }).addTo(group);
    }
  });
  return group;
}
