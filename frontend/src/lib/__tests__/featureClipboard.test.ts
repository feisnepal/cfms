import { describe, it, expect } from 'vitest'
import type { GeoJSON } from 'geojson'
import {
  buildSubAreaBodies,
  cleanProperties,
  explodeFeature,
  newLayerName,
  pasteTargetIssue,
  prepareImportedFeatures,
  subAreaCategoryOf,
  toClipboardFeatures,
  uniqueName,
  wasTrimmed,
} from '../featureClipboard'

const square = (x: number, y: number, props: Record<string, unknown> = {}): GeoJSON.Feature => ({
  type: 'Feature',
  geometry: {
    type: 'Polygon',
    coordinates: [[[x, y], [x + 1, y], [x + 1, y + 1], [x, y + 1], [x, y]]],
  },
  properties: props,
})
const point = (props: Record<string, unknown> = {}): GeoJSON.Feature => ({
  type: 'Feature',
  geometry: { type: 'Point', coordinates: [85, 27] },
  properties: props,
})
const line = (): GeoJSON.Feature => ({
  type: 'Feature',
  geometry: { type: 'LineString', coordinates: [[85, 27], [85.1, 27.1]] },
  properties: {},
})

const OPEN = { structureLocked: false }

describe('cleanProperties', () => {
  it('drops identity, sync bookkeeping, per-feature style and derived measurements, keeps attributes', () => {
    const out = cleanProperties({
      id: 'abc', featureId: 'f1', colorIndex: 3, _vectorClock: { x: 1 },
      style_fill: '#fff', created_at: 'now', area_hectares: 4.2, geo_area_ha: 4.2,
      name: 'North slope', category: 'protected', remarks: 'steep',
    })
    expect(out).toEqual({ name: 'North slope', category: 'protected', remarks: 'steep' })
  })
})

describe('explodeFeature / toClipboardFeatures', () => {
  it('splits a MultiPolygon into one Polygon per part, sharing attributes', () => {
    const multi: GeoJSON.Feature = {
      type: 'Feature',
      properties: { name: 'M' },
      geometry: {
        type: 'MultiPolygon',
        coordinates: [
          [[[0, 0], [1, 0], [1, 1], [0, 0]]],
          [[[5, 5], [6, 5], [6, 6], [5, 5]]],
        ],
      },
    }
    const parts = explodeFeature(multi)
    expect(parts).toHaveLength(2)
    expect(parts.every((p) => p.geometry.type === 'Polygon')).toBe(true)
    expect(parts.map((p) => p.properties?.name)).toEqual(['M', 'M'])
  })

  it('deep-copies (mutating the source afterwards does not change the clipboard) and counts geometry-less inputs', () => {
    const src = square(0, 0, { name: 'A', id: 'x' })
    const { features, dropped } = toClipboardFeatures([src, { type: 'Feature', geometry: null as never, properties: {} }])
    expect(features).toHaveLength(1)
    expect(dropped).toBe(1)
    ;(src.geometry as GeoJSON.Polygon).coordinates[0][0][0] = 99
    expect((features[0].geometry as GeoJSON.Polygon).coordinates[0][0][0]).toBe(0)
    expect(features[0].properties).toEqual({ name: 'A' }) // id stripped
  })
})

describe('pasteTargetIssue — which layers may receive a paste', () => {
  const polys = [square(0, 0)]

  it('needs something on the clipboard and a target', () => {
    expect(pasteTargetIssue({ kind: 'builtin', id: 'sub_areas' }, [], OPEN)?.code).toBe('empty_clipboard')
    expect(pasteTargetIssue(null, polys, OPEN)?.code).toBe('no_target')
  })

  it('is refused while the structure (or the layer) is locked', () => {
    expect(pasteTargetIssue({ kind: 'builtin', id: 'sub_areas' }, polys, { structureLocked: true })?.code).toBe('structure_locked')
    expect(pasteTargetIssue({ kind: 'builtin', id: 'sub_areas' }, polys, { structureLocked: false, layerLocked: true })?.code).toBe('structure_locked')
  })

  it('accepts polygons into sub-areas and rejects points / lines with the reason', () => {
    expect(pasteTargetIssue({ kind: 'builtin', id: 'sub_areas' }, polys, OPEN)).toBeNull()
    const issue = pasteTargetIssue({ kind: 'builtin', id: 'sub_areas' }, [square(0, 0), point()], OPEN)
    expect(issue).toEqual({ code: 'geometry_mismatch', params: { have: 'Point', need: 'Polygon' } })
  })

  it.each(['boundary', 'blocks', 'compartments', 'sub_compartments', 'user_group',
    'sample_plots', 'stem_mapping', 'fieldbook', 'activity_features'])(
    'never accepts a paste into the built-in %s layer',
    (id) => {
      expect(pasteTargetIssue({ kind: 'builtin', id }, polys, OPEN)?.code).toBe('layer_not_pastable')
    },
  )

  it('accepts what an imported layer purpose allows and rejects the rest', () => {
    expect(pasteTargetIssue({ kind: 'imported', id: 1, purpose: 'other' }, [square(0, 0), point(), line()], OPEN)).toBeNull()
    expect(pasteTargetIssue({ kind: 'imported', id: 2, purpose: 'roads' }, [line()], OPEN)).toBeNull()
    const bad = pasteTargetIssue({ kind: 'imported', id: 2, purpose: 'roads' }, [square(0, 0)], OPEN)
    expect(bad).toEqual({ code: 'geometry_mismatch', params: { have: 'Polygon', need: 'LineString' } })
  })

  it('refuses imported layers that carry their own topology rules', () => {
    for (const purpose of ['blocks', 'compartments', 'sub_compartments', 'boundary', 'user_group_boundary', 'inventory', 'sample_plot']) {
      expect(pasteTargetIssue({ kind: 'imported', id: 3, purpose }, polys, OPEN)?.code).toBe('purpose_not_pastable')
    }
  })
})

