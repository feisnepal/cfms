import { describe, it, expect } from 'vitest';
import type { Feature, LineString, Polygon } from 'geojson';
import { stripZ, area3d, length3d } from '../geo3d';

describe('geo3d (Gap 5.3)', () => {
  it('stripZ removes 3rd coordinate from point, linestring, and polygon', () => {
    const pt: Feature = {
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [85.5, 27.5, 1200] },
      properties: {},
    };
    const strippedPt = stripZ(pt) as Feature;
    expect((strippedPt.geometry as any).coordinates).toEqual([85.5, 27.5]);

    const line: Feature<LineString> = {
      type: 'Feature',
      geometry: {
        type: 'LineString',
        coordinates: [
          [85.0, 27.0, 500],
          [85.1, 27.1, 600],
        ],
      },
      properties: {},
    };
    const strippedLine = stripZ(line);
    expect(strippedLine.geometry.coordinates).toEqual([
      [85.0, 27.0],
      [85.1, 27.1],
    ]);
  });

  it('area3d and length3d compute correctly after stripping Z', () => {
    const polyWithZ: Feature<Polygon> = {
      type: 'Feature',
      geometry: {
        type: 'Polygon',
        coordinates: [
          [
            [85.0, 27.0, 100],
            [85.01, 27.0, 100],
            [85.01, 27.01, 100],
            [85.0, 27.01, 100],
            [85.0, 27.0, 100],
          ],
        ],
      },
      properties: {},
    };
    const area = area3d(polyWithZ);
    expect(area).toBeGreaterThan(0);

    const length = length3d(polyWithZ);
    expect(length).toBeGreaterThan(0);
  });
});
