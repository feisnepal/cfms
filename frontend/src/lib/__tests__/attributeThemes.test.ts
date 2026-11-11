import { describe, expect, it } from 'vitest';
import { availableThemes, columnsForTheme, themeOfColumn } from '../attributeThemes';

const cols = ['#', 'name', 'area', 'dominant_slope_band', 'management_orientation', 'an_elevation_mean_m', 'fi_stock', 'sfm_type', 'hz_soil_mean', '__actions'].map((key) => ({ key }));

describe('attribute themes', () => {
  it('groups columns by the component that fills them', () => {
    expect(themeOfColumn('an_ward')).toBe('raster');
    expect(themeOfColumn('fi_stock')).toBe('inventory');
    expect(themeOfColumn('sfm_gs')).toBe('sfm');
    expect(themeOfColumn('hz_prone_pct')).toBe('hazard');
    expect(themeOfColumn('dominant_aspect')).toBe('classification');
    expect(themeOfColumn('management_orientation')).toBe('classification');
    expect(themeOfColumn('area')).toBe('basic');
  });

  it('every view keeps the row number and the name; All keeps everything', () => {
    expect(columnsForTheme(cols, 'all')).toHaveLength(cols.length);
    expect(columnsForTheme(cols, 'raster').map((c) => c.key)).toEqual(['#', 'name', 'an_elevation_mean_m', '__actions']);
    expect(columnsForTheme(cols, 'basic').map((c) => c.key)).toEqual(['#', 'name', 'area', '__actions']);
  });

  it('offers only views that have columns here', () => {
    expect(availableThemes([{ key: 'name' }, { key: 'area' }])).toEqual(['all', 'basic']);
    expect(availableThemes(cols)).toEqual(['all', 'basic', 'raster', 'inventory', 'sfm', 'hazard', 'classification']);
  });
});
