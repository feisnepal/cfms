import { describe, it, expect } from 'vitest'
import type { FireLineRow } from '../../services/api'
import {
  KIND_DEFAULT_SIDE, KIND_GROUPS, chainOrder, groupByPair, DEFAULT_SIDE_M, allWidthsValid, defaultWidths, errorMessage, filterRows, newClientId, pendingChanges, projectedTotals,
  segmentCount, stageAll, statusMessage, toggle, validWidth, wanted,
} from '../fireLines'

const row = (unit_key: string, name: string, ticked = true, group: 'boundary' | 'road' = 'boundary', length_m = 100, area_ha = 0.03): FireLineRow => ({
  unit_key, name, group, highway: '', ticked, strip_id: ticked ? `id-${unit_key}` : null, length_m, area_ha, edited: false,
})

const ROWS = [row('a', 'SC1-SC2'), row('b', 'SC1-SC3'), row('c', 'बाटो (path)', true, 'road', 243, 0.073), row('d', 'SC2-SC3', false)]

describe('widths', () => {
  it('counts segments and defaults every one to the fire-line width', () => {
    expect(segmentCount({ coordinates: [[0, 0], [1, 1], [2, 2]] })).toBe(2)
    expect(segmentCount(null)).toBe(0)
    expect(defaultWidths(3)).toEqual([DEFAULT_SIDE_M, DEFAULT_SIDE_M, DEFAULT_SIDE_M])
  })

  it('accepts only 0.1 to 50 metres', () => {
    expect([0.1, 1.5, 50].every(validWidth)).toBe(true)
    expect([0, -1, 50.5, Number.NaN, '3' as unknown as number].some(validWidth)).toBe(false)
    expect(allWidthsValid([1.5, 2])).toBe(true)
    expect(allWidthsValid([1.5, Number.NaN])).toBe(false)
    expect(allWidthsValid([])).toBe(false)
  })
})

describe('the tick-list', () => {
  it('filters by name, ignoring case', () => {
    expect(filterRows(ROWS, 'sc1').map((r) => r.unit_key)).toEqual(['a', 'b'])
    expect(filterRows(ROWS, '  ').length).toBe(4)
    expect(filterRows(ROWS, 'zzz')).toEqual([])
  })

  it('a staged tick that matches the stored state is no change at all', () => {
    let staged = toggle(ROWS[0], {})
    expect(wanted(ROWS[0], staged)).toBe(false)
    expect(pendingChanges(ROWS, staged)).toEqual([{ unit_key: 'a', included: false }])
    staged = toggle(ROWS[0], staged)                       // ticked again: back to where it was
    expect(staged).toEqual({})
    expect(pendingChanges(ROWS, staged)).toEqual([])
  })

  it('ticks an unticked row', () => {
    const staged = toggle(ROWS[3], {})
    expect(pendingChanges(ROWS, staged)).toEqual([{ unit_key: 'd', included: true }])
  })

  it('select none / select all work on the rows shown and leave the others alone', () => {
    const shown = filterRows(ROWS, 'sc1')
    const none = stageAll(shown, {}, false)
    expect(pendingChanges(ROWS, none)).toEqual([{ unit_key: 'a', included: false }, { unit_key: 'b', included: false }])
    const all = stageAll(shown, none, true)
    expect(all).toEqual({})
    expect(pendingChanges(ROWS, stageAll(ROWS, {}, true))).toEqual([{ unit_key: 'd', included: true }])
  })

  it('projects the totals of what would exist after the ticks', () => {
    const now = projectedTotals(ROWS, {})
    expect(now.boundary).toEqual({ count: 2, km: 0.2, ha: 0.06 })
    expect(now.road).toEqual({ count: 1, km: 0.243, ha: 0.073 })
    const after = projectedTotals(ROWS, { a: false, d: true, c: false })
    expect(after.boundary.count).toBe(2)                    // b and d
    expect(after.road.count).toBe(0)
  })
})

