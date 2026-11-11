import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { Feature } from 'geojson'
import { makeClickHandler, isDigitizingToolbarMode } from '../MapCanvas'
import { useWorkspaceStore } from '../../store/workspaceStore'

function makeFeature(): Feature {
  return { type: 'Feature', id: 'blk-1', geometry: { type: 'Polygon', coordinates: [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]] }, properties: { id: 'blk-1' } }
}

function mockEvent(feature: Feature) {
  return {
    target: { feature },
    originalEvent: {},
  } as any
}

// makeClickHandler reads the LIVE store via useWorkspaceStore.getState(), not a
// snapshot — that is the fix for "can only digitize where no other layer is
// visible". So the tests drive the real store rather than passing a fake.
function armStore(toolbarMode: unknown, extra: Record<string, unknown> = {}) {
  const selectFeatures = vi.fn()
  const toggleFeatureSelection = vi.fn()
  const setActiveLayer = vi.fn()
  const setActiveImportedLayer = vi.fn()
  const setActiveRasterLayer = vi.fn()
  const patch: Record<string, unknown> = {
    toolbarMode,
    selectFeatures,
    toggleFeatureSelection,
    setActiveLayer,
    setActiveImportedLayer,
    setActiveRasterLayer,
    activeLayerId: null,
    activeImportedLayerId: null,
    activeRasterLayerId: null,
    ...extra,
  }
  useWorkspaceStore.setState(patch as never)
  return { selectFeatures, toggleFeatureSelection, setActiveLayer, setActiveImportedLayer, setActiveRasterLayer }
}

describe('MapCanvas makeClickHandler (draw-gesture selection guard)', () => {
  beforeEach(() => {
    useWorkspaceStore.setState({ toolbarMode: null })
  })

  it('selects the feature when no tool is active and its layer is already active', () => {
    const store = armStore(null, { activeLayerId: 'blocks' })
    makeClickHandler('blocks')(mockEvent(makeFeature()))
    expect(store.selectFeatures).toHaveBeenCalledWith('blocks', ['blk-1'])
    expect(store.toggleFeatureSelection).not.toHaveBeenCalled()
  })

  it('does NOT mutate selection while a split gesture is running', () => {
    const store = armStore('split', { activeLayerId: 'blocks' })
    makeClickHandler('blocks')(mockEvent(makeFeature()))
    expect(store.selectFeatures).not.toHaveBeenCalled()
    expect(store.toggleFeatureSelection).not.toHaveBeenCalled()
  })

  it('does NOT mutate selection during the other live draw modes', () => {
    for (const mode of ['merge', 'move', 'draw_polygon', 'draw_point', 'draw_line', 'subarea_category']) {
      const store = armStore(mode, { activeLayerId: 'blocks' })
      makeClickHandler('blocks')(mockEvent(makeFeature()))
      expect(store.selectFeatures).not.toHaveBeenCalled()
      expect(store.toggleFeatureSelection).not.toHaveBeenCalled()
    }
  })

  it('reads the LIVE toolbar mode, not the one in effect when the layer mounted', () => {
    // Layer mounts with no tool armed → handler bound now.
    armStore(null, { activeLayerId: 'sub_areas' })
    const handler = makeClickHandler('sub_areas')
    // User then arms "Add sub-area" → draw_polygon, WITHOUT the layer remounting.
    const store = armStore('draw_polygon', { activeLayerId: 'sub_areas' })
    handler(mockEvent(makeFeature()))
    // The click must be ignored so Geoman keeps the vertex; nothing selected.
    expect(store.selectFeatures).not.toHaveBeenCalled()
    expect(store.toggleFeatureSelection).not.toHaveBeenCalled()
  })

  it('still allows selection during plain select mode', () => {
    const store = armStore('select', { activeLayerId: 'blocks' })
    makeClickHandler('blocks')(mockEvent(makeFeature()))
    expect(store.selectFeatures).toHaveBeenCalledWith('blocks', ['blk-1'])
  })
})

describe('MapCanvas makeClickHandler — layer panel is the only way to arm a layer (owner directive 2026-10-02)', () => {
  beforeEach(() => {
    useWorkspaceStore.setState({ toolbarMode: null })
  })

  it('is a no-op when the clicked feature is on a built-in layer that is not active', () => {
    const store = armStore(null, { activeLayerId: 'compartments' })
    makeClickHandler('blocks')(mockEvent(makeFeature()))
    expect(store.setActiveLayer).not.toHaveBeenCalled()
    expect(store.selectFeatures).not.toHaveBeenCalled()
  })

  it('selects when the clicked feature is already on the active built-in layer', () => {
    const store = armStore(null, { activeLayerId: 'blocks' })
    makeClickHandler('blocks')(mockEvent(makeFeature()))
    expect(store.setActiveLayer).not.toHaveBeenCalled()
    expect(store.selectFeatures).toHaveBeenCalledWith('blocks', ['blk-1'])
  })

  it('is a no-op for an imported layer (imported:<id>) that is not the active imported layer', () => {
    const store = armStore(null, { activeImportedLayerId: 7 })
    makeClickHandler('imported:42')(mockEvent(makeFeature()))
    expect(store.setActiveImportedLayer).not.toHaveBeenCalled()
    expect(store.selectFeatures).not.toHaveBeenCalled()
  })

  it('selects when the imported layer clicked is already active', () => {
    const store = armStore(null, { activeImportedLayerId: 42 })
    makeClickHandler('imported:42')(mockEvent(makeFeature()))
    expect(store.selectFeatures).toHaveBeenCalledWith('imported:42', ['blk-1'])
  })

  it('is a no-op for a raster layer (raster:<id>) that is not the active raster layer', () => {
    const store = armStore(null, { activeRasterLayerId: null })
    makeClickHandler('raster:abc-123')(mockEvent(makeFeature()))
    expect(store.setActiveRasterLayer).not.toHaveBeenCalled()
    expect(store.selectFeatures).not.toHaveBeenCalled()
  })

  it('selects when the raster layer clicked is already active', () => {
    const store = armStore(null, { activeRasterLayerId: 'abc-123' })
    makeClickHandler('raster:abc-123')(mockEvent(makeFeature()))
    expect(store.selectFeatures).toHaveBeenCalledWith('raster:abc-123', ['blk-1'])
  })

  it('does NOT select on a non-active layer even while vertex-edit is armed', () => {
    const store = armStore('vertex_edit', { activeLayerId: 'compartments' })
    makeClickHandler('blocks')(mockEvent(makeFeature()))
    expect(store.setActiveLayer).not.toHaveBeenCalled()
    expect(store.selectFeatures).not.toHaveBeenCalled()
  })
})

describe('isDigitizingToolbarMode — gates `interactive` on every registry GeoJSON layer', () => {
  it('is true for the 3 pure draw-new-geometry tools', () => {
    for (const mode of ['draw_polygon', 'draw_point', 'draw_line']) {
      expect(isDigitizingToolbarMode(mode)).toBe(true)
    }
  })

  it('is false for tools that click existing features on purpose', () => {
    for (const mode of ['split', 'merge', 'move', 'vertex_edit', 'subarea_category', 'select', null]) {
      expect(isDigitizingToolbarMode(mode)).toBe(false)
    }
  })
})
