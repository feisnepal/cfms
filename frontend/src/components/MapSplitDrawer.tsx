import { useState, useEffect, useCallback, useRef } from 'react';
import type { GeoJSON } from 'geojson';
import L from 'leaflet';
import * as turf from '@turf/turf';
import type { SplitPreviewResult, SplitApiResponse } from '../lib/editOperations';
import { useT } from '../i18n/hooks';
import { formatNumber } from '../i18n/numberFormat';

interface MapSplitDrawerProps {
  map: L.Map;
  targetFeature: GeoJSON.Feature<GeoJSON.Polygon | GeoJSON.MultiPolygon>;
  layerId: string;
  onSplitPreview: (result: SplitPreviewResult | null) => void;
  onSplitConfirm: (cutLine: GeoJSON.LineString) => void;
  onCancel: () => void;
  existingFeatures?: GeoJSON.Feature[];
  historyManager?: unknown;
  isTouchDevice?: boolean;
}

interface InternalSplitPreviewResult {
  cutLine: GeoJSON.LineString;
  pieces: GeoJSON.Feature<GeoJSON.Polygon>[];
  isValid: boolean;
  error?: string;
  pieceIds: string[];
  pieceAreas: number[];
}

export function MapSplitDrawer({
  map, targetFeature, layerId,
  onSplitPreview, onSplitConfirm, onCancel,
  existingFeatures, isTouchDevice,
}: MapSplitDrawerProps) {
  const t = useT();
  const [state, setState] = useState<'idle' | 'drawing' | 'preview'>('idle');
  const [cutLine, setCutLine] = useState<L.Polyline | null>(null);
  const [previewPieces, setPreviewPieces] = useState<L.GeoJSON[]>([]);
  const drawnPointsRef = useRef<L.LatLng[]>([]);

  useEffect(() => {
    if (!map) return;

    const cutLayer = L.geoJSON().addTo(map);
    (cutLayer as any).pm.enable({
      allowSelfIntersection: false,
      templineStyle: { color: '#FF0000', weight: 3, dashArray: '10, 10' },
      hintlineStyle: { color: '#FF0000', weight: 1, dashArray: '5, 5' },
      markerStyle: { color: '#FF0000', weight: 2 },
    } as any);

    if (isTouchDevice) {
      map.doubleClickZoom.disable();
      (cutLayer as any).pm.setGlobalOptions({ dragWidth: 12 });
    }

    const handleCreate = (e: any) => {
      const lineLayer = e.layer as L.Polyline;
      const latlngs = lineLayer.getLatLngs() as L.LatLng[];
      const coords = latlngs.map(ll => [ll.lng, ll.lat]);
      const lineString: GeoJSON.LineString = {
        type: 'LineString',
        coordinates: coords as [number, number][],
      };

      const preview = computeSplitPreview(targetFeature, lineString);
      setState('preview');
      setCutLine(lineLayer);

      if (!preview.isValid) {
        lineLayer.setStyle({ color: '#FF4444', opacity: 0.5 });
      } else {
        lineLayer.setStyle({ color: '#00CC00', weight: 3 });
        renderPreviewPieces(preview.pieces);
      }

      onSplitPreview({
        cutLine: preview.cutLine,
        pieces: preview.pieces,
        isValid: preview.isValid,
        error: preview.error,
        pieceIds: preview.pieceIds,
        pieceAreas: preview.pieceAreas,
      });
    };

    map.on('pm:create', handleCreate);
    return () => {
      map.off('pm:create', handleCreate);
      if (isTouchDevice) {
        map.doubleClickZoom.enable();
      }
      (cutLayer as any).pm.disable();
      map.removeLayer(cutLayer);
    };
  }, [map, targetFeature, isTouchDevice, onSplitPreview]);

  function computeSplitPreview(
    target: GeoJSON.Feature<GeoJSON.Polygon | GeoJSON.MultiPolygon>,
    line: GeoJSON.LineString,
  ): InternalSplitPreviewResult {
    const result: InternalSplitPreviewResult = {
      cutLine: line, pieces: [], isValid: false, pieceIds: [], pieceAreas: [],
    };

    try {
      if (line.coordinates.length < 2) {
        result.error = 'geometry.split.not_enough_points';
        return result;
      }

      const targetPoly = turf.polygon(
        target.geometry.type === 'MultiPolygon'
          ? target.geometry.coordinates[0]
          : target.geometry.coordinates
      );
      const lineTurf = turf.lineString(line.coordinates);
      const intersection = turf.lineIntersect(lineTurf, targetPoly);

      if (intersection.features.length < 2) {
        result.error = 'geometry.split.line_too_short';
        return result;
      }

      const splitResult = (turf as any).polygonSplit(targetPoly, lineTurf);
      if (!splitResult || splitResult.features.length < 2) {
        const extended = extendCutLine(line, targetPoly);
        const extendedResult = (turf as any).polygonSplit(targetPoly, extended);
        if (!extendedResult || extendedResult.features.length < 2) {
          result.error = 'geometry.split.line_too_short';
          return result;
        }
        result.pieces = extendedResult.features as GeoJSON.Feature<GeoJSON.Polygon>[];
      } else {
        result.pieces = splitResult.features as GeoJSON.Feature<GeoJSON.Polygon>[];
      }

      const minAreaHa = 0.01;
      for (const piece of result.pieces) {
        const area = turf.area(piece) / 10000;
        if (area < minAreaHa) {
          result.error = 'geometry.split.result_too_small';
          result.pieceAreas = [];
          return result;
        }
        result.pieceAreas.push(area);
      }

      const baseId = (target.properties as any)?.id || (target.properties as any)?.featureId || 'piece';
      result.pieceIds = result.pieces.map((_, i) => `${baseId}_${i + 1}`);
      result.isValid = true;
    } catch (err) {
      result.error = `geometry.split.invalid_cut: ${err}`;
    }

    return result;
  }

  function extendCutLine(
    line: GeoJSON.LineString,
    polygon: GeoJSON.Feature<GeoJSON.Polygon | GeoJSON.MultiPolygon>,
  ): GeoJSON.LineString {
    const coords = line.coordinates;
    if (coords.length < 2) return line;

    const first = coords[0];
    const last = coords[coords.length - 1];
    const dx = last[0] - first[0];
    const dy = last[1] - first[1];
    const length = Math.sqrt(dx * dx + dy * dy);
    if (length === 0) return line;

    const extendFactor = 10;
    const extendedFirst: [number, number] = [
      first[0] - dx / length * extendFactor * length,
      first[1] - dy / length * extendFactor * length,
    ];
    const extendedLast: [number, number] = [
      last[0] + dx / length * extendFactor * length,
      last[1] + dy / length * extendFactor * length,
    ];

    return {
      type: 'LineString',
      coordinates: [extendedFirst, ...coords, extendedLast],
    };
  }

  function renderPreviewPieces(pieces: GeoJSON.Feature<GeoJSON.Polygon>[]) {
    previewPieces.forEach(p => map.removeLayer(p));
    const layers = pieces.map((piece) => {
      const ghostLayer = L.geoJSON(piece as any, {
        style: {
          color: '#00CC00',
          weight: 2,
          fillColor: '#00CC00',
          fillOpacity: 0.15,
          dashArray: '8, 4',
        },
      }).addTo(map);
      const area = turf.area(piece) / 10000;
      ghostLayer.bindTooltip(t('editing.split.areaTooltip', {
        area: formatNumber(area, { maximumFractionDigits: 2 }),
        hectare: t('units.hectare'),
      }), {
        permanent: true, direction: 'center', className: 'split-preview-label',
      });
      return ghostLayer;
    });
    setPreviewPieces(layers);
  }

  const handleConfirm = useCallback(() => {
    if (!cutLine) return;
    const latlngs = cutLine.getLatLngs() as L.LatLng[];
    const coords = latlngs.map(ll => [ll.lng, ll.lat]);
    onSplitConfirm({
      type: 'LineString',
      coordinates: coords as [number, number][],
    });
  }, [cutLine, onSplitConfirm]);

  const handleCancel = useCallback(() => {
    previewPieces.forEach(p => map.removeLayer(p));
    setPreviewPieces([]);
    setCutLine(null);
    setState('idle');
    onCancel();
  }, [map, previewPieces, onCancel]);

  return (
    <div className="split-drawer-overlay" role="dialog" aria-label={t('editing.split.title')}>
      <div className="split-instructions" role="status" aria-live="polite">
        {state === 'drawing' && (
          <p>{t('editing.split.instruction')}</p>
        )}
        {state === 'preview' && <p>{t('editing.split.previewPrompt')}</p>}
      </div>

      <div className="split-actions" role="toolbar" aria-label={t('editing.split.actionsAria')}>
        <button onClick={handleConfirm} disabled={state !== 'preview'} aria-label={t('editing.split.confirm')}>
          {t('editing.split.confirm')}
        </button>
        <button onClick={handleCancel} aria-label={t('editing.split.cancelAria')}>
          {t('common.cancel')}
        </button>
      </div>
    </div>
  );
}

export default MapSplitDrawer;
