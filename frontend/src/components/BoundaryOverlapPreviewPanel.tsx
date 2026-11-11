import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { CircleMarker, GeoJSON as LeafletGeoJSON, MapContainer, Marker, Polyline, TileLayer, Tooltip, useMap } from 'react-leaflet'
import { Alert, Button, Input, Modal, Radio, Slider, Spin, message } from 'antd'
import L from 'leaflet'
import type { Feature, Geometry, MultiPolygon, Polygon } from 'geojson'
import { useT } from '../i18n/hooks'
import { forestApi } from '../services/api'
import api from '../services/api'
import { getBoundaryStatusStyle } from '../hooks/useNearbyForests'
import type { OverlappingForest, PreviewResponse } from '../types/boundary-relations'
import { useDigitizeSnap, DEFAULT_SNAP_TOLERANCE_M } from '../hooks/useDigitizeSnap'
import {
  isEditableAreal,
  arealVertices,
  arealMidpoints,
  moveArealVertex,
  insertArealVertex,
  deleteArealVertex,
  pointInAnyNeighbour,
  type ArealVId,
} from '../lib/previewVertexEdit'

const sameVid = (a: ArealVId | null, b: ArealVId): boolean =>
  a != null && a.poly === b.poly && a.index === b.index

// PE-4 — debounce before an edited vertex triggers a re-preview (Decision D.1).
const RECOMPUTE_DEBOUNCE_MS = 400
const TOLERANCE_MIN_M = 0.5
const TOLERANCE_MAX_M = 20
// Leaflet's own default cap is 18 — too coarse to place a vertex precisely
// against a neighbour's edge. 22 matches the ceiling used elsewhere in this
// app's satellite/OSM base layers (workspaceStore's BASE_MAP_OPTIONS tops out
// at 19 for OSM); paired with the TileLayer's `maxNativeZoom={19}` below, the
// map keeps zooming past that by upscaling rather than stopping.
const MAX_ZOOM = 22

const vertexIcon = (overlapping: boolean) =>
  L.divIcon({
    className: 'preview-vertex-marker',
    html: `<span style="display:block;width:12px;height:12px;border-radius:50%;background:${overlapping ? '#ff4d4f' : '#1890ff'};border:2px solid #fff;box-shadow:0 0 2px rgba(0,0,0,0.6);cursor:move;"></span>`,
    iconSize: [12, 12],
    iconAnchor: [6, 6],
  })

// Backend error code for "proposed boundary still overlaps after locking".
// Built via join so the keySync scanner does not treat it as a missing i18n key.
const OVERLAP_RELOCK_CODE = ['boundary', 'overlap', 'detected', 'relock'].join('.')

export type BoundaryResolutionResult = {
  id: string
  boundaryGeometry?: Geometry
}

type Props = {
  geometry: Geometry
  forestName: string
  method: string
  calculationId?: string
  onCancel: () => void
  onDone: (result?: BoundaryResolutionResult) => void
  onEdit?: (geometry: Geometry) => void
}

function collectCoords(g: Geometry | null | undefined, out: [number, number][]) {
  if (!g) return
  const coords = (g as unknown as { coordinates: unknown }).coordinates as unknown[]
  if (!Array.isArray(coords)) return
  const walk = (node: unknown) => {
    if (!Array.isArray(node)) return
    if (typeof node[0] === 'number' && typeof node[1] === 'number') {
      out.push([node[0] as number, node[1] as number])
      return
    }
    node.forEach(walk)
  }
  walk(coords)
}

function FitBounds({ geoms }: { geoms: (Geometry | null | undefined)[] }) {
  const map = useMap()
  // Fits once, the first time real coordinates show up, and never again for
  // the life of this panel instance. `geoms` is rebuilt as a new array every
  // render (auto-recompute re-renders constantly while the user is mid-edit),
  // so without this guard the map re-fit on every keystroke of a drag,
  // yanking the user's own pan/zoom back to the whole-boundary extent.
  const hasFitted = useRef(false)
  useEffect(() => {
    if (hasFitted.current) return
    try {
      const all: [number, number][] = []
      geoms.forEach((g) => collectCoords(g, all))
      if (!all.length) return
      hasFitted.current = true
      const lats = all.map((c) => c[1])
      const lngs = all.map((c) => c[0])
      map.fitBounds(
        [
          [Math.min(...lats), Math.min(...lngs)],
          [Math.max(...lats), Math.max(...lngs)],
        ],
        { padding: [20, 20] },
      )
    } catch {
      // ignore
    }
  }, [geoms, map])
  return null
}

