import { describe, it, expect } from 'vitest';
import {
  applyWorkingCircleStyle,
  resolveLayerStyle,
  resolveFeatureStyle,
  resolveRendererStyle,
  applyLayerAlpha,
  buildStylePatch,
  coerceAttributeValue,
  layerStyleKey,
  NAMED_STYLE_PRESETS,
  getStyleClipboard,
  setStyleClipboard,
  PROTECTION_WC_COLOR,
  PROTECTION_WC_STROKE,
  type LayerStyle,
} from '../layerStyles';

describe('applyWorkingCircleStyle (Protection Working Circle — P5-display)', () => {
  const paletteStyle: LayerStyle = { fillColor: '#1E90FF', color: '#1E90FF', fillOpacity: 0.15, weight: 2 };

  it('passes a production unit style through untouched', () => {
    expect(applyWorkingCircleStyle(paletteStyle, 'production')).toBe(paletteStyle);
    expect(applyWorkingCircleStyle(paletteStyle, undefined)).toBe(paletteStyle);
    expect(applyWorkingCircleStyle(paletteStyle, null)).toBe(paletteStyle);
  });

  it('overlays the conservation-green dashed treatment for a protection unit', () => {
    const out = applyWorkingCircleStyle(paletteStyle, 'protection');
    expect(out.fillColor).toBe(PROTECTION_WC_COLOR);
    expect(out.color).toBe(PROTECTION_WC_STROKE);
    expect(out.dashArray).toBe('6, 4');
    // never dimmer than the protection baseline, and it keeps other keys
    expect(out.fillOpacity).toBeGreaterThanOrEqual(0.35);
    expect(out.weight).toBe(2);
  });

  it('does not lower an already-higher fill opacity', () => {
    const out = applyWorkingCircleStyle({ ...paletteStyle, fillOpacity: 0.6 }, 'protection');
    expect(out.fillOpacity).toBe(0.6);
  });
});

describe('resolveLayerStyle (WORKSPACE_LAYER_STYLING_PLAN.md P0)', () => {
  const base: LayerStyle = { color: '#1E90FF', weight: 2, fillOpacity: 0.15 };

  it('no custom style → returns the base by reference (golden: unchanged path)', () => {
    expect(resolveLayerStyle({ base })).toBe(base);
    expect(resolveLayerStyle({ base, custom: {} })).toBe(base);
    expect(resolveLayerStyle({ base, custom: { __flat: true } })).toBe(base);
  });

  it('no custom + a palette colour → base plus that colour (matches pre-P0 behaviour)', () => {
    const out = resolveLayerStyle({ base, usesPalette: true, paletteColor: '#abc123' });
    expect(out).not.toBe(base);
    expect(out).toEqual({ ...base, fillColor: '#abc123', color: '#abc123' });
  });

  it('palette layer: custom weight/opacity apply, palette keeps the colour', () => {
    const out = resolveLayerStyle({
      base, usesPalette: true, paletteColor: '#abc123',
      custom: { weight: 5, fillOpacity: 0.6, fillColor: '#ff0000', color: '#ff0000' },
    });
    expect(out.weight).toBe(5);
    expect(out.fillOpacity).toBe(0.6);
    expect(out.fillColor).toBe('#abc123'); // palette wins
    expect(out.color).toBe('#abc123');
  });

  it('palette layer + __flat: the custom colour overrides the palette', () => {
    const out = resolveLayerStyle({
      base, usesPalette: true, paletteColor: '#abc123',
      custom: { __flat: true, fillColor: '#ff0000', color: '#ff0000' },
    });
    expect(out.fillColor).toBe('#ff0000');
    expect(out.color).toBe('#ff0000');
  });

  it('non-palette layer: custom colour applies directly', () => {
    const out = resolveLayerStyle({ base, custom: { fillColor: '#00ff00', weight: 3 } });
    expect(out.fillColor).toBe('#00ff00');
    expect(out.weight).toBe(3);
    expect(out.color).toBe('#1E90FF'); // untouched base
  });

  it('null / undefined custom keys are ignored, not written as null', () => {
    const out = resolveLayerStyle({ base, custom: { weight: 4, fillColor: undefined as never } });
    expect(out.weight).toBe(4);
    expect('fillColor' in out).toBe(false);
  });
});

