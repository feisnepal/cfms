import { describe, it, expect } from 'vitest'
import { renderHook } from '@testing-library/react'
import {
  hasCompartmentsFromResultData,
  hasCompartmentsFromStream,
  analysisUnitKey,
  useDimensionLabels,
} from '../useDimensionLabels'

describe('useDimensionLabels sub-unit terms (FS-4a.1)', () => {
  it('a block-mode forest gets Sub-Block terms, not the top-level Block term reused', () => {
    const { result } = renderHook(() => useDimensionLabels({ hasCompartments: false }))
    expect(result.current.subUnitLabel).toBe('Sub-Block')
    expect(result.current.subUnitLabelNp).toBe('उप-ब्लक')
    expect(result.current.labelForLevel(1)).toBe('Block')
    expect(result.current.labelForLevel(2)).toBe('Sub-Block')
    expect(result.current.labelForLevelNp(2)).toBe('उप-ब्लक')
  })

  it('a compartment-mode forest is unchanged (already had sub-compartment terms)', () => {
    const { result } = renderHook(() => useDimensionLabels({ hasCompartments: true }))
    expect(result.current.subUnitLabel).toBe('Sub-Compartment')
    expect(result.current.labelForLevel(2)).toBe('Sub-Compartment')
  })
})

describe('analysisUnitKey', () => {
  it('is "blocks" for a plain block forest', () => {
    expect(analysisUnitKey({ blocks: [{}, {}], total_blocks: 2 })).toBe('blocks')
  })

  it('is "compartments" once a populated compartments array exists', () => {
    expect(analysisUnitKey({ blocks: [{}], compartments: [{}, {}, {}] })).toBe('compartments')
  })

  it('stays "blocks" when compartments is empty even if polygon_type says compartment', () => {
    // stricter than hasCompartmentsFromResultData on purpose — nothing to render
    expect(analysisUnitKey({ blocks: [{}], compartments: [], polygon_type: 'compartment' })).toBe('blocks')
    expect(hasCompartmentsFromResultData({ compartments: [], polygon_type: 'compartment' })).toBe(true)
  })

  it('handles null / undefined / missing', () => {
    expect(analysisUnitKey(null)).toBe('blocks')
    expect(analysisUnitKey(undefined)).toBe('blocks')
    expect(analysisUnitKey({})).toBe('blocks')
  })
})

describe('hasCompartmentsFromStream (FS-1a.15)', () => {
  it('trusts the API stream over the fallback', () => {
    expect(hasCompartmentsFromStream('compartment', false)).toBe(true)
    expect(hasCompartmentsFromStream('block', true)).toBe(false)
    expect(hasCompartmentsFromStream('undecided', true)).toBe(false)
  })

  it('falls back to the result_data rule when the response carries no stream', () => {
    expect(hasCompartmentsFromStream(undefined, true)).toBe(true)
    expect(hasCompartmentsFromStream(null, false)).toBe(false)
    expect(hasCompartmentsFromStream('something-new', true)).toBe(true)
  })
})
