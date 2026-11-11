/**
 * Tests for browserCache IndexedDB wrapper.
 *
 * These tests work with the memory fallback when IndexedDB is unavailable
 * (jsdom does not implement indexedDB), so no fake-indexeddb package is needed.
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { browserCache } from '../browserCache'

beforeEach(async () => {
  await browserCache.clearAll()
})

describe('browserCache.setMap + getMap', () => {
  it('roundtrips map data', async () => {
    const calcId = 'calc-1'
    const geoData = { type: 'FeatureCollection', features: [] }
    await browserCache.setMap(calcId, 'boundary', geoData)
    const result = await browserCache.getMap(calcId, 'boundary')
    expect(result).toEqual(geoData)
  })

  it('returns null for missing key', async () => {
    const result = await browserCache.getMap('calc-999', 'nonexistent')
    expect(result).toBeNull()
  })
})

describe('browserCache.clearMaps', () => {
  it('removes only the specified calcId', async () => {
    await browserCache.setMap('calc-1', 'layerA', { a: 1 })
    await browserCache.setMap('calc-2', 'layerB', { b: 2 })

    await browserCache.clearMaps('calc-1')

    expect(await browserCache.getMap('calc-1', 'layerA')).toBeNull()
    expect(await browserCache.getMap('calc-2', 'layerB')).toEqual({ b: 2 })
  })
})

describe('browserCache.getStats', () => {
  it('returns correct counts and backend type', async () => {
    await browserCache.setMap('calc-1', 'layerA', { a: 1 })
    await browserCache.setMap('calc-1', 'layerB', { b: 2 })
    await browserCache.setChart('calc-1', 'pieChart', { labels: ['a'] })
    await browserCache.setAnalysis('calc-1', 'analysis', { result: 42 })

    const stats = await browserCache.getStats()
    expect(stats.maps).toBeGreaterThanOrEqual(2)
    expect(stats.charts).toBeGreaterThanOrEqual(1)
    expect(stats.analysis).toBeGreaterThanOrEqual(1)
    // backend may be 'indexeddb' or 'memory' depending on environment
    expect(['indexeddb', 'memory']).toContain(stats.backend)
  })
})

describe('browserCache digitizeDrafts (Gap 9.1)', () => {
  it('roundtrips a digitize draft buffer per calcId:layerId', async () => {
    const features = [{ type: 'Feature', geometry: null, properties: { featureId: 'f1' } }]
    await browserCache.setDigitizeDraft('calc-1', 7, features)
    expect(await browserCache.getDigitizeDraft('calc-1', 7)).toEqual(features)
    expect(await browserCache.getDigitizeDraft('calc-1', 999)).toBeNull()
  })

  it('keeps other calc drafts when clearing one calcId', async () => {
    await browserCache.setDigitizeDraft('calc-1', 7, [{ type: 'Feature', geometry: null, properties: {} }])
    await browserCache.setDigitizeDraft('calc-2', 8, [{ type: 'Feature', geometry: null, properties: {} }])

    await browserCache.clearDigitizeDraft('calc-1')

    expect(await browserCache.getDigitizeDraft('calc-1', 7)).toBeNull()
    expect(await browserCache.getDigitizeDraft('calc-2', 8)).not.toBeNull()
  })
})