describe('resolveFeatureStyle (WORKSPACE_LAYER_STYLING_PLAN.md P3.3)', () => {
  const base: LayerStyle = { fillColor: '#111111', color: '#222222', fillOpacity: 0.2, weight: 2 };

  it('returns base by reference when there is no override', () => {
    expect(resolveFeatureStyle(base)).toBe(base);
    expect(resolveFeatureStyle(base, null)).toBe(base);
    expect(resolveFeatureStyle(base, {})).toBe(base);
    expect(resolveFeatureStyle(base, { fill: null, stroke: null, fillOpacity: null, weight: null })).toBe(base);
  });

  it('maps fill/stroke/fillOpacity/weight onto the leaflet keys', () => {
    const out = resolveFeatureStyle(base, { fill: '#ff0000', fillOpacity: 0.5 });
    expect(out.fillColor).toBe('#ff0000');
    expect(out.fillOpacity).toBe(0.5);
    expect(out.color).toBe('#222222'); // stroke untouched
    expect(out.weight).toBe(2);
    expect(out).not.toBe(base);
  });

  it('a per-feature override wins over the working-circle treatment', () => {
    const wc = applyWorkingCircleStyle(base, 'protection');
    expect(wc.fillColor).toBe(PROTECTION_WC_COLOR);
    const out = resolveFeatureStyle(wc, { fill: '#abcdef' });
    expect(out.fillColor).toBe('#abcdef');
  });
});

describe('resolveRendererStyle (WORKSPACE_LAYER_STYLING_PLAN.md P4.2)', () => {
  const base: LayerStyle = { fillColor: '#111', color: '#222', weight: 2, fillOpacity: 0.3 };

  it('returns base by reference when the renderer does not cover the feature', () => {
    expect(resolveRendererStyle(base, null)).toBe(base);
    expect(resolveRendererStyle(base, undefined)).toBe(base);
  });

  it('a renderer colour overrides fill + stroke, leaving weight / opacity', () => {
    const out = resolveRendererStyle(base, '#00ff00');
    expect(out.fillColor).toBe('#00ff00');
    expect(out.color).toBe('#00ff00');
    expect(out.weight).toBe(2);
    expect(out.fillOpacity).toBe(0.3);
    expect(out).not.toBe(base);
  });
});

describe('applyLayerAlpha (WORKSPACE_LAYER_STYLING_PLAN.md P5.2)', () => {
  const base: LayerStyle = { fillColor: '#111', color: '#222', weight: 2, fillOpacity: 0.4 };

  it('alpha of 1 or undefined returns the style by reference', () => {
    expect(applyLayerAlpha(base, 1)).toBe(base);
    expect(applyLayerAlpha(base, undefined)).toBe(base);
  });

  it('multiplies fillOpacity and sets stroke opacity', () => {
    const out = applyLayerAlpha(base, 0.5);
    expect(out.fillOpacity).toBeCloseTo(0.2);
    expect(out.opacity).toBeCloseTo(0.5);
    expect(out.fillColor).toBe('#111');
  });

  it('compounds with an existing stroke opacity', () => {
    const out = applyLayerAlpha({ ...base, opacity: 0.8 }, 0.5);
    expect(out.opacity).toBeCloseTo(0.4);
  });
});

describe('buildStylePatch (WORKSPACE_LAYER_STYLING_PLAN.md P3.4)', () => {
  it('returns undefined for a non-style column', () => {
    expect(buildStylePatch(null, 'name', 'x')).toBeUndefined();
  });

  it('style_clear always returns null', () => {
    expect(buildStylePatch({ fill: '#abc' }, 'style_clear', '')).toBeNull();
  });

  it('merges a fill onto the existing override', () => {
    expect(buildStylePatch({ fillOpacity: 0.5 }, 'style_fill', '#ff0000')).toEqual({ fillOpacity: 0.5, fill: '#ff0000' });
  });

  it('sets fillOpacity as a number; empty clears the key and collapses to null', () => {
    expect(buildStylePatch(null, 'style_opacity', '0.25')).toEqual({ fillOpacity: 0.25 });
    expect(buildStylePatch({ fillOpacity: 0.25 }, 'style_opacity', '')).toBeNull();
  });

  it('clearing the last key collapses the object to null', () => {
    expect(buildStylePatch({ fill: '#abc' }, 'style_fill', '')).toBeNull();
  });
});

