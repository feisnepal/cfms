import { describe, it, expect } from 'vitest'
import {
  STATIC_LEGENDS,
  STATIC_FALLBACKS,
  resolveRasterLegend,
  buildRasterTileUrl,
  generateDynamicElevationLegend,
  generateDynamicSlopeLegend,
  generateDynamicLandcoverLegend,
  generateDynamicNasaForestLegend,
  generateDynamicForestTypeLegend,
  generateDynamicFireLossLegend,
  generateDynamicForestHealthLegend,
  generateDynamicAspectLegend,
  type LegendItem,
  type RasterLayerMeta,
} from '../rasterLegends'

describe('STATIC_LEGENDS', () => {
  it('defines legends for all categorical layers', () => {
    const ids = ['aspect', 'forest_health', 'nasa_forest_2020', 'landcover', 'forest_loss', 'forest_gain', 'fire', 'soil_ph', 'soil_texture', 'soil_carbon', 'soil_fertility', 'soil_density']
    for (const id of ids) {
      expect(STATIC_LEGENDS[id], id).toBeDefined()
      expect(STATIC_LEGENDS[id].length).toBeGreaterThan(0)
    }
  })

  it('defines fallbacks for all continuous layers', () => {
    const ids = ['dem', 'canopy', 'temperature', 'precipitation', 'biomass', 'slope', 'min_temp_coldest', 'forest_type']
    for (const id of ids) {
      expect(STATIC_FALLBACKS[id], id).toBeDefined()
      expect(STATIC_FALLBACKS[id].length).toBeGreaterThan(0)
    }
  })

  it('every legend item has a color and a label', () => {
    const all: LegendItem[] = [...Object.values(STATIC_LEGENDS), ...Object.values(STATIC_FALLBACKS)].flat()
    for (const item of all) {
      expect(item.color, item.label).toMatch(/^#[0-9A-Fa-f]{6}$/)
      expect(item.label.length).toBeGreaterThan(0)
    }
  })
})

describe('resolveRasterLegend', () => {
  it('returns the static legend for a categorical layer without result data', () => {
    expect(resolveRasterLegend('aspect')).toEqual(STATIC_LEGENDS.aspect)
    expect(resolveRasterLegend('soil_ph')).toEqual(STATIC_LEGENDS.soil_ph)
    expect(resolveRasterLegend('landcover')).toEqual(STATIC_LEGENDS.landcover)
  })

  it('returns a static fallback for a continuous layer without result data', () => {
    expect(resolveRasterLegend('dem')).toEqual(STATIC_FALLBACKS.dem)
    expect(resolveRasterLegend('slope')).toEqual(STATIC_FALLBACKS.slope)
  })

  it('uses the dynamic elevation legend when valid min/max elevation exists', () => {
    const legend = resolveRasterLegend('dem', { elevation_min_m: 200, elevation_max_m: 3000 })
    expect(legend.length).toBe(4)
    expect(legend[0].range).toMatch(/m$/)
  })

  it('falls back to static legend when elevation data is invalid', () => {
    expect(resolveRasterLegend('dem', { elevation_min_m: -32768, elevation_max_m: -32768 })).toEqual(STATIC_FALLBACKS.dem)
  })

  it('returns only slope classes present in the data', () => {
    const legend = resolveRasterLegend('slope', { slope_min_code: 2, slope_max_code: 3 })
    expect(legend.map(l => l.label)).toEqual(['Moderate', 'Steep'])
  })

  it('returns only landcover classes present, sorted by share desc', () => {
    const legend = resolveRasterLegend('landcover', {
      landcover_percentages: { 'Grassland': 19.6, 'Tree cover': 80.4 },
    })
    expect(legend).toEqual([
      { color: '#006400', label: 'Tree cover', range: '10 (80.4%)' },
      { color: '#FFFF4C', label: 'Grassland', range: '30 (19.6%)' },
    ])
  })

  it('uses whole-forest NASA percentages when present', () => {
    const legend = resolveRasterLegend('nasa_forest_2020', {
      whole_nasa_forest_2020_percentages: { 'Primary Forest': 100 },
    })
    expect(legend.length).toBe(1)
    expect(legend[0].label).toBe('Primary Forest')
    expect(legend[0].range).toContain('(100.0%)')
  })

  it('groups fire loss by time period', () => {
    const legend = resolveRasterLegend('fire', {
      fire_loss_by_year: { '2001': 5.5, '2019': 2.25 },
    })
    expect(legend.map(l => l.label)).toEqual(['2001-2008', '2017-2024'])
    expect(legend[0].range).toBe('5.50 ha')
    expect(legend[1].range).toBe('2.25 ha')
  })

  it('matches forest types with flexible naming and shortens labels', () => {
    const legend = resolveRasterLegend('forest_type', {
      forest_type_percentages: { 'Shorea robusta Forest': 60, 'Unmatched Legacy Type': 40 },
    })
    const shorea = legend.find(l => l.label === 'Shorea robusta')
    expect(shorea).toBeDefined()
    expect(shorea!.color).toBe('#006400')
    expect(shorea!.range).toBe('60.0%')
  })

  it('returns an empty array for an unknown layer id', () => {
    expect(resolveRasterLegend('does_not_exist')).toEqual([])
  })

  it('resolves user-group overlays to the host layer legend (BG-1)', () => {
    expect(resolveRasterLegend('ug_landcover')).toEqual(STATIC_LEGENDS.landcover)
    expect(resolveRasterLegend('ug_biomass')).toEqual(STATIC_FALLBACKS.biomass)
    expect(resolveRasterLegend('ug_landcover', { landcover_percentages: { 'Tree cover': 50, 'Grassland': 50 } })).toEqual([
      { color: '#006400', label: 'Tree cover', range: '10 (50.0%)' },
      { color: '#FFFF4C', label: 'Grassland', range: '30 (50.0%)' },
    ])
  })

  it('tolerates malformed result data', () => {
    expect(resolveRasterLegend('dem', { elevation_min_m: 'oops' } as any)).toEqual(STATIC_FALLBACKS.dem)
    expect(resolveRasterLegend('landcover', { landcover_percentages: 42 } as any)).toEqual(STATIC_LEGENDS.landcover)
    expect(resolveRasterLegend('canopy', null)).toEqual(STATIC_FALLBACKS.canopy)
  })
})

describe('buildRasterTileUrl', () => {
  const UG_OV: RasterLayerMeta = {
    id: 'ug_landcover', name: 'x', description: 'y',
    tilesPath: 'user-group-tiles', tileKey: 'landcover', extraParams: { exclude_forest: 'true' },
  }

  it('keeps the default /tiles route byte-identical to the historic URL', () => {
    expect(buildRasterTileUrl('calc-1', 'ndvi')).toBe('/api/calculations/calc-1/tiles/ndvi/{z}/{x}/{y}.png?alpha=255')
    expect(buildRasterTileUrl('calc-1', 'ndvi', null, 128)).toBe('/api/calculations/calc-1/tiles/ndvi/{z}/{x}/{y}.png?alpha=128')
  })

  it('uses the catalog tilesPath/tileKey/extraParams for user-group overlays', () => {
    expect(buildRasterTileUrl('calc-1', 'ug_landcover', UG_OV, 255)).toBe(
      '/api/calculations/calc-1/user-group-tiles/landcover/{z}/{x}/{y}.png?alpha=255&exclude_forest=true',
    )
    expect(buildRasterTileUrl('calc-1', 'ug_biomass', { ...UG_OV, id: 'ug_biomass', tileKey: 'biomass' }, 128)).toBe(
      '/api/calculations/calc-1/user-group-tiles/biomass/{z}/{x}/{y}.png?alpha=128&exclude_forest=true',
    )
  })
})

describe('dynamic generators', () => {
  it('elevation legend uses 4 equal classes', () => {
    const legend = generateDynamicElevationLegend(100, 500)
    expect(legend.length).toBe(4)
  })

  it('slope legend falls back to all classes when range is empty', () => {
    expect(generateDynamicSlopeLegend(1, 0)).toEqual(STATIC_FALLBACKS.slope)
  })

  it('forest health legend sorts Stressed → Excellent and strips ordering metadata', () => {
    const legend = generateDynamicForestHealthLegend({ 'Excellent': 10, 'Stressed': 90 })
    expect(legend.map(l => l.label)).toEqual(['Stressed', 'Excellent'])
    expect(Object.keys(legend[0])).not.toContain('order')
  })

  it('aspect legend preserves compass order', () => {
    const legend = generateDynamicAspectLegend({ 'S': 30, 'Flat': 10, 'N': 60 })
    expect(legend.map(l => l.label)).toEqual(['Flat', 'North (N)', 'South (S)'])
  })

  it('NASA legend sorts by percentage descending', () => {
    const legend = generateDynamicNasaForestLegend({ 'Young Secondary Forest': 20, 'Primary Forest': 80 })
    expect(legend[0].label).toBe('Primary Forest')
    expect(legend[1].label).toBe('Young Secondary Forest')
  })

  it('landcover legend returns empty when percentages empty', () => {
    expect(generateDynamicLandcoverLegend({})).toEqual([])
  })

  it('fire legend returns empty when no fire data', () => {
    expect(generateDynamicFireLossLegend({})).toEqual([])
  })

  it('forest type legend uses hash-based fallback for unmatched names', () => {
    const legend = generateDynamicForestTypeLegend({ 'Something Odd': 100 })
    expect(legend.length).toBe(1)
    expect(legend[0].color).toMatch(/^#[0-9A-Fa-f]{6}$/)
  })
})