describe('uniqueName', () => {
  it('keeps a free name, then numbers the copies', () => {
    expect(uniqueName('Ridge', new Set())).toBe('Ridge')
    expect(uniqueName('Ridge', new Set(['ridge']))).toBe('Ridge (copy)')
    expect(uniqueName('Ridge', new Set(['ridge', 'ridge (copy)']))).toBe('Ridge (copy 2)')
    expect(uniqueName('  ', new Set())).toBe('Feature')
  })
})

describe('subAreaCategoryOf', () => {
  it('accepts only a real category key', () => {
    expect(subAreaCategoryOf({ category: 'protected' })).toBe('protected')
    expect(subAreaCategoryOf({ category: 'nonsense' })).toBeNull()
    expect(subAreaCategoryOf({})).toBeNull()
    expect(subAreaCategoryOf(null)).toBeNull()
  })
})

describe('buildSubAreaBodies', () => {
  it('keeps the exact geometry, carries the name, and makes names unique against existing + earlier ones', () => {
    const a = square(0, 0, { name: 'Ridge', category: 'protected' })
    const b = square(2, 0, { name: 'Ridge', category: 'protected' })
    const bodies = buildSubAreaBodies([a, b], new Set(['ridge']), (f) => subAreaCategoryOf(f.properties as never), 'Pasted')
    expect(bodies.map((x) => x.name)).toEqual(['Ridge (copy)', 'Ridge (copy 2)'])
    expect(bodies[0].geometry).toEqual(a.geometry) // no offset: exact coordinates
    expect(bodies[0].category).toBe('protected')
  })

  it('falls back to a category chosen for features that have none, and skips a feature with no category at all', () => {
    const f = square(0, 0, { block_name: 'Block-1' })
    const withPick = buildSubAreaBodies([f], new Set(), () => 'plantation', 'Pasted')
    expect(withPick[0].name).toBe('Block-1') // a block's own name is reused
    expect(withPick[0].category).toBe('plantation')
    expect(buildSubAreaBodies([f], new Set(), () => null, 'Pasted')).toEqual([])
  })

  it('marks private land as excluded', () => {
    const [body] = buildSubAreaBodies([square(0, 0, { category: 'private_land' })], new Set(), () => 'private_land', 'Pasted')
    expect(body.is_excluded).toBe(true)
  })
})

describe('prepareImportedFeatures', () => {
  it('gives every feature a fresh, unique temp id and keeps attributes + geometry', () => {
    const src = [square(0, 0, { name: 'A' }), square(2, 0, { name: 'B' })]
    const out = prepareImportedFeatures(src)
    const ids = out.map((f) => (f.properties as Record<string, unknown>).featureId)
    expect(new Set(ids).size).toBe(2)
    expect(out[0].properties).toMatchObject({ name: 'A' })
    expect(out[1].geometry).toEqual(src[1].geometry)
  })
})

describe('wasTrimmed', () => {
  it('only reports a material loss, not sphere-vs-UTM rounding', () => {
    expect(wasTrimmed(10, 10)).toBe(false)
    expect(wasTrimmed(10, 9.95)).toBe(false) // 0.5 % — measurement noise
    expect(wasTrimmed(10, 7)).toBe(true)
    expect(wasTrimmed(10, undefined)).toBe(false)
    expect(wasTrimmed(0, 5)).toBe(false)
  })
})

describe('newLayerName', () => {
  it('appends the suffix and stays unique', () => {
    expect(newLayerName('Blocks', [], '(copy)')).toBe('Blocks (copy)')
    expect(newLayerName('Blocks', ['blocks (copy)'], '(copy)')).toBe('Blocks (copy) 2')
    expect(newLayerName('Blocks', ['Blocks (copy)', 'Blocks (copy) 2'], '(copy)')).toBe('Blocks (copy) 3')
  })
})