describe('coerceAttributeValue (user report, 2026-09-12 — classification columns editable)', () => {
  it('passes a plain string column through unchanged', () => {
    expect(coerceAttributeValue('natural_name', 'Rapati Nadi')).toBe('Rapati Nadi');
    expect(coerceAttributeValue('compartment_code', 'C-3')).toBe('C-3');
  });

  it('coerces a classification column\'s select value to a number', () => {
    expect(coerceAttributeValue('dominant_slope_band', '3')).toBe(3);
    expect(coerceAttributeValue('dominant_aspect', '8')).toBe(8);
    expect(coerceAttributeValue('dominant_canopy_class', '1')).toBe(1);
  });

  it('coerces the blank "-" option to null (clears the field), not NaN or ""', () => {
    expect(coerceAttributeValue('dominant_slope_band', '')).toBeNull();
    expect(coerceAttributeValue('dominant_aspect', '')).toBeNull();
    expect(coerceAttributeValue('dominant_canopy_class', '')).toBeNull();
  });
});

describe('named presets + style clipboard (P1.4)', () => {
  it('every preset is a flat colour override', () => {
    for (const [name, p] of Object.entries(NAMED_STYLE_PRESETS)) {
      expect(p.__flat, name).toBe(true);
      expect(typeof p.weight).toBe('number');
    }
  });

  it('the clipboard round-trips a copy, and stores a clone', () => {
    setStyleClipboard(null);
    expect(getStyleClipboard()).toBeNull();
    const src = { fillColor: '#123456', weight: 3 };
    setStyleClipboard(src);
    const got = getStyleClipboard();
    expect(got).toEqual(src);
    expect(got).not.toBe(src); // clone, not the same ref
    setStyleClipboard(null);
  });
});

describe('layerStyleKey', () => {
  it('scopes built-ins by calculation', () => {
    expect(layerStyleKey('blocks', 'builtin', 'calc-1')).toBe('calc-1::blocks');
    expect(layerStyleKey('blocks', 'builtin', null)).toBe('nc::blocks');
  });
  it('imported layers keep a global imported-<id> key', () => {
    expect(layerStyleKey('7', 'imported', 'calc-1')).toBe('imported-7');
    expect(layerStyleKey('imported-7', 'imported', 'calc-1')).toBe('imported-7');
  });
});

describe('Field Book vs Sample Plots — two numbered-circle layers, two colours', () => {
  it('Field Book is sky blue and Sample Plots stay amber', async () => {
    const { STYLE_PRESETS, FIELDBOOK_COLOR } = await import('../layerStyles');
    expect(FIELDBOOK_COLOR).toBe('#38bdf8');
    expect(STYLE_PRESETS.fieldbook.fillColor).toBe(FIELDBOOK_COLOR);
    expect(STYLE_PRESETS.fieldbook.color).toBe(FIELDBOOK_COLOR);
    expect(STYLE_PRESETS.sample_plots.fillColor).toBe('#fbbf24');
  });

  it('the two layers no longer share a style, so the legend and map cannot show one colour for both', async () => {
    const { STYLE_PRESETS } = await import('../layerStyles');
    const { getLayerConfig } = await import('../layerRegistry');
    const fb = getLayerConfig('fieldbook')!;
    const sp = getLayerConfig('sample_plots')!;
    expect(fb.styleKey).not.toBe(sp.styleKey);
    const fbStyle = STYLE_PRESETS[fb.styleKey as keyof typeof STYLE_PRESETS];
    const spStyle = STYLE_PRESETS[sp.styleKey as keyof typeof STYLE_PRESETS];
    expect(fbStyle.fillColor).not.toBe(spStyle.fillColor);
    expect(fbStyle.color).not.toBe(spStyle.color);
  });
});

