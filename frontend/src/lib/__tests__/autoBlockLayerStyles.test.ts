/**
 * RS-2.20 (owner directive 2026-10-01) — default per-source Auto-Block layer
 * styling. Verifies each source's style shape (flat/ramp/categorical) and
 * that promoted vs trial layers are visually distinguishable.
 */
import { describe, it, expect } from 'vitest';
import { autoBlockFeatureStyle, defaultLabelField, SOURCE_LABEL_KEY } from '../autoBlockLayerStyles';

function feature(props: Record<string, unknown>): GeoJSON.Feature {
  return { type: 'Feature', properties: props, geometry: { type: 'Polygon', coordinates: [] } };
}

describe('autoBlockFeatureStyle', () => {
  it('mmu is a flat cyan outline with a near-hollow fill', () => {
    const s = autoBlockFeatureStyle('mmu', feature({ Name: 'mmu-1' }), true);
    expect(s.color).toBe('#00FFFF');
    expect(s.fillColor).toBe('#00FFFF');
    expect(s.fillOpacity).toBeLessThan(0.15);
  });

  it('canopy is a flat emerald, not graded by class', () => {
    const a = autoBlockFeatureStyle('canopy', feature({ 'Canopy Class': 'Tree' }), true);
    const b = autoBlockFeatureStyle('canopy', feature({ 'Canopy Class': 'Regeneration' }), true);
    expect(a.fillColor).toBe(b.fillColor);
    expect(a.fillColor).toBe('#00FF66');
  });

  it('slope ramps from yellow (gentle) to crimson (very steep) by ordinal code', () => {
    const gentle = autoBlockFeatureStyle('slope', feature({ 'Slope Band': 'Gentle', '_Slope Band_code': 1 }), true);
    const steep = autoBlockFeatureStyle('slope', feature({ 'Slope Band': 'Very Steep', '_Slope Band_code': 4 }), true);
    expect(gentle.fillColor).toBe('#ffff00');
    expect(steep.fillColor).toBe('#d32f2f');
  });

  it('forest_health ramps from healthy green to stressed magenta', () => {
    const healthy = autoBlockFeatureStyle('forest_health', feature({ 'Forest Health': 'Excellent', '_Forest Health_code': 5 }), true);
    const stressed = autoBlockFeatureStyle('forest_health', feature({ 'Forest Health': 'Stressed', '_Forest Health_code': 1 }), true);
    expect(healthy.fillColor).toBe('#1b5e20');
    expect(stressed.fillColor).toBe('#e91e63');
  });

  it('aspect is categorical, reusing the existing semantic SSOT palette (not a forked copy)', () => {
    const north = autoBlockFeatureStyle('aspect', feature({ Aspect: 'N' }), true);
    const south = autoBlockFeatureStyle('aspect', feature({ Aspect: 'S' }), true);
    expect(north.fillColor).not.toBe(south.fillColor);
    expect(north.fillColor).toBe('#4575b4');
  });

  it('landcover uses the official ESA hexes, keyed by the exact label backend emits', () => {
    const tree = autoBlockFeatureStyle('landcover', feature({ 'Land Cover': 'Tree cover' }), true);
    expect(tree.fillColor).toBe('#006400');
  });

  it('an unknown/missing classification falls back to a visible neutral grey, not a crash', () => {
    const s = autoBlockFeatureStyle('landcover', feature({}), true);
    expect(s.fillColor).toBeTruthy();
  });

  it('trial (unpromoted) layers render dashed and dimmer than promoted ones', () => {
    const promoted = autoBlockFeatureStyle('slope', feature({ 'Slope Band': 'Steep', '_Slope Band_code': 3 }), true);
    const trial = autoBlockFeatureStyle('slope', feature({ 'Slope Band': 'Steep', '_Slope Band_code': 3 }), false);
    expect(promoted.dashArray).toBeUndefined();
    expect(trial.dashArray).toBeTruthy();
    expect((trial.fillOpacity ?? 0)).toBeLessThan((promoted.fillOpacity ?? 1));
  });

  it('every source has a default label field, mmu falls back to Natural Name', () => {
    for (const source of Object.keys(SOURCE_LABEL_KEY)) {
      expect(defaultLabelField(source)).toBeTruthy();
    }
    expect(defaultLabelField('mmu')).toBe('Natural Name');
    expect(defaultLabelField('slope')).toBe('Slope Band');
  });

  it('union_zonal and union_fusion share ONE default style, both keyed on slope band (owner directive 2026-10-02)', () => {
    const gentleZonal = autoBlockFeatureStyle('union_zonal', feature({ 'Slope Band': 'Gentle', '_Slope Band_code': 1, 'Forest Type': 'Sal' }), true);
    const gentleFusion = autoBlockFeatureStyle('union_fusion', feature({ 'Slope Band': 'Gentle', '_Slope Band_code': 1, 'Forest Type': 'Oak' }), true);
    // Same code -> same colour, regardless of source and regardless of any
    // of the other 8 attributes -- "user will get the same sense from
    // those layers" (owner).
    expect(gentleZonal.fillColor).toBe(gentleFusion.fillColor);

    const steep = autoBlockFeatureStyle('union_zonal', feature({ 'Slope Band': 'Very Steep', '_Slope Band_code': 4 }), true);
    expect(steep.fillColor).not.toBe(gentleZonal.fillColor);
  });

  it('Union slope-band colours are exactly green/yellow/orange/red, in that band order', () => {
    const colourFor = (code: number) =>
      autoBlockFeatureStyle('union_zonal', feature({ '_Slope Band_code': code }), true).fillColor;
    expect(colourFor(1)).toBe('#2E7D32'); // green  — gentle,     < 19°
    expect(colourFor(2)).toBe('#F9A825'); // yellow — moderate, 19-31°
    expect(colourFor(3)).toBe('#EF6C00'); // orange — steep,    31-45°
    expect(colourFor(4)).toBe('#C62828'); // red    — very steep, > 45°
  });

  it('a Union piece with no slope coverage at all falls back to neutral grey, not a crash', () => {
    const s = autoBlockFeatureStyle('union_fusion', feature({}), true);
    expect(s.fillColor).toBe('#9CA3AF');
  });

  it('union_zonal falls back to Natural Name like mmu — no single column to show', () => {
    expect(defaultLabelField('union_zonal')).toBe('Natural Name');
    expect(defaultLabelField('union_fusion')).toBe('Natural Name');
  });
});
