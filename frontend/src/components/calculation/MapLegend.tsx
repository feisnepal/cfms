/**
 * The dynamic legend shown just below a map in the Sustainable Forest Management and Hazard & Erosion tabs.
 *
 * Dynamic means it lists only what THIS forest has - the forest types, orientations, stock or hazard classes that occur - with what each covers
 * (units and hectares for the SFM maps, hectares and share for the hazard rasters), coloured exactly as the map is. It reads the server's
 * stored result only (the same colour source as the print maps and the workspace) and never starts a computation.
 */
import React, { useEffect, useState } from 'react';
import i18n from '../../i18n';
import { useT } from '../../i18n/hooks';
import { formatDecimal, formatNumber } from '../../i18n/numberFormat';
import {
  hazardErosionApi,
  sfmApi,
  type HazardDotsSummary,
  type HazardMapLegend as HazardLegendData,
  type SfmMapLegend as SfmLegendData,
  type SfmVariant,
} from '../../services/api';
import { sampleRamp } from '../../lib/colorRamps';
import { SfmTypeTag } from './SfmTypeTag';

// ── presentation ────────────────────────────────────────────────────────────────────────────────────────────────────────────
interface Row {
  key: string;
  color: string;
  label: React.ReactNode;
  detail?: string;
}

function LegendBox({ rows, note, message, testId }: { rows?: Row[]; note?: string | null; message?: string | null; testId: string }) {
  const t = useT();
  return (
    <div
      data-testid={testId}
      style={{ marginTop: 8, padding: '8px 12px', border: '1px solid #f0f0f0', borderRadius: 8, background: '#fff' }}
    >
      <div style={{ fontSize: 12, fontWeight: 600, color: '#444', marginBottom: 4 }}>{t('mapLegend.title')}</div>
      {message && <div style={{ fontSize: 12, color: '#888' }}>{message}</div>}
      {rows && rows.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: '4px 16px' }}>
          {rows.map((r) => (
            <div key={r.key} data-testid={`legend-row-${r.key}`} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
              <span
                aria-hidden="true"
                style={{ width: 14, height: 14, flex: '0 0 14px', background: r.color, border: '1px solid rgba(0,0,0,0.2)', display: 'inline-block' }}
              />
              <span style={{ color: '#333' }}>{r.label}</span>
              {r.detail && <span style={{ marginLeft: 'auto', color: '#777', whiteSpace: 'nowrap' }}>{r.detail}</span>}
            </div>
          ))}
        </div>
      )}
      {note && <div style={{ marginTop: 6, fontSize: 11, color: '#888' }}>{note}</div>}
    </div>
  );
}

// ── Sustainable Forest Management ──────────────────────────────────────────────────────────────────────────────────────────────
export function SfmMapLegend({
  calculationId,
  specKey,
  variant,
  refreshKey = 0,
}: {
  calculationId: string;
  specKey: string;
  variant?: SfmVariant;
  refreshKey?: number;
}) {
  const t = useT();
  const [data, setData] = useState<SfmLegendData | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let live = true;
    setData(null);
    setFailed(false);
    sfmApi
      .getMapLegend(calculationId, specKey, variant)
      .then((d) => live && setData(d))
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
  }, [calculationId, specKey, variant, refreshKey]);

  if (failed) return <LegendBox testId="map-legend" message={t('mapLegend.failed')} />;
  if (!data) return <LegendBox testId="map-legend" message={t('mapLegend.loading')} />;
  if (data.state !== 'ready') return <LegendBox testId="map-legend" message={t('mapLegend.sfmNotComputed')} />;

  const gsLabels = [`< 150 ${t('sfm.map.gsUnit')}`, `150 – 200 ${t('sfm.map.gsUnit')}`, `> 200 ${t('sfm.map.gsUnit')}`];
  const lang = String(i18n.language || '').startsWith('ne') ? 'ne' : 'en';
  const rows: Row[] = data.classes.map((c) => {
    let label: React.ReactNode = lang === 'ne' ? c.label_ne || c.label_en : c.label_en || c.label_ne;
    if (specKey === 'sfm__forest_type' && /^\d+$/.test(c.key)) label = <SfmTypeTag n={Number(c.key)} />;
    else if (specKey === 'sfm__orientation') label = t(`sfm.orientation.${c.key}`, c.key);
    else if (specKey === 'sfm__gs_vs_threshold' && /^\d+$/.test(c.key) && gsLabels[Number(c.key)]) label = gsLabels[Number(c.key)];
    return {
      key: c.key,
      color: c.color,
      label,
      detail: t('mapLegend.sfmDetail', {
        count: formatNumber(c.count ?? 0),
        area: formatDecimal(c.area_ha, 1),
        share: formatDecimal(c.share_pct, 1),
      }),
    };
  });
  return <LegendBox testId="map-legend" rows={rows} note={t('mapLegend.sfmNote', { area: formatDecimal(data.total_ha, 1) })} />;
}

// ── Hazard & Erosion ──────────────────────────────────────────────────────────────────────────────────────────────────────────
export interface HazardLegendTarget {
  /** a raster layer served by /hazard-legend/{layer}, or the dots of households / settlements */
  kind: 'raster' | 'dots';
  layer: string;
  area: 'forest' | 'user_group';
}

const LSI_FACTORS = ['slope', 'lithology', 'curvature_twi', 'dist_drainage', 'dist_road', 'landcover', 'landcover_change', 'aspect', 'rainfall', 'soil_texture'];

