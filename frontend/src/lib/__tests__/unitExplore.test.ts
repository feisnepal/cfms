import { describe, it, expect, beforeEach, vi } from 'vitest';
import { rankUnits } from '../unitRanking';
import { unitFacts } from '../unitFacts';
import { compareFact, hoverFactHtml, COMPARABLE_MAPS, type HoverOptions } from '../analysisHover';
import { dynamicLegend, defaultAnalysisRenderer } from '../analysisMaps';
import { rendererLegendRows } from '../layerRenderers';
import { findUnits, selectionFor, unitsOfClass, zoomToUnits } from '../unitFocus';
import { getFeatureLayerRegistry } from '../featureLayerRegistry';
import { sfmPropsFor } from '../sfmFeatureProps';
import type { SfmBlockTypeInfo } from '../../services/api';

const t: HoverOptions['t'] = (k, o) => {
  if (k === 'sfm.ref.typeDash') return `Type-${o?.n}`;
  const text = (o?.defaultValue as string) ?? k;
  return text.replace(/\{\{(\w+)\}\}/g, (_m, v) => String(o?.[v] ?? ''));
};
const opts: HoverOptions = { lang: 'en', t, saved: {} };
const info = (o: Partial<SfmBlockTypeInfo> = {}): SfmBlockTypeInfo => ({
  type_no: 7, state: 'classified', land_class: 'forest', plot_count: 6, proposed_type_no: 7, overridden: false,
  orientation: 'Production', gs_ge40_m3_per_ha: 100, area_ha: 10, slope_band: 2, confidence: null, needs_review: false, reasons_ne: null, reasons_en: null, ...o,
});

describe('rankUnits — top and bottom of the active map', () => {
  const sfm = Object.fromEntries(['A', 'B', 'C'].map((n, i) => [n, info({ gs_ge40_m3_per_ha: 50 * (i + 1) })]));

  it('few units: one list, highest first', () => {
    const r = rankUnits('sfm_stock', { sfmBlockTypes: sfm })!;
    expect(r.top.map((u) => u.name)).toEqual(['C', 'B', 'A']);
    expect(r.bottom).toEqual([]);
    expect(r.top[0].text).toBe('150 m³/ha');
    expect(r.highIsWorse).toBe(false);
  });

  it('many units: the five highest and the five lowest (lowest first)', () => {
    const many = Object.fromEntries(Array.from({ length: 12 }, (_, i) => [`U${i}`, info({ gs_ge40_m3_per_ha: i * 10 })]));
    const r = rankUnits('sfm_stock', { sfmBlockTypes: many })!;
    expect(r.top.map((u) => u.value)).toEqual([110, 100, 90, 80, 70]);
    expect(r.bottom.map((u) => u.value)).toEqual([0, 10, 20, 30, 40]);
    expect(r.total).toBe(12);
  });

  it('hazard maps rank their own number and flag that HIGH is the risky end', () => {
    const hz = { A: { soil: { mean: 12.34, severe_pct: 10, area_ha: 1 } }, B: { soil: { mean: 48, severe_pct: 59, area_ha: 1 } }, C: {} };
    const r = rankUnits('hazard_soil', { hazardUnits: hz as never })!;
    expect(r.top.map((u) => [u.name, u.text])).toEqual([['B', '48.0 t/ha/yr'], ['A', '12.3 t/ha/yr']]); // C has no value: not ranked
    expect(r.highIsWorse).toBe(true);
    expect(rankUnits('hazard_fs', { hazardUnits: { A: { fs: { unstable_pct: 1, unsafe_pct: 3 } } } as never })!.top[0].text).toBe('3% unsafe');
  });

  it('a field-inventory map ranks numeric values only; a categorical one has no order', () => {
    const num = { state: 'ready', token: 't', custom_colours: false, legend: [], units: { A: { color: '#1', value: 5, text: '5 m³/ha' }, B: { color: '#2', value: 9, text: '9 m³/ha' } } } as never;
    expect(rankUnits('fi_growing_stock', { unitMap: num })!.top.map((u) => u.name)).toEqual(['B', 'A']);
    const cat = { state: 'ready', token: 't', custom_colours: false, legend: [], units: { A: { color: '#1', value: 'Weak', text: 'Weak' } } } as never;
    expect(rankUnits('fi_condition', { unitMap: cat })).toBeNull();
    expect(rankUnits('fi_growing_stock', { unitMap: null })).toBeNull();
  });

  it('class maps, charts and no map have no ranking', () => {
    expect(rankUnits('sfm_type', { sfmBlockTypes: sfm })).toBeNull();
    expect(rankUnits('hazard_hh', {})).toBeNull();
    expect(rankUnits(null, {})).toBeNull();
    expect(rankUnits('sfm_stock', { sfmBlockTypes: {} })).toBeNull();
  });
});

