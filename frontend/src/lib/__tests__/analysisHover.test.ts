import { describe, it, expect } from 'vitest';
import { analysisHoverFact, hoverFactHtml, type HoverOptions } from '../analysisHover';
import { defaultAnalysisRenderer } from '../analysisMaps';
import { CATEGORICAL } from '../semanticPalettes';
import type { RendererSpec } from '../layerRenderers';

// the translator returns the default text with {{vars}} filled, and the key for keys that have none (like the app does)
const t: HoverOptions['t'] = (k, o) => {
  if (k === 'sfm.ref.typeDash') return `Type-${o?.n}`;
  const text = (o?.defaultValue as string) ?? k;
  return text.replace(/\{\{(\w+)\}\}/g, (_m, v) => String(o?.[v] ?? ''));
};
const opts = (over: Partial<HoverOptions> = {}): HoverOptions => ({ lang: 'en', t, saved: {}, ...over });
const saved: Record<string, RendererSpec | undefined> = {};

describe('analysisHoverFact — the legend fact for the unit under the pointer', () => {
  it('forest type: the type with its legend colour, slope band as the value, plots and orientation underneath', () => {
    const f = analysisHoverFact('sfm_type', { sfm_type: '7', sfm_state: 'classified', sfm_slope_band: '19–31°', sfm_plot_count: 6, sfm_orientation: 'Production' }, opts())!;
    expect(f.heading).toBe('Type-7');
    expect(f.swatch).toBe(CATEGORICAL.sfm_forest_type['7']); // exactly the legend's colour for that type
    expect(f.value).toBe('19–31°');
    expect(f.lines).toEqual(['6 sample plots', 'Production']);
  });

  it('a block with no type says why, in the neutral class; an unclassified unit gets no card', () => {
    const f = analysisHoverFact('sfm_type', { sfm_type: 'none', sfm_state: 'non_forest' }, opts())!;
    expect(f.heading).toBe('sfm.state.nonForest');
    expect(analysisHoverFact('sfm_type', {}, opts())).toBeNull();
  });

  it('stock: the legend class (the bucket) and the value; no stock reads a dash and no swatch', () => {
    const f = analysisHoverFact('sfm_stock', { sfm_type: '7', sfm_gs: 210 }, opts())!;
    expect(f.value).toBe('210 m³/ha');
    expect(f.heading).toMatch(/200/); // the bucket above the 200 step edge
    const none = analysisHoverFact('sfm_stock', { sfm_type: 'none', sfm_state: 'non_forest', sfm_gs: null }, opts())!;
    expect(none.value).toBe('—');
    expect(none.swatch).toBeNull();
  });

  it('a user-changed colour is what the card shows (it reads the same renderer as the legend)', () => {
    const custom = { ...defaultAnalysisRenderer('sfm_orientation')! } as RendererSpec;
    const mine: Record<string, RendererSpec | undefined> = {
      'analysis:sfm_orientation': { ...(custom as { mode: 'categorized'; field: string; classes: Array<{ value: string; color: string }> }), classes: [{ value: 'Production', color: '#123456' }] } as RendererSpec,
    };
    expect(analysisHoverFact('sfm_orientation', { sfm_type: '7', sfm_orientation: 'Production' }, opts({ saved: mine }))!.swatch).toBe('#123456');
  });

  it('field inventory: the class the legend names for that colour, and the value with its unit', () => {
    const legend = [
      { key: '1', color: '#bae4b3', label: '15.05 – 51.85', label_ne: 'क', label_en: '15.05 – 51.85', count: 1, editable: true },
      { key: '2', color: '#238b45', label: '> 70.67', label_ne: 'ख', label_en: '> 70.67', count: 1, editable: true },
    ];
    const f = analysisHoverFact('fi_growing_stock', { um_color: '#238B45', um_text: '80 m³/ha' }, opts({ unitLegend: legend }))!;
    expect(f).toMatchObject({ swatch: '#238B45', heading: '> 70.67', value: '80 m³/ha' }); // colour match is case-insensitive
    expect(analysisHoverFact('fi_growing_stock', { um_color: '#238B45', um_text: '80 m³/ha' }, opts({ unitLegend: legend, lang: 'ne' }))!.heading).toBe('ख');
    expect(analysisHoverFact('fi_growing_stock', {}, opts({ unitLegend: legend }))).toBeNull(); // no field inventory for the unit
  });

  it('a categorical field-inventory map does not say the same word twice', () => {
    const legend = [{ key: 'Weak', color: '#c62828', label: 'कमजोर', label_ne: 'कमजोर', label_en: 'Weak', count: 3, editable: true }];
    const f = analysisHoverFact('fi_condition', { um_color: '#c62828', um_text: 'Weak' }, opts({ unitLegend: legend }))!;
    expect(f.heading).toBe('Weak');
    expect(f.value).toBeNull();
  });

  it('hazard maps: the unit’s own numbers from the cached surface', () => {
    expect(analysisHoverFact('hazard_soil', { hz_soil_mean: 36.4, hz_soil_severe_pct: 30.2 }, opts())).toMatchObject({
      value: '36.4 t/ha/yr (mean)', lines: ['30% of its area is Severe or worse'],
    });
    const lsi = analysisHoverFact('hazard_lsi', { hz_lsi_class_en: 'High', hz_lsi_class_ne: 'उच्च', hz_lsi_high_pct: 44.6 }, opts())!;
    expect(lsi.heading).toBe('High');
    expect(lsi.lines).toContain('45% of its area is High or above');
    expect(lsi.lines).toContain('Classes are relative to this forest.'); // the relative method is always said
    expect(analysisHoverFact('hazard_lsi', { hz_lsi_class_en: 'High', hz_lsi_class_ne: 'उच्च' }, opts({ lang: 'ne' }))!.heading).toBe('उच्च');
    expect(analysisHoverFact('hazard_fs', { hz_fs_unsafe_pct: 3.2, hz_fs_unstable_pct: 1 }, opts()))
      .toMatchObject({ value: '3% unsafe (unstable + marginal)', lines: ['1% unstable'] });
    expect(analysisHoverFact('hazard_prone', { hz_prone_pct: 40.4 }, opts())!.value).toBe('40% relatively high susceptibility');
  });

  it('a unit the hazard maps have nothing for, and maps with no per-unit fact, get no card', () => {
    expect(analysisHoverFact('hazard_soil', {}, opts())).toBeNull();
    expect(analysisHoverFact('hazard_hh', { hz_soil_mean: 3 }, opts())).toBeNull();
    expect(analysisHoverFact('hazard_f_soil_r', {}, opts())).toBeNull();
    expect(analysisHoverFact(null, { sfm_type: '7' }, opts())).toBeNull();
    void saved;
  });
});

