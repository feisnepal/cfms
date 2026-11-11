import { describe, it, expect } from 'vitest';
import { stemRadius, stemShape, stemZoomFactor, treeGroupOf } from '../stemSymbols';

describe('stem symbol rules', () => {
  it('maps the server tree_group to a shape: mother = star, everything else = circle', () => {
    expect(stemShape(treeGroupOf('mother'))).toBe('star');
    expect(stemShape(treeGroupOf('felling'))).toBe('circle');
    expect(stemShape(treeGroupOf('seedling'))).toBe('circle');
    expect(stemShape(treeGroupOf(undefined))).toBe('circle');
    expect(treeGroupOf('garbage')).toBe('other');
  });

  it('size grows with the DBH class', () => {
    const radii = [5, 15, 25, 35, 45, 55, 65, 90].map((d) => stemRadius(d, 'felling', 18));
    for (let i = 1; i < radii.length; i++) expect(radii[i]).toBeGreaterThan(radii[i - 1]);
  });

  it('grows with the zoom, within sane limits', () => {
    expect(stemZoomFactor(18)).toBe(1);
    expect(stemZoomFactor(20)).toBeCloseTo(2, 5);
    expect(stemZoomFactor(10)).toBe(0.9);   // floor
    expect(stemZoomFactor(30)).toBe(2.6);   // cap
    expect(stemRadius(45, 'felling', 21)).toBeGreaterThan(stemRadius(45, 'felling', 18));
    expect(stemRadius(200, 'mother', 30)).toBeLessThanOrEqual(12);
  });

  it('a mother-tree star is never too small to read, even for the smallest DBH', () => {
    expect(stemRadius(5, 'mother', 18)).toBeGreaterThanOrEqual(3.5);
    expect(stemRadius(5, 'mother', 18)).toBeGreaterThan(stemRadius(5, 'felling', 18));
  });

  it('seedlings are small and ignore DBH', () => {
    expect(stemRadius(90, 'seedling', 18)).toBe(stemRadius(5, 'seedling', 18));
    expect(stemRadius(90, 'seedling', 18)).toBeLessThan(stemRadius(45, 'felling', 18));
  });

  it('an unknown DBH reads mid-size, not zero', () => {
    expect(stemRadius(null, 'felling', 18)).toBeGreaterThan(0);
    expect(stemRadius(NaN, 'felling', 18)).toBe(stemRadius(25, 'felling', 18));
  });
});
