import { useCallback, useState } from 'react'
import type { GeoJSON } from 'geojson'
import { snapToBlock, type SnapToBlockResult } from '../lib/snapToBlock'

export interface SnapConfig {
  enabled: boolean
  toleranceMeters?: number
}

export function useSnapToBlock(blockFeatures: GeoJSON.Feature[] | null | undefined) {
  const [lastResult, setLastResult] = useState<SnapToBlockResult | null>(null)

  const applySnap = useCallback(
    (geometry: GeoJSON.Geometry, config?: SnapConfig): GeoJSON.Geometry => {
      const result = snapToBlock({
        geometry,
        blockFeatures,
        tolerance: config?.toleranceMeters ?? 5,
        enabled: config?.enabled ?? true,
      })
      setLastResult(result)
      return result.geometry
    },
    [blockFeatures],
  )

  const applySnapWithResult = useCallback(
    (geometry: GeoJSON.Geometry, config?: SnapConfig): SnapToBlockResult => {
      const result = snapToBlock({
        geometry,
        blockFeatures,
        tolerance: config?.toleranceMeters ?? 5,
        enabled: config?.enabled ?? true,
      })
      setLastResult(result)
      return result
    },
    [blockFeatures],
  )

  return { applySnap, applySnapWithResult, lastSnapResult: lastResult }
}
