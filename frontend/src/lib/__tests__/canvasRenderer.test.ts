import { describe, it, expect } from 'vitest'
import { determineRenderStrategy, shouldUseCanvas, getCanvasRendererOptions } from '../canvasRenderer'

describe('determineRenderStrategy', () => {
  it('returns canvas for 500+ features', () => {
    expect(determineRenderStrategy(500).strategy).toBe('canvas')
    expect(determineRenderStrategy(1000).strategy).toBe('canvas')
  })

  it('returns svg for fewer than 500 features', () => {
    expect(determineRenderStrategy(0).strategy).toBe('svg')
    expect(determineRenderStrategy(499).strategy).toBe('svg')
  })

  it('includes reason in result', () => {
    const result = determineRenderStrategy(600)
    expect(result.reason).toContain('600')
  })
})

describe('shouldUseCanvas', () => {
  it('returns true at threshold', () => {
    expect(shouldUseCanvas(500)).toBe(true)
    expect(shouldUseCanvas(501)).toBe(true)
  })

  it('returns false below threshold', () => {
    expect(shouldUseCanvas(0)).toBe(false)
    expect(shouldUseCanvas(499)).toBe(false)
  })
})

describe('getCanvasRendererOptions', () => {
  it('returns preferCanvas true', () => {
    const opts = getCanvasRendererOptions()
    expect(opts.preferCanvas).toBe(true)
    expect(opts.renderer).toBe('canvas')
  })
})
