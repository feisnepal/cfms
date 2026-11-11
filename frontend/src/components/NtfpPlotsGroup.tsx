/**
 * NtfpPlotsGroup — the NTFP survey's sample plots as a built-in layer of the map workspace (owner, 2026-10-22).
 *
 * One toggle in the layer panel. Switched on, it draws the plots the NTFP page laid out (grey: not visited, amber: partly recorded, green: recorded; a blue or red ring is the
 * "I am here" check; a dashed outline is something saved on this device and not yet sent). A click on a plot opens the same entry sheet as the NTFP page, so findings can be typed in
 * from the workspace; saving, the position check, photos and offline keeping are the page's own, not a copy. The plots themselves are made and changed on the NTFP page.
 * Its print twin is the map variable `thememap:unit__ntfp_plots`, which uses the same three colours.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import * as L from 'leaflet';
import { useT } from '../i18n/hooks';
import { useWorkspaceStore } from '../store/workspaceStore';
import { ntfpApi, type NtfpDesign, type NtfpPlotBadge, type NtfpRecords } from '../services/api';
import { apiErrorText } from '../lib/apiErrorText';
import { NTFP_PLOTS_PANE, NTFP_PLOTS_PANE_Z, PLOT_STATUS_COLOUR, VERDICT_RING, overlayPending, plotSummaries, readNtfpLayerOn, writeNtfpLayerOn } from '../lib/ntfp';
import { useNtfpOutbox } from '../hooks/useNtfpOutbox';
import NtfpPlotEntry from './ntfp/NtfpPlotEntry';

interface Props { calculationId?: string; map?: L.Map | null }

export function NtfpPlotsGroup({ calculationId, map = null }: Props) {
  const t = useT();
  const geometryVersion = useWorkspaceStore((s) => s.geometryVersion);
  const [on, setOn] = useState<boolean>(() => readNtfpLayerOn(calculationId));
  const [design, setDesign] = useState<NtfpDesign | null | undefined>(undefined);   // undefined: not read yet; null: the forest has no design
  const [records, setRecords] = useState<NtfpRecords | null>(null);
  const [badges, setBadges] = useState<Record<string, NtfpPlotBadge>>({});
  const [error, setError] = useState<string | null>(null);
  const [plotOpen, setPlotOpen] = useState<number | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);

  useEffect(() => { setOn(readNtfpLayerOn(calculationId)); setDesign(undefined); setRecords(null); setBadges({}); }, [calculationId]);

  const load = useCallback(() => {
    if (!calculationId) return;
    setError(null);
    ntfpApi.getDesign(calculationId)
      .then(async (d) => {
        setDesign(d.design);
        if (!d.design) { setRecords(null); setBadges({}); return; }
        const [r, e] = await Promise.all([ntfpApi.records(calculationId), ntfpApi.allExtras(calculationId).catch(() => ({ plots: {} as Record<string, NtfpPlotBadge> }))]);   // without the rings the plots still show
        setRecords(r);
        setBadges(e.plots);
      })
      .catch((err) => setError(apiErrorText(err, t('ntfpPlotsLayer.error'))));
  }, [calculationId, t]);
  // read when switched on, and again when the forest's geometry changed
  useEffect(() => { if (on) load(); }, [on, load, geometryVersion]);

  const outbox = useNtfpOutbox(calculationId ?? '', () => { load(); });
  const shown = useMemo(() => overlayPending(records?.observations ?? [], outbox.waiting.filter((i) => i.kind === 'plot')), [records, outbox.waiting]);
  const summaries = useMemo(() => (design ? plotSummaries(design.plots, shown) : {}), [design, shown]);
  const pendingPlots = useMemo(() => new Set(outbox.waiting.map((i) => i.plotNumber)), [outbox.waiting]);

  // draw the plots on the workspace map
  useEffect(() => {
    if (!map) return;
    const remove = () => { if (layer.current) { map.removeLayer(layer.current); layer.current = null; } };
    remove();
    if (!on || !design) return remove;
    if (!map.getPane(NTFP_PLOTS_PANE)) { const pane = map.createPane(NTFP_PLOTS_PANE); pane.style.zIndex = NTFP_PLOTS_PANE_Z; }
    const group = L.layerGroup();
    design.plots.forEach((p) => {
      const s = summaries[p.plot_number];
      const verdict = badges[String(p.plot_number)]?.verdict ?? null;
      const waiting = pendingPlots.has(p.plot_number);
      const m = L.circleMarker([p.latitude, p.longitude], {
        pane: NTFP_PLOTS_PANE, radius: 11, fillColor: PLOT_STATUS_COLOUR[s?.status ?? 'none'], fillOpacity: 0.95,
        color: (verdict && VERDICT_RING[verdict]) || '#1b5e20', weight: verdict || waiting ? 3 : 1, dashArray: waiting ? '3 3' : undefined,
      });
      m.bindTooltip(String(p.plot_number), { permanent: true, direction: 'center', className: 'ntfp-plot-label' });   // text, not markup
      m.on('click', () => setPlotOpen(p.plot_number));
      group.addLayer(m);
    });
    group.addTo(map);
    layer.current = group;
    return remove;
  }, [map, on, design, summaries, badges, pendingPlots]);

  const toggle = () => { const next = !on; setOn(next); writeNtfpLayerOn(calculationId, next); if (!next) setPlotOpen(null); };

  if (!calculationId) return null;
  const plot = design?.plots.find((p) => p.plot_number === plotOpen) ?? null;
  const names: Record<string, string> = {};
  design?.species.forEach((s) => { names[s.species_key] = s.label; });
  const count = (status: 'none' | 'partial' | 'done') => Object.values(summaries).filter((s) => s.status === status).length;
  return (
    <div className="analysis-maps ntfp-plots-layer" data-testid="ntfp-plots-group">
      <style>{`.ntfp-plot-label{background:transparent;border:0;box-shadow:none;font-weight:700;font-size:11px;color:#111;padding:0}.ntfp-plot-label:before{display:none}`}</style>
      <label className="analysis-row">
        <input type="checkbox" checked={on} onChange={toggle} aria-label={t('ntfpPlotsLayer.title')} />
        <span aria-hidden="true">🌿</span> {t('ntfpPlotsLayer.title')}
        {on && design && <span className="analysis-count"> · {design.plots.length}</span>}
      </label>
      {on && error && <div className="analysis-map-missing" role="alert">{error}</div>}
      {on && design === null && <div className="analysis-note" role="status">{t('ntfpPlotsLayer.noDesign')}</div>}
      {on && design && (
        <div className="reference-source">
          <div role="list" aria-label={t('ntfpPlotsLayer.legend')}>
            {(['none', 'partial', 'done'] as const).map((k) => (
              <div key={k} role="listitem" data-testid={`ntfp-plots-legend-${k}`}>
                <span aria-hidden="true" style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 5, background: PLOT_STATUS_COLOUR[k], marginRight: 6 }} />
                {t(`ntfpPlotsLayer.status.${k}`)} · {count(k)}
              </div>
            ))}
          </div>
          <div>{t('ntfpPlotsLayer.hint')}</div>
        </div>
      )}
      {plot && (
        <NtfpPlotEntry open calculationId={calculationId} plotNumber={plot.plot_number} stratum={plot.stratum} speciesKeys={plot.species_keys} names={names}
          stored={shown.filter((o) => o.plot_number === plot.plot_number)} pending={outbox.items}
          onClose={() => setPlotOpen(null)} onSaved={load} onExtrasChanged={load} />
      )}
    </div>
  );
}
