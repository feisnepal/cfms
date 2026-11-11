import { describe, it, expect } from 'vitest'
import {
  defaultPropertiesForPurpose,
  hasDefaultProperties,
} from '../defaultProperties'

describe('defaultProperties (GD 2.2.5)', () => {
  it('inventory → species/dbh/height/gps_type defaults', () => {
    expect(defaultPropertiesForPurpose('inventory')).toEqual({
      species: '',
      dbh: 0,
      height: 0,
      gps_type: 'manual',
    })
  })

  it('roads → trail default type', () => {
    expect(defaultPropertiesForPurpose('roads')).toEqual({ type: 'trail' })
  })

  it('water → stream default type', () => {
    expect(defaultPropertiesForPurpose('water')).toEqual({ type: 'stream' })
  })

  it('sample_plot → plot size default', () => {
    expect(defaultPropertiesForPurpose('sample_plot')).toEqual({
      plot_size_m2: 0,
      gps_type: 'manual',
    })
  })

  it('boundary/blocks/other/user_group_boundary → empty', () => {
    for (const p of ['boundary', 'blocks', 'other', 'user_group_boundary']) {
      expect(defaultPropertiesForPurpose(p)).toEqual({})
    }
  })

  it('unknown purpose → empty', () => {
    expect(defaultPropertiesForPurpose('bogus')).toEqual({})
  })

  it('returns a fresh copy each call (no shared mutation)', () => {
    const a = defaultPropertiesForPurpose('inventory')
    const b = defaultPropertiesForPurpose('inventory')
    a.species = 'Pine'
    expect(b.species).toBe('')
  })

  it('hasDefaultProperties mirrors non-empty defaults', () => {
    expect(hasDefaultProperties('inventory')).toBe(true)
    expect(hasDefaultProperties('roads')).toBe(true)
    expect(hasDefaultProperties('boundary')).toBe(false)
    expect(hasDefaultProperties('bogus')).toBe(false)
  })
})
