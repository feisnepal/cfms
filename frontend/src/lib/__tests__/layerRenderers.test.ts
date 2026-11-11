import { describe, it, expect } from 'vitest';
import {
  rendererColorFor,
  rendererLegendRows,
  buildCategorizedRenderer,
  buildGraduatedRenderer,
  CONDITION_RENDERER,
  SLOPE_BAND_RENDERER,
  ASPECT_RENDERER,
  CANOPY_CLASS_RENDERER,
  type CategorizedRenderer,
  type GraduatedRenderer,
} from '../layerRenderers';

const feats = (pairs: Array<Record<string, unknown>>) =>
  pairs.map((properties) => ({ type: 'Feature' as const, geometry: null as never, properties }));

describe('rendererColorFor — categorized (P4.2)', () => {
  const spec: CategorizedRenderer = {
    mode: 'categorized',
    field: 'working_circle',
    classes: [
      { value: 'production', color: '#111111' },
      { value: 'protection', color: '#222222' },
    ],
    otherColor: '#999999',
  };

  it('maps a matching value to its class colour', () => {
    expect(rendererColorFor(spec, 'protection')).toBe('#222222');
  });
  it('an unmatched value falls to otherColor', () => {
    expect(rendererColorFor(spec, 'grazing')).toBe('#999999');
  });
  it('without otherColor an unmatched value yields null (keeps normal style)', () => {
    expect(rendererColorFor({ ...spec, otherColor: undefined }, 'x')).toBeNull();
  });
});

describe('rendererColorFor — graduated (P4.2)', () => {
  const spec: GraduatedRenderer = {
    mode: 'graduated',
    field: 'area',
    method: 'equal',
    breaks: [10, 20],
    colors: ['#a', '#b', '#c'],
    ramp: 'blues',
  };

  it('picks the bucket by break (value <= break)', () => {
    expect(rendererColorFor(spec, 5)).toBe('#a');
    expect(rendererColorFor(spec, 10)).toBe('#a');
    expect(rendererColorFor(spec, 15)).toBe('#b');
    expect(rendererColorFor(spec, 999)).toBe('#c');
  });
  it('non-numeric → null', () => {
    expect(rendererColorFor(spec, 'nope')).toBeNull();
    expect(rendererColorFor(spec, null)).toBeNull();
  });
});

describe('buildCategorizedRenderer', () => {
  it('one class per distinct value, sorted, coloured from the ramp', () => {
    const r = buildCategorizedRenderer(
      feats([{ wc: 'protection' }, { wc: 'production' }, { wc: 'production' }]),
      'wc', 'blues',
    );
    expect(r.mode).toBe('categorized');
    expect(r.classes.map((c) => c.value)).toEqual(['production', 'protection']);
    expect(r.classes.every((c) => /^#[0-9a-f]{6}$/i.test(c.color))).toBe(true);
  });
});

describe('buildGraduatedRenderer', () => {
  it('computes breaks + one more colour than breaks', () => {
    const r = buildGraduatedRenderer(
      feats([1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((area) => ({ area }))),
      'area', 4, 'equal', 'greens',
    );
    expect(r.breaks).toHaveLength(3);
    expect(r.colors).toHaveLength(4);
    expect(r.method).toBe('equal');
    expect(r.ramp).toBe('greens');
  });
});

describe('CONDITION_RENDERER (P4.5 preset)', () => {
  it('is a categorized renderer on forest_condition with Good/Moderate/Weak + Other', () => {
    expect(CONDITION_RENDERER.mode).toBe('categorized');
    expect(CONDITION_RENDERER.field).toBe('forest_condition');
    expect(CONDITION_RENDERER.classes.map((c) => c.value)).toEqual(['Good', 'Moderate', 'Weak']);
    expect(CONDITION_RENDERER.otherColor).toBeTruthy();
    expect(rendererColorFor(CONDITION_RENDERER, 'Good')).toBe('#2e7d32');
    expect(rendererColorFor(CONDITION_RENDERER, 'unknown')).toBe(CONDITION_RENDERER.otherColor);
  });
});

describe('Auto-Block classification presets (SLOPE_BAND_RENDERER / ASPECT_RENDERER / CANOPY_CLASS_RENDERER)', () => {
  it('SLOPE_BAND_RENDERER colours 1-4 (gentle green -> steep red) and matches the raw integer property', () => {
    expect(SLOPE_BAND_RENDERER.mode).toBe('categorized');
    expect(SLOPE_BAND_RENDERER.field).toBe('dominant_slope_band');
    expect(SLOPE_BAND_RENDERER.classes).toHaveLength(4);
    // The stored property is a number (1-4); rendererColorFor must still match it
    // against the renderer's string-keyed classes.
    expect(rendererColorFor(SLOPE_BAND_RENDERER, 1)).toBe('#a5d6a7');
    expect(rendererColorFor(SLOPE_BAND_RENDERER, 4)).toBe('#e53935');
    expect(rendererColorFor(SLOPE_BAND_RENDERER, null)).toBe(SLOPE_BAND_RENDERER.otherColor);
  });

  it('ASPECT_RENDERER is symmetric on the N-S axis (NE=NW, E=W, SE=SW colours)', () => {
    expect(ASPECT_RENDERER.field).toBe('dominant_aspect');
    expect(ASPECT_RENDERER.classes).toHaveLength(8);
    expect(rendererColorFor(ASPECT_RENDERER, 1)).toBe('#08519c'); // N
    expect(rendererColorFor(ASPECT_RENDERER, 5)).toBe('#bd0026'); // S
    expect(rendererColorFor(ASPECT_RENDERER, 2)).toBe(rendererColorFor(ASPECT_RENDERER, 8)); // NE = NW
    expect(rendererColorFor(ASPECT_RENDERER, 3)).toBe(rendererColorFor(ASPECT_RENDERER, 7)); // E = W
    expect(rendererColorFor(ASPECT_RENDERER, 4)).toBe(rendererColorFor(ASPECT_RENDERER, 6)); // SE = SW
    // N and S must be genuinely distinct (the diverging axis is real, not flat).
    expect(rendererColorFor(ASPECT_RENDERER, 1)).not.toBe(rendererColorFor(ASPECT_RENDERER, 5));
  });

  it('CANOPY_CLASS_RENDERER runs pale (young) -> deep green (mature), non-forest is grey not green', () => {
    expect(CANOPY_CLASS_RENDERER.field).toBe('dominant_canopy_class');
    expect(CANOPY_CLASS_RENDERER.classes).toHaveLength(4);
    expect(rendererColorFor(CANOPY_CLASS_RENDERER, 1)).toBe('#bcaaa4'); // non-forest: not green
    expect(rendererColorFor(CANOPY_CLASS_RENDERER, 2)).not.toBe(rendererColorFor(CANOPY_CLASS_RENDERER, 4));
  });
});

describe('rendererLegendRows', () => {
  it('categorized → one row per class + Other', () => {
    const rows = rendererLegendRows({
      mode: 'categorized', field: 'wc',
      classes: [{ value: 'a', color: '#1' }, { value: 'b', color: '#2' }],
      otherColor: '#3',
    });
    expect(rows.map((r) => r.label)).toEqual(['a', 'b', 'Other']);
  });

  it('graduated → range labels low → high', () => {
    const rows = rendererLegendRows({
      mode: 'graduated', field: 'area', method: 'equal',
      breaks: [10, 20], colors: ['#1', '#2', '#3'], ramp: 'blues',
    });
    expect(rows[0].label).toBe('≤ 10');
    expect(rows[1].label).toBe('10 – 20');
    expect(rows[2].label).toBe('> 20');
  });
});
