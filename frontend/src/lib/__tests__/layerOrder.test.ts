import { describe, it, expect } from 'vitest'
import {
  LAYER_REGISTRY,
  LAYER_ORDER,
  LAYER_ORDER_IDS,
  LAYER_DEFAULT_VISIBILITY,
  getAllLayerConfigs,
  resolveLayerOrder,
  isLayerVisibleByDefault,
  type LayerTypeId,
} from '../layerRegistry'

/**
 * The owner's expected order and default show/hide (2026-09-29). This is the
 * table the panel must render, top to bottom.
 */
const EXPECTED: Array<[LayerTypeId, boolean]> = [
  ['boundary', true],
  ['user_group', false],
  ['blocks', true],
  ['sub_blocks', true],
  ['compartments', true],
  ['sub_compartments', true],
  ['sub_areas', false],
  ['sample_plots', true],
  ['stem_mapping', false],
  ['activity_features', false],
  ['fieldbook', false],
]

describe('layer registry — canonical panel order and defaults (owner 2026-09-29)', () => {
  it('lists every built-in layer exactly once, in the expected order', () => {
    expect(LAYER_ORDER_IDS).toEqual(EXPECTED.map(([id]) => id))
  })

  it('covers every registry entry — no layer is missing from LAYER_ORDER_IDS', () => {
    // Spread: `.sort()` mutates in place, and LAYER_ORDER_IDS is a module export.
    expect([...LAYER_ORDER_IDS].sort()).toEqual(Object.keys(LAYER_REGISTRY).sort())
  })

  it('carries the expected default show/hide for every layer', () => {
    for (const [id, visible] of EXPECTED) {
      expect(LAYER_DEFAULT_VISIBILITY[id], `defaultVisible for ${id}`).toBe(visible)
    }
  })

  it('has no duplicate order values (two layers tying is what made the panel arbitrary)', () => {
    const orders = LAYER_ORDER_IDS.map((id) => LAYER_REGISTRY[id].order)
    expect(new Set(orders).size).toBe(orders.length)
  })

  it('agrees with getAllLayerConfigs() sorting', () => {
    expect(getAllLayerConfigs().map((c) => c.id)).toEqual([...LAYER_ORDER_IDS])
  })
})

describe('resolveLayerOrder', () => {
  it('falls back to the registry order, not to 0', () => {
    // The bug this fixes: `layerOrder[id] ?? 0` tied seven of eleven layers at 0
    // and their real position came from an array literal nobody could see.
    expect(resolveLayerOrder({}, 'boundary')).toBe(LAYER_ORDER.boundary)
    expect(resolveLayerOrder({}, 'fieldbook')).toBe(LAYER_ORDER.fieldbook)
    expect(resolveLayerOrder(undefined, 'sample_plots')).toBe(LAYER_ORDER.sample_plots)
  })

  it('an explicit user override wins for that layer only', () => {
    const order = { blocks: 99 }
    expect(resolveLayerOrder(order, 'blocks')).toBe(99)
    expect(resolveLayerOrder(order, 'boundary')).toBe(LAYER_ORDER.boundary)
  })

  it('sorts the full set into the expected order with no overrides at all', () => {
    const sorted = [...LAYER_ORDER_IDS].sort((a, b) => resolveLayerOrder({}, a) - resolveLayerOrder({}, b))
    expect(sorted).toEqual(EXPECTED.map(([id]) => id))
  })
})

describe('isLayerVisibleByDefault', () => {
  it('returns the registry default when there is no override', () => {
    expect(isLayerVisibleByDefault({}, 'sub_areas')).toBe(false)
    expect(isLayerVisibleByDefault({}, 'boundary')).toBe(true)
  })

  it('returns the override when the user set one', () => {
    expect(isLayerVisibleByDefault({ sub_areas: true }, 'sub_areas')).toBe(true)
    expect(isLayerVisibleByDefault({ boundary: false }, 'boundary')).toBe(false)
  })
})
