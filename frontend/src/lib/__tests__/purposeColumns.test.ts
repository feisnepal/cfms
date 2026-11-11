import { describe, it, expect } from 'vitest'
import {
  PURPOSE_FIELD_DEFS,
  purposeFieldDefs,
  purposeColumnsForFeatures,
} from '../purposeColumns'
import type { GeoJSON } from 'geojson'

function feature(props: Record<string, unknown>): GeoJSON.Feature {
  return {
    type: 'Feature',
    geometry: { type: 'Point', coordinates: [85.5, 27.5] },
    properties: props,
  }
}

describe('purposeColumns (GD 2.3.2)', () => {
  it('defines purpose column schemas for the 8 purposes', () => {
    const purposes = ['inventory', 'sample_plot', 'user_group_boundary', 'boundary', 'blocks', 'roads', 'water', 'other']
    for (const p of purposes) {
      expect(PURPOSE_FIELD_DEFS[p as keyof typeof PURPOSE_FIELD_DEFS]).toBeDefined()
    }
  })

  it('inventory → species/dbh/height/gps_type canonical columns', () => {
    const cols = purposeColumnsForFeatures('inventory', [
      feature({ species: 'Pine', dbh: 30, height: 25, gps_type: 'manual', featureId: 'f1' }),
    ])
    const keys = cols.map((c) => c.key)
    expect(keys.slice(1)).toEqual(['species', 'dbh', 'height', 'gps_type', 'featureId'])
  })

  it('roads → type only (plus dynamic extras)', () => {
    const cols = purposeColumnsForFeatures('roads', [feature({ type: 'trail', featureId: 'r1' })])
    expect(cols.map((c) => c.key).slice(1)).toEqual(['type', 'featureId'])
  })

  it('water → type only (plus dynamic extras)', () => {
    const cols = purposeColumnsForFeatures('water', [feature({ type: 'stream', featureId: 'w1' })])
    expect(cols.map((c) => c.key).slice(1)).toEqual(['type', 'featureId'])
  })

  it('boundary/blocks/other → no canonical columns, dynamic extras only', () => {
    for (const p of ['boundary', 'blocks', 'other']) {
      const cols = purposeColumnsForFeatures(p, [feature({ featureId: 'x' })])
      expect(cols.map((c) => c.key)).toEqual(['#', 'featureId'])
    }
  })

  it('unknown purpose → generic dynamic columns', () => {
    const cols = purposeColumnsForFeatures('bogus', [feature({ a: 1, b: 2 })])
    expect(cols.map((c) => c.key)).toEqual(['#', 'a', 'b'])
  })

  it('canonical columns include properties absent from every feature? No — they are filtered to present keys', () => {
    const cols = purposeColumnsForFeatures('inventory', [feature({ species: 'Oak', featureId: 'f1' })])
    const keys = cols.map((c) => c.key)
    expect(keys).toContain('species')
    expect(keys).not.toContain('dbh') // absent from all features → dropped
  })

  it('extra properties beyond canonical follow canonical order', () => {
    const cols = purposeColumnsForFeatures('inventory', [
      feature({ species: 'Pine', dbh: 30, height: 25, gps_type: 'manual', featureId: 'f1', notes: 'healthy' }),
    ])
    const keys = cols.map((c) => c.key)
    expect(keys.slice(1)).toEqual(['species', 'dbh', 'height', 'gps_type', 'featureId', 'notes'])
  })

  it('columnLabels override display labels (i18n / rename)', () => {
    const cols = purposeColumnsForFeatures('inventory', [
      feature({ species: 'Pine', dbh: 30, featureId: 'f1' }),
    ], { species: 'वृक्ष प्रजाति' })
    const speciesCol = cols.find((c) => c.key === 'species')!
    expect(speciesCol.label).toBe('वृक्ष प्रजाति')
  })

  it('canonical columns are editable and read properties', () => {
    const cols = purposeColumnsForFeatures('inventory', [
      feature({ species: 'Pine', dbh: 30, featureId: 'f1' }),
    ])
    const speciesCol = cols.find((c) => c.key === 'species')!
    expect(speciesCol.editable).toBe(true)
    expect(speciesCol.getValue?.(cols.length > 0 ? feature({ species: 'Sal' }) as GeoJSON.Feature : undefined as never, 0)).toBe('Sal')
  })

  it('purposeFieldDefs returns empty for unknown purposes', () => {
    expect(purposeFieldDefs('bogus')).toEqual([])
    expect(purposeFieldDefs('inventory').map((f) => f.key)).toEqual(['species', 'dbh', 'height', 'gps_type'])
  })
})
