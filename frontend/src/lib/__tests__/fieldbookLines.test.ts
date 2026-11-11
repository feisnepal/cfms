import { describe, it, expect } from 'vitest';
import type { Feature } from 'geojson';
import { buildFieldbookLines, lineIsClosed, lineKind, summariseLines } from '../fieldbookLines';

const pt = (label: string, lng: number, lat: number, lines: Record<string, number>): Feature => ({
  type: 'Feature',
  geometry: { type: 'Point', coordinates: [lng, lat] },
  properties: { point_label: label, lines },
});

// A 2x2 grid of units: an outer ring O1..O4 (a square), and two internal edges I-1, I-2 meeting at the centre I1.
const GRID: Feature[] = [
  pt('O1', 0, 2, { 'O-1': 1 }),
  pt('O2', 2, 2, { 'O-1': 2 }),
  pt('O3', 2, 0, { 'O-1': 3 }),
  pt('O4', 0, 0, { 'O-1': 4 }),
  // the outer point where an internal edge starts is on BOTH the ring and the edge
  pt('O5', 1, 2, { 'O-1': 5, 'I-1': 1 }),
  pt('I1', 1, 1, { 'I-1': 2, 'I-2': 1 }),
  pt('O6', 1, 0, { 'O-1': 6, 'I-2': 2 }),
];

describe('buildFieldbookLines', () => {
  it('closes the outer ring back on its first point so it draws as a polygon outline', () => {
    const ring = buildFieldbookLines(GRID).find((l) => l.id === 'O-1')!;
    expect(ring.kind).toBe('outer');
    expect(ring.closed).toBe(true);
    expect(ring.positions[0]).toEqual(ring.positions[ring.positions.length - 1]);
    expect(ring.labels).toEqual(['O1', 'O2', 'O3', 'O4', 'O5', 'O6']);        // in line order, not input order
    expect(ring.positions).toHaveLength(7);                                    // 6 points + the closing repeat
  });

  it('leaves an internal edge open, never closing it', () => {
    const edges = buildFieldbookLines(GRID).filter((l) => l.kind === 'internal');
    expect(edges.map((l) => l.id)).toEqual(['I-1', 'I-2']);
    for (const e of edges) {
      expect(e.closed).toBe(false);
      expect(e.positions[0]).not.toEqual(e.positions[e.positions.length - 1]);
    }
  });

  it('puts a shared end point on every line that meets there, so each edge is rebuilt end to end', () => {
    const lines = Object.fromEntries(buildFieldbookLines(GRID).map((l) => [l.id, l]));
    expect(lines['I-1'].labels).toEqual(['O5', 'I1']);       // starts at an outer point, ends at the junction
    expect(lines['I-2'].labels).toEqual(['I1', 'O6']);
    expect(lines['O-1'].labels).toContain('O5');             // ...and that outer point is still on the ring
  });

  it('never joins two internal edges just because their point numbers are consecutive', () => {
    // I-1 ends at 'I1' and a different edge I-9 starts at a far-away 'I2': consecutive numbers, different edges
    const feats = [
      pt('O1', 0, 0, { 'I-1': 1 }), pt('I1', 1, 0, { 'I-1': 2 }),
      pt('I2', 50, 50, { 'I-9': 1 }), pt('I3', 51, 50, { 'I-9': 2 }),
    ];
    const lines = buildFieldbookLines(feats);
    expect(lines.map((l) => l.positions.length)).toEqual([2, 2]);          // two separate 2-point lines
    expect(lines.every((l) => !l.positions.some((p) => p[0] === 50) || !l.positions.some((p) => p[0] === 0))).toBe(true);
  });

  it('treats a free-standing loop as closed (it has no ends) and does not list its start twice', () => {
    const loop = buildFieldbookLines([
      pt('I1', 0, 0, { 'L-1': 1 }), pt('I2', 1, 0, { 'L-1': 2 }), pt('I3', 1, 1, { 'L-1': 3 }), pt('I4', 0, 1, { 'L-1': 4 }),
    ])[0];
    expect(loop.id).toBe('L-1');
    expect(loop.closed).toBe(true);
    expect(loop.kind).toBe('internal');
    expect(loop.labels).toEqual(['I1', 'I2', 'I3', 'I4']);
    expect(loop.positions[0]).toEqual(loop.positions[loop.positions.length - 1]);
  });

  it('lists outer rings first, then internal edges in numeric (not alphabetical) order', () => {
    const ids = buildFieldbookLines([
      pt('a', 0, 0, { 'I-10': 1 }), pt('b', 0, 0, { 'I-2': 1 }), pt('c', 0, 0, { 'O-2': 1 }), pt('d', 0, 0, { 'O-1': 1 }),
      pt('e', 0, 0, { 'L-1': 1 }),
    ]).map((l) => l.id);
    expect(ids).toEqual(['O-1', 'O-2', 'I-2', 'I-10', 'L-1']);
  });

  it('an older, ungrouped field book (no `lines`) gives no lines, and does not throw', () => {
    expect(buildFieldbookLines([{ type: 'Feature', geometry: { type: 'Point', coordinates: [1, 1] }, properties: { point_number: 1 } }])).toEqual([]);
    expect(buildFieldbookLines(null)).toEqual([]);
    expect(buildFieldbookLines([])).toEqual([]);
  });

  it('ignores non-point features', () => {
    const feats = [{ type: 'Feature', geometry: { type: 'LineString', coordinates: [[0, 0], [1, 1]] }, properties: { lines: { 'O-1': 1 } } } as Feature];
    expect(buildFieldbookLines(feats)).toEqual([]);
  });
});

describe('line helpers', () => {
  it('kinds and closure by id', () => {
    expect(lineKind('O-1')).toBe('outer');
    expect(lineKind('I-3')).toBe('internal');
    expect(lineKind('L-1')).toBe('internal');
    expect(lineIsClosed('O-1')).toBe(true);
    expect(lineIsClosed('L-2')).toBe(true);
    expect(lineIsClosed('I-3')).toBe(false);
  });

  it('summarises the lines for the legend', () => {
    expect(summariseLines(buildFieldbookLines(GRID))).toEqual({ outerRings: 1, internalEdges: 2, loops: 0 });
  });
});