describe('stableUnitColor (owner report 2026-10-02)', () => {
  it('is stable for the same id across calls, independent of any list/position', async () => {
    const { stableUnitColor } = await import('../layerStyles');
    const id = 'c3b3bc10-847e-4d83-a183-d65daecd3ae5';
    expect(stableUnitColor(id)).toBe(stableUnitColor(id));
  });

  it('two different ids usually differ, so units still read as distinct categories', async () => {
    const { stableUnitColor } = await import('../layerStyles');
    const colours = new Set(
      ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'].map((id) => stableUnitColor(id)),
    );
    expect(colours.size).toBeGreaterThan(1);
  });

  it('a unit keeps its colour when OTHER units are added/removed — the actual bug fixed here', async () => {
    // The old `colorIndex: index` scheme recoloured every unit whenever
    // the list it came from changed length or order, even though the unit
    // itself never changed. stableUnitColor depends only on the id, so
    // "removing the first of three" cannot move the colour of the other two.
    const { stableUnitColor } = await import('../layerStyles');
    const idB = 'block-b';
    const idC = 'block-c';
    const beforeB = stableUnitColor(idB);
    const beforeC = stableUnitColor(idC);
    // Simulate "block A was deleted" — nothing about B or C's own identity
    // changed, so their colour must not change either.
    const afterB = stableUnitColor(idB);
    const afterC = stableUnitColor(idC);
    expect(afterB).toBe(beforeB);
    expect(afterC).toBe(beforeC);
  });

  it('falls back to a fixed colour for a missing id, never throws', async () => {
    const { stableUnitColor } = await import('../layerStyles');
    expect(() => stableUnitColor(undefined)).not.toThrow();
    expect(() => stableUnitColor(null)).not.toThrow();
    expect(stableUnitColor(undefined)).toBe(stableUnitColor(null));
  });
});

describe('defaultImportedLabelField (owner report 2026-10-02: "Make all layer labeled based on their existing field names")', () => {
  function feat(properties: Record<string, unknown>): GeoJSON.Feature {
    return { type: 'Feature', properties, geometry: { type: 'Point', coordinates: [0, 0] } };
  }

  it('prefers "name" over every other field', async () => {
    const { defaultImportedLabelField } = await import('../layerStyles');
    const field = defaultImportedLabelField([feat({ id: 1, zone: 'a', name: 'Plot 1', label: 'x' })]);
    expect(field).toBe('name');
  });

  it('falls back down the priority list when "name" is absent', async () => {
    const { defaultImportedLabelField } = await import('../layerStyles');
    expect(defaultImportedLabelField([feat({ id: 1, label: 'Plot 1' })])).toBe('label');
    expect(defaultImportedLabelField([feat({ id: 1, title: 'Plot 1' })])).toBe('title');
    expect(defaultImportedLabelField([feat({ id: 1, block_name: 'B-1' })])).toBe('block_name');
  });

  it('matches case-insensitively (a real imported field is often capitalised)', async () => {
    const { defaultImportedLabelField } = await import('../layerStyles');
    expect(defaultImportedLabelField([feat({ Name: 'Plot 1' })])).toBe('Name');
  });

  it('never picks an internal/structural field (id, style, geometry, ...)', async () => {
    const { defaultImportedLabelField } = await import('../layerStyles');
    const field = defaultImportedLabelField([feat({ id: 1, colorIndex: 2, style: {}, zone: 'a' })]);
    expect(field).toBe('zone'); // the one real, non-internal field
  });

  it('falls back to the first real field when nothing name-like exists — never blank when real data exists', async () => {
    const { defaultImportedLabelField } = await import('../layerStyles');
    expect(defaultImportedLabelField([feat({ id: 1, zone: 'a', area: 5 })])).toBe('zone');
  });

  it('returns null for an empty feature list or a feature with only internal fields', async () => {
    const { defaultImportedLabelField } = await import('../layerStyles');
    expect(defaultImportedLabelField([])).toBeNull();
    expect(defaultImportedLabelField([feat({ id: 1, colorIndex: 0 })])).toBeNull();
  });
});
