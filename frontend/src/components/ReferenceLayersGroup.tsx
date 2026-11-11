/**
 * ReferenceLayersGroup — ready-made context round the forest, in the layer panel (owner, 2026-10-22).
 *
 * Rivers, roads, municipalities, wards, protected areas, settlements and buildings: shared national data, cut to the forest's neighbourhood by the server and drawn BELOW the
 * forest's own layers. They are read-only context: switching one on reads it, nothing is copied into the forest and nothing can be edited. What was on, and how wide the neighbourhood
 * was, is remembered for the forest. Each layer says where it comes from, and says plainly when its licence has not been confirmed.
 *
 * The group draws on the Leaflet map it is given (like the analysis maps' own overlays), in its own pane under the forest's layers, with one shared canvas renderer so thousands of
 * building footprints stay quick.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import * as L from 'leaflet';
import { useT } from '../i18n/hooks';
import i18n from '../i18n';
import { useWorkspaceStore } from '../store/workspaceStore';
import { referenceLayersApi, type ReferenceFeatureCollection, type ReferenceLayerInfo } from '../services/api';
import { apiErrorText } from '../lib/apiErrorText';
import {
  ATTRIBUTION, BUFFER_CHOICES_M, REFERENCE_PANE, canvasAvailable, REFERENCE_PANE_Z, layerLabel, licenceState, pathStyle, pointRadius, popupContent, readSaved, writeSaved,
} from '../lib/referenceLayers';

interface Props { calculationId?: string; map?: L.Map | null }
interface LayerState { loading?: boolean; error?: string; count?: number; truncated?: boolean; limit?: number }

const swatch = (info: ReferenceLayerInfo) => {
  const s = pathStyle(info);
  const common = { display: 'inline-block', marginRight: 6, verticalAlign: 'middle' } as const;
  if (info.geometry === 'line') return <span aria-hidden="true" style={{ ...common, width: 18, height: 0, borderTop: `3px ${s.dashArray ? 'dashed' : 'solid'} ${s.color}` }} />;
  if (info.geometry === 'point') return <span aria-hidden="true" style={{ ...common, width: 10, height: 10, borderRadius: 5, background: s.fillColor, border: `1px solid ${s.color}` }} />;
  return <span aria-hidden="true" style={{ ...common, width: 16, height: 10, background: s.fill ? s.fillColor : 'transparent', opacity: 0.9, border: `2px ${s.dashArray ? 'dashed' : 'solid'} ${s.color}`, boxSizing: 'border-box' }} />;
};

export function ReferenceLayersGroup({ calculationId, map = null }: Props) {
  const t = useT();
  const geometryVersion = useWorkspaceStore((s) => s.geometryVersion);
  const [open, setOpen] = useState(false);
  const [catalog, setCatalog] = useState<ReferenceLayerInfo[]>([]);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const saved = useMemo(() => readSaved(calculationId), [calculationId]);
  const [visible, setVisible] = useState<string[]>(saved.visible);
  const [bufferM, setBufferM] = useState<number>(saved.bufferM);
  const [state, setState] = useState<Record<string, LayerState>>({});

  const drawn = useRef<Map<string, L.GeoJSON>>(new Map());
  const credited = useRef<Set<string>>(new Set());
  const renderer = useRef<L.Canvas | null>(null);
  const cache = useRef<Map<string, ReferenceFeatureCollection>>(new Map());
  const wanted = useRef<Map<string, string>>(new Map());   // layer key -> the request it currently waits for (a later toggle makes an earlier answer stale)

  // a different forest: what was remembered for it, and nothing drawn from the last one
  useEffect(() => {
    setVisible(saved.visible);
    setBufferM(saved.bufferM);
    cache.current.clear();
  }, [saved]);

  // the catalogue is read when the group is opened, or at once when layers were left on
  useEffect(() => {
    if (!calculationId || catalog.length > 0 || (!open && visible.length === 0)) return;
    let alive = true;
    referenceLayersApi.catalog(calculationId)
      .then((r) => { if (alive) setCatalog(r.layers); })
      .catch((err) => { if (alive) setCatalogError(apiErrorText(err, t('referenceLayers.error'))); });
    return () => { alive = false; };
  }, [calculationId, open, visible.length, catalog.length, t]);

  const removeLayer = (key: string) => {
    const layer = drawn.current.get(key);
    if (layer && map) map.removeLayer(layer);
    drawn.current.delete(key);
    const credit = ATTRIBUTION[key];
    if (credit && credited.current.has(key)) { map?.attributionControl?.removeAttribution(credit); credited.current.delete(key); }
  };

  const draw = (info: ReferenceLayerInfo, fc: ReferenceFeatureCollection) => {
    if (!map) return;
    if (!map.getPane(REFERENCE_PANE)) {
      const pane = map.createPane(REFERENCE_PANE);
      pane.style.zIndex = REFERENCE_PANE_Z;
    }
    if (canvasAvailable() && (!renderer.current || (renderer.current as any)._map !== map)) renderer.current = L.canvas({ pane: REFERENCE_PANE, padding: 0.4 });
    const style = pathStyle(info);
    const name = layerLabel(info, i18n.language);
    // Leaflet hands a GeoJSON layer's options on to the paths it makes, so the pane and the shared canvas renderer reach every feature
    const options: L.GeoJSONOptions & { renderer?: L.Renderer } = {
      pane: REFERENCE_PANE,
      renderer: renderer.current ?? undefined,
      style: () => style,
      pointToLayer: (_f, latlng) => L.circleMarker(latlng, { ...style, radius: pointRadius(info), pane: REFERENCE_PANE, ...(renderer.current ? { renderer: renderer.current } : {}) }),
      onEachFeature: (f, l) => {
        const props = (f.properties ?? {}) as Record<string, unknown>;
        const label = typeof props._label === 'string' && props._label.trim() ? props._label : '';
        if (label) l.bindTooltip(label, { sticky: true, direction: 'top' });   // text, not markup
        l.bindPopup(() => popupContent(label || name, props));
      },
    };
    const layer = L.geoJSON(fc as any, options);
    layer.addTo(map);
    drawn.current.set(info.key, layer);
    const credit = ATTRIBUTION[info.key];
    if (credit && !credited.current.has(info.key)) { map.attributionControl?.addAttribution(credit); credited.current.add(info.key); }
  };

  // keep the map in step with what is switched on, how wide the neighbourhood is, and the forest's boundary
  useEffect(() => {
    if (!calculationId || !map || catalog.length === 0) return;
    const on = new Set(visible);
    Array.from(drawn.current.keys()).filter((k) => !on.has(k)).forEach(removeLayer);
    visible.forEach((key) => {
      const info = catalog.find((c) => c.key === key);
      if (!info) return;
      const request = `${calculationId}|${key}|${bufferM}|${geometryVersion}`;
      if (wanted.current.get(key) === request && drawn.current.has(key)) return;
      wanted.current.set(key, request);
      const show = (fc: ReferenceFeatureCollection) => {
        if (wanted.current.get(key) !== request) return;            // the person changed their mind while it loaded
        removeLayer(key);
        draw(info, fc);
        setState((s) => ({ ...s, [key]: { count: fc.count, truncated: fc.truncated, limit: fc.max_features } }));
      };
      const kept = cache.current.get(request);
      if (kept) { show(kept); return; }
      setState((s) => ({ ...s, [key]: { ...s[key], loading: true, error: undefined } }));
      referenceLayersApi.features(calculationId, key, bufferM)
        .then((fc) => { cache.current.set(request, fc); show(fc); })
        .catch((err) => {
          if (wanted.current.get(key) !== request) return;
          wanted.current.delete(key);
          setState((s) => ({ ...s, [key]: { error: apiErrorText(err, t('referenceLayers.error')) } }));
        });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- draw/removeLayer only read refs and `map`; the inputs that change what is drawn are listed
  }, [calculationId, map, catalog, visible, bufferM, geometryVersion]);

  // leaving the page: take everything off the map
  useEffect(() => () => { Array.from(drawn.current.keys()).forEach(removeLayer); wanted.current.clear(); },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only on unmount
    []);

  const toggle = (key: string) => {
    const next = visible.includes(key) ? visible.filter((k) => k !== key) : [...visible, key];
    if (!next.includes(key)) wanted.current.delete(key);
    setVisible(next);
    writeSaved(calculationId, { visible: next, bufferM });
  };
  const changeBuffer = (m: number) => {
    setBufferM(m);
    writeSaved(calculationId, { visible, bufferM: m });
  };

  if (!calculationId) return null;
  return (
    <div className="analysis-maps reference-layers" data-testid="reference-layers-group">
      <button type="button" className="analysis-maps-header" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <span aria-hidden="true">{open ? '▾' : '▸'}</span> <span aria-hidden="true">🧭</span> {t('referenceLayers.title')}
        {visible.length > 0 && <span className="analysis-maps-active"> · {t('referenceLayers.onCount', { count: visible.length })}</span>}
      </button>
      {open && (
        <div>
          <p className="reference-note">{t('referenceLayers.intro')}</p>
          {catalogError && <div className="analysis-map-missing" role="alert">{catalogError}</div>}
          <label className="analysis-row analysis-factor-row">
            <span>{t('referenceLayers.buffer')}</span>
            <select value={bufferM} aria-label={t('referenceLayers.buffer')} onChange={(e) => changeBuffer(Number(e.target.value))}>
              {BUFFER_CHOICES_M.map((m) => <option key={m} value={m}>{m >= 1000 ? `${m / 1000} km` : `${m} m`}</option>)}
            </select>
          </label>
          {catalog.map((info) => {
            const on = visible.includes(info.key);
            const st = state[info.key] ?? {};
            const lic = licenceState(info);
            return (
              <div key={info.key} className="reference-row">
                <label className="analysis-row">
                  <input type="checkbox" checked={on} onChange={() => toggle(info.key)} />
                  {swatch(info)}{layerLabel(info, i18n.language)}
                  {on && st.loading && <span className="analysis-count"> · {t('referenceLayers.loading')}</span>}
                  {on && !st.loading && st.count != null && <span className="analysis-count"> · {st.count}</span>}
                </label>
                {on && st.error && <div className="analysis-map-missing" role="alert">{st.error}</div>}
                {on && st.truncated && <div className="analysis-note" role="status">{t('referenceLayers.truncated', { limit: st.limit })}</div>}
                {on && st.count === 0 && !st.loading && !st.error && <div className="analysis-note">{t('referenceLayers.none')}</div>}
                {on && (
                  <div className="reference-source">
                    {info.source}{' '}
                    {lic.confirmed
                      ? <span className="reference-licence reference-licence-ok">{lic.name}</span>
                      : <span className="reference-licence" title={info.licence_note ?? undefined}>{t('referenceLayers.licenceUnconfirmed')}</span>}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
