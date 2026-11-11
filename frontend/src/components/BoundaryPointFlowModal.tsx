/** Two-step modal for the boundary point-file flow (CSV/XLSX/TXT → forest boundary). */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, Modal, Radio, message } from 'antd';
import { useT } from '../i18n/hooks';
import { formatNumber } from '../i18n/numberFormat';
import { MapContainer, TileLayer, CircleMarker, Polyline, useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import CrsSelector from './CrsSelector';
import ColumnMappingPreview from './ColumnMappingPreview';
import type { ImportResult } from '../hooks/useImportLayer';
import { forestApi } from '../services/api';
import { BASE_MAP_OPTIONS } from '../store/workspaceStore';
import BoundaryOverlapPreviewPanel from './BoundaryOverlapPreviewPanel';
import type { Geometry } from 'geojson';

interface BoundaryPointFlowModalProps {
  file: File;
  preview: any;
  calculationId: string;
  onBoundarySaved?: () => void;
  onComplete: (result: ImportResult) => void;
  onCancel: () => void;
}

function FitPoints({ points }: { points: { lng: number; lat: number }[] }) {
  const map = useMap();
  useEffect(() => {
    if (!points.length) return;
    const latlngs = points.map((p) => [p.lat, p.lng] as [number, number]);
    try {
      map.fitBounds(L.latLngBounds(latlngs).pad(0.1), { padding: [40, 40] });
    } catch {
      map.setView([28.3949, 84.124], 8);
    }
  }, [map, points]);
  return null;
}

interface StationIssue {
  row: number;
  point: { lng: number; lat: number };
  detour_m: number;
  typical_leg_m: number;
  typed: { x: string | null; y: string | null };
  repairs: { axis: 'x' | 'y'; kind: string; typed_from: string; typed_to: string; point: { lng: number; lat: number }; moved_m: number }[];
}

function GhostPreview({ points, method, issues = [] }: { points: { lng: number; lat: number }[]; method: 'ordered' | 'hull'; issues?: StationIssue[] }) {
  const activeOption = BASE_MAP_OPTIONS.find((o) => o.id === 'esri_satellite') || BASE_MAP_OPTIONS[1];
  const latlngs = useMemo(() => points.map((p) => [p.lat, p.lng] as [number, number]), [points]);
  const closed = useMemo(() => (latlngs.length > 2 ? [...latlngs, latlngs[0]] : latlngs), [latlngs]);

  return (
    <div className="h-64 rounded-md overflow-hidden border border-gray-200">
      <MapContainer
        center={[28.3949, 84.124]}
        zoom={8}
        style={{ height: '100%', width: '100%' }}
        key={points.length}
        zoomControl={true}
      >
        {activeOption?.url && (
          <TileLayer
            url={activeOption.url}
            attribution={activeOption.attribution}
            maxZoom={activeOption.maxZoom}
          />
        )}
        <FitPoints points={points} />
        {latlngs.map((pos, i) => (
          <CircleMarker key={i} center={pos} radius={4} pathOptions={{ color: '#dc2626', fillColor: '#dc2626', fillOpacity: 1 }} />
        ))}
        {method === 'ordered' && closed.length > 2 && (
          <Polyline positions={closed} pathOptions={{ color: '#16a34a', weight: 2 }} />
        )}
        {issues.map((s) => (
          <CircleMarker key={`issue-${s.row}`} center={[s.point.lat, s.point.lng]} radius={10} pathOptions={{ color: '#ea580c', fillOpacity: 0, weight: 3 }} />
        ))}
        {issues.map((s) =>
          s.repairs[0] ? (
            <CircleMarker key={`fix-${s.row}`} center={[s.repairs[0].point.lat, s.repairs[0].point.lng]} radius={6} pathOptions={{ color: '#2563eb', fillColor: '#ffffff', fillOpacity: 1, weight: 2 }} />
          ) : null,
        )}
        {method === 'hull' && latlngs.length > 2 && (
          <Polyline
            positions={latlngs}
            pathOptions={{ color: '#f59e0b', weight: 1.5, dashArray: '6 4' }}
          />
        )}
      </MapContainer>
    </div>
  );
}

export default function BoundaryPointFlowModal({
  file,
  preview: initialPreview,
  calculationId,
  onBoundarySaved,
  onComplete,
  onCancel,
}: BoundaryPointFlowModalProps) {
  const t = useT();
  const [step, setStep] = useState<'mapping' | 'geometry'>('mapping');
  const [preview, setPreview] = useState<any>(initialPreview);
  const [method, setMethod] = useState<'ordered' | 'hull'>('ordered');
  const [saving, setSaving] = useState(false);
  const [swapPrompt, setSwapPrompt] = useState<{ message: string; opts: { crsEpsg?: number; mapping?: Record<string, string> } } | null>(null);
  const [showOverlapPanel, setShowOverlapPanel] = useState(false);
  const [pendingGeometry, setPendingGeometry] = useState<Geometry | null>(null);

  // re-preview helper: any response flagged `swap_detected` pauses the flow with
  // a confirmation instead of jumping to the geometry step with 0 points.
  const repreview = useCallback(async (opts: { crsEpsg?: number; mapping?: Record<string, string> }, errKey: string) => {
    const next = await forestApi.previewBoundaryMapping(calculationId, file, opts);
    if (next?.swap_detected) {
      setSwapPrompt({
        message: next.swap_message || t('import.dialog.swappedFixMessage'),
        opts,
      });
      return null;
    }
    setPreview(next);
    return next;
  }, [calculationId, file, t]);

  const handleSwapFix = useCallback(async () => {
    if (!swapPrompt) return;
    try {
      const next = await forestApi.previewBoundaryMapping(calculationId, file, { ...swapPrompt.opts, fixSwap: true });
      if (next?.swap_detected) {
        setSwapPrompt({ message: next.swap_message || t('import.dialog.swappedFixMessage'), opts: swapPrompt.opts });
        return;
      }
      setPreview(next);
      setSwapPrompt(null);
      setStep('geometry');
      message.info(t('import.dialog.swappedFixed'));
    } catch (err: any) {
      message.error(err?.response?.data?.detail || err?.message || t('import.boundaryPoints.swapFixFail'));
    }
  }, [calculationId, file, swapPrompt, t]);

  useEffect(() => {
    if (preview?.swap_detected) {
      setSwapPrompt({ message: preview.swap_message || t('import.dialog.swappedFixMessage'), opts: {} });
      return;
    }
    if (!preview?.needs_user_input) setStep('geometry');
  }, [preview, t]);

  const handleMappingConfirm = async (mapping: Record<string, string>) => {
    try {
      const next = await repreview({ mapping }, t('import.boundaryPoints.remapFailed'));
      setStep('geometry');
    } catch (err: any) {
      message.error(err?.response?.data?.detail || err?.message || t('import.boundaryPoints.remapFailed'));
    }
  };

  const handleCrsChange = async (epsg: number) => {
    try {
      const opts = { crsEpsg: epsg, mapping: preview?.mapping as Record<string, string> | undefined };
      const next = await repreview(opts, t('import.boundaryPoints.recrsFailed'));
      if (next && !next.swap_detected) setStep('geometry');
    } catch (err: any) {
      message.error(err?.response?.data?.detail || err?.message || t('import.boundaryPoints.recrsFailed'));
    }
  };

  const buildPreviewPolygon = useCallback((): Geometry | null => {
    const pts: { lng: number; lat: number }[] = preview?.points_4326 || []
    if (pts.length < 3) return null
    const coords = pts.map((p) => [p.lng, p.lat] as [number, number])
    // Close ring
    if (coords[0][0] !== coords[coords.length - 1][0] || coords[0][1] !== coords[coords.length - 1][1]) coords.push(coords[0])
    return { type: 'Polygon', coordinates: [coords] } as unknown as Geometry
  }, [preview])

  const handleConfirm = async () => {
    // PF-3: preview gate — if the proposed boundary adjoins/overlaps another CF, show the decision panel instead of saving directly.
    const pending = buildPreviewPolygon()
    if (pending && typeof (forestApi as unknown as { previewBoundaryOverlap?: unknown }).previewBoundaryOverlap === 'function') {
      setSaving(true)
      try {
        const rel = await (forestApi as unknown as { previewBoundaryOverlap: (p: { geometry: Geometry; method: string; forest_id?: string }) => Promise<unknown> }).previewBoundaryOverlap({
          geometry: pending,
          method: 'points',
          forest_id: calculationId,
        })
        const hasRelations = Boolean(
          (rel as { overlapping_forests?: unknown[]; gaps?: unknown[] })?.overlapping_forests?.length ||
            (rel as { gaps?: unknown[] })?.gaps?.length,
        )
        if (hasRelations) {
          setPendingGeometry(pending)
          setShowOverlapPanel(true)
          setSaving(false)
          return
        }
      } catch {
        // Preview failed — fall through to direct save (fast path remains)
      }
      setSaving(false)
    }

    setSaving(true)
    try {
      const resp = await forestApi.updateBoundaryFromPoints(calculationId, preview.points_4326 || [], method)
      if (resp?.success) {
        onBoundarySaved?.()
        onComplete({
          success: true,
          layerName: 'Forest Boundary',
          featureCount: 1,
          geometryTypes: ['Polygon'],
          purpose: 'boundary',
        })
      } else {
        message.error(resp?.detail || resp?.message || t('import.boundaryPoints.createFailed'))
        setSaving(false)
      }
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || (err as Error)?.message || t('import.boundaryPoints.createFailed')
      message.error(msg)
      setSaving(false)
    }
  };

  const points4326 = preview?.points_4326 || [];

  return (
    <>
      {step === 'mapping' && preview && (
        <ColumnMappingPreview
          previewData={{
            filename: file.name,
            total_rows: preview.total_rows ?? 0,
            csv_columns: preview.csv_columns || [],
            sample_data: preview.sample_data || [],
            mapping: preview.mapping || {},
            confidence: preview.confidence || {},
            unmapped_columns: preview.unmapped_columns || [],
            missing_required: preview.missing_required || [],
            duplicates: preview.duplicates || {},
            needs_user_input: !!preview.needs_user_input,
            required_columns: preview.required_columns || ['LONGITUDE', 'LATITUDE'],
            optional_columns: preview.optional_columns || [],
          }}
          onConfirm={handleMappingConfirm}
          onCancel={onCancel}
        />
      )}

      {step === 'geometry' && (
        <Modal
          open
          onOk={handleConfirm}
          onCancel={onCancel}
          confirmLoading={saving}
          okText={t('import.boundaryPoints.createBoundary')}
          cancelText={t('common.cancel')}
          title={t('import.boundaryPoints.title')}
          centered
          width={720}
        >
          <div className="space-y-4">
            <div className="flex items-center justify-between text-sm text-gray-600">
              <span>
                {t('import.dialog.file')} <span className="font-mono font-medium">{file.name}</span>
              </span>
              <span>
                {t('import.boundaryPoints.points')} <span className="font-semibold">{formatNumber(points4326.length)}</span>
              </span>
              <span>
                {t('import.boundaryPoints.detectedCrs')} <span className="font-semibold">EPSG:{preview?.detected_crs ?? 4326}</span>
              </span>
            </div>

            <CrsSelector value={preview?.detected_crs || 4326} onChange={handleCrsChange} />

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">{t('import.boundaryPoints.method')}</label>
              <Radio.Group value={method} onChange={(e) => setMethod(e.target.value)}>
                <Radio value="ordered">{t('import.boundaryPoints.methodOrdered')}</Radio>
                <Radio value="hull">{t('import.boundaryPoints.methodHull')}</Radio>
              </Radio.Group>
            </div>

            {!!preview?.station_issues?.length && (
              <Alert
                type="warning"
                showIcon
                data-testid="station-issues"
                message={t('import.boundaryPoints.stationIssuesTitle', { count: preview.station_issues.length })}
                description={
                  <ul className="list-disc pl-4 space-y-1">
                    {(preview.station_issues as StationIssue[]).slice(0, 5).map((s) => (
                      <li key={s.row}>
                        {t('import.boundaryPoints.stationIssue', { row: s.row, detour: formatNumber(Math.round(s.detour_m)), leg: formatNumber(Math.round(s.typical_leg_m)) })}{' '}
                        {s.repairs[0]
                          ? t('import.boundaryPoints.stationRepair', {
                              from: s.repairs[0].typed_from,
                              to: s.repairs[0].typed_to,
                              axis: s.repairs[0].axis === 'x' ? t('import.boundaryPoints.axisX') : t('import.boundaryPoints.axisY'),
                              moved: formatNumber(Math.round(s.repairs[0].moved_m)),
                            })
                          : t('import.boundaryPoints.stationNoRepair')}
                      </li>
                    ))}
                  </ul>
                }
              />
            )}

            {points4326.length > 0 && <GhostPreview points={points4326} method={method} issues={(preview?.station_issues as StationIssue[]) ?? []} />}
          </div>
        </Modal>
      )}

      {swapPrompt && (
        <Modal
          open
          onOk={handleSwapFix}
          onCancel={() => setSwapPrompt(null)}
          okText={t('import.boundaryPoints.swapFixOk')}
          cancelText={t('common.cancel')}
          title={t('import.dialog.swappedFixTitle')}
          centered
          width={520}
        >
          <Alert
            type="warning"
            showIcon
            message={swapPrompt.message || t('import.dialog.swappedFixMessage')}
          />
        </Modal>
      )}

      {showOverlapPanel && pendingGeometry && (
        <Modal
          open
          onCancel={() => {
            setShowOverlapPanel(false)
            setPendingGeometry(null)
          }}
          footer={null}
          width={1100}
          title={t('boundaryPreview.title')}
          centered
          destroyOnHidden
        >
          <BoundaryOverlapPreviewPanel
            geometry={pendingGeometry}
            forestName={preview?.forest_name || file.name.replace(/\.[^/.]+$/, '')}
            method="points"
            calculationId={calculationId}
            onCancel={() => {
              setShowOverlapPanel(false)
              setPendingGeometry(null)
            }}
            onDone={() => {
              // Tear down this panel before handing off, or the
              // `showOverlapPanel` branch keeps rendering it and Accept looks
              // like it re-opens the same window.
              setShowOverlapPanel(false)
              setPendingGeometry(null)
              onBoundarySaved?.()
              onComplete({
                success: true,
                layerName: 'Forest Boundary',
                featureCount: 1,
                geometryTypes: ['Polygon'],
                purpose: 'boundary',
              })
            }}
            onEdit={() => {
              setShowOverlapPanel(false)
              setPendingGeometry(null)
            }}
          />
        </Modal>
      )}
    </>
  );
}
