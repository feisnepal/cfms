import { useCallback } from 'react'
import type { GeoJSON } from 'geojson'
import type { Feature, Polygon, Position } from 'geojson'
import * as turf from '@turf/turf'

/** Default snap tolerance (m) when a caller doesn't pass its own. */
export const DEFAULT_SNAP_TOLERANCE_M = 5

/**
 * `turf.nearestPointOnLine` requires a LineString/MultiLineString; fed a
 * Polygon it does not throw, it silently returns `[null, null]` (verified
 * against the installed turf build), which then compares as `NaN` and never
 * snaps. "Nearby features" are routinely forest boundary Polygons (a
 * neighbour's outline), so every caller would otherwise silently stop
 * snapping the moment it passed one. Convert Polygon/MultiPolygon geometry
 * to its boundary line first; anything already line-shaped passes through.
 */
function asLineGeometry(geometry: GeoJSON.Geometry): GeoJSON.Geometry | null {
  if (geometry.type === 'Polygon' || geometry.type === 'MultiPolygon') {
    try {
      // A Polygon input always yields a single Feature; only a MultiPolygon
      // with disjoint parts can yield a FeatureCollection.
      const result = turf.polygonToLine(geometry as any)
      return result.type === 'Feature' ? (result.geometry as unknown as GeoJSON.Geometry) : null
    } catch {
      return null
    }
  }
  if (geometry.type === 'LineString' || geometry.type === 'MultiLineString') {
    return geometry
  }
  return null
}

/**
 * @param toleranceM Snap tolerance in metres. Defaults to
 * {@link DEFAULT_SNAP_TOLERANCE_M}. Callers that expose a user-adjustable
 * tolerance (e.g. the boundary preview's inline vertex editor) pass their own
 * live value here instead of relying on the default.
 */
export function useDigitizeSnap(toleranceM: number = DEFAULT_SNAP_TOLERANCE_M) {
  const snapVertex = useCallback((
    latlng: { lat: number; lng: number },
    nearbyFeatures: GeoJSON.Feature[],
  ): { lat: number; lng: number } => {
    const pt = turf.point([latlng.lng, latlng.lat])

    let minDist = Infinity
    let snapPt: Position | null = null

    for (const feature of nearbyFeatures) {
      if (!feature.geometry) continue
      const lineGeom = asLineGeometry(feature.geometry)
      if (!lineGeom) continue
      const snapped = turf.nearestPointOnLine(
        lineGeom as any,
        pt,
      )
      const dist = turf.distance(pt, snapped, { units: 'meters' })
      if (dist < minDist && dist <= toleranceM) {
        minDist = dist
        snapPt = snapped.geometry.coordinates
      }
    }

    if (snapPt) {
      return { lat: snapPt[1], lng: snapPt[0] }
    }
    return latlng
  }, [toleranceM])

  return { snapVertex }
}