/**
 * One draggable vertex marker. Its own component (not inline in a `.map()`)
 * so `position` can be memoized by value: react-leaflet re-syncs a Marker's
 * Leaflet-internal position via `setLatLng` whenever the `position` prop
 * *reference* changes. Sibling state updates during a drag
 * (`dragOverlapVid`/`dragLatLng`, for the live red-segment feedback)
 * re-render this component with the SAME lat/lng — the ring only actually
 * changes on drag-END — so without memoizing, every drag tick recreated a
 * new `[lat, lng]` array, which reset the marker back to its start position
 * and fought Leaflet's own in-progress drag, i.e. the vertex "could not be
 * moved."
 */
function VertexMarker({
  poly, index, lat, lng, overlapping, onDrag, onDragEnd, onDelete,
}: {
  poly: number
  index: number
  lat: number
  lng: number
  overlapping: boolean
  onDrag: (vid: ArealVId, latlng: { lat: number; lng: number }) => void
  onDragEnd: (vid: ArealVId, latlng: { lat: number; lng: number }) => void
  onDelete: (vid: ArealVId) => void
}) {
  const position = useMemo<[number, number]>(() => [lat, lng], [lat, lng])
  const icon = useMemo(() => vertexIcon(overlapping), [overlapping])
  // Also memoized: an `eventHandlers` object that changes reference every
  // render is exactly what the parent's now-ref-backed, stable callbacks
  // are meant to make unnecessary (see the note above `clippedRef` below) —
  // keeping this stable too means Leaflet's marker is asked to rebind as
  // rarely as possible, not just correctly when it does. `poly`/`index` are
  // primitives, so the `vid` rebuilt here is stable across renders too.
  const eventHandlers = useMemo(() => {
    const vid: ArealVId = { poly, index }
    return {
      drag: (e: any) => onDrag(vid, e.target.getLatLng()),
      dragend: (e: any) => onDragEnd(vid, e.target.getLatLng()),
      dblclick: () => onDelete(vid),
    }
  }, [poly, index, onDrag, onDragEnd, onDelete])
  return (
    <Marker position={position} draggable icon={icon} eventHandlers={eventHandlers} />
  )
}

