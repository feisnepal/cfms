import { describe, expect, it } from 'vitest';
import L from 'leaflet';
import { buildPendingPlacesLayer } from '../pendingPlacesLayer';

const point = (lng: number, lat: number): GeoJSON.Geometry => ({ type: 'Point', coordinates: [lng, lat] });

describe('the places drawn but not saved yet', () => {
  it('shows a point as a numbered marker at its place, in the order drawn', () => {
    const group = buildPendingPlacesLayer([{ geometry: point(85.1, 27.2) }, { geometry: point(85.3, 27.4) }]);
    const markers = group.getLayers() as L.Marker[];
    expect(markers).toHaveLength(2);
    expect(markers[0].getLatLng()).toEqual(L.latLng(27.2, 85.1)); // GeoJSON is [lng, lat]
    expect((markers[1].options.icon as L.DivIcon).options.html).toContain('2');
  });

  it('shows a line as a polyline through its vertices', () => {
    const group = buildPendingPlacesLayer([
      { geometry: { type: 'LineString', coordinates: [[85, 27], [85.1, 27.1], [85.2, 27.1]] } },
    ]);
    const [line] = group.getLayers() as L.Polyline[];
    expect(line).toBeInstanceOf(L.Polyline);
    expect(line.getLatLngs()).toHaveLength(3);
  });

  it('shows a polygon as a filled polygon', () => {
    const group = buildPendingPlacesLayer([
      { geometry: { type: 'Polygon', coordinates: [[[85, 27], [85.1, 27], [85.1, 27.1], [85, 27]]] } },
    ]);
    const [polygon] = group.getLayers() as L.Polygon[];
    expect(polygon).toBeInstanceOf(L.Polygon);
    expect(polygon.options.fillOpacity).toBeGreaterThan(0);
  });

  it('is empty when nothing has been drawn', () => {
    expect(buildPendingPlacesLayer([]).getLayers()).toHaveLength(0);
  });
});
