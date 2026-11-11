import { describe, it, expect } from 'vitest'
import {
  PURPOSES,
  PURPOSE_ALLOWED_GEOMETRY_TYPES,
  allowedGeometryTypes,
  geometryTypesForPurpose,
  isGeometryTypeAllowed,
  isDrawModeAllowed,
  purposeLabel,
  purposeLabelNp,
} from '../purposeGeometryRules'

describe('purposeGeometryRules', () => {
  it('exposes exactly the 12 purposes', () => {
    expect(PURPOSES.map((p) => p.id)).toEqual([
      'inventory',
      'sample_plot',
      'user_group_boundary',
      'boundary',
      'blocks',
      'sub_blocks',
      'compartments',
      'sub_compartments',
      'roads',
      'water',
      'sub_areas',
      'other',
    ])
  })

  it('covers every purpose with a geometry rule', () => {
    for (const p of PURPOSES) {
      expect(PURPOSE_ALLOWED_GEOMETRY_TYPES[p.id].length).toBeGreaterThan(0)
    }
  })

  it('parity with backend matrix', () => {
    // Mirrors backend/app/services/purpose_geometry_rules.py
    const backendMatrix = {
      inventory: ['Point'],
      sample_plot: ['Point'],
      user_group_boundary: ['Polygon'],
      boundary: ['Polygon'],
      blocks: ['Polygon'],
      sub_blocks: ['Polygon'],
      compartments: ['Polygon'],
      sub_compartments: ['Polygon'],
      roads: ['LineString'],
      water: ['LineString', 'Polygon'],
      sub_areas: ['Polygon'],
      other: ['Point', 'LineString', 'Polygon'],
    }
    expect(PURPOSE_ALLOWED_GEOMETRY_TYPES).toEqual(backendMatrix)
  })

  it('maps geometry types to draw modes', () => {
    expect(geometryTypesForPurpose('inventory')).toEqual(['point'])
    expect(geometryTypesForPurpose('roads')).toEqual(['line'])
    expect(geometryTypesForPurpose('water')).toEqual(['line', 'polygon'])
    expect(geometryTypesForPurpose('other')).toEqual(['point', 'line', 'polygon'])
  })

  it('unknown purpose yields empty allowed set', () => {
    expect(allowedGeometryTypes('bogus')).toEqual([])
    expect(geometryTypesForPurpose('bogus')).toEqual([])
  })

  it('isGeometryTypeAllowed / isDrawModeAllowed', () => {
    expect(isGeometryTypeAllowed('inventory', 'Point')).toBe(true)
    expect(isGeometryTypeAllowed('inventory', 'Polygon')).toBe(false)
    expect(isDrawModeAllowed('inventory', 'point')).toBe(true)
    expect(isDrawModeAllowed('inventory', 'polygon')).toBe(false)
    expect(isDrawModeAllowed('roads', 'line')).toBe(true)
    expect(isDrawModeAllowed('roads', 'polygon')).toBe(false)
  })

  it('purpose labels resolve', () => {
    expect(purposeLabel('inventory')).toBe('Tree Inventory')
    expect(purposeLabel('nope')).toBe('nope')
    expect(purposeLabelNp('blocks')).toBe('ब्लक')
    expect(purposeLabelNp('nope')).toBe('nope')
  })
})