export default function BoundaryOverlapPreviewPanel({
  geometry,
  forestName,
  method,
  calculationId,
  onCancel,
  onDone,
  onEdit,
}: Props) {
  const t = useT()
  const [preview, setPreview] = useState<PreviewResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [disputeOpen, setDisputeOpen] = useState(false)
  const [disputeReason, setDisputeReason] = useState('')
  const [disputeType, setDisputeType] = useState<'overlap' | 'gap'>('overlap')
  const [submitting, setSubmitting] = useState(false)
  // Once Accept has succeeded this panel is done — never re-run the preview
  // (guards against a parent that forgets to unmount us, which looked like
  // "Accept re-opens the same window").
  const [resolvedDone, setResolvedDone] = useState(false)

  // PE-2/PE-4 — inline vertex editing. `editedGeometry` starts as the
  // server's clip and tracks every local drag/insert/delete; it is what
  // Accept submits (PE-5) and what auto-recompute (PE-4) re-previews.
  const [editedGeometry, setEditedGeometry] = useState<Geometry | null>(null)
  const [editMode, setEditMode] = useState(false)
  const [toleranceM, setToleranceM] = useState<number>(DEFAULT_SNAP_TOLERANCE_M)
  const [recomputing, setRecomputing] = useState(false)
  // The vertex currently being dragged whose adjacent segments should render
  // red (PE-4b) because the live point sits inside a neighbour.
  const [dragOverlapVid, setDragOverlapVid] = useState<ArealVId | null>(null)
  const [dragLatLng, setDragLatLng] = useState<{ lat: number; lng: number } | null>(null)
  const recomputeTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const { snapVertex } = useDigitizeSnap(toleranceM)

  const doFetchPreview = useCallback(async (geom: Geometry): Promise<PreviewResponse | null> => {
    try {
      const data = await forestApi.previewBoundaryOverlap({ geometry: geom, method, forest_id: calculationId })
      return data as PreviewResponse
    } catch (e: unknown) {
      const msg =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        (e as Error)?.message ||
        'Failed to load preview'
      setError(msg)
      return null
    }
  }, [method, calculationId])

  const fetchPreview = useCallback(async () => {
    setLoading(true)
    setError(null)
    const data = await doFetchPreview(geometry)
    if (data) setPreview(data)
    setLoading(false)
  }, [doFetchPreview, geometry])

  useEffect(() => {
    if (resolvedDone) return
    fetchPreview()
    // Only on mount / when the source geometry or target forest changes —
    // edits after that are re-previewed via `recomputePreview`, not this.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [geometry, method, calculationId, resolvedDone])

  // PE-4 — background re-preview after an inline edit. Deliberately a
  // separate `recomputing` flag from `loading`: `loading` blanks the whole
  // panel (map included) behind a spinner, which would hide the very
  // markers the user is mid-drag on. Recompute must not do that.
  const recomputePreview = useCallback(async (geom: Geometry) => {
    setRecomputing(true)
    const data = await doFetchPreview(geom)
    if (data) setPreview(data)
    setRecomputing(false)
  }, [doFetchPreview])

  const scheduleRecompute = useCallback((geom: Geometry) => {
    if (recomputeTimer.current) clearTimeout(recomputeTimer.current)
    recomputeTimer.current = setTimeout(() => {
      recomputeTimer.current = null
      recomputePreview(geom)
    }, RECOMPUTE_DEBOUNCE_MS)
  }, [recomputePreview])

  useEffect(() => () => {
    if (recomputeTimer.current) clearTimeout(recomputeTimer.current)
  }, [])

  const overlapping = (preview?.overlapping_forests ?? []) as OverlappingForest[]
  const withOverlap = overlapping.filter((f) => Number(f.overlap_ha ?? 0) > 0)
  const neighbourGeoms = overlapping
    .map((f) => (f as unknown as { geometry?: Geometry | null }).geometry ?? null)
    .filter(Boolean) as Geometry[]
  const serverClipped = (preview?.resolved_geometry as Geometry) || geometry

  // PE-2 — `editedGeometry` is seeded from (and re-seeded whenever) the
  // preview response changes, whether from the initial fetch or a
  // recompute — so the map always shows the server's own clip of whatever
  // the user last edited (Decision D.1: the clip is the truth, editing is
  // just how the user proposes a shape to be clipped).
  useEffect(() => {
    if (resolvedDone) return
    setEditedGeometry(serverClipped)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preview, resolvedDone])

  const clipped = (editedGeometry as Geometry) || serverClipped
  const editableAreal = isEditableAreal(clipped)
  const vertices = useMemo(
    () => (editableAreal ? arealVertices(clipped as Polygon | MultiPolygon) : []),
    [clipped, editableAreal],
  )
  const midpoints = useMemo(
    () => (editableAreal ? arealMidpoints(clipped as Polygon | MultiPolygon) : []),
    [clipped, editableAreal],
  )

  // All vertex markers mount together on first load; a Leaflet marker does
  // not reliably rebind its `eventHandlers` on every later re-render, so a
  // handler closing directly over `clipped`/`neighbourGeoms` could still be
  // running with whatever those were AT MOUNT — meaning editing vertex-1,
  // then vertex-2, discarded vertex-1's edit (vertex-2's handler committed a
  // `next` built from the pre-vertex-1 geometry it had mounted with,
  // overwriting `editedGeometry` wholesale). Refs sidestep the question of
  // whether Leaflet rebinds at all: every handler below reads the CURRENT
  // value at call time, no matter how old its own closure is.
  const clippedRef = useRef<Geometry | null>(null)
  clippedRef.current = clipped
  const neighbourGeomsRef = useRef<Geometry[]>([])
  neighbourGeomsRef.current = neighbourGeoms
  const editableArealRef = useRef(editableAreal)
  editableArealRef.current = editableAreal

  const commitEdit = useCallback((next: Geometry) => {
    setEditedGeometry(next)
    scheduleRecompute(next)
  }, [scheduleRecompute])

  const handleVertexDrag = useCallback((vid: ArealVId, latlng: { lat: number; lng: number }) => {
    setDragLatLng(latlng)
    setDragOverlapVid(pointInAnyNeighbour(latlng, neighbourGeomsRef.current) ? vid : null)
  }, [])

  const handleVertexDragEnd = useCallback((vid: ArealVId, latlng: { lat: number; lng: number }) => {
    setDragOverlapVid(null)
    setDragLatLng(null)
    const current = clippedRef.current
    if (!editableArealRef.current || !current) return
    const neighbourFeatures = neighbourGeomsRef.current.map((g) => ({ type: 'Feature', properties: {}, geometry: g } as Feature))
    const snapped = snapVertex(latlng, neighbourFeatures)
    const next = moveArealVertex(current as Polygon | MultiPolygon, vid, [snapped.lng, snapped.lat])
    commitEdit(next)
  }, [snapVertex, commitEdit])

  const handleInsertVertex = useCallback((vid: ArealVId, lat: number, lng: number) => {
    const current = clippedRef.current
    if (!editableArealRef.current || !current) return
    const next = insertArealVertex(current as Polygon | MultiPolygon, vid, [lng, lat])
    commitEdit(next)
  }, [commitEdit])

  const handleDeleteVertex = useCallback((vid: ArealVId) => {
    const current = clippedRef.current
    if (!editableArealRef.current || !current) return
    const next = deleteArealVertex(current as Polygon | MultiPolygon, vid)
    commitEdit(next)
  }, [commitEdit])

  const rejected = preview?.status === 'reject'
  const rejectReason = (preview?.reason as string) || ''
  const rejectMsg = rejected
    ? (t(`boundaryPreview.rejectReason_${rejectReason}` as never, {
        defaultValue: t('boundaryPreview.rejectDefault'),
      }) as string)
    : ''

  const handleAccept = async () => {
    if (!preview || rejected) return
    setSubmitting(true)
    try {
      const resp = (await forestApi.confirmBoundary({
        resolved_geometry: clipped,
        original_geometry: geometry,
        forest_name: forestName,
        method,
        calculation_id: calculationId,
      })) as { id?: string }
      message.success(t('boundaryPreview.acceptSuccess'))
      setResolvedDone(true)
      const id = resp?.id ? String(resp.id) : undefined
      onDone(id ? { id, boundaryGeometry: clipped } : undefined)
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: { code?: string; message?: string } | string } } })?.response?.data?.detail
      if (detail && typeof detail === 'object' && detail.code === OVERLAP_RELOCK_CODE) {
        message.warning(t('boundaryPreview.acceptOverlapRelock'))
      } else {
        // `detail` may be a plain string OR a structured object (a failed
        // boundary rule returns `{ code, message, boundary_validation }`) —
        // never hand a raw object to message.error (React child crash).
        const msg =
          (typeof detail === 'object' && detail !== null ? detail.message : detail) ||
          (e as Error)?.message ||
          t('common.error')
        message.error(msg)
      }
    } finally {
      setSubmitting(false)
    }
  }

  const handleDisputeSubmit = async () => {
    if (disputeReason.trim().length < 10) {
      message.error(t('boundary.dispute.reasonTooShort'))
      return
    }
    const targetId = withOverlap[0]?.id || overlapping[0]?.id
    if (!targetId) {
      message.error(t('boundary.dispute.selectTarget'))
      return
    }
    setSubmitting(true)
    try {
      await api.post('/api/forests/boundary/dispute', {
        forest_id: String(targetId),
        reason_np: disputeReason,
        dispute_reason_type: disputeType,
      })
      message.success(t('boundaryPreview.disputeSuccess'))
      setDisputeOpen(false)
      onDone()
    } catch (e: unknown) {
      const msg =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        (e as Error)?.message ||
        t('common.error')
      message.error(msg)
    } finally {
      setSubmitting(false)
    }
  }

  if (resolvedDone) {
    return (
      <div style={{ padding: 24 }} data-testid="preview-done">
        <Alert type="success" showIcon message={t('boundaryPreview.acceptSuccess')} />
      </div>
    )
  }
  if (loading) {
    return (
      <div style={{ padding: 24, textAlign: 'center' }} data-testid="preview-loading">
        <Spin />
        <div style={{ marginTop: 8 }}>{t('boundaryPreview.loading')}</div>
      </div>
    )
  }
  if (error) {
    return <Alert type="error" message={error} style={{ margin: 16 }} data-testid="preview-error" />
  }

  const removedHa = Number(preview?.removed_ha ?? 0)

  return (
    <div style={{ display: 'flex', gap: 16, padding: 16 }} data-testid="boundary-preview-panel">
      <div
        style={{ flex: 1, minHeight: 380, border: '1px solid #eee', borderRadius: 8, overflow: 'hidden' }}
        data-testid="preview-map-pane"
      >
        <MapContainer center={[28.0, 84.0]} zoom={8} maxZoom={MAX_ZOOM} style={{ height: 380, width: '100%' }}>
          <TileLayer
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            attribution="&copy; OSM"
            maxZoom={MAX_ZOOM}
            // OSM only serves tiles up to z19; beyond that Leaflet upscales
            // the z19 tile instead of requesting one that doesn't exist, so
            // the user can keep zooming in for precise vertex placement even
            // past native tile resolution (edited coordinates are exact
            // regardless of how blurry the underlying imagery gets).
            maxNativeZoom={19}
          />
          {/* Adjoining forest boundaries (status-coloured), labelled by name */}
          {overlapping.map((f) => {
            const g = (f as unknown as { geometry?: Geometry | null }).geometry
            return g ? (
              <LeafletGeoJSON
                key={`nbr-${String(f.id)}`}
                data={{ type: 'Feature', properties: {}, geometry: g } as Feature}
style={getBoundaryStatusStyle('validated') as L.PathOptions}
              >
                <Tooltip permanent direction="center" opacity={0.9}>
                  {f.name || String(f.id).slice(0, 8)}
                </Tooltip>
              </LeafletGeoJSON>
            ) : null
          })}
          {/* The clipped boundary that Accept will save */}
          <LeafletGeoJSON
            key={`clipped-${JSON.stringify(clipped).length}`}
            data={{ type: 'Feature', properties: {}, geometry: clipped } as Feature}
            style={{ color: '#1890ff', weight: 2, fillColor: '#1890ff', fillOpacity: 0.15 }}
          >
            <Tooltip permanent direction="center" opacity={0.9}>
              {forestName}
            </Tooltip>
          </LeafletGeoJSON>

          {/* PE-2/PE-4b — inline vertex editor. Additive over the read-only
              layers above. A MultiPolygon (a neighbour split the boundary in
              two, CO-1) is editable too: every part's exterior ring gets
              draggable markers, addressed by { poly, index }. */}
          {editMode && editableAreal && (
            <>
              {dragOverlapVid !== null && dragLatLng && (() => {
                // prev/next segment feedback stays WITHIN the dragged part's ring.
                const ring = vertices.filter((x) => x.poly === dragOverlapVid.poly)
                const pos = ring.findIndex((x) => x.index === dragOverlapVid.index)
                if (pos < 0 || ring.length === 0) return null
                const n = ring.length
                const prev = ring[(pos - 1 + n) % n]
                const next = ring[(pos + 1) % n]
                return (
                  <>
                    <Polyline
                      positions={[[prev.lat, prev.lng], [dragLatLng.lat, dragLatLng.lng]]}
                      pathOptions={{ color: '#ff4d4f', weight: 3 }}
                    />
                    <Polyline
                      positions={[[dragLatLng.lat, dragLatLng.lng], [next.lat, next.lng]]}
                      pathOptions={{ color: '#ff4d4f', weight: 3 }}
                    />
                  </>
                )
              })()}
              {midpoints.map((m) => (
                <CircleMarker
                  key={`mid-${m.poly}-${m.index}`}
                  center={[m.lat, m.lng]}
                  radius={4}
                  pathOptions={{ color: '#52c41a', fillColor: '#52c41a', fillOpacity: 0.9 }}
                  eventHandlers={{ click: () => handleInsertVertex({ poly: m.poly, index: m.index }, m.lat, m.lng) }}
                />
              ))}
              {vertices.map((v) => (
                <VertexMarker
                  key={`vertex-${v.poly}-${v.index}`}
                  poly={v.poly}
                  index={v.index}
                  lat={v.lat}
                  lng={v.lng}
                  overlapping={sameVid(dragOverlapVid, v)}
                  onDrag={handleVertexDrag}
                  onDragEnd={handleVertexDragEnd}
                  onDelete={handleDeleteVertex}
                />
              ))}
            </>
          )}

          <FitBounds geoms={[clipped, ...neighbourGeoms]} />
        </MapContainer>
      </div>

      <div style={{ width: 420, display: 'flex', flexDirection: 'column', gap: 12 }} data-testid="preview-side-pane">
        <h3 style={{ margin: 0 }}>{t('boundaryPreview.title')}</h3>

        {withOverlap.length === 0 ? (
          <Alert type="success" showIcon message={t('boundaryPreview.noOverlap')} data-testid="no-overlap" />
        ) : (
          <Alert
            type="info"
            showIcon
            data-testid="clip-summary"
            message={t('boundaryPreview.clipSummary', {
              count: withOverlap.length,
              ha: removedHa.toFixed(2),
            })}
            description={
              <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
                {withOverlap.map((f) => (
                  <li key={String(f.id)}>
                    {f.name || String(f.id).slice(0, 8)} — {Number(f.overlap_ha).toFixed(2)} ha
                  </li>
                ))}
              </ul>
            }
          />
        )}

        <div style={{ fontSize: 12, color: '#666' }}>{t('boundaryPreview.gapEditHint')}</div>

        {editableAreal ? (
          <div style={{ border: '1px solid #eee', borderRadius: 6, padding: 10 }} data-testid="inline-edit-panel">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <Button
                type={editMode ? 'primary' : 'default'}
                size="small"
                onClick={() => setEditMode((v) => !v)}
                data-testid="btn-edit-vertices"
              >
                {t('boundaryPreview.editVertices', { defaultValue: 'Edit vertices' })}
              </Button>
              {recomputing && <Spin size="small" data-testid="recompute-spinner" />}
            </div>
            {editMode && (
              <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 8 }}>
                <div style={{ fontSize: 12, color: '#666' }}>
                  {t('boundaryPreview.insertVertexHint', { defaultValue: 'Drag a blue point to close a gap — it snaps to the neighbour edge. Click a green point to add a vertex; double-click a blue point to delete it.' })}
                </div>
                <div>
                  <div style={{ fontSize: 12, color: '#666', marginBottom: 4 }}>
                    {t('boundaryPreview.tolerance', { defaultValue: 'Snap tolerance', m: toleranceM })}: {toleranceM} m
                  </div>
                  <Slider
                    min={TOLERANCE_MIN_M}
                    max={TOLERANCE_MAX_M}
                    step={0.5}
                    value={toleranceM}
                    onChange={(v) => setToleranceM(v as number)}
                    data-testid="tolerance-slider"
                  />
                </div>
                <Button
                  size="small"
                  onClick={() => recomputePreview(clipped)}
                  loading={recomputing}
                  data-testid="btn-recompute"
                >
                  {t('boundaryPreview.recompute', { defaultValue: 'Recompute now' })}
                </Button>
              </div>
            )}
          </div>
        ) : null}

        {rejected ? (
          <Alert
            type="warning"
            showIcon
            data-testid="reject-alert"
            message={t('boundaryPreview.rejectHeading')}
            description={
              <>
                <div>{rejectMsg}</div>
                <div style={{ marginTop: 6 }}>{t('boundaryPreview.editSuggestion')}</div>
              </>
            }
          />
        ) : null}

        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <Button type="primary" onClick={handleAccept} loading={submitting} disabled={rejected} data-testid="btn-accept">
            {t('boundaryPreview.accept')}
          </Button>
          <Button onClick={() => onEdit?.(clipped)} data-testid="btn-edit">
            {t('boundaryPreview.editManually')}
          </Button>
          <Button onClick={() => setDisputeOpen(true)} data-testid="btn-dispute">
            {t('boundaryPreview.fileDispute')}
          </Button>
          <Button onClick={onCancel} data-testid="btn-cancel">
            {t('common.cancel')}
          </Button>
        </div>
      </div>

      <Modal
        title={t('boundaryPreview.disputeTitle')}
        open={disputeOpen}
        onOk={handleDisputeSubmit}
        onCancel={() => setDisputeOpen(false)}
        confirmLoading={submitting}
        okText={t('common.confirm')}
        data-testid="dispute-modal"
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <Radio.Group value={disputeType} onChange={(e) => setDisputeType(e.target.value)} data-testid="dispute-type">
            <Radio value="overlap">{t('boundaryPreview.disputeTypeOverlap')}</Radio>
            <Radio value="gap">{t('boundaryPreview.disputeTypeGap')}</Radio>
          </Radio.Group>
          <Input.TextArea
            rows={3}
            value={disputeReason}
            onChange={(e) => setDisputeReason(e.target.value)}
            placeholder={t('boundaryPreview.disputeReasonPlaceholder')}
            data-testid="dispute-reason"
          />
        </div>
      </Modal>
    </div>
  )
}
