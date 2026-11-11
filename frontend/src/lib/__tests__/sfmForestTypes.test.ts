import { describe, it, expect, beforeEach } from 'vitest';
import {
  formatYieldStep, harvestLines, primaryBranchKey, slopeKey, orientationColor, loadForestTypes, resetForestTypesCache,
} from '../sfmForestTypes';
import type { SfmPrescription } from '../../services/api';

// echo the key and options so the wording rules can be asserted without the i18n bundle
const t = (key: string, opts?: Record<string, unknown>) => (opts ? `${key}${JSON.stringify(opts)}` : key);

const type7 = {
  type_no: 7, slope_band: null,
  branches: {
    adequate: {
      yield_rules: { basis: 'growing_stock_pct_ge40', steps: [
        { pct: 1, gs_per_ha_min: 200, gs_per_ha_max: null },
        { pct: 0.5, gs_per_ha_min: 150, gs_per_ha_max: 200 },
        { pct: 0.5, gs_per_ha_min: null, gs_per_ha_max: 150 },
      ], target_stems_per_ha: null, note_ne: 'ने', note_en: 'en' },
    },
    inadequate: { yield_rules: { basis: 'area_volume', steps: [], target_stems_per_ha: null, note_ne: 'क्षेत्रफल', note_en: 'By area' } },
  },
} as unknown as SfmPrescription;

describe('sfmForestTypes', () => {
  it('words a yield step by which bounds it has', () => {
    expect(formatYieldStep({ pct: 1, gs_per_ha_min: 200, gs_per_ha_max: null }, t)).toContain('sfm.ref.stepGe{"min":200}');
    expect(formatYieldStep({ pct: 0.5, gs_per_ha_min: 150, gs_per_ha_max: 200 }, t)).toContain('sfm.ref.stepRange{"min":150,"max":200}');
    expect(formatYieldStep({ pct: 0.5, gs_per_ha_min: null, gs_per_ha_max: 150 }, t)).toContain('sfm.ref.stepLt{"max":150}');
    expect(formatYieldStep({ pct: 2, gs_per_ha_min: null, gs_per_ha_max: null }, t)).toContain('sfm.ref.stepAny');
  });

  it('leads a tooltip with the adequate-regeneration branch, and with the only branch otherwise', () => {
    expect(primaryBranchKey(type7)).toBe('adequate');
    expect(primaryBranchKey({ branches: { default: {} } } as unknown as SfmPrescription)).toBe('default');
    expect(primaryBranchKey({ branches: {} } as unknown as SfmPrescription)).toBeNull();
  });

  it('lists the harvest steps, and falls back to the rule note (both languages) when a branch has none', () => {
    expect(harvestLines(type7.branches.adequate, t)).toHaveLength(3);
    expect(harvestLines(type7.branches.inadequate, t)).toEqual(['क्षेत्रफल', 'By area']);
  });

  it('maps slope and orientation to a stable key / colour', () => {
    expect(slopeKey({ slope_band: 2 } as SfmPrescription)).toBe('sfm.ref.slopeBand.2');
    expect(slopeKey({ slope_band: null } as SfmPrescription)).toBe('sfm.ref.slopeBand.any');
    expect(orientationColor('Production')).not.toBe(orientationColor('Protection'));
    expect(orientationColor('nonsense')).toBe('#8c8c8c');
  });

  describe('the shared fetch', () => {
    beforeEach(() => resetForestTypesCache());
    it('fetches once however many tags ask', async () => {
      let calls = 0;
      const f = async () => { calls += 1; return [type7]; };
      const [a, b] = await Promise.all([loadForestTypes(f), loadForestTypes(f)]);
      expect(calls).toBe(1);
      expect(a[7]).toBe(b[7]);
    });
    it('forgets a failure, so the next tag retries', async () => {
      await expect(loadForestTypes(async () => { throw new Error('x'); })).rejects.toThrow();
      await expect(loadForestTypes(async () => [type7])).resolves.toHaveProperty('7');
    });
  });
});

import { typeCardHtml, escapeHtml } from '../sfmForestTypes';

describe('typeCardHtml (the workspace map hover card)', () => {
  const p = { ...type7, name_ne: 'पहाडी साल वन', name_en: 'Hill Sal forest', orientation: 'Conservation',
    zone_triggers: ['HILL'], species_groups: ['SAL'], notes_ne: 'ने', notes_en: 'en' } as unknown as SfmPrescription;
  const tt = (key: string, opts?: Record<string, unknown>) => (opts && typeof opts === 'object' ? `${key}${JSON.stringify(opts)}` : key);

  it('names the block and the type in both languages and lists the harvest steps', () => {
    const html = typeCardHtml(p, { type_no: 7 }, 'Block-1', tt);
    expect(html).toContain('Block-1');
    expect(html).toContain('पहाडी साल वन');
    expect(html).toContain('Hill Sal forest');
    expect(html).toContain('sfm.ref.stepGe');
  });

  it('says so when the user changed the type, naming what the system had proposed', () => {
    const html = typeCardHtml(p, { type_no: 11, overridden: true, proposed_type_no: 7 }, 'Block-1', tt);
    expect(html).toContain('sfm.ref.overridden{&quot;n&quot;:7}'); // escaped, like everything dynamic
    expect(typeCardHtml(p, { type_no: 7, overridden: false }, 'Block-1', tt)).not.toContain('sfm.ref.overridden');
  });

  it('escapes anything dynamic, so a block name cannot inject markup into the map', () => {
    const html = typeCardHtml(p, { type_no: 7, reasons: ['<img src=x onerror=alert(1)>'] }, '<b>x</b>', tt);
    expect(html).not.toContain('<img');
    expect(html).not.toContain('<b>x</b>');
    expect(escapeHtml('<a href="x">&')).toBe('&lt;a href=&quot;x&quot;&gt;&amp;');
  });
});
