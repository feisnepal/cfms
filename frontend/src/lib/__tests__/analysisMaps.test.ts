import { describe, it, expect } from 'vitest';
import { mergeSfmProps, SFM_NO_TYPE } from '../sfmFeatureProps';
import {
  FI_MAPS, fiSpecKey, isFiMap, analysisLabelLine as _label, placeholderToken, CHART_MAPS, isChartMap, withIndexColour, FACTOR_MAPS, analysisMapDef, dotsKind, hazardLayerKey, isDotsMap, isFactorMap, isHazardMap,
  ANALYSIS_MAPS, analysisRendererKey, defaultAnalysisRenderer, hasCustomColours, resolveAnalysisRenderer,
} from '../analysisMaps';
import { rendererColorFor, type RendererSpec } from '../layerRenderers';
import { CATEGORICAL } from '../semanticPalettes';
import type { SfmBlockTypeInfo } from '../../services/api';

const info = (o: Partial<SfmBlockTypeInfo> = {}): SfmBlockTypeInfo => ({
  type_no: 7, state: 'classified', land_class: 'forest', plot_count: 8, proposed_type_no: 7, overridden: false,
  orientation: 'Production', gs_ge40_m3_per_ha: 210, slope_band: '19–31°', confidence: 0.9, needs_review: false,
  reasons_ne: null, reasons_en: null, ...o,
});
const feat = (name: string): GeoJSON.Feature => ({
  type: 'Feature', geometry: { type: 'Point', coordinates: [0, 0] }, properties: { name },
});

describe('mergeSfmProps', () => {
  it('puts the classification on the matching unit and leaves others untouched', () => {
    const out = mergeSfmProps([feat('Block-1'), feat('Block-2')], { 'Block-1': info() })!;
    expect(out[0].properties).toMatchObject({ sfm_type: '7', sfm_orientation: 'Production', sfm_gs: 210, sfm_slope_band: '19–31°' });
    expect(out[1].properties).not.toHaveProperty('sfm_type');
  });
  it('a unit with no type carries the neutral class, never "0"', () => {
    const out = mergeSfmProps([feat('B')], { B: info({ type_no: null, orientation: null, gs_ge40_m3_per_ha: null, state: 'inventory_missing' }) })!;
    expect(out[0].properties).toMatchObject({ sfm_type: SFM_NO_TYPE, sfm_orientation: SFM_NO_TYPE, sfm_gs: null });
  });
  it('returns the same array when there is nothing to merge', () => {
    const list = [feat('A')];
    expect(mergeSfmProps(list, {})).toBe(list);
    expect(mergeSfmProps(null, { A: info() })).toBeNull();
  });
});

describe('analysis map renderers', () => {
  it('forest type uses exactly the shared SFM palette (one source of truth)', () => {
    const spec = defaultAnalysisRenderer('sfm_type')!;
    for (const [n, colour] of Object.entries(CATEGORICAL.sfm_forest_type)) {
      expect(rendererColorFor(spec, n)).toBe(colour);
    }
  });
  it('orientation uses the shared palette; no-type and unknown read neutral grey', () => {
    const spec = defaultAnalysisRenderer('sfm_orientation')!;
    expect(rendererColorFor(spec, 'Protection')).toBe(CATEGORICAL.sfm_orientation.Protection);
    expect(rendererColorFor(spec, SFM_NO_TYPE)).toBe('#bdbdbd');
    expect(rendererColorFor(spec, undefined)).toBe('#bdbdbd');
  });
  it('stock is graduated at the 150 / 200 step edges', () => {
    const spec = defaultAnalysisRenderer('sfm_stock')!;
    expect(spec.mode).toBe('graduated');
    const c = (v: number) => rendererColorFor(spec, v);
    expect(c(100)).not.toBe(c(175));
    expect(c(175)).not.toBe(c(250));
    expect(c(150)).toBe(c(100)); // an edge belongs to the lower class (value <= break)
    expect(rendererColorFor(spec, null)).toBeNull(); // no stock: the caller paints neutral grey
  });
  it('a saved colour wins; deleting it restores the default', () => {
    const custom: RendererSpec = { mode: 'categorized', field: 'sfm_type', classes: [{ value: '7', color: '#123456' }] };
    const saved = { [analysisRendererKey('sfm_type')]: custom };
    expect(resolveAnalysisRenderer('sfm_type', saved)).toBe(custom);
    expect(hasCustomColours('sfm_type', saved)).toBe(true);
    expect(hasCustomColours('sfm_type', {})).toBe(false);
    expect(resolveAnalysisRenderer('sfm_type', {})).toEqual(defaultAnalysisRenderer('sfm_type'));
    expect(resolveAnalysisRenderer(null, saved)).toBeNull();
  });
  it('declares the three SFM maps and the hazard maps (tiles and dots)', () => {
    expect(ANALYSIS_MAPS.map((m) => m.id)).toEqual(['sfm_type', 'sfm_orientation', 'sfm_stock', 'hazard_soil', 'hazard_lsi', 'hazard_fs', 'hazard_prone', 'hazard_hh', 'hazard_settle']);
  });
});

