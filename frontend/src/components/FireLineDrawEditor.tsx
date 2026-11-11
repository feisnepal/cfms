/** Draw a fire line, give every segment its own width, see the strip it makes, then create it (or change the widths of an
 *  existing one). The widths are metres PER SIDE. The preview is the backend's own computation (clipped to the forest area), so
 *  what is shown is what will be stored. */
import { useEffect, useMemo, useRef, useState } from 'react';
import L from 'leaflet';
import { fireLineApi, type FireLinePreview, type StripApi } from '../services/api';
import { useT } from '../i18n/hooks';
import { allWidthsValid, DEFAULT_SIDE_M, defaultWidths, errorMessage, MAX_SIDE_M, MIN_SIDE_M, newClientId, segmentCount, validWidth } from '../lib/fireLines';

export interface FireLineDrawEditorProps {
  calculationId: string;
  map: L.Map | null;
  mode: 'create' | 'edit';
  centerline: GeoJSON.LineString;
  initialWidths?: number[];
  initialName?: string;
  stripId?: string | null;
  /** the calls of the kind being drawn (the fire line by default) */
  api?: StripApi;
  /** metres per side a new segment starts at */
  defaultSide?: number;
  /** the heading for a new strip (the fire line's by default) */
  createTitleKey?: string;
  onClose: () => void;
  onDone: () => void;
}

const PREVIEW_DELAY_MS = 350;

