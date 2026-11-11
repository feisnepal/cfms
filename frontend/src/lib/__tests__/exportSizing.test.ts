import { describe, it, expect } from 'vitest'
import { fitA5Size, A5_150DPI_WIDTH, A5_150DPI_HEIGHT } from '../exportSizing'

describe('fitA5Size', () => {
  it('does not upscale a canvas smaller than A5', () => {
    expect(fitA5Size(500, 400)).toEqual({ width: 500, height: 400 })
  })

  it('keeps exact A5 bounds untouched', () => {
    expect(fitA5Size(A5_150DPI_WIDTH, A5_150DPI_HEIGHT)).toEqual({ width: A5_150DPI_WIDTH, height: A5_150DPI_HEIGHT })
  })

  it('downscales a wide landscape canvas to fit within A5', () => {
    const r = fitA5Size(2604, 1912)
    expect(r.width).toBeLessThanOrEqual(A5_150DPI_WIDTH)
    expect(r.height).toBeLessThanOrEqual(A5_150DPI_HEIGHT)
    expect(Math.abs(r.width / r.height - 2604 / 1912)).toBeLessThan(0.01)
  })

  it('downscales a tall portrait canvas to fit within A5', () => {
    const r = fitA5Size(1200, 2400)
    expect(r.width).toBeLessThanOrEqual(A5_150DPI_WIDTH)
    expect(r.height).toBeLessThanOrEqual(A5_150DPI_HEIGHT)
    expect(Math.abs(r.width / r.height - 1200 / 2400)).toBeLessThan(0.01)
  })

  it('never produces zero-size output', () => {
    expect(fitA5Size(1, 1)).toEqual({ width: 1, height: 1 })
  })
})
