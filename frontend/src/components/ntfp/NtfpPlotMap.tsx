/** NtfpPlotMap — the forest boundary, the transect lines and the sample plot positions of an NTFP design. */
import { useEffect, useMemo } from 'react';
import { CircleMarker, GeoJSON, MapContainer, Popup, TileLayer, Tooltip, useMap } from 'react-leaflet';
import * as L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { useT } from '../../i18n/hooks';
import type { NtfpPlot } from '../../services/api';
import { VERDICT_RING, layerColour, layerLabel, plotColour, type PlotLayer, type PlotSummary } from '../../lib/ntfp';

interface Props {
  boundary?: any;
  plots: NtfpPlot[];
  transects?: { type: 'FeatureCollection'; features: any[] } | null;
  /** species_key -> the name to show in a plot's popup */
  names: Record<string, string>;
  height?: number;
  /** With these the icons carry a value (recorded/assigned, or a count) and a click selects the plot instead of opening the popup. */
  summaries?: Record<number, PlotSummary>;
  layer?: PlotLayer;
  selected?: number | null;
  onSelect?: (plotNumber: number) => void;
  /** plot number -> the verdict of its last "I am here" check: a blue ring (at the plot) or a red one (far away) */
  verdicts?: Record<number, string | null | undefined>;
  /** plots with something saved on the phone and not yet sent: drawn with a dashed outline */
  pending?: Set<number>;
}

function FitTo({ boundary, plots }: { boundary?: any; plots: NtfpPlot[] }) {
  const map = useMap();
  useEffect(() => {
    const bounds = L.latLngBounds([]);
    if (boundary) {
      try {
        bounds.extend(L.geoJSON(boundary).getBounds());
      } catch {
        /* an unreadable boundary only means we fit to the plots instead */
      }
    }
    plots.forEach((p) => bounds.extend([p.latitude, p.longitude]));
    if (bounds.isValid()) map.fitBounds(bounds, { padding: [20, 20] });
  }, [map, boundary, plots]);
  return null;
}

export default function NtfpPlotMap({ boundary, plots, transects, names, height = 420, summaries, layer = 'status', selected, onSelect, verdicts, pending }: Props) {
  const t = useT();
  const valued = !!summaries;
  const maxValue = useMemo(() => {
    if (!summaries) return 0;
    return Math.max(0, ...Object.values(summaries).map((s) => (layer === 'count' ? s.plants : layer.startsWith('species:') ? (s.counts[layer.slice(8)] ?? 0) : 0)));
  }, [summaries, layer]);
  // a new key re-creates the transect layer: react-leaflet's GeoJSON does not redraw when its data prop changes
  const transectKey = useMemo(() => `${plots.length}-${transects?.features.length ?? 0}-${plots[0]?.longitude ?? 0}`, [plots, transects]);
  return (
    <div style={{ height }} data-testid="ntfp-plot-map" aria-label={t('ntfp.design.mapLabel')}>
      <style>{`.ntfp-plot-label{background:transparent;border:0;box-shadow:none;font-weight:700;font-size:12px;color:#111;padding:0}.ntfp-plot-label:before{display:none}`}</style>
      <MapContainer center={[28.0, 84.0]} zoom={13} style={{ height: '100%', width: '100%' }} scrollWheelZoom>
        <TileLayer attribution="&copy; OpenStreetMap" url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
        {boundary && <GeoJSON key="boundary" data={boundary} style={{ color: '#1b5e20', weight: 2, fillOpacity: 0.04 }} />}
        {transects && transects.features.length > 0 && (
          <GeoJSON key={transectKey} data={transects as any} style={{ color: '#6d4c41', weight: 1, dashArray: '4 3' }} />
        )}
        {plots.map((p) => {
          const s = summaries?.[p.plot_number];
          const label = valued ? layerLabel(layer, s) : '';
          return (
            <CircleMarker key={`${p.plot_number}-${layer}-${s?.recorded ?? 0}-${s?.plants ?? 0}-${verdicts?.[p.plot_number] ?? ''}-${pending?.has(p.plot_number) ? 'p' : ''}`} center={[p.latitude, p.longitude]} radius={valued ? 13 : 5}
              eventHandlers={onSelect ? { click: () => onSelect(p.plot_number) } : undefined}
              pathOptions={{
                color: selected === p.plot_number ? '#000' : (VERDICT_RING[verdicts?.[p.plot_number] ?? ''] ?? '#1b5e20'),
                weight: selected === p.plot_number || verdicts?.[p.plot_number] || pending?.has(p.plot_number) ? 3 : 1,
                dashArray: pending?.has(p.plot_number) ? '3 3' : undefined,
                fillColor: valued ? layerColour(layer, s, maxValue) : plotColour(p.species_keys.length), fillOpacity: 0.95,
              }}>
              {valued && label && <Tooltip permanent direction="center" className="ntfp-plot-label">{label}</Tooltip>}
              {!valued && (
                <Popup>
                  <strong>{t('ntfp.design.plotN', { n: p.plot_number })}</strong>
                  <div>{p.stratum}</div>
                  <ul style={{ margin: 0, paddingLeft: 16 }}>
                    {p.species_keys.map((k) => <li key={k}>{names[k] ?? k}</li>)}
                  </ul>
                </Popup>
              )}
            </CircleMarker>
          );
        })}
        <FitTo boundary={boundary} plots={plots} />
      </MapContainer>
    </div>
  );
}
