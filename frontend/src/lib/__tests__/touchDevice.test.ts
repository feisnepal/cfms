import { describe, it, expect, beforeEach } from 'vitest'
import { isTouchDevice, getTouchInfo, isCoarsePointer, resetTouchDetection } from '../touchDevice'

beforeEach(() => {
  resetTouchDetection()
})

describe('isTouchDevice', () => {
  it('returns a boolean', () => {
    expect(typeof isTouchDevice()).toBe('boolean')
  })

  it('resets cached result after resetTouchDetection', () => {
    const first = isTouchDevice()
    resetTouchDetection()
    const second = isTouchDevice()
    expect(typeof first).toBe('boolean')
    expect(typeof second).toBe('boolean')
  })

  it('caches result across calls', () => {
    const first = isTouchDevice()
    const second = isTouchDevice()
    expect(first).toBe(second)
  })
})

describe('getTouchInfo', () => {
  it('includes isTouch, maxTouchPoints, pointerType', () => {
    const info = getTouchInfo()
    expect(info).toHaveProperty('isTouch')
    expect(info).toHaveProperty('maxTouchPoints')
    expect(info).toHaveProperty('pointerType')
  })
})

describe('isCoarsePointer', () => {
  it('returns a boolean', () => {
    expect(typeof isCoarsePointer()).toBe('boolean')
  })
})
