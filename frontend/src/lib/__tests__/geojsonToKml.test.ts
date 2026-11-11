import { describe, it, expect } from 'vitest';
import { geojsonToKml } from '../geojsonToKml';
import type { GeoJSON } from 'geojson';

describe('geojsonToKml', () => {
  it('wraps features in a Document with the layer name', () => {
    const kml = geojsonToKml([], 'Blocks');
    expect(kml).toContain('<kml xmlns="http://www.opengis.net/kml/2.2">');
    expect(kml).toContain('<Document>');
    expect(kml).toContain('<name>Blocks</name>');
    expect(kml).toContain('</kml>');
  });

  it('converts a Point feature', () => {
    const f: GeoJSON.Feature = {
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [84.12, 28.34] },
      properties: { name: 'Well', depth_m: 12 },
    };
    const kml = geojsonToKml([f], 'Points');
    expect(kml).toContain('<Placemark>');
    expect(kml).toContain('<name>Well</name>');
    expect(kml).toContain('<Point><coordinates>84.12,28.34</coordinates></Point>');
  });

  it('converts a LineString with multiple coordinates', () => {
    const f: GeoJSON.Feature = {
      type: 'Feature',
      geometry: { type: 'LineString', coordinates: [[84, 28], [84.1, 28.1]] },
      properties: { name: 'Trail' },
    };
    const kml = geojsonToKml([f], 'Lines');
    expect(kml).toContain('<LineString><coordinates>84,28 84.1,28.1</coordinates></LineString>');
  });

  it('converts a Polygon with outer ring and inner hole', () => {
    const f: GeoJSON.Feature = {
      type: 'Feature',
      geometry: {
        type: 'Polygon',
        coordinates: [
          [[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]],
          [[2, 2], [2, 3], [3, 3], [3, 2], [2, 2]],
        ],
      },
      properties: { name: 'Area' },
    };
    const kml = geojsonToKml([f], 'Polygons');
    expect(kml).toContain('<Polygon><outerBoundaryIs><LinearRing><coordinates>0,0 0,10 10,10 10,0 0,0</coordinates></LinearRing></outerBoundaryIs>');
    expect(kml).toContain('<innerBoundaryIs><LinearRing><coordinates>2,2 2,3 3,3 3,2 2,2</coordinates></LinearRing></innerBoundaryIs>');
  });

  it('converts MultiPolygon into MultiGeometry', () => {
    const f: GeoJSON.Feature = {
      type: 'Feature',
      geometry: {
        type: 'MultiPolygon',
        coordinates: [
          [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]],
          [[[5, 5], [5, 6], [6, 6], [6, 5], [5, 5]]],
        ],
      },
      properties: { name: 'Islands' },
    };
    const kml = geojsonToKml([f], 'Multi');
    expect(kml).toContain('<MultiGeometry>');
    expect((kml.match(/<Polygon>/g) || []).length).toBe(2);
  });

  it('escapes XML special characters in names', () => {
    const f: GeoJSON.Feature = {
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [1, 2] },
      properties: { name: 'A & B <C>' },
    };
    const kml = geojsonToKml([f], 'Layer');
    expect(kml).toContain('<name>A &amp; B &lt;C&gt;</name>');
  });

  it('includes properties as a description and skips geo_ keys', () => {
    const f: GeoJSON.Feature = {
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [1, 2] },
      properties: { name: 'P', area_hectares: 3.2, geo_area_ha: 3.2, nested: { a: 1 } },
    };
    const kml = geojsonToKml([f], 'Layer');
    expect(kml).toContain('area_hectares: 3.2');
    expect(kml).not.toContain('geo_area_ha');
    expect(kml).not.toContain('nested');
  });

  it('falls back to a default name when none is present', () => {
    const f: GeoJSON.Feature = {
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [1, 2] },
      properties: {},
    };
    const kml = geojsonToKml([f], 'Layer');
    expect(kml).toContain('<name>Feature 1</name>');
  });
});
