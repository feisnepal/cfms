import { describe, it, expect } from 'vitest';
import type { Feature } from 'geojson';
import {
  buildMergePlan,
  minimizeN,
  unionFamily,
  isGlueShrinkUsable,
  type AutoBlockPiece,
  type AdjacencyEdge,
} from '../autoBlockMerge';

/**
 * Build a triangle-ish/simple square feature of a fixed area (ha). Geometry is
 * only used for unionFamily; we need the ring to enclose `areaHa`.
 */
const piece = (index: number, areaHa: number, natural_name: string | null = null): AutoBlockPiece => {
  const sideKm = Math.sqrt(areaHa) / 10; // 1 side squared * 10000 = areaHa
  const h = sideKm / 2;
  return {
    index,
    name: `Block-${index + 1}`,
    block_name: `Block-${index + 1}`,
    natural_name,
    area_hectares: areaHa,
    geometry: {
      type: 'Polygon',
      coordinates: [
        [
          [-h, -h],
          [h, -h],
          [h, h],
          [-h, h],
          [-h, -h],
        ],
      ],
    },
  };
};

/** A row of n adjacent squares with equal sides, shifted so they touch. */
const row = (n: number, areaHa: number): AutoBlockPiece[] => {
  const out: AutoBlockPiece[] = [];
  const sideKm = Math.sqrt(areaHa) / 10;
  for (let i = 0; i < n; i++) {
    const p = piece(i, areaHa);
    const h = sideKm / 2;
    const g = p.geometry as GeoJSON.Polygon;
    g.coordinates[0] = [
      [i * sideKm - h, -h],
      [i * sideKm + h, -h],
      [i * sideKm + h, h],
      [i * sideKm - h, h],
      [i * sideKm - h, -h],
    ];
    out.push(p);
  }
  return out;
};

const rowEdges = (n: number): AdjacencyEdge[] =>
  Array.from({ length: n - 1 }, (_, i) => ({ a: i, b: i + 1, shared_m: 1000 }));

const descByArea = (ps: AutoBlockPiece[]) => [...ps].sort((a, b) => b.area_hectares - a.area_hectares);

describe('minimizeN', () => {
  it('uses the 5 ha floor', () => {
    expect(minimizeN(100, 5)).toBe(20);
    expect(minimizeN(12.1, 5)).toBe(3);
    expect(minimizeN(0.4, 5)).toBe(1);
  });
});

describe('buildMergePlan', () => {
  it('keeps a single piece untouched', () => {
    const pieces = row(1, 100);
    const plan = buildMergePlan({ pieces, edges: [], n: 1 });
    expect(plan.effectiveN).toBe(1);
    expect(plan.anchors).toEqual([0]);
    expect(plan.familyOf[0]).toBe(0);
  });

  it('merges a row of 4 into 2 blocks (largest anchors)', () => {
    const pieces = descByArea(row(4, 2)); // total 8 ha → floor 2
    const plan = buildMergePlan({ pieces, edges: rowEdges(4), n: 2 });
    expect(minimizeN(8, 5)).toBe(2);
    expect(plan.effectiveN).toBe(2);
    expect(plan.anchors).toHaveLength(2);
    // exactly two families
    const fams = new Set(Object.values(plan.familyOf));
    expect(fams.size).toBe(2);
  });

  it('clamps n to the piece count upper bound', () => {
    const pieces = row(3, 2);
    const plan = buildMergePlan({ pieces, edges: [], n: 99 });
    expect(plan.effectiveN).toBe(3);
    for (const i of [0, 1, 2]) expect(plan.familyOf[i]).toBe(i);
  });

  it('allows merging below the 5 ha area floor (floor only drives Minimize)', () => {
    const pieces = descByArea(row(4, 50)); // total 200 ha → floor recommends 40, but user may merge
    const plan = buildMergePlan({ pieces, edges: rowEdges(4), n: 2 });
    expect(plan.effectiveN).toBe(2); // slider freely merges 4 → 2
    const fams = new Set(Object.values(plan.familyOf));
    expect(fams.size).toBe(2);
  });

  it('locks raise the effective minimum N', () => {
    const pieces = descByArea(row(4, 2)); // total 8 ha, floor 2
    const edges = rowEdges(4);
    const plan = buildMergePlan({ pieces, edges, n: 2, locked: [0, 1, 2] });
    expect(plan.minN).toBe(3);
    expect(plan.effectiveN).toBe(3);
    for (const i of [0, 1, 2]) expect(plan.familyOf[i]).toBe(i);
  });

  it('lock forces a piece to stay an anchor even if small', () => {
    const pieces = descByArea(row(4, 2));
    const edges = rowEdges(4);
    const plan = buildMergePlan({ pieces, edges, n: 2, locked: [3] });
    expect(plan.effectiveN).toBe(2);
    expect(plan.anchors).toContain(3); // smallest piece is an anchor
    expect(plan.familyOf[3]).toBe(3);
  });

  it('fold otherwise-unreachable pieces into the smallest anchor', () => {
    const pieces = descByArea(row(3, 2)); // total 6 ha → floor 2
    const edges: AdjacencyEdge[] = [{ a: 0, b: 1, shared_m: 1000 }]; // piece 2 isolated
    const plan = buildMergePlan({ pieces, edges, n: 2 });
    expect(plan.effectiveN).toBe(2);
    const smallestAnchor = [...plan.anchors].sort(
      (a, b) => pieces[a].area_hectares - pieces[b].area_hectares,
    )[0];
    expect(plan.familyOf[2]).toBe(smallestAnchor);
  });
});

