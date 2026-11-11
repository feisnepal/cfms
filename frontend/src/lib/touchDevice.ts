let cachedResult: boolean | null = null

export function isTouchDevice(): boolean {
  if (cachedResult !== null) return cachedResult
  return detectTouch()
}

function detectTouch(): boolean {
  if (typeof window === 'undefined') return false
  return (
    'ontouchstart' in window ||
    navigator.maxTouchPoints > 0 ||
    (navigator as any).msMaxTouchPoints > 0
  )
}

export function resetTouchDetection(): void {
  cachedResult = null
}

export function getTouchInfo(): { isTouch: boolean; maxTouchPoints: number; pointerType: string | null } {
  if (typeof window === 'undefined') {
    return { isTouch: false, maxTouchPoints: 0, pointerType: null }
  }

  const maxTouchPoints = navigator.maxTouchPoints || (navigator as any).msMaxTouchPoints || 0
  const pointerType = window.matchMedia?.('(pointer: coarse)').matches ? 'coarse' : 'fine'

  return {
    isTouch: isTouchDevice(),
    maxTouchPoints,
    pointerType,
  }
}

export function isCoarsePointer(): boolean {
  if (typeof window === 'undefined') return false
  return window.matchMedia?.('(pointer: coarse)').matches || false
}
