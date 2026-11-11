import { describe, it, expect } from 'vitest'
import {
  PURPOSE_STYLE,
  purposeStyle,
  purposeLeafletStyle,
} from '../purposeStyleMap'

describe('purposeStyleMap (GD 2.2.3)', () => {
  it('defines a style for all 8 purposes', () => {
    const purposes = ['inventory', 'sample_plot', 'user_group_boundary', 'boundary', 'blocks', 'roads', 'water', 'other']
    for (const p of purposes) {
      expect(PURPOSE_STYLE[p as keyof typeof PURPOSE_STYLE]).toBeDefined()
      expect(PURPOSE_STYLE[p as keyof typeof PURPOSE_STYLE].color).toBeTruthy()
    }
  })

  it('water uses blue + diagonal-hatch pattern (colorblind support)', () => {
    const w = purposeStyle('water')
    expect(w.fillColor).toBe('#29b6f6')
    expect(w.fillPattern).toBe('diagonal-hatch')
  })

  it('roads uses red + dashed border', () => {
    const r = purposeStyle('roads')
    expect(r.color).toBe('#d32f2f')
    expect(r.dashArray).toBe('8 6')
  })

  it('inventory uses green circle point markers', () => {
    const i = purposeStyle('inventory')
    expect(i.color).toBe('#2e7d32')
    expect(i.pointRadius).toBe(6)
    expect(i.pointShape).toBe('circle')
  })

  it('unknown purpose falls back to other/gray', () => {
    expect(purposeStyle('bogus')).toBe(PURPOSE_STYLE.other)
  })

  it('purposeLeafletStyle keeps draft hatch pattern but strips it for finalized', () => {
    const draft = purposeLeafletStyle('water', true)
    expect(draft.fillPattern).toBe('diagonal-hatch')
    expect(draft.fillColor).toBe('#29b6f6')
    const finalized = purposeLeafletStyle('water', false)
    expect(finalized.fillPattern).toBeUndefined()
  })

  it('purposeLeafletStyle emits numeric stroke params', () => {
    const s = purposeLeafletStyle('blocks', false)
    expect(s.color).toBe('#1565c0')
    expect(s.weight).toBe(2)
    expect(typeof s.opacity).toBe('number')
  })
})