/** Which legend source a hazard map token ("thememap:hazard__landslide_susceptibility__user_group" ...) uses; null when it has none. */
export function hazardLegendTarget(token: string): HazardLegendTarget | null {
  let base = String(token || '').replace(/^thememap:/, '');
  const area: 'forest' | 'user_group' = base.endsWith('__user_group') ? 'user_group' : 'forest';
  base = base.replace(/__user_group$/, '');
  const raster: Record<string, string> = {
    soil__annual_loss: 'soil',
    hazard__landslide_susceptibility: 'lsi',
    hazard__factor_of_safety: 'fs',
    hazard__landslide_prone_area: 'prone',
  };
  if (raster[base]) return { kind: 'raster', layer: raster[base], area };
  const soil = /^soil__factor_(r|k|ls|c)$/.exec(base);
  if (soil) return { kind: 'raster', layer: `f_soil_${soil[1]}`, area };
  const lsi = /^hazard__lsi_factor_(.+)$/.exec(base);
  if (lsi && LSI_FACTORS.includes(lsi[1])) return { kind: 'raster', layer: `f_lsi_${lsi[1]}`, area };
  if (base === 'hh__vulnerability') return { kind: 'dots', layer: 'households', area };
  if (base === 'hh__priority_settlements') return { kind: 'dots', layer: 'settlements', area };
  return null;
}

export function HazardMapLegend({
  calculationId,
  mapKey,
  lang = 'en',
  refreshKey = 0,
}: {
  calculationId: string;
  mapKey: string;
  lang?: string;
  refreshKey?: number;
}) {
  const t = useT();
  const target = hazardLegendTarget(mapKey);
  const [raster, setRaster] = useState<HazardLegendData | null>(null);
  const [dots, setDots] = useState<HazardDotsSummary | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let live = true;
    setRaster(null);
    setDots(null);
    setFailed(false);
    if (!target || !calculationId) return;
    const call =
      target.kind === 'raster'
        ? hazardErosionApi.getMapLegend(calculationId, target.layer, target.area).then((d) => live && setRaster(d))
        : hazardErosionApi.getDotsSummary(calculationId, target.layer as 'households' | 'settlements', target.area).then((d) => live && setDots(d));
    call.catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [calculationId, mapKey, refreshKey]);

  if (!target) return null; // a map with no legend source: the image carries its own
  if (failed) return <LegendBox testId="map-legend" message={t('mapLegend.failed')} />;

  if (target.kind === 'dots') {
    if (!dots) return <LegendBox testId="map-legend" message={t('mapLegend.loading')} />;
    if (dots.state !== 'ready') {
      return (
        <LegendBox
          testId="map-legend"
          message={
            dots.state === 'not_computed'
              ? t('analysisMaps.dotsNotComputed', { defaultValue: 'Needs the soil-loss, landslide and stability maps first.' })
              : dots.state === 'no_user_group'
                ? t('analysisMaps.noUserGroup', { defaultValue: 'No user group boundary yet.' })
                : t('analysisMaps.dotsNoData', { defaultValue: 'No placed households in this area.' })
          }
        />
      );
    }
    return (
      <div data-testid="map-legend" style={{ marginTop: 8, padding: '8px 12px', border: '1px solid #f0f0f0', borderRadius: 8, background: '#fff' }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: '#444', marginBottom: 4 }}>{t('mapLegend.title')}</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
          <span>{t('mapLegend.dotsLow', { value: formatDecimal(dots.min, 2) })}</span>
          <span
            aria-hidden="true"
            data-testid="legend-gradient"
            style={{ flex: '0 1 240px', height: 10, background: `linear-gradient(to right, ${sampleRamp('reds', 9).join(',')})` }}
          />
          <span>{t('mapLegend.dotsHigh', { value: formatDecimal(dots.max, 2) })}</span>
        </div>
        <div style={{ marginTop: 4, fontSize: 12, color: '#555' }}>
          {dots.kind === 'settlements'
            ? t('analysisMaps.settlementsCount', { defaultValue: '{{n}} settlements (dot size = households)', n: dots.count })
            : t('analysisMaps.householdsCount', { defaultValue: '{{n}} households · {{p}} priority', n: dots.count, p: dots.n_priority })}
        </div>
      </div>
    );
  }

  if (!raster) return <LegendBox testId="map-legend" message={t('mapLegend.loading')} />;
  if (raster.state !== 'ready') {
    return (
      <LegendBox
        testId="map-legend"
        message={
          raster.state === 'not_computed'
            ? t('analysisMaps.hazardNotComputed', { defaultValue: 'Not computed yet.' })
            : raster.state === 'no_user_group'
              ? t('analysisMaps.noUserGroup', { defaultValue: 'No user group boundary yet.' })
              : t('analysisMaps.noData', { defaultValue: 'No data for this layer in this forest.' })
        }
      />
    );
  }
  const ne = String(lang).startsWith('ne');
  const range = (c: { from: number; to: number | null }) =>
    c.to == null ? `≥ ${formatDecimal(c.from, 2)}` : `${formatDecimal(c.from, 2)} – ${formatDecimal(c.to, 2)}`;
  const rows: Row[] = raster.classes.map((c) => ({
    key: String(c.index),
    color: c.color,
    label: (ne ? c.label_ne : c.label_en) || range(c),
    detail: t('mapLegend.hazardDetail', { area: formatDecimal(c.area_ha, 1), share: formatDecimal(c.share_pct, 1) }),
  }));
  return (
    <LegendBox
      testId="map-legend"
      rows={rows}
      note={raster.relative ? t('analysisMaps.relativeNote', { defaultValue: 'Classes are relative to this forest.' }) : null}
    />
  );
}
