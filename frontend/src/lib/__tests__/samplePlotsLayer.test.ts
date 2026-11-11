import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../../services/api', () => ({
  samplingApi: {
    list: vi.fn(),
    getMapLayers: vi.fn(),
    deleteSamplePlot: vi.fn(),
  },
}));

import { getLayerConfig, isBuiltinLayerId, getLabelFieldsForLayer } from '../layerRegistry';
import { samplingApi } from '../../services/api';

describe('Phase G — built-in Sample Plots layer (rule G)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('registers sample_plots as a built-in read-only Point layer', () => {
    expect(isBuiltinLayerId('sample_plots')).toBe(true);
    const cfg = getLayerConfig('sample_plots')!;
    expect(cfg.alwaysReadOnly).toBe(true);
    expect(cfg.editable).toBe(false);
    expect(cfg.geometryTypes).toEqual(['Point']);
    // the dataSource cannot create or update a plot as a feature (plots are made by a sampling design, and a coordinate is changed through
    // the Sample Plots table's own save); deleting one plot is allowed (owner report 2026-10-02) and goes to the sampling API
    await_throws(cfg.dataSource.create);
    await_throws(cfg.dataSource.update);
  });

  it('deleting one plot goes to the sampling API, by design id and plot number', async () => {
    const cfg = getLayerConfig('sample_plots')!;
    await cfg.dataSource.delete!('calc-1', '7' as never);
    expect(samplingApi.deleteSamplePlot).toHaveBeenCalledTimes(1);
  });

  it('shows the position of a plot once, as editable WGS84 latitude / longitude and UTM easting / northing - no repeated centroid or bounding-box columns', () => {
    const cols = getLayerConfig('sample_plots')!.columns;
    const keys = cols.map((c) => c.key);
    expect(keys).toEqual(expect.arrayContaining(['latitude', 'longitude', 'utm_easting', 'utm_northing', 'utm_zone']));
    expect(keys.some((k) => k.startsWith('geo_bbox') || k.startsWith('geo_centroid'))).toBe(false);
    expect(cols.filter((c) => c.editable).map((c) => c.key).sort()).toEqual(['latitude', 'longitude', 'utm_easting', 'utm_northing']);
    const zone = cols.find((c) => c.key === 'utm_zone')!;
    expect(zone.editable).toBeFalsy(); // the UTM zone is the plot's own: never typed
    const point = { type: 'Feature', geometry: { type: 'Point', coordinates: [83.5, 27.5] }, properties: {} } as GeoJSON.Feature;
    expect(cols.find((c) => c.key === 'latitude')!.getValue!(point, 0)).toBe('27.500000');
    expect(cols.find((c) => c.key === 'longitude')!.getValue!(point, 0)).toBe('83.500000');
  });

  it('exposes a non-empty label field list', () => {
    const fields = getLabelFieldsForLayer('sample_plots');
    expect(fields.length).toBeGreaterThan(0);
    expect(fields).toContain('plot_number');
  });

  it('resolves the design id then map-layers sampling_points (two-call fetch)', async () => {
    (samplingApi.list as any).mockResolvedValue([
      { id: 'design-abc', sampling_type: 'systematic', total_points: 2 },
    ]);
    (samplingApi.getMapLayers as any).mockResolvedValue({
      calculation_id: 'calc-1',
      sampling_points: {
        type: 'FeatureCollection',
        features: [
          { type: 'Feature', geometry: { type: 'Point', coordinates: [83.5, 27.5] }, properties: { plot_number: 1, plot_id: 'P1', block_name: 'Block 1', zone_type: 'productive' } },
          { type: 'Feature', geometry: { type: 'Point', coordinates: [83.51, 27.51] }, properties: { plot_number: 2, plot_id: 'P2', block_name: 'Block 1', zone_type: 'productive' } },
        ],
      },
    });

    const cfg = getLayerConfig('sample_plots')!;
    const features = await cfg.dataSource.fetch('calc-1');

    expect(samplingApi.list).toHaveBeenCalledWith('calc-1');
    expect(samplingApi.getMapLayers).toHaveBeenCalledWith('design-abc');
    expect(features).toHaveLength(2);
    expect(features[0].properties!.plot_number).toBe(1);
    expect(features[0].properties!.block_name).toBe('Block 1');
    expect(features[0].properties!.zone_type).toBe('productive');
    expect((features[0].geometry as any).type).toBe('Point');
    expect(features[0].properties!.geo_centroid_lat).toBeDefined();
  });

  it('returns an empty feature list when no design exists (no throws)', async () => {
    (samplingApi.list as any).mockResolvedValue([]);
    const cfg = getLayerConfig('sample_plots')!;
    const features = await cfg.dataSource.fetch('calc-1');
    expect(features).toEqual([]);
    expect(samplingApi.getMapLayers).not.toHaveBeenCalled();
  });
});

async function await_throws(fn: (...args: any[]) => Promise<any>) {
  await expect(fn('calc-1')).rejects.toThrow('Read-only layer');
}