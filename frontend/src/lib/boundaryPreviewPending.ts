/**
 * boundaryPreviewPending.ts — shared helpers to detect a server "provisional"
 * boundary overlap/gap response and surface it through the boundary preview.
 *
 * The four boundary save endpoints (PUT /boundary, convert-to-builtin,
 * POST /forests/upload, POST /forests/create-from-map) return a provisional
 * body `{ needs_overlap_review: true, provisional: true, preview_geometry,
 * overlapping_forests, gaps, ... }` WITHOUT writing whenever the proposed
 * boundary overlaps or gaps an adjoining forest and `confirmed` was not set.
 * (A provisional can also arrive as the error-body on a 409/400.)
 */
import type { Geometry } from 'geojson'

export type ProvisionalBody = {
  needs_overlap_review?: boolean
  provisional?: boolean
  preview_geometry?: Geometry
  overlapping_forests?: unknown[]
  gaps?: unknown[]
  [k: string]: unknown
}

/** Pull a provisional body out of an axios/any error if it carries one. */
export function provisionalFromError(err: unknown): ProvisionalBody | null {
  const data = (err as { response?: { data?: unknown } })?.response?.data
  if (data && typeof data === 'object') {
    const d = data as ProvisionalBody
    if (d.needs_overlap_review === true) return d
  }
  return null
}

/**
 * Given a save-endpoint result (or error), return the boundary "preview
 * geometry" + whether review is needed, or null when the save went through.
 * `geometryFromResponse` lets callers decide what geometry to show (server's
 * `preview_geometry` preferred, else the caller's own proposed geometry).
 */
export function needsBoundaryReview(
  resp: unknown,
  fallbackGeometry: Geometry,
  provisionalBody?: ProvisionalBody | null,
): { review: boolean; geometry: Geometry } {
  const body = provisionalBody ?? (resp as ProvisionalBody | undefined) ?? null
  const review = Boolean(body?.needs_overlap_review === true)
  if (!review) return { review: false, geometry: fallbackGeometry }
  const geom = (body?.preview_geometry as Geometry | undefined) ?? fallbackGeometry
  return { review: true, geometry: geom }
}
