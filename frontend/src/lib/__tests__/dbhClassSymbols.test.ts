import { describe, it, expect } from 'vitest';
import { DBH_BAND_BREAKS, DBH_BAND_COLORS, DBH_CLASS_RENDERER, dbhClassRadius } from '../dbhClassSymbols';
import { rendererColorFor } from '../layerRenderers';

describe('DBH_CLASS_RENDERER (Stem Mapping default)', () => {
  it('is a graduated renderer over the numeric dbh_cm', () => {
    expect(DBH_CLASS_RENDERER.mode).toBe('graduated');
    expect(DBH_CLASS_RENDERER.field).toBe('dbh_cm');
    expect(DBH_CLASS_RENDERER.breaks).toEqual(DBH_BAND_BREAKS);
    expect(DBH_CLASS_RENDERER.colors).toEqual(DBH_BAND_COLORS);
  });

  it('has 7 breaks and 8 colours (8 bands: 1-10 .. >70)', () => {
    expect(DBH_BAND_BREAKS).toEqual([10, 20, 30, 40, 50, 60, 70]);
    expect(DBH_BAND_COLORS).toHaveLength(8);
  });

  it.each([
    [5, '#C8E6C9'],   // 1-10  pale mint green   (growing)
    [10, '#C8E6C9'],
    [15, '#81C784'],  // 10-20 medium green      (growing)
    [25, '#388E3C'],  // 20-30 deep green        (growing)
    [35, '#FBC02D'],  // 30-40 amber             (watch)
    [45, '#FF8A65'],  // 40-50 soft orange       (felling candidate)
    [55, '#E53935'],  // 50-60 red               (felling candidate)
    [65, '#D81B60'],  // 60-70 deep pink/magenta (felling candidate)
    [90, '#880E4F'],  // >70   dark maroon       (felling candidate)
  ])('dbh_cm=%d resolves to %s', (dbh, color) => {
    expect(rendererColorFor(DBH_CLASS_RENDERER, dbh)).toBe(color);
  });

  it('groups bands into 3 management-meaning colour families (green -> yellow -> red), not one continuous ramp', () => {
    // <30cm: green family
    expect(DBH_BAND_COLORS.slice(0, 3)).toEqual(['#C8E6C9', '#81C784', '#388E3C']);
    // 30-40cm: yellow, the watch/transition band
    expect(DBH_BAND_COLORS[3]).toBe('#FBC02D');
    // >=40cm: red family (felling candidate), 4 distinguishable shades
    expect(DBH_BAND_COLORS.slice(4)).toEqual(['#FF8A65', '#E53935', '#D81B60', '#880E4F']);
  });
});

describe('dbhClassRadius', () => {
  it('grows monotonically small DBH -> large DBH', () => {
    const radii = [5, 15, 25, 35, 45, 55, 65, 90].map(dbhClassRadius);
    for (let i = 1; i < radii.length; i++) {
      expect(radii[i]).toBeGreaterThan(radii[i - 1]);
    }
  });

  it('is a quarter of the pre-reduction 4..15.2 px range (a 75% cut)', () => {
    expect(dbhClassRadius(5)).toBeCloseTo(1, 5);
    expect(dbhClassRadius(90)).toBeCloseTo(3.8, 5);
  });

  it('a missing or non-finite DBH reads mid-size, not zero', () => {
    expect(dbhClassRadius(null)).toBeGreaterThan(0);
    expect(dbhClassRadius(undefined)).toBeGreaterThan(0);
    expect(dbhClassRadius(NaN)).toBeGreaterThan(0);
  });
});
