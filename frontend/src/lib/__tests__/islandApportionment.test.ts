/**
 * Client mirror of `app/services/island_apportionment.py` — the worked cases
 * in MULTI_ISLAND_DIVIDE_PLAN.md must produce the same allocation on both
 * sides so a submit without `island_counts` lands identically.
 * Keep in sync with `backend/tests/test_island_apportionment.py`.
 */
import { describe, it, expect } from 'vitest';
import { allocateIslandCounts, UNDERSIZED_REL } from '../islandApportionment';

const counts = (areas: number[], n: number) => allocateIslandCounts(areas, n).counts;

describe('allocateIslandCounts — worked cases from the plan', () => {
  it('90 + 10 into 10 → 9 + 1, nothing flagged', () => {
    const r = allocateIslandCounts([90, 10], 10);
    expect(r.counts).toEqual([9, 1]);
    expect(r.nEffective).toBe(10);
    expect(r.targetArea).toBeCloseTo(10);
    expect(r.undersized).toEqual([]);
  });

  it('90 + 3 into 10 → 9 + 1, small parcel flagged', () => {
    const r = allocateIslandCounts([90, 3], 10);
    expect(r.counts).toEqual([9, 1]);
    expect(r.targetArea).toBeCloseTo(9.3);
    expect(r.undersized).toEqual([1]);
  });

  it('990 + 10 into 10 → 9 + 1, small parcel flagged', () => {
    const r = allocateIslandCounts([990, 10], 10);
    expect(r.counts).toEqual([9, 1]);
    expect(r.targetArea).toBeCloseTo(100);
    expect(r.undersized).toEqual([1]);
    expect(r.counts.reduce((a, b) => a + b, 0)).toBe(10);
  });

  it('more parcels than n → n raised to the parcel count', () => {
    const r = allocateIslandCounts([2, 2, 2, 2, 2], 3);
    expect(r.counts).toEqual([1, 1, 1, 1, 1]);
    expect(r.nEffective).toBe(5);
  });
});

describe('allocateIslandCounts — invariants', () => {
  const cases: [number[], number][] = [
    [[100], 1],
    [[100], 7],
    [[50, 50], 4],
    [[90, 10], 10],
    [[90, 3], 10],
    [[1000, 10, 5], 12],
    [[50, 1, 1, 1], 4],
    [[10, 6, 4], 5],
    [[33.3, 33.3, 33.4], 9],
    [[500, 5], 2],
    [[1, 1, 1, 1, 1, 1], 2],
  ];
  it.each(cases)('areas=%j n=%i', (areas, n) => {
    const r = allocateIslandCounts(areas, n);
    expect(r.counts).toHaveLength(areas.length);
    expect(r.counts.every((c) => c >= 1)).toBe(true);
    expect(r.counts.reduce((a, b) => a + b, 0)).toBe(r.nEffective);
    expect(r.nEffective).toBe(Math.max(n, areas.length));
    expect(r.targetArea).toBeCloseTo(areas.reduce((a, b) => a + b, 0) / r.nEffective);
  });

  it('claw-back when the floor-of-one over-allocates', () => {
    expect(counts([50, 1, 1, 1], 4)).toEqual([1, 1, 1, 1]);
  });

  it('equal islands split evenly', () => {
    expect(counts([25, 25, 25, 25], 8)).toEqual([2, 2, 2, 2]);
  });

  it('single island behaves like a plain divide', () => {
    expect(counts([120], 6)).toEqual([6]);
    expect(counts([120], 1)).toEqual([1]);
  });

  it('rejects bad input', () => {
    expect(() => allocateIslandCounts([10, 5], 0)).toThrow();
    expect(() => allocateIslandCounts([], 3)).toThrow();
    expect(() => allocateIslandCounts([10, 0], 3)).toThrow();
    expect(() => allocateIslandCounts([10, -2], 3)).toThrow();
  });

  it('is deterministic', () => {
    const a = [10, 6, 4, 7.5, 2.2];
    expect(allocateIslandCounts(a, 11)).toEqual(allocateIslandCounts([...a], 11));
  });

  it('UNDERSIZED_REL is 0.5', () => {
    expect(UNDERSIZED_REL).toBe(0.5);
  });
});