export function FireLineDrawEditor({
  calculationId, map, mode, centerline, initialWidths, initialName, stripId, onClose, onDone,
  api = fireLineApi, defaultSide = DEFAULT_SIDE_M, createTitleKey = 'fireLines.drawEditor.title',
}: FireLineDrawEditorProps) {
  const t = useT();
  const segments = segmentCount(centerline);
  const [widths, setWidths] = useState<number[]>(() =>
    initialWidths && initialWidths.length === segments ? initialWidths : defaultWidths(segments, defaultSide),
  );
  const [name, setName] = useState(initialName ?? '');
  const [preview, setPreview] = useState<FireLinePreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const clientId = useRef(newClientId());
  const lineLayer = useRef<L.LayerGroup | null>(null);
  const stripLayer = useRef<L.GeoJSON | null>(null);

  const valid = allWidthsValid(widths);

  // the drawn centerline, with a numbered marker on every segment
  useEffect(() => {
    if (!map) return undefined;
    const group = L.layerGroup().addTo(map);
    const latlngs = centerline.coordinates.map(([lng, lat]) => L.latLng(lat, lng));
    L.polyline(latlngs, { color: '#c62828', weight: 2, dashArray: '6 4' }).addTo(group);
    latlngs.slice(0, -1).forEach((a, i) => {
      const b = latlngs[i + 1];
      L.marker(L.latLng((a.lat + b.lat) / 2, (a.lng + b.lng) / 2), {
        interactive: false,
        icon: L.divIcon({ className: 'fire-line-seg', html: `<span style="background:#fff;border:1px solid #c62828;border-radius:9px;padding:0 5px;font-size:11px">${i + 1}</span>`, iconSize: [0, 0] }),
      }).addTo(group);
    });
    lineLayer.current = group;
    return () => {
      group.remove();
      lineLayer.current = null;
    };
  }, [map, centerline]);

  // the strip, from the backend, a moment after the last change
  useEffect(() => {
    if (!valid) {
      setPreview(null);
      return undefined;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      api
        .preview(calculationId, centerline, widths)
        .then((p) => {
          if (cancelled) return;
          setPreview(p);
          setError(null);
          if (!name) setName((n) => n || p.name);
        })
        .catch((err) => {
          if (cancelled) return;
          setPreview(null);
          setError(errorMessage(err, t('fireLines.drawEditor.failed')));
        });
    }, PREVIEW_DELAY_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [calculationId, centerline, widths, valid]);

  useEffect(() => {
    if (!map) return undefined;
    stripLayer.current?.remove();
    stripLayer.current = null;
    if (preview) {
      stripLayer.current = L.geoJSON(preview.geometry as GeoJSON.GeoJsonObject, {
        style: { color: '#c62828', weight: 1, fillColor: '#c62828', fillOpacity: 0.45 },
      }).addTo(map);
    }
    return () => {
      stripLayer.current?.remove();
      stripLayer.current = null;
    };
  }, [map, preview]);

  const setOne = (i: number, raw: string) => {
    const v = raw === '' ? Number.NaN : Number(raw.replace(',', '.'));
    setWidths((w) => w.map((x, j) => (j === i ? v : x)));
  };
  const setAll = (raw: string) => {
    const v = raw === '' ? Number.NaN : Number(raw.replace(',', '.'));
    setWidths((w) => w.map(() => v));
  };

  const save = async () => {
    if (!valid || busy) return;
    setBusy(true);
    setError(null);
    try {
      if (mode === 'edit' && stripId) await api.setWidths(calculationId, stripId, widths);
      else await api.create(calculationId, { centerline, widths_m: widths, name: name.trim() || undefined, client_id: clientId.current });
      onDone();
    } catch (err) {
      setError(errorMessage(err, t('fireLines.saveFailed')));
    } finally {
      setBusy(false);
    }
  };

  const same = useMemo(() => (widths.length && widths.every((w) => w === widths[0]) ? String(widths[0]) : ''), [widths]);

  return (
    <div data-testid="fire-line-draw-editor" style={{ borderTop: '1px solid #ddd', paddingTop: 8, marginTop: 8 }}>
      <b>{mode === 'edit' ? t('fireLines.drawEditor.editTitle') : t(createTitleKey)}</b>
      {mode === 'create' && (
        <label style={{ display: 'block', marginTop: 6 }}>
          {t('fireLines.drawEditor.name')}
          <input data-testid="fire-line-name" value={name} onChange={(e) => setName(e.target.value)} style={{ width: '100%' }} />
        </label>
      )}
      <label style={{ display: 'block', marginTop: 6 }}>
        {t('fireLines.drawEditor.sameForAll')} ({t('fireLines.drawEditor.eachSide')})
        <input data-testid="fire-line-width-all" inputMode="decimal" value={same} onChange={(e) => setAll(e.target.value)} style={{ width: 70, marginLeft: 6 }} />
      </label>
      <ol style={{ margin: '6px 0', paddingLeft: 0, listStyle: 'none', maxHeight: 160, overflow: 'auto' }}>
        {widths.map((w, i) => (
          <li key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
            <span style={{ width: 80 }}>{t('fireLines.drawEditor.segment', { n: i + 1 })}</span>
            <input
              data-testid={`fire-line-width-${i}`}
              inputMode="decimal"
              value={Number.isNaN(w) ? '' : String(w)}
              onChange={(e) => setOne(i, e.target.value)}
              aria-invalid={!validWidth(w)}
              style={{ width: 70, borderColor: validWidth(w) ? undefined : '#c62828' }}
            />
            <small>{MIN_SIDE_M}–{MAX_SIDE_M}</small>
          </li>
        ))}
      </ol>
      {preview && (
        <div data-testid="fire-line-preview-summary">
          {t('fireLines.drawEditor.summary', { m: Math.round(preview.length_m), ha: preview.area_ha.toFixed(3) })}
          {preview.warnings.includes('clipped_to_forest') && <div>{t('fireLines.drawEditor.clipped')}</div>}
          {preview.parts > 1 && <div>{t('fireLines.drawEditor.parts', { n: preview.parts })}</div>}
        </div>
      )}
      {error && <div role="alert" style={{ color: '#c62828' }}>{error}</div>}
      <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
        <button type="button" data-testid="fire-line-save" disabled={!valid || busy || (mode === 'create' && !preview)} onClick={save}>
          {mode === 'edit' ? t('fireLines.drawEditor.save') : t('fireLines.drawEditor.create')}
        </button>
        <button type="button" data-testid="fire-line-cancel" onClick={onClose}>{t('fireLines.drawEditor.cancel')}</button>
      </div>
    </div>
  );
}