describe('hoverFactHtml — user text never becomes markup', () => {
  const fact = { map: 'Growing Stock <Map>', swatch: '#238b45', heading: '> 70 "x"', value: '80 m³/ha', lines: ['<b>line</b>'] };

  it('escapes the unit name, the map name, the class, the value and the extra lines', () => {
    const html = hoverFactHtml('<img src=x onerror=alert(1)>', fact);
    expect(html).not.toContain('<img');
    expect(html).not.toContain('<Map>');
    expect(html).not.toContain('<b>line</b>');
    expect(html).toContain('&lt;img src=x onerror=alert(1)&gt;');
    expect(html).toContain('&quot;x&quot;');
  });

  it('a colour must be a plain #rrggbb to reach a style attribute', () => {
    expect(hoverFactHtml('A', fact)).toContain('background:#238b45');
    const bad = hoverFactHtml('A', { ...fact, swatch: 'red;} body{display:none' });
    expect(bad).not.toContain('display:none');
    expect(bad).not.toContain('background:red');
  });

  it('a unit with no class or value still shows its name and the map', () => {
    const html = hoverFactHtml('blocks-3', { map: 'Soil loss', swatch: null, heading: null, value: null, lines: [] });
    expect(html).toContain('blocks-3');
    expect(html).toContain('Soil loss');
  });
});
