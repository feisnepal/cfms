import { useState, useEffect, useCallback } from 'react'
import type { GeoJSON } from 'geojson'

export interface NearbyForest {
  id: string
  name: string
  boundary_status: 'draft' | 'validated' | 'approved' | 'disputed'
  geometry: GeoJSON.Geometry | null
  area_ha: number
}

const STATUS_STYLES: Record<string, { color: string; weight: number; dashArray: string | null; fillColor: string; fillOpacity: number }> = {
  draft: { color: '#FFD700', weight: 2, dashArray: '8,6', fillColor: '#FFD700', fillOpacity: 0.25 },
  validated: { color: '#228B22', weight: 2, dashArray: null, fillColor: '#228B22', fillOpacity: 0.2 },
  approved: { color: '#1E90FF', weight: 2.5, dashArray: null, fillColor: '#1E90FF', fillOpacity: 0.2 },
  disputed: { color: '#FF4444', weight: 2, dashArray: '4,4', fillColor: '#FF4444', fillOpacity: 0.2 },
}

export function getBoundaryStatusStyle(status: string) {
  return STATUS_STYLES[status] || STATUS_STYLES.draft
}

export const BOUNDARY_STATUS_STYLES = STATUS_STYLES

export function useNearbyForests(forestId: string | null) {
  const [forests, setForests] = useState<NearbyForest[]>([])
  const [loading, setLoading] = useState(false)

  const fetchNearby = useCallback(async () => {
    if (!forestId) return
    setLoading(true)
    try {
      const resp = await fetch(`/api/forests/${forestId}/nearby`)
      const data = await resp.json()
      setForests(data?.forests || [])
    } catch {
      setForests([])
    } finally {
      setLoading(false)
    }
  }, [forestId])

  useEffect(() => {
    fetchNearby()
  }, [fetchNearby])

  return { nearbyForests: forests, loading, refresh: fetchNearby }
}
