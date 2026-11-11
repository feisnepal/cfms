import { describe, expect, it } from 'vitest';
import { computeSplitPreview, extendCutLineEnds, MIN_SLIVER_AREA_M2 } from '../splitPreview';

const block = {
  type: 'Feature' as const,
  properties: {},
  geometry: {
    type: 'Polygon' as const,
    // backend box(2.5, 2.5, 5.5, 5.5) → closed exterior ring
    coordinates: [
      [
        [2.5, 2.5],
        [5.5, 2.5],
        [5.5, 5.5],
        [2.5, 5.5],
        [2.5, 2.5],
      ],
    ],
  },
};

describe('extendCutLineEnds', () => {
  it('extrapolates both ends along their own segment direction, preserving interior vertices', () => {
    // zig-zag fixture from backend test_cut_polygon_zigzag_line_inside_polygon
    const cut: Array<[number, number]> = [
      [3.2, 3.1],
      [3.6, 3.6],
      [3.3, 4.1],
      [3.7, 4.6],
      [3.4, 5.2],
    ];
    const bounds: [number, number, number, number] = [2.5, 2.5, 5.5, 5.5];
    const ext = extendCutLineEnds(cut, bounds);
    expect(ext.length).toBe(5);
    // interior vertices preserved exactly
    expect(ext.slice(1, -1)).toEqual(cut.slice(1, -1));
    // first endpoint must lie outside the bbox to the left/below of the first segment
    expect(ext[0][0]).toBeLessThan(2.5);
    expect(ext[ext.length - 1][1]).toBeGreaterThan(5.5);
  });
});

describe('computeSplitPreview', () => {
  it('splits a block into 2 pieces with a zig-zag line whose ends stop inside', () => {
    const cut: Array<[number, number]> = [
      [3.2, 3.1],
      [3.6, 3.6],
      [3.3, 4.1],
      [3.7, 4.6],
      [3.4, 5.2],
    ];
    const r = computeSplitPreview(block.geometry, cut);
    expect(r.warnings).toEqual([]);
    expect(r.pieces.length).toBe(2);
    expect(r.partHa.length).toBe(2);
    // each piece must be > sliver threshold and its area recovered within ~1%
    for (const ha of r.partHa) expect(ha).toBeGreaterThan(MIN_SLIVER_AREA_M2 / 10000);
    expect(Math.abs(r.totalHa - r.parentHa) / r.parentHa).toBeLessThan(0.01);
  });

  it('returns a warning when the cut misses the polygon', () => {
    const r = computeSplitPreview(block.geometry, [
      [1, 1],
      [1.5, 1.5],
    ]);
    expect(r.pieces.length).toBe(0);
    expect(r.warnings.join(' ')).toMatch(/does not cross/i);
  });

  it('a straight midline cut yields two near-equal halves', () => {
    const r = computeSplitPreview(block.geometry, [
      [4, 2],
      [4, 6],
    ]);
    expect(r.pieces.length).toBe(2);
    const [a, b] = r.partHa;
    expect(Math.abs(a - b) / Math.max(a, b)).toBeLessThan(0.05);
    expect(Math.abs(a + b - r.parentHa) / r.parentHa).toBeLessThan(0.01);
  });
});