import { describe, expect, it } from 'vitest';
import { ANALYSIS_FIELDS, ANALYSIS_GROUPS, analysisGroupOf } from '../analysisFields';
import { ANALYSIS_COLUMNS } from '../layerRegistry';
import { availableAnalysisGroups, columnsForTheme } from '../attributeThemes';

// The keys "Run analysis" stored for a unit when this table was written (with the Nepali ones the analysis also returns).
const STORED_WHEN_WRITTEN = [
  'access_info', 'agb_max_mg_ha', 'agb_mean_mg_ha', 'agb_total_mg', 'aspect_dominant', 'aspect_percentages', 'canopy_dominant_class',
  'canopy_max_m', 'canopy_mean_m', 'canopy_min_m', 'canopy_percentages', 'carbon_stock_mg', 'carbon_stock_t_ha', 'compaction_alert',
  'compaction_status', 'district', 'division_n', 'ecoregion_percentages', 'elevation_max_m', 'elevation_mean_m', 'elevation_min_m',
  'fertility_class', 'fertility_score', 'fire_loss_hectares', 'forest_gain_hectares', 'forest_health_dominant',
  'forest_health_percentages', 'forest_loss_by_year', 'forest_loss_hectares', 'forest_type_dominant', 'forest_type_percentages',
  'geology_percentages', 'hansen2000_dominant', 'hansen2000_percentages', 'juridiction_ne', 'landcover_1984_dominant',
  'landcover_1984_percentages', 'landcover_dominant', 'landcover_percentages', 'limiting_factors', 'major_river_basin',
  'min_temp_coldest_max_c', 'min_temp_coldest_mean_c', 'min_temp_coldest_min_c', 'municipality', 'municipality_n', 'municipality_type',
  'municipality_type_nep', 'nasa_forest_2020_dominant', 'nasa_forest_2020_percentages', 'physiography_ne', 'physiography_percentages',
  'precipitation_max_mm', 'precipitation_mean_mm', 'precipitation_min_mm', 'province', 'province_ne', 'slope_dominant_class',
  'slope_max_code', 'slope_min_code', 'slope_percentages', 'soil_texture', 'soil_texture_system', 'species_count', 'subdivis_n',
  'temperature_max_c', 'temperature_mean_c', 'temperature_min_c', 'ward', 'ward_ne', 'watershed',
];

describe('analysis fields and their groups', () => {
  it('lists every stored value exactly once, each in one group', () => {
    const keys = ANALYSIS_FIELDS.map((x) => x.key);
    expect(new Set(keys).size).toBe(keys.length);
    expect([...keys].sort()).toEqual([...STORED_WHEN_WRITTEN].sort());
    for (const fld of ANALYSIS_FIELDS) expect(ANALYSIS_GROUPS).toContain(fld.group);
  });

  it('has the agreed seven groups with their columns', () => {
    const count = (g: string) => ANALYSIS_FIELDS.filter((x) => x.group === g).length;
    expect(ANALYSIS_GROUPS).toEqual(['location', 'geography', 'terrain', 'vegetation', 'environment', 'change', 'breakdowns']);
    expect(Object.fromEntries(ANALYSIS_GROUPS.map((g) => [g, count(g)]))).toEqual({
      location: 11, geography: 5, terrain: 7, vegetation: 8, environment: 22, change: 6, breakdowns: 12,
    });
  });

  it('puts the merged subjects where the owner asked', () => {
    for (const k of ['physiography_ne', 'division_n', 'subdivis_n', 'access_info', 'watershed']) expect(analysisGroupOf(`an_${k}`)).toBe('geography');
    for (const k of ['temperature_mean_c', 'precipitation_mean_mm', 'soil_texture', 'fertility_class', 'landcover_dominant', 'forest_type_dominant', 'species_count']) {
      expect(analysisGroupOf(`an_${k}`)).toBe('environment');
    }
    expect(analysisGroupOf('an_major_river_basin')).toBe('location');
    expect(analysisGroupOf('an_landcover_percentages')).toBe('breakdowns'); // the dominant class is in Environment, its breakdown here
  });

  it('every long "% area" breakdown is under Class breakdowns, none elsewhere', () => {
    for (const fld of ANALYSIS_FIELDS) expect(fld.group === 'breakdowns').toBe(fld.key.endsWith('_percentages'));
  });

  it('headers carry no "Analysis:" prefix and the columns follow the table', () => {
    expect(ANALYSIS_COLUMNS).toHaveLength(ANALYSIS_FIELDS.length);
    expect(ANALYSIS_COLUMNS.some((c) => String(c.label).startsWith('Analysis:'))).toBe(false);
    expect(ANALYSIS_COLUMNS.find((c) => c.key === 'an_elevation_mean_m')?.label).toBe('Elevation, mean (m)');
  });

  it('under Raster analysis, a group narrows the analysis columns and keeps the name column', () => {
    const cols = [{ key: '#' }, { key: 'name' }, { key: 'area' }, { key: 'fi_stock' }, ...ANALYSIS_COLUMNS];
    const all = columnsForTheme(cols, 'raster', 'all').map((c) => c.key);
    expect(all).toContain('an_province');
    expect(all).not.toContain('fi_stock');
    const terrain = columnsForTheme(cols, 'raster', 'terrain').map((c) => c.key);
    expect(terrain).toEqual(['#', 'name', 'an_elevation_min_m', 'an_elevation_mean_m', 'an_elevation_max_m', 'an_slope_dominant_class', 'an_slope_min_code', 'an_slope_max_code', 'an_aspect_dominant']);
    // the group only matters under Raster analysis
    expect(columnsForTheme(cols, 'inventory', 'terrain').map((c) => c.key)).toEqual(['#', 'name', 'fi_stock']);
    expect(availableAnalysisGroups(cols)).toEqual(ANALYSIS_GROUPS);
    expect(availableAnalysisGroups([{ key: 'name' }, { key: 'an_ward' }])).toEqual(['location']);
  });
});
