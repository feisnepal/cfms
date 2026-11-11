import { describe, it, expect } from 'vitest';
import {
  validateCalculationInput,
  validateBoundary,
  getVertexCount,
  VERTEX_LIMIT,
} from '../validation';

const validPolygon = {
  type: 'Polygon',
  coordinates: [[
    [85.0, 27.0],
    [85.1, 27.0],
    [85.1, 27.1],
    [85.0, 27.1],
    [85.0, 27.0],
  ]],
};

const validInput = {
  forest_name: 'Shivapuri Forest',
  outer_boundary: validPolygon,
  blocks: [],
};

describe('validateCalculationInput', () => {
  it('accepts valid calculation input', () => {
    const result = validateCalculationInput(validInput);
    expect(result.valid).toBe(true);
  });

  it('rejects missing forest_name', () => {
    const result = validateCalculationInput({
      outer_boundary: validPolygon,
      blocks: [],
    });
    expect(result.valid).toBe(false);
    if (!result.valid) {
      expect(result.errors.some((e) => e.field === 'forest_name')).toBe(true);
    }
  });

  it('rejects empty forest_name', () => {
    const result = validateCalculationInput({
      forest_name: '   ',
      outer_boundary: validPolygon,
      blocks: [],
    });
    expect(result.valid).toBe(false);
  });

  it('rejects unclosed linear ring', () => {
    const badPolygon = {
      type: 'Polygon',
      coordinates: [[
        [85.0, 27.0],
        [85.1, 27.0],
        [85.1, 27.1],
        [85.0, 27.1], // last point does not equal first point
      ]],
    };
    const result = validateCalculationInput({
      forest_name: 'Test',
      outer_boundary: badPolygon,
      blocks: [],
    });
    expect(result.valid).toBe(false);
  });

  it('rejects non-geojson geometry', () => {
    const result = validateCalculationInput({
      forest_name: 'Test',
      outer_boundary: { type: 'LineString', coordinates: [] },
      blocks: [],
    });
    expect(result.valid).toBe(false);
  });
});

describe('validateBoundary', () => {
  it('accepts a valid polygon', () => {
    expect(validateBoundary(validPolygon).success).toBe(true);
  });

  it('rejects an invalid geometry', () => {
    expect(validateBoundary({ type: 'Point', coordinates: [0, 0] }).success).toBe(false);
  });
});

describe('getVertexCount', () => {
  it('counts vertices in a Polygon', () => {
    expect(getVertexCount(validPolygon)).toBe(5);
  });

  it('counts vertices in a MultiPolygon', () => {
    const mp = {
      type: 'MultiPolygon',
      coordinates: [[
        [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]],
      ]],
    };
    expect(getVertexCount(mp)).toBe(5);
  });

  it('returns 0 for unknown/empty geometry', () => {
    expect(getVertexCount(null)).toBe(0);
  });
});

describe('VERTEX_LIMIT', () => {
  it('is a positive number', () => {
    expect(VERTEX_LIMIT).toBeGreaterThan(0);
  });

  it('rejects a boundary exceeding the vertex limit', () => {
    const ring = Array.from(
      { length: VERTEX_LIMIT + 10 },
      (_, i) => [(i % 175) - 85, (i % 80) - 45]
    );
    const bigGeo = { type: 'Polygon', coordinates: [ring] };
    const result = validateCalculationInput({
      forest_name: 'Big',
      outer_boundary: bigGeo,
      blocks: [],
    });
    expect(result.valid).toBe(false);
    if (!result.valid) {
      expect(result.errors.some((e) => e.field === 'outer_boundary')).toBe(true);
    }
  });
});