describe('factor layers and dots', () => {
  it('the original tab factor layers are all offered, and each maps to a backend layer key', () => {
    expect(FACTOR_MAPS).toHaveLength(14);
    expect(FACTOR_MAPS.filter((f) => f.key.startsWith('f_soil_'))).toHaveLength(4);
    expect(FACTOR_MAPS.filter((f) => f.key.startsWith('f_lsi_'))).toHaveLength(10);
    for (const f of FACTOR_MAPS) {
      expect(isFactorMap(f.id)).toBe(true);
      expect(isHazardMap(f.id)).toBe(true);
      expect(hazardLayerKey(f.id)).toBe(f.key);
      expect(analysisMapDef(f.id)?.fallbackLabel).toBe(f.fallbackLabel);
      expect(defaultAnalysisRenderer(f.id)).toBeNull();
    }
  });
  it('household and settlement dots are hazard maps drawn as points, not tiles', () => {
    expect(isDotsMap('hazard_hh') && isDotsMap('hazard_settle')).toBe(true);
    expect(isDotsMap('hazard_soil')).toBe(false);
    expect(dotsKind('hazard_hh')).toBe('households');
    expect(dotsKind('hazard_settle')).toBe('settlements');
    expect(isHazardMap('hazard_hh')).toBe(true);
  });
});

describe('withIndexColour (hazard colours)', () => {
  it('keeps only changed classes, by index, and builds on what is already saved', () => {
    const a = withIndexColour(undefined, 4, '#00ff00');
    expect(a).toEqual({ mode: 'indexed', colors: { '4': '#00ff00' } });
    expect(withIndexColour(a, 0, '#112233')).toEqual({ mode: 'indexed', colors: { '4': '#00ff00', '0': '#112233' } });
    expect(withIndexColour(a, 4, '#ffffff').colors).toEqual({ '4': '#ffffff' });
    // a saved entry of another shape (e.g. an SFM renderer) is not mixed in
    expect(withIndexColour({ mode: 'categorized', classes: [] }, 1, '#000000')).toEqual({ mode: 'indexed', colors: { '1': '#000000' } });
  });
});

describe('placeholders', () => {
  it('every workspace map has a placeholder token (a thememap: key)', () => {
    for (const m of [...ANALYSIS_MAPS, ...CHART_MAPS, ...FACTOR_MAPS]) {
      expect(placeholderToken(m.id), m.id).toMatch(/^thememap:[a-z]+__[a-z0-9_]+$/);
    }
  });
  it('known bindings', () => {
    expect(placeholderToken('sfm_type')).toBe('thememap:sfm__forest_type');
    expect(placeholderToken('hazard_soil')).toBe('thememap:soil__annual_loss');
    expect(placeholderToken('hazard_f_soil_ls')).toBe('thememap:soil__factor_ls');
    expect(placeholderToken('hazard_f_lsi_dist_road')).toBe('thememap:hazard__lsi_factor_dist_road');
    expect(placeholderToken('hazard_hh')).toBe('thememap:hh__vulnerability');
    expect(placeholderToken('chart_timber')).toBe('thememap:unit__dbh_class_stock__stackbar');
    expect(placeholderToken(null)).toBeNull();
    expect(placeholderToken('hazard_unknown' as never)).toBeNull();
  });
  it('the chart is an overlay, not one of the exclusive colourings', () => {
    expect(isChartMap('chart_timber')).toBe(true);
    expect(ANALYSIS_MAPS.some((m) => m.group === 'chart')).toBe(false);
    expect(defaultAnalysisRenderer('chart_timber')).toBeNull();
  });
});

describe('field-inventory (single-number) maps', () => {
  it('the 21 maps are offered, each bound to a unit-level print map variable', () => {
    expect(FI_MAPS).toHaveLength(21);
    for (const m of FI_MAPS) {
      expect(isFiMap(m.id)).toBe(true);
      expect(fiSpecKey(m.id)).toBe(m.specKey);
      expect(placeholderToken(m.id)).toBe(`thememap:${m.specKey}`);
      expect(m.specKey.startsWith('unit__')).toBe(true);
      expect(analysisMapDef(m.id)?.fallbackLabel).toBe(m.fallbackLabel);
      expect(defaultAnalysisRenderer(m.id)).toBeNull(); // the server paints it
    }
  });
  it('they are colourings of the units, so they are never an exclusive radio row or an overlay chart', () => {
    expect(ANALYSIS_MAPS.some((m) => m.group === 'fi')).toBe(false);
    expect(isFiMap('chart_timber')).toBe(false);
    expect(isFiMap('sfm_type')).toBe(false);
  });
  it('the compact label is the server-formatted value with its unit', () => {
    const t = (k: string) => k;
    expect(_label('fi_growing_stock', { um_text: '80 m³/ha' }, 'en', t)).toBe('80 m³/ha');
    expect(_label('fi_growing_stock', {}, 'en', t)).toBeNull();
  });
});

describe('slope band names', () => {
  it('the stored 1-4 codes are shown as the bands the print map names; a name passes through; junk is no band', async () => {
    const { slopeBandLabel, mergeSfmProps } = await import('../sfmFeatureProps');
    expect([1, 2, 3, 4].map(slopeBandLabel)).toEqual(['<19°', '19–31°', '31–45°', '>45°']);
    expect(slopeBandLabel('19–31°')).toBe('19–31°');
    expect([null, undefined, '', 9].map(slopeBandLabel)).toEqual([null, null, null, null]);
    const f = { type: 'Feature', geometry: null, properties: { name: 'B' } } as never;
    const out = mergeSfmProps([f], { B: { type_no: 7, state: 'classified', land_class: 'forest', plot_count: 5, slope_band: 2 } as never })!;
    expect(out[0].properties).toMatchObject({ sfm_slope_band: '19–31°' });
  });
});

