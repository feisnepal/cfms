import { describe, it, expect, vi } from 'vitest';

// turf's polygon-clipping union can throw "Unable to complete output ring" on
// complex raster-derived polygons (jagged shared edges). unionFamily MUST never
// let that escape (it runs from React render), so this test forces the throw
// and asserts the MultiPolygon fallback is returned instead.
vi.mock('@turf/turf', async (orig) => {
  const actual = await orig<typeof import('@turf/turf')>();
  return {
    ...actual,
    union: vi.fn(() => {
      throw new Error(
        'Unable to complete output ring starting at [85.03413644, 27.377086489]. ' +
          'Last matching segment found ends at [85.04224889748792, 27.385991667553228].',
      );
    }),
    buffer: vi.fn((f) => f),
  };
});

import { describe as describeReal, it as itReal, expect as expectReal } from 'vitest';
import { unionFamily, type AutoBlockPiece } from '../autoBlockMerge';

const pieceGeom = (ring: number[][]): AutoBlockPiece => ({
  index: 0,
  name: 'p',
  block_name: 'p',
  natural_name: null,
  area_hectares: 10,
  geometry: { type: 'Polygon', coordinates: [ring] },
});

describeReal('unionFamily — turf union throws (ring error)', () => {
  itReal('never throws and returns a valid MultiPolygon fallback', () => {
    const square1: number[][] = [
      [85.034, 27.377],
      [85.035, 27.377],
      [85.035, 27.378],
      [85.034, 27.378],
      [85.034, 27.377],
    ];
    const square2: number[][] = [
      [85.042, 27.386],
      [85.043, 27.386],
      [85.043, 27.387],
      [85.042, 27.387],
      [85.042, 27.386],
    ];
    const pieces = [pieceGeom(square1), pieceGeom(square2)];
    let merged: GeoJSON.Feature;
    expectReal(() => {
      merged = unionFamily(pieces, { 0: 0, 1: 0 }, 0);
    }).not.toThrow();
    expectReal(merged!.geometry.type).toBe('MultiPolygon');
    expectReal((merged!.geometry as GeoJSON.MultiPolygon).coordinates.length).toBe(2);
  });

  itReal('keeps a single-member family untouched even when union throws', () => {
    const square: number[][] = [
      [85.0, 27.0],
      [85.01, 27.0],
      [85.01, 27.01],
      [85.0, 27.01],
      [85.0, 27.0],
    ];
    const merged = unionFamily([pieceGeom(square)], { 0: 0 }, 0);
    expectReal(merged.geometry.type).toBe('Polygon');
  });
});