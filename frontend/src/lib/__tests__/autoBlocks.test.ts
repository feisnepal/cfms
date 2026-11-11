import { describe, it, expect } from 'vitest';
import { buildAutoBlocks } from '../autoBlocks';

const squarePolygon = {
  type: 'Polygon',
  coordinates: [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]],
};

describe('buildAutoBlocks', () => {
  it('creates a single block from a Polygon boundary', () => {
    const blocks = buildAutoBlocks(squarePolygon, 'Sundari Forest');
    expect(blocks).toHaveLength(1);
    expect(blocks[0].name).toBe('B1');
    expect(blocks[0].geometry.type).toBe('Polygon');
    expect(blocks[0].area).toBeGreaterThan(0);
  });

  it('creates one block per polygon in a MultiPolygon boundary', () => {
    const mp = {
      type: 'MultiPolygon',
      coordinates: [squarePolygon.coordinates, squarePolygon.coordinates],
    };
    const blocks = buildAutoBlocks(mp, 'Sundari Forest');
    expect(blocks).toHaveLength(2);
    expect(blocks[0].name).toBe('B1');
    expect(blocks[1].name).toBe('B2');
  });

  it('returns [] for non-polygon or missing geometry', () => {
    expect(buildAutoBlocks(null, 'x')).toEqual([]);
    expect(buildAutoBlocks({ type: 'Point', coordinates: [0, 0] }, 'x')).toEqual([]);
  });
});
