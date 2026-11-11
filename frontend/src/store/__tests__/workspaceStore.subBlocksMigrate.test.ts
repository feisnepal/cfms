import { describe, it, expect } from 'vitest'
import { migrateWorkspacePersist } from '../workspaceStore'
import { LAYER_ORDER, LAYER_DEFAULT_VISIBILITY } from '../../lib/layerRegistry'

describe('migrateWorkspacePersist — v4 sub_blocks keys (FS-4a.18)', () => {
  it('seeds layerOrder.sub_blocks next to blocks when a v3 store already customised the order', () => {
    const out = migrateWorkspacePersist(
      { layerOrder: { boundary: 0, blocks: 1, sub_areas: 2 } },
      3,
    )
    // v5 then replaces the whole order with the canonical registry order, so
    // assert the END state — the intermediate v4 seed is not what survives.
    expect((out.layerOrder as Record<string, number>).sub_blocks).toBe(LAYER_ORDER.sub_blocks)
  })

  it('falls back to the registry default when layerOrder has no blocks entry either', () => {
    const out = migrateWorkspacePersist({ layerOrder: { boundary: 0 } }, 3)
    expect((out.layerOrder as Record<string, number>).sub_blocks).toBe(LAYER_ORDER.sub_blocks)
  })

  it('gives a store that already had a sub_blocks entry the canonical order (v5 supersedes v4)', () => {
    const out = migrateWorkspacePersist({ layerOrder: { blocks: 1, sub_blocks: 99 } }, 3)
    expect(out.layerOrder).toEqual(LAYER_ORDER)
  })

  it('gives a store with no layerOrder at all the full canonical order', () => {
    const out = migrateWorkspacePersist({}, 3)
    expect(out.layerOrder).toEqual(LAYER_ORDER)
  })

  it('seeds layerVisibility.sub_blocks = true when absent', () => {
    const out = migrateWorkspacePersist({ layerVisibility: { boundary: true, blocks: false } }, 3)
    const vis = out.layerVisibility as Record<string, boolean>
    expect(vis.sub_blocks).toBe(LAYER_DEFAULT_VISIBILITY.sub_blocks)
    // an existing explicit false is left alone
    expect(vis.blocks).toBe(false)
  })

  it('does not overwrite an existing layerVisibility.sub_blocks entry', () => {
    const out = migrateWorkspacePersist({ layerVisibility: { sub_blocks: false } }, 3)
    const vis = out.layerVisibility as Record<string, boolean>
    expect(vis.sub_blocks).toBe(false)
  })

  it('runs alongside the earlier v2/v3 migrations for a store starting from v1', () => {
    const out = migrateWorkspacePersist(
      {
        importedLayers: [1],
        customLayerStyles: { blocks: { color: '#f00' }, 'calc-1::blocks': { color: '#00f' } },
        layerOrder: { blocks: 1 },
      },
      1,
    )
    expect(out.importedLayers).toBeUndefined()
    expect(Object.keys(out.customLayerStyles as object)).toEqual(['calc-1::blocks'])
    expect(out.layerOrder).toEqual(LAYER_ORDER)
  })
})

describe('migrateWorkspacePersist — v5 canonical layer order and defaults (owner 2026-09-29)', () => {
  it('replaces a v4 store layerOrder with the registry order', () => {
    // The exact shape a v4 store carries: 4 seeded layers plus sub_blocks, with
    // the other 7 absent — which is why the panel's `?? 0` fallback tied them
    // all and the rendered order was nobody's decision.
    const out = migrateWorkspacePersist(
      { layerOrder: { boundary: 0, blocks: 1, sub_blocks: 1.5, sub_areas: 2, activity_features: 3 } },
      4,
    )
    expect(out.layerOrder).toEqual(LAYER_ORDER)
  })

  it('is a no-op for a store already at v5', () => {
    const out = migrateWorkspacePersist({ layerOrder: { blocks: 99 } }, 5)
    expect(out.layerOrder).toEqual({ blocks: 99 })
  })

  it('fills in a missing default visibility without touching a deliberate one', () => {
    const out = migrateWorkspacePersist(
      // `sample_plots: false` is the user clicking the eye; the rest are absent.
      { layerVisibility: { boundary: true, blocks: true, sample_plots: false } },
      4,
    )
    const vis = out.layerVisibility as Record<string, boolean>
    // preserved
    expect(vis.sample_plots).toBe(false)
    expect(vis.blocks).toBe(true)
    // newly seeded to the registry default
    expect(vis.sub_areas).toBe(LAYER_DEFAULT_VISIBILITY.sub_areas)
    expect(vis.activity_features).toBe(LAYER_DEFAULT_VISIBILITY.activity_features)
    expect(vis.stem_mapping).toBe(LAYER_DEFAULT_VISIBILITY.stem_mapping)
    expect(vis.user_group).toBe(LAYER_DEFAULT_VISIBILITY.user_group)
    expect(vis.fieldbook).toBe(LAYER_DEFAULT_VISIBILITY.fieldbook)
    // every built-in is now decided
    expect(Object.keys(vis).sort()).toEqual(Object.keys(LAYER_DEFAULT_VISIBILITY).sort())
  })

  it('leaves a store with no layerVisibility alone (a fresh store gets the registry defaults)', () => {
    const out = migrateWorkspacePersist({ layerOrder: { blocks: 1 } }, 4)
    expect(out.layerVisibility).toBeUndefined()
  })

  it('seeds nothing on a fresh store — createInitialState already has the defaults', () => {
    const out = migrateWorkspacePersist({}, 5)
    expect(out.layerOrder).toBeUndefined()
    expect(out.layerVisibility).toBeUndefined()
  })
})
