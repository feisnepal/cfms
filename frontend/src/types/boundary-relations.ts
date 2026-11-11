/** PF-1 — relation payloads for the boundary overlap+gap preview (mirror backend schemas/boundary.py). */
import type { Geometry } from 'geojson'

export type GapShape = 'none' | 'ribbon' | 'island' | 'mixed'
export type GapSize = 'none' | 'small' | 'medium' | 'large'
/** How the system proposes to handle a detected gap — see GAP_HANDLING_PLAN.md. */
export type GapAction = 'snap' | 'absorb' | 'offer' | 'report'

export interface OverlappingForest {
  id: string
  name?: string | null
  name_np?: string | null
  overlap_ha: number
  forest_area_ha: number
  gap_ha: number
  gap_shape: GapShape
  gap_size: GapSize
  gap_width_m?: number
  gap_action?: GapAction
  adjacent: boolean
  geometry?: Geometry | null
}

export interface GapForest {
  id: string
  name?: string | null
  name_np?: string | null
  overlap_ha: number
  gap_ha: number
  gap_shape: GapShape
  gap_size: GapSize
  gap_width_m?: number
  gap_action?: GapAction
  gap_geometry?: Geometry | null
  geometry?: Geometry | null
  adjacent: boolean
}

export interface PreviewResponse {
  status: string
  orig_area_ha: number
  resolved_area_ha: number
  removed_ha: number
  removed_pct: number
  requires_confirmation: boolean
  reason?: string | null
  overlapping_forests: OverlappingForest[]
  gaps: GapForest[]
  gap_total_ha: number
  resolved_geometry?: Geometry | null
  original_geometry?: Geometry | null
  warnings: string[]
}

export interface ConfirmBoundaryPayload {
  resolved_geometry: Geometry
  original_geometry: Geometry
  forest_name: string
  forest_name_np?: string
  mode?: string
  forest_group_id?: number | null
  method: string
}

export interface ConfirmBoundaryResponse {
  id: string
  boundary_status: string
  boundary_geom_updated_at?: string | null
  audit_id: number
}

export interface IncludeGapRow {
  forest_id: string
  gap_ha: number
}

export interface IncludeGapPayload {
  geometry: Geometry
  original_geometry: Geometry
  forest_name: string
  forest_name_np?: string
  method: string
  calculation_id?: string | null
  forest_id?: string | null
  gaps: IncludeGapRow[]
}

export interface IncludeGapResponse {
  id: string
  boundary_status: string
  boundary_geom_updated_at?: string | null
  audit_id: number
  gap_included_ha: number
}

export interface NearbyRelation {
  id: string
  name: string
  boundary_status: string
  geometry?: Geometry | null
  area_ha: number
  overlap_ha: number
  gap_ha: number
  gap_shape: GapShape
  gap_size: GapSize
  adjacent: boolean
}

export interface NearbyResponse {
  forests?: NearbyRelation[]
  total?: number
  [k: string]: unknown
}

/** Gap overlay style for the map (amber hatched — an "offer"/"report" gap). */
export const GAP_STYLE = {
  color: '#F59E0B',
  dashArray: '6 3',
  fillColor: '#F59E0B',
  fillOpacity: 0.15,
} as const

/** A gap that will be absorbed into the new forest — solid green. */
export const GAP_ABSORB_STYLE = {
  color: '#16A34A',
  dashArray: '4 2',
  fillColor: '#16A34A',
  fillOpacity: 0.25,
} as const
