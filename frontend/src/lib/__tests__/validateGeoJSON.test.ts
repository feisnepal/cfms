import { describe, it, expect } from 'vitest'
import { validateGeoJSON, validateFeatureCollection } from '../validateGeoJSON'

describe('validateGeoJSON', () => {
  it('rejects null', () => {
    const r = validateGeoJSON(null)
    expect(r.valid).toBe(false)
    expect(r.errors[0].code).toBe('missing_type')
  })

  it('rejects non-object', () => {
    const r = validateGeoJSON('foo')
    expect(r.valid).toBe(false)
  })

  it('rejects missing type', () => {
    const r = validateGeoJSON({})
    expect(r.valid).toBe(false)
  })

  it('rejects unknown type', () => {
    const r = validateGeoJSON({ type: 'Unknown' })
    expect(r.valid).toBe(false)
    expect(r.errors[0].code).toBe('invalid_type')
  })

  it('accepts valid Feature', () => {
    const r = validateGeoJSON({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [0, 0] },
      properties: {},
    })
    expect(r.valid).toBe(true)
  })

  it('accepts null geometry Feature', () => {
    const r = validateGeoJSON({
      type: 'Feature',
      geometry: null,
      properties: {},
    })
    expect(r.valid).toBe(true)
  })

  it('rejects Feature missing geometry', () => {
    const r = validateGeoJSON({
      type: 'Feature',
      properties: {},
    })
    expect(r.valid).toBe(false)
    expect(r.errors[0].code).toBe('missing_geometry')
  })

  it('accepts valid FeatureCollection', () => {
    const r = validateGeoJSON({
      type: 'FeatureCollection',
      features: [
        { type: 'Feature', geometry: { type: 'Point', coordinates: [0, 0] }, properties: {} },
      ],
    })
    expect(r.valid).toBe(true)
  })

  it('rejects FeatureCollection without features', () => {
    const r = validateGeoJSON({ type: 'FeatureCollection', features: [] })
    expect(r.valid).toBe(false)
    expect(r.errors[0].code).toBe('no_features')
  })

  it('rejects FeatureCollection with non-array features', () => {
    const r = validateGeoJSON({ type: 'FeatureCollection', features: 'bad' })
    expect(r.valid).toBe(false)
    expect(r.errors[0].code).toBe('invalid_feature_collection')
  })

  it('accepts bare geometry object', () => {
    const r = validateGeoJSON({ type: 'Point', coordinates: [0, 0] })
    expect(r.valid).toBe(true)
  })

  it('accepts Polygon geometry', () => {
    const r = validateGeoJSON({
      type: 'Polygon',
      coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]],
    })
    expect(r.valid).toBe(true)
  })

  it('rejects geometry without coordinates', () => {
    const r = validateGeoJSON({ type: 'Point' })
    expect(r.valid).toBe(false)
    expect(r.errors[0].code).toBe('missing_coordinates')
  })

  it('rejects GeometryCollection without geometries', () => {
    const r = validateGeoJSON({ type: 'GeometryCollection' })
    expect(r.valid).toBe(false)
  })
})

describe('validateFeatureCollection', () => {
  it('returns FeatureCollection for valid input', () => {
    const fc = validateFeatureCollection({
      type: 'FeatureCollection',
      features: [{ type: 'Feature', geometry: { type: 'Point', coordinates: [0, 0] }, properties: {} }],
    })
    expect(fc).not.toBeNull()
    expect(fc!.features).toHaveLength(1)
  })

  it('returns null for invalid input', () => {
    expect(validateFeatureCollection(null)).toBeNull()
    expect(validateFeatureCollection({ type: 'Feature', geometry: null })).toBeNull()
  })
})
