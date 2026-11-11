import { describe, it, expect } from 'vitest'
import {
  SUB_AREA_CATEGORIES,
  getSubAreaCategory,
  subAreaCategoryColor,
  isExcludedCategory,
  getCategoryLabel,
  subAreaCategoryOptions,
  subAreaCategoryByAlias,
} from '../subAreaCategories'

const OFFICIAL_13 = [
  'protected', 'plantation', 'pro-poor', 'religious', 'biodiversity',
  'tourist', 'office', 'private_land', 'agroforestry', 'tree_strata',
  'water_hole', 'wildlife_corridor', 'encroached',
]

describe('SUB_AREA_CATEGORIES (List A single source)', () => {
  it('provides exactly the official 13 categories', () => {
    const keys = SUB_AREA_CATEGORIES.map((c) => c.key)
    expect(keys.sort()).toEqual([...OFFICIAL_13].sort())
    // no legacy List B keys (road/stream/river/degraded/settlement/...)
    for (const legacy of ['road', 'stream', 'river', 'degraded', 'settlement', 'agriculture', 'water_body', 'cliff', 'wetland', 'grassland', 'shrubland', 'conservation']) {
      expect(keys, legacy).not.toContain(legacy)
    }
  })

  it('every entry carries EN + NP labels, a color and isExcluded', () => {
    for (const c of SUB_AREA_CATEGORIES) {
      expect(c.label, c.key).toBeTruthy()
      expect(c.labelNp, c.key).toBeTruthy()
      expect(c.color, c.key).toMatch(/^#[0-9a-f]{6}$/)
      expect(typeof c.isExcluded, c.key).toBe('boolean')
      expect(c.value, c.key).toBe(c.key)
    }
  })

  it('isExcluded is true only for private_land', () => {
    for (const c of SUB_AREA_CATEGORIES) {
      expect(c.isExcluded, c.key).toBe(c.key === 'private_land')
    }
  })
})

describe('helpers', () => {
  it('getSubAreaCategory / subAreaCategoryColor', () => {
    expect(getSubAreaCategory('private_land')?.isExcluded).toBe(true)
    expect(getSubAreaCategory('nope')).toBeUndefined()
    expect(subAreaCategoryColor('protected')).toMatch(/^#/)
    expect(subAreaCategoryColor('nope')).toBe('#808080')
  })

  it('isExcludedCategory', () => {
    expect(isExcludedCategory('private_land')).toBe(true)
    expect(isExcludedCategory('plantation')).toBe(false)
    expect(isExcludedCategory('unknown')).toBe(false)
  })

  it('getCategoryLabel supports en + np, falls back to key', () => {
    expect(getCategoryLabel('private_land', 'en')).toBe('Private Land (Excluded)')
    expect(getCategoryLabel('protected', 'np')).toBe('संरक्षित क्षेत्र')
    expect(getCategoryLabel('nope')).toBe('nope')
  })

  it('subAreaCategoryOptions exposes select-friendly shape', () => {
    const opts = subAreaCategoryOptions()
    expect(opts).toHaveLength(13)
    expect(opts[0]).toHaveProperty('value')
    expect(opts[0]).toHaveProperty('label')
  })
})

describe('subAreaCategoryByAlias (R3 import auto-detect)', () => {
  it('resolves by key, EN label, NP label', () => {
    expect(subAreaCategoryByAlias('private_land')?.key).toBe('private_land')
    expect(subAreaCategoryByAlias('Protected Area')?.key).toBe('protected')
    expect(subAreaCategoryByAlias('संरक्षित क्षेत्र')?.key).toBe('protected')
  })

  it('maps retired List B keys to official categories', () => {
    expect(subAreaCategoryByAlias('road')?.key).toBe('office')
    expect(subAreaCategoryByAlias('river')?.key).toBe('water_hole')
    expect(subAreaCategoryByAlias('conservation')?.key).toBe('biodiversity')
  })

  it('returns undefined for unknown/non-string', () => {
    expect(subAreaCategoryByAlias('not-a-category')).toBeUndefined()
    expect(subAreaCategoryByAlias('')).toBeUndefined()
    expect(subAreaCategoryByAlias(undefined as any)).toBeUndefined()
  })
})
describe('STRIP_CATEGORIES (fire line is a strip, not a zone)', () => {
  it('is rendered by every lookup but never offered in a picker', async () => {
    const { STRIP_CATEGORIES, ALL_SUB_AREA_CATEGORIES, isStripCategory } = await import('../subAreaCategories')
    expect(STRIP_CATEGORIES.map((c) => c.key)).toEqual(['fire_line', 'river_bank'])
    expect(isStripCategory('river_bank')).toBe(true)
    expect(getSubAreaCategory('river_bank')?.labelNp).toBe('खोला किनार')
    expect(isStripCategory('fire_line')).toBe(true)
    expect(isStripCategory('plantation')).toBe(false)
    expect(getSubAreaCategory('fire_line')?.labelNp).toBe('अग्नी रेखा')
    expect(getCategoryLabel('fire_line')).toBe('Fire line')
    expect(subAreaCategoryColor('fire_line')).toBe('#c62828')
    expect(isExcludedCategory('fire_line')).toBe(false)
    expect(SUB_AREA_CATEGORIES.map((c) => c.key)).not.toContain('fire_line')
    expect(subAreaCategoryOptions().map((o) => o.value)).not.toContain('fire_line')
    expect(subAreaCategoryByAlias('fire_line')).toBeUndefined()
    expect(ALL_SUB_AREA_CATEGORIES).toHaveLength(SUB_AREA_CATEGORIES.length + STRIP_CATEGORIES.length)
  })
})
