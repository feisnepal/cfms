import { describe, it, expect } from 'vitest'
import { selectedIdsForLayer } from '../selectionScope'

const sel = (layerId: string | null, ids: string[]) => ({ layerId, featureIds: ids })

describe('selectedIdsForLayer', () => {
  it('same layer: the selection as is', () => {
    expect(selectedIdsForLayer(sel('compartments', ['c2']), 'compartments')).toEqual(['c2'])
  })
  it('a unit selected in Compartments reads as selected in Sub-Compartments, and back', () => {
    expect(selectedIdsForLayer(sel('compartments', ['c2']), 'sub_compartments')).toEqual(['c2'])
    expect(selectedIdsForLayer(sel('sub_compartments', ['c2']), 'compartments')).toEqual(['c2'])
  })
  it('same for the block branch', () => {
    expect(selectedIdsForLayer(sel('blocks', ['b1']), 'sub_blocks')).toEqual(['b1'])
    expect(selectedIdsForLayer(sel('sub_blocks', ['b1']), 'blocks')).toEqual(['b1'])
  })
  it('never leaks into an unrelated layer', () => {
    expect(selectedIdsForLayer(sel('compartments', ['c2']), 'sub_areas')).toEqual([])
    expect(selectedIdsForLayer(sel('sub_areas', ['s1']), 'compartments')).toEqual([])
    expect(selectedIdsForLayer(sel('imported:7', ['x']), 'blocks')).toEqual([])
  })
  it('nothing selected / no layer', () => {
    expect(selectedIdsForLayer(sel(null, []), 'blocks')).toEqual([])
    expect(selectedIdsForLayer(sel('blocks', ['b1']), null)).toEqual([])
  })
})
