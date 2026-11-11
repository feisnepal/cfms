import { describe, it, expect } from 'vitest'
import { migrateWorkspacePersist } from '../workspaceStore'

describe('migrateWorkspacePersist — v3 layer-style keys (WORKSPACE_LAYER_STYLING_PLAN.md P0)', () => {
  it('drops bare built-in style keys, keeps imported and per-calc keys', () => {
    const out = migrateWorkspacePersist(
      {
        customLayerStyles: {
          blocks: { color: '#f00' }, // bare built-in → dropped
          sub_areas: { weight: 3 }, // bare built-in → dropped
          'imported-7': { color: '#0f0' }, // kept
          'calc-1::blocks': { color: '#00f' }, // kept
        },
      },
      2,
    )
    expect(Object.keys(out.customLayerStyles as object).sort()).toEqual([
      'calc-1::blocks',
      'imported-7',
    ])
  })

  it('is a no-op for a store already at v3', () => {
    const styles = { blocks: { color: '#f00' } }
    const out = migrateWorkspacePersist({ customLayerStyles: styles }, 3)
    expect(out.customLayerStyles).toBe(styles)
  })

  it('v2 still strips stale imported-layer fields', () => {
    const out = migrateWorkspacePersist({ importedLayers: [1], activeImportedLayerId: 5 }, 1)
    expect(out.importedLayers).toBeUndefined()
    expect(out.activeImportedLayerId).toBeUndefined()
  })
})