describe('unitFacts — everything about one unit, in sections', () => {
  const props = {
    name: 'blocks-3', area_hectares: 12.345,
    ...sfmPropsFor(info({ slope_band: 3, state: 'provisional' })),
    hz_soil_mean: 48, hz_soil_severe_pct: 59.2, hz_lsi_class_en: 'High', hz_lsi_class_ne: 'उच्च', hz_lsi_high_pct: 44.6, hz_fs_unsafe_pct: 3.2, hz_prone_pct: 40.4,
    fi_stock: 80.1, fi_aah: 0.641, fi_regeneration: 3750, fi_condition: 'Weak', fi_plots: 4,
  };

  it('has a section per source, with the numbers formatted and the units named', () => {
    const s = unitFacts(props, 'en', t);
    expect(s.map((x) => x.id)).toEqual(['unit', 'sfm', 'hazard', 'inventory']);
    const row = (sec: string, label: string) => s.find((x) => x.id === sec)!.rows.find((r) => r.label === label)?.value;
    expect(row('unit', 'Area')).toBe('12.35 ha');
    expect(row('sfm', 'Forest type')).toBe('Type-7');
    expect(row('sfm', 'Slope band')).toBe('31–45°');
    expect(row('sfm', 'Status')).toBe('Provisional (few plots)');
    expect(row('hazard', 'Soil loss (mean)')).toBe('48 t/ha/yr');
    expect(row('hazard', 'Landslide class (relative)')).toBe('High'); // always labelled relative
    expect(row('inventory', 'Growing stock')).toBe('80.1 m³/ha');
    expect(row('inventory', 'AAH')).toBe('0.64 m³/ha/yr');
    expect(row('inventory', 'Regeneration')).toBe('3,750 /ha');
  });

  it('a unit with no data for a source shows no section for it (no blanks)', () => {
    expect(unitFacts({ name: 'x', area_hectares: 2 }, 'en', t).map((x) => x.id)).toEqual(['unit']);
    expect(unitFacts({}, 'en', t)).toEqual([]);
    expect(unitFacts({ name: 'x', fi_stock: 5 }, 'en', t).map((x) => x.id)).toEqual(['inventory']);
  });

  it('a block with no type says why, and the landslide class follows the language', () => {
    const s = unitFacts({ ...sfmPropsFor(info({ type_no: null, state: 'non_forest', orientation: null, gs_ge40_m3_per_ha: null })) }, 'en', t);
    expect(s[0].rows[0].value).toBe('sfm.state.nonForest');
    const ne = unitFacts({ hz_lsi_class_en: 'High', hz_lsi_class_ne: 'उच्च' }, 'ne', t);
    expect(ne[0].rows[0].value).toBe('उच्च');
  });
});

describe('compare two maps on the hover card', () => {
  it('a hazard / SFM map gives the very same fact as when it is active', () => {
    const f = compareFact('hazard_fs', { hz_fs_unsafe_pct: 3.2 }, opts)!;
    expect(f.value).toBe('3% unsafe (unstable + marginal)');
  });
  it('a field-inventory map reads its raw number with its unit; no number means no second block', () => {
    expect(compareFact('fi_carbon', { fi_carbon: 62.31 }, opts)).toMatchObject({ value: '62.3 tC/ha', swatch: null });
    expect(compareFact('fi_condition', { fi_condition: 'Weak' }, opts)!.value).toBe('Weak');
    expect(compareFact('fi_carbon', {}, opts)).toBeNull();
    expect(compareFact(null, {}, opts)).toBeNull();
  });
  it('the second fact sits under the first, escaped, with its own map name', () => {
    const first = { map: 'Soil loss', swatch: null, heading: null, value: '48 t/ha/yr', lines: [] };
    const html = hoverFactHtml('blocks-3', first, { map: 'Carbon <b>', swatch: null, heading: null, value: '62.3 tC/ha', lines: [] });
    expect(html.indexOf('Soil loss')).toBeLessThan(html.indexOf('Carbon'));
    expect(html).toContain('Carbon &lt;b&gt;');
    expect(html).toContain('62.3 tC/ha');
    expect(hoverFactHtml('blocks-3', first)).not.toContain('border-top'); // no compare: no rule
  });
  it('every comparable map is one a card can say something about', () => {
    expect(COMPARABLE_MAPS).toContain('sfm_stock');
    expect(COMPARABLE_MAPS).toContain('hazard_soil');
    expect(COMPARABLE_MAPS).toContain('fi_growing_stock');
    expect(COMPARABLE_MAPS).not.toContain('hazard_hh'); // dots: no per-unit fact
    expect(new Set(COMPARABLE_MAPS).size).toBe(COMPARABLE_MAPS.length);
  });
});

