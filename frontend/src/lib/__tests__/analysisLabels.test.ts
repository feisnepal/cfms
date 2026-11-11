import { describe, it, expect } from 'vitest';
import { analysisLabelLine } from '../analysisMaps';
import { mergeHazardProps, unitsByName, hazardPropsFor } from '../hazardFeatureProps';

// a translator that returns the key (with the n of the type), so the test pins the rule, not the wording
const t = (k: string, o?: Record<string, unknown>) => (k === 'sfm.ref.typeDash' ? `Type-${o?.n}` : (o?.defaultValue as string) ?? k);
const line = (id: Parameters<typeof analysisLabelLine>[0], p: Record<string, unknown>, lang = 'en') => analysisLabelLine(id, p, lang, t);

describe('analysisLabelLine — the main summary under a unit name', () => {
  it('forest type: type, slope band, and the plot count only when provisional', () => {
    expect(line('sfm_type', { sfm_type: '7', sfm_state: 'classified', sfm_slope_band: '19–31°' })).toBe('Type-7 · 19–31°');
    expect(line('sfm_type', { sfm_type: '7', sfm_state: 'provisional', sfm_slope_band: '19–31°', sfm_plot_count: 3 })).toBe('Type-7 · 19–31° · 3 plots');
  });
  it('a unit with no type says why, and an unclassified unit gets nothing', () => {
    expect(line('sfm_type', { sfm_type: 'none', sfm_state: 'non_forest' })).toBe('sfm.state.nonForest');
    expect(line('sfm_type', { sfm_type: 'none', sfm_state: 'inventory_missing' })).toBe('sfm.state.noPlots');
    expect(line('sfm_type', {})).toBeNull();
  });
  it('orientation and stock', () => {
    expect(line('sfm_orientation', { sfm_type: '7', sfm_orientation: 'Production' })).toBe('Production');
    expect(line('sfm_stock', { sfm_type: '7', sfm_gs: 209.6 })).toBe('210 m³/ha');
    expect(line('sfm_stock', { sfm_type: '7', sfm_gs: null })).toBe('—');
  });
  it('hazard maps: the same lines the print map uses', () => {
    expect(line('hazard_soil', { hz_soil_mean: 12.4 })).toBe('12 t/ha/yr');
    expect(line('hazard_fs', { hz_fs_unsafe_pct: 3.2 })).toBe('3% unsafe');
    expect(line('hazard_prone', { hz_prone_pct: 44.6 })).toBe('45% high');
    expect(line('hazard_lsi', { hz_lsi_class_en: 'High', hz_lsi_class_ne: 'उच्च' })).toBe('High');
    expect(line('hazard_lsi', { hz_lsi_class_en: 'High', hz_lsi_class_ne: 'उच्च' }, 'ne')).toBe('उच्च');
  });
  it('a hazard unit with no data, or no active map, gets no second line', () => {
    expect(line('hazard_soil', {})).toBeNull();
    expect(line(null, { sfm_type: '7' })).toBeNull();
  });
});

describe('hazard unit properties', () => {
  const res = {
    layers: {
      soil: { B1: { mean: 12.4, severe_pct: 30, area_ha: 5 } },
      lsi: { B1: { dominant: { index: 3, label_en: 'High', label_ne: 'उच्च' }, high_pct: 45 } },
      fs: { B1: { unstable_pct: 1, unsafe_pct: 3 } },
      prone: { B2: { high_pct: 10 } },
    },
    missing: [],
  };
  it('turns the response inside out, per unit', () => {
    const u = unitsByName(res as never);
    expect(Object.keys(u).sort()).toEqual(['B1', 'B2']);
    expect(hazardPropsFor(u.B1)).toMatchObject({ hz_soil_mean: 12.4, hz_lsi_class_en: 'High', hz_fs_unsafe_pct: 3 });
    expect(hazardPropsFor(u.B2)).toEqual({ hz_prone_pct: 10 });
  });
  it('merges onto matching features only, and is a no-op when empty', () => {
    const f = (name: string) => ({ type: 'Feature', geometry: null, properties: { name } }) as never;
    const list = [f('B1'), f('B3')];
    const out = mergeHazardProps(list, unitsByName(res as never))!;
    expect(out[0].properties).toHaveProperty('hz_soil_mean', 12.4);
    expect(out[1].properties).not.toHaveProperty('hz_soil_mean');
    expect(mergeHazardProps(list, {})).toBe(list);
  });
});
