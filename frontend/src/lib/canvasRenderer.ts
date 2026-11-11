const CANVAS_THRESHOLD = 500

export type RenderStrategy = 'svg' | 'canvas'

export interface RenderStrategyResult {
  strategy: RenderStrategy
  reason: string
}

export interface CanvasRendererOpts {
  preferCanvas: boolean
  renderer: string
}

export function determineRenderStrategy(featureCount: number): RenderStrategyResult {
  if (featureCount >= CANVAS_THRESHOLD) {
    return { strategy: 'canvas', reason: `Feature count ${featureCount} exceeds threshold ${CANVAS_THRESHOLD}` }
  }
  return { strategy: 'svg', reason: `Feature count ${featureCount} below threshold ${CANVAS_THRESHOLD}` }
}

export function getCanvasRendererOptions(): CanvasRendererOpts {
  return {
    renderer: 'canvas',
    preferCanvas: true,
  }
}

export function shouldUseCanvas(featureCount: number): boolean {
  return featureCount >= CANVAS_THRESHOLD
}