describe('status and errors', () => {
  it('says nothing when all is well and explains a refusal', () => {
    expect(statusMessage({ state: 'ok' })).toBeNull()
    expect(statusMessage({ state: 'synced' })).toBeNull()
    expect(statusMessage({ state: 'dirty_units', overlap_m2: 2685.9 })).toEqual({ key: 'fireLines.status.dirty_units', params: { m2: 2686 } })
    expect(statusMessage({ state: 'unresolved_edges', unresolved_legs: 62, legs: 463 })?.params).toEqual({ n: 62, total: 463 })
    expect(statusMessage(undefined)?.key).toBe('fireLines.status.never')
    expect(statusMessage({ state: 'fragmented_edges', pieces: 308, pairs: 43 })).toEqual({ key: 'fireLines.status.fragmented_edges', params: { pieces: 308, pairs: 43 } })
  })

  it("prefers the backend's friendly message", () => {
    expect(errorMessage({ response: { data: { detail: { code: 'bad_widths', message: 'Each width must be…' } } } }, 'x')).toBe('Each width must be…')
    expect(errorMessage({ response: { data: { detail: 'Permission denied' } } }, 'x')).toBe('Permission denied')
    expect(errorMessage(new Error('boom'), 'fallback')).toBe('fallback')
  })

  it('makes a different replay-safe id each time', () => {
    expect(newClientId()).not.toBe(newClientId())
  })
})


describe('the two kinds', () => {
  it('have their own groups and their own default width per side', () => {
    expect(KIND_GROUPS.fire_line).toEqual(['boundary', 'road'])
    expect(KIND_GROUPS.river_bank).toEqual(['river'])
    expect(KIND_DEFAULT_SIDE).toEqual({ fire_line: 1.5, river_bank: 20 })
    expect(defaultWidths(2, KIND_DEFAULT_SIDE.river_bank)).toEqual([20, 20])
  })

  it('count a river row in the river group', () => {
    const riverRow = { ...row('r', 'A (Khola)', true, 'river' as unknown as 'boundary', 2000, 8) }
    expect(projectedTotals([riverRow], {}).river).toEqual({ count: 1, km: 2, ha: 8 })
  })
})

describe('chainOrder', () => {
  const row = (k: string, coords: number[][] | null) => ({ unit_key: k, name: k, centerline: coords ? { type: 'LineString', coordinates: coords } : null }) as never
  it('puts each line next to the one it touches, starting north-west', () => {
    const a = row('a', [[0, 0], [1, 0]])
    const b = row('b', [[5, 5], [6, 5]])
    const c = row('c', [[1, 0], [1, -1]])
    const d = row('d', [[6, 5], [0, 5.001]])
    const none = row('x', null)
    const order = chainOrder([a, b, c, d, none]).map((r: { unit_key: string }) => r.unit_key)
    expect(order.slice(-1)).toEqual(['x'])
    expect(order.indexOf('c') - order.indexOf('a')).toBe(1)
    expect(Math.abs(order.indexOf('b') - order.indexOf('d'))).toBe(1)
  })
})

describe('groupByPair', () => {
  const r = (unit_key: string, name: string, group = 'boundary', length_m = 10) => ({ unit_key, name, group, length_m, area_ha: 0.1 }) as never
  it('makes one entry per unit pair, however many pieces and lines it has; roads stay single', () => {
    const out = groupByPair([r('u4+u7||1', 'e-g'), r('u1+u2||1', 'a-b'), r('u4+u7||1~1', 'e-g ·2'), r('u4+u7||2', 'e-g (3)'), r('road:1|1', 'bato', 'road')])
    expect(out.map((g) => g.name)).toEqual(['e-g', 'a-b', 'bato'])
    expect(out[0].rows).toHaveLength(3)
    expect(out[0].length_m).toBe(30)
  })
})

describe('projectedTotals counts a pair once', () => {
  it('three pieces of e-g are one in the count, all in the length', () => {
    const r = (unit_key: string) => ({ unit_key, name: unit_key, group: 'boundary', ticked: true, length_m: 100, area_ha: 0.1 }) as never
    const t = projectedTotals([r('u4+u7||1'), r('u4+u7||1~1'), r('u4+u7||2'), r('u1+u2||1')], {})
    expect(t.boundary.count).toBe(2)
    expect(t.boundary.km).toBe(0.4)
  })
})