describe('unionFamily', () => {
  it('unions adjacent squares into a single polygon', () => {
    const pieces = row(2, 2);
    const merged = unionFamily(pieces, { 0: 0, 1: 0 }, 0);
    expect(merged.type).toBe('Feature');
    expect((merged.geometry as GeoJSON.Polygon).coordinates.length).toBeGreaterThan(0);
  });

  it('returns the single geometry unchanged when a family has one member', () => {
    const pieces = row(1, 100);
    const merged = unionFamily(pieces, { 0: 0 }, 0);
    expect(merged.type).toBe('Feature');
    expect(merged.geometry).toEqual(pieces[0].geometry);
  });

  it('glues two pieces left disconnected by a small smoothing-gap into one polygon', () => {
    // Two 2 ha squares side by side, but with an artificial ~11 m gap between
    // them — the kind of gap independent per-piece backend smoothing
    // (geom_generalize.py) can leave along a shared edge. A plain turf union
    // of these would be a MultiPolygon (server rejects that as 400).
    const pieces = row(2, 2);
    const g = pieces[1].geometry as GeoJSON.Polygon;
    const gapDeg = 0.0001; // ~11 m at these latitudes, well inside the 30 m glue radius
    g.coordinates[0] = g.coordinates[0].map(([x, y]) => [x + gapDeg, y]);
    const merged = unionFamily(pieces, { 0: 0, 1: 0 }, 0);
    expect(merged.geometry.type).toBe('Polygon');
  });

  it('leaves a genuinely far-apart family as an honest (disconnected) union', () => {
    // ~1.1 km apart — far beyond any plausible smoothing artifact. The glue
    // radius (30 m each side) cannot bridge this, so the result must stay a
    // MultiPolygon rather than being silently forced into one polygon.
    const pieces = row(2, 2);
    const g = pieces[1].geometry as GeoJSON.Polygon;
    const farDeg = 0.01;
    g.coordinates[0] = g.coordinates[0].map(([x, y]) => [x + farDeg, y]);
    const merged = unionFamily(pieces, { 0: 0, 1: 0 }, 0);
    expect(merged.geometry.type).toBe('MultiPolygon');
  });
});

describe('isGlueShrinkUsable', () => {
  it('accepts a Polygon shrink result', () => {
    const f: Feature = {
      type: 'Feature',
      properties: {},
      geometry: {
        type: 'Polygon',
        coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]],
      },
    };
    expect(isGlueShrinkUsable(f)).toBe(true);
  });

  it('accepts a MultiPolygon shrink result', () => {
    const f: Feature = {
      type: 'Feature',
      properties: {},
      geometry: {
        type: 'MultiPolygon',
        coordinates: [[[[0, 0], [0, 0]]]],
      },
    };
    expect(isGlueShrinkUsable(f)).toBe(true);
  });

  it('rejects a Point (ring-trace) shrink result', () => {
    const f: Feature = {
      type: 'Feature',
      properties: {},
      geometry: { type: 'Point', coordinates: [0, 0] },
    };
    expect(isGlueShrinkUsable(f)).toBe(false);
  });

  it('rejects a LineString shrink result', () => {
    const f: Feature = {
      type: 'Feature',
      properties: {},
      geometry: { type: 'LineString', coordinates: [[0, 0], [1, 1]] },
    };
    expect(isGlueShrinkUsable(f)).toBe(false);
  });

  it('rejects an undefined / empty shrink result (collapse-to-empty)', () => {
    expect(isGlueShrinkUsable(undefined)).toBe(false);
    const f = { type: 'Feature', properties: {}, geometry: null } as unknown as Feature;
    expect(isGlueShrinkUsable(f)).toBe(false);
  });
});