describe('class area on the SFM legend', () => {
  it('each class carries the hectares of its units; classes cover the units exactly once', () => {
    const spec = defaultAnalysisRenderer('sfm_type')!;
    const rows = rendererLegendRows(spec);
    const entries = dynamicLegend(spec, rows, { A: info({ type_no: 7, area_ha: 10 }), B: info({ type_no: 7, area_ha: 5.5 }), C: info({ type_no: 3, area_ha: 2 }) });
    const by = Object.fromEntries(entries.map((e) => [e.label, e]));
    expect(by['Type-7']).toMatchObject({ count: 2, areaHa: 15.5 });
    expect(by['Type-3']).toMatchObject({ count: 1, areaHa: 2 });
    expect(entries.reduce((a, e) => a + e.areaHa, 0)).toBe(17.5);
  });
  it('a unit with no known area adds nothing (never NaN)', () => {
    const spec = defaultAnalysisRenderer('sfm_stock')!;
    const e = dynamicLegend(spec, rendererLegendRows(spec), { A: info({ area_ha: null, gs_ge40_m3_per_ha: 100 }) });
    expect(e[0].areaHa).toBe(0);
  });
});

describe('find, select and zoom to units by name', () => {
  const fake = (name: string, layerId: string | null, bounds?: { valid: boolean }) => {
    const l: Record<string, unknown> = {
      feature: { properties: { name } }, on: vi.fn(),
      getBounds: () => ({ isValid: () => bounds?.valid ?? true, extend(o: unknown) { return o; } }),
    };
    if (layerId) l.__unitLayerId = layerId;
    return l as never;
  };
  beforeEach(() => getFeatureLayerRegistry().clear());

  it('finds units by name across levels, ignoring layers that are not unit layers', () => {
    const reg = getFeatureLayerRegistry();
    reg.register('1', fake('blocks-1', 'blocks'));
    reg.register('2', fake('blocks-1-SC1', 'sub_blocks'));
    reg.register('3', fake('blocks-1', null)); // e.g. an imported layer that happens to share a name
    expect(findUnits(['blocks-1', 'blocks-1-SC1']).map((u) => u.id).sort()).toEqual(['1', '2']);
    expect(findUnits(['nope'])).toEqual([]);
  });

  it('selection goes to the layer most of the units are on, with only that layer’s ids', () => {
    const reg = getFeatureLayerRegistry();
    reg.register('1', fake('A', 'blocks'));
    reg.register('2', fake('B', 'blocks'));
    reg.register('3', fake('C', 'sub_blocks'));
    expect(selectionFor(['A', 'B', 'C'])).toEqual({ layerId: 'blocks', ids: ['1', '2'] });
    expect(selectionFor(['C'])).toEqual({ layerId: 'sub_blocks', ids: ['3'] });
    expect(selectionFor(['zzz'])).toBeNull();
  });

  it('zoom fits the found units and does nothing without a map or without any', () => {
    getFeatureLayerRegistry().register('1', fake('A', 'blocks'));
    const map = { fitBounds: vi.fn() };
    expect(zoomToUnits(map as never, ['A'])).toBe(1);
    expect(map.fitBounds).toHaveBeenCalledTimes(1);
    expect(zoomToUnits(map as never, ['zzz'])).toBe(0);
    expect(zoomToUnits(null, ['A'])).toBe(0);
    expect(map.fitBounds).toHaveBeenCalledTimes(1);
  });

  it('the units of an isolated class: by the server colour (field inventory) or the renderer colour (SFM)', () => {
    const unitMap = { state: 'ready', token: 't', custom_colours: false, legend: [], units: { A: { color: '#AA0000', value: 1, text: '' }, B: { color: '#00aa00', value: 2, text: '' } } } as never;
    expect(unitsOfClass('fi_growing_stock', '#aa0000', { unitMap, sfmBlockTypes: {}, saved: {} })).toEqual(['A']);
    const sfm = { A: info({ type_no: 7 }), B: info({ type_no: 7 }), C: info({ type_no: 3 }) };
    const spec = defaultAnalysisRenderer('sfm_type')!;
    const seven = rendererLegendRows(spec).find((r) => r.label === 'Type-7')!.color;
    expect(unitsOfClass('sfm_type', seven, { unitMap: null, sfmBlockTypes: sfm, saved: {} }).sort()).toEqual(['A', 'B']);
    expect(unitsOfClass('hazard_soil', '#aa0000', { unitMap, sfmBlockTypes: sfm, saved: {} })).toEqual([]); // tiles: no per-unit class
    expect(unitsOfClass('sfm_type', null, { unitMap: null, sfmBlockTypes: sfm, saved: {} })).toEqual([]);
  });
});
