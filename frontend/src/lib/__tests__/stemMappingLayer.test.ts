import { describe, it, expect, vi, beforeEach } from 'vitest';

const getTreesForMap = vi.fn();
vi.mock('../../services/api', () => ({
  samplingApi: { list: vi.fn(), getMapLayers: vi.fn() },
  // Wrapped, not passed directly: vi.mock factories are hoisted above this
  // file's own `const`, so a direct reference would hit the TDZ — the lambda
  // defers the actual lookup until the mock is called (matches ReanalyzeModal.test.tsx).
  compartmentApi: { getTreesForMap: (...a: unknown[]) => getTreesForMap(...a) },
}));

import type { Feature } from 'geojson';
import { getLayerConfig, isBuiltinLayerId, getLabelFieldsForLayer } from '../layerRegistry';

describe('built-in Stem Mapping layer', () => {
  beforeEach(() => {
    getTreesForMap.mockReset();
  });

  it('registers stem_mapping as a built-in read-only Point layer', async () => {
    expect(isBuiltinLayerId('stem_mapping')).toBe(true);
    const cfg = getLayerConfig('stem_mapping')!;
    expect(cfg.alwaysReadOnly).toBe(true);
    expect(cfg.editable).toBe(false);
    expect(cfg.geometryTypes).toEqual(['Point']);
    await expect(cfg.dataSource.create('calc-1', {} as Feature)).rejects.toThrow('Read-only layer');
    await expect(cfg.dataSource.update('calc-1', 't1', {})).rejects.toThrow('Read-only layer');
    await expect(cfg.dataSource.delete('calc-1', 't1')).rejects.toThrow('Read-only layer');
  });

  it('exposes a non-empty label field list', () => {
    const fields = getLabelFieldsForLayer('stem_mapping');
    expect(fields.length).toBeGreaterThan(0);
    expect(fields).toContain('species');
  });

  it('maps compartmentApi.getTreesForMap trees into Point features', async () => {
    getTreesForMap.mockResolvedValue({
      count: 2,
      trees: [
        {
          id: 't1', latitude: 27.5, longitude: 83.5, species: 'Sal', dbh_cm: 34.2,
          height_m: 18.5, volume_m3: 0.42, dbh_class: 'Lg. Tree (30-40)',
          block_id: 'b1', block_name: 'Block 1', remark: 'Mother', grid_cell_id: 3, source: 'inventory',
        },
        {
          id: 't2', latitude: 27.51, longitude: 83.51, species: 'Chilaune', dbh_cm: 12.1,
          height_m: 9.0, volume_m3: 0.05, dbh_class: 'Sm. Pole (10-20)',
          block_id: 'b1', block_name: 'Block 1', remark: null, grid_cell_id: 3, source: 'inventory',
        },
      ],
      grid_spacing_meters: 20,
      inventory_id: 'inv-1',
    });

    const cfg = getLayerConfig('stem_mapping')!;
    const features = await cfg.dataSource.fetch('calc-1');

    expect(getTreesForMap).toHaveBeenCalledWith('calc-1');
    expect(features).toHaveLength(2);
    expect(features[0].geometry).toEqual({ type: 'Point', coordinates: [83.5, 27.5] });
    expect(features[0].properties!.species).toBe('Sal');
    expect(features[0].properties!.dbh_cm).toBe(34.2);
    expect(features[0].properties!.block_name).toBe('Block 1');
    expect(features[0].properties!.geo_centroid_lat).toBeDefined();
  });

  it('returns an empty feature list when there are no trees (no throw)', async () => {
    getTreesForMap.mockResolvedValue({
      count: 0, trees: [], grid_spacing_meters: null, inventory_id: null,
    });
    const cfg = getLayerConfig('stem_mapping')!;
    const features = await cfg.dataSource.fetch('calc-1');
    expect(features).toEqual([]);
  });
});
