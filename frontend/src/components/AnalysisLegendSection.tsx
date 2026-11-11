/**
 * The active Analysis map's legend inside the map's Legend panel, where there is room for it (the Layers panel is
 * small). Dynamic: only the classes this forest has, with unit count (SFM) or area and share (hazard).
 * Rendered only while an analysis map is on, so the Legend panel is unchanged otherwise.
 */
import type React from 'react';
import i18n from '../i18n';
import { useWorkspaceStore } from '../store/workspaceStore';
import { useT } from '../i18n/hooks';
import { useHazardLegend } from '../hooks/useHazardLegend';
import {
  analysisMapDef, chartSlug, dotsKind, dynamicLegend, hazardLayerKey, isDotsMap, isFiMap, isHazardMap, resolveAnalysisRenderer,
  type AnalysisMapId,
} from '../lib/analysisMaps';
import { useHazardHouseholds } from '../hooks/useHazardHouseholds';
import { useFieldGlyphs } from '../hooks/useFieldGlyphs';
import { useUnitMapQuery } from '../hooks/useUnitMap';
import { useSettledColours } from '../hooks/useSettledColours';
import { DOT_RAMP } from './map/HouseholdDotsLayer';
import { rendererLegendRows, type RendererSpec } from '../lib/layerRenderers';

interface Row { key: string; color: string; label: string; right: string }

/** `pickable`: a click on a row isolates that class's units on the map (the unit-class maps: SFM and field inventory). */
function Rows({ rows, pickable = false }: { rows: Row[]; pickable?: boolean }) {
  const active = useWorkspaceStore((s) => s.analysisHighlight);
  const toggle = useWorkspaceStore((s) => s.toggleAnalysisHighlight);
  return (
    <>
      {rows.map((r) => (
        <div
          key={r.key}
          className="legend-item"
          {...(pickable ? { role: 'button', tabIndex: 0, 'aria-pressed': !!active && active === r.color.toLowerCase(), style: { cursor: 'pointer', fontWeight: active === r.color.toLowerCase() ? 700 : undefined }, onClick: () => toggle(r.color), onKeyDown: (e: React.KeyboardEvent) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(r.color); } } } : {})}
        >
          <span className="legend-swatch" style={{ background: r.color }} />
          <span className="legend-label">{r.label}</span>
          <span className="legend-range">{r.right}</span>
        </div>
      ))}
    </>
  );
}

function SfmRows({ id }: { id: AnalysisMapId }) {
  const store = useWorkspaceStore();
  const spec = resolveAnalysisRenderer(id, store.layerRenderers as Record<string, RendererSpec | undefined>);
  if (!spec) return null;
  const entries = dynamicLegend(spec, rendererLegendRows(spec), store.sfmBlockTypes ?? {});
  return <Rows pickable rows={entries.map((e) => ({ key: String(e.index), color: e.color, label: e.label, right: `${e.count}${e.areaHa > 0 ? ` · ${e.areaHa.toLocaleString(undefined, { maximumFractionDigits: 1 })} ha` : ''}` }))} />;
}

function DotsRows({ id }: { id: AnalysisMapId }) {
  const store = useWorkspaceStore();
  const t = useT();
  const { data } = useHazardHouseholds(store.calculationId, dotsKind(id), store.analysisArea, store.geometryVersion);
  if (!data) return null;
  if (data.state !== 'ready') {
    return (
      <div className="legend-item">
        <span className="legend-label">
          {data.state === 'not_computed'
            ? t('analysisMaps.dotsNotComputed', { defaultValue: 'Needs the soil-loss, landslide and stability maps first — open the Hazard & Erosion tab.' })
            : data.state === 'no_user_group'
              ? t('analysisMaps.noUserGroup', { defaultValue: 'No user group boundary yet — draw it in the User group step.' })
              : t('analysisMaps.dotsNoData', { defaultValue: 'No placed households in this area.' })}
        </span>
      </div>
    );
  }
  const ramp = DOT_RAMP();
  return (
    <>
      <div className="legend-item">
        <span className="legend-label">{data.min.toFixed(2)}</span>
        <span style={{ flex: 1, height: 10, margin: '0 6px', background: `linear-gradient(to right, ${ramp.join(',')})` }} />
        <span className="legend-label">{data.max.toFixed(2)}</span>
      </div>
      <div className="legend-item">
        <span className="legend-label">
          {data.kind === 'settlements'
            ? t('analysisMaps.settlementsCount', { defaultValue: '{{n}} settlements (dot size = households)', n: data.count })
            : t('analysisMaps.householdsCount', { defaultValue: '{{n}} households · {{p}} priority', n: data.count, p: data.n_priority })}
        </span>
      </div>
    </>
  );
}

function HazardRows({ id }: { id: AnalysisMapId }) {
  const store = useWorkspaceStore();
  const t = useT();
  const ne = String(i18n.language || '').startsWith('ne');
  const colourVersion = useSettledColours(id);
  const { data } = useHazardLegend(store.calculationId, hazardLayerKey(id), store.geometryVersion, store.analysisArea, colourVersion);
  if (!data) return null;
  if (data.state !== 'ready') {
    return (
      <div className="legend-item">
        <span className="legend-label">
          {data.state === 'not_computed'
            ? t('analysisMaps.hazardNotComputed', { defaultValue: 'Not computed yet — open the Hazard & Erosion tab.' })
            : data.state === 'no_user_group'
              ? t('analysisMaps.noUserGroup', { defaultValue: 'No user group boundary yet — draw it in the User group step.' })
              : t('analysisMaps.noData', { defaultValue: 'No data for this layer in this forest.' })}
        </span>
      </div>
    );
  }
  return (
    <>
      <Rows
        rows={data.classes.map((c) => ({
          key: String(c.index),
          color: c.color,
          label: (ne ? c.label_ne : c.label_en) || (c.to == null ? `≥${c.from.toLocaleString(undefined, { maximumFractionDigits: 2 })}` : `${c.from.toLocaleString(undefined, { maximumFractionDigits: 2 })}–${c.to.toLocaleString(undefined, { maximumFractionDigits: 2 })}`),
          right: `${c.area_ha.toLocaleString(undefined, { maximumFractionDigits: 1 })} ha · ${c.share_pct.toLocaleString(undefined, { maximumFractionDigits: 1 })}%`,
        }))}
      />
      {data.relative && (
        <div className="legend-item"><span className="legend-label">{t('analysisMaps.relativeNote', { defaultValue: 'Classes are relative to this forest.' })}</span></div>
      )}
    </>
  );
}

function FiRows({ id }: { id: AnalysisMapId }) {
  const store = useWorkspaceStore();
  const t = useT();
  const ne = String(i18n.language || '').startsWith('ne');
  const colourVersion = useSettledColours(id);
  const { data } = useUnitMapQuery(store.calculationId, id, store.geometryVersion, colourVersion);
  if (!data) return null;
  if (data.state !== 'ready') {
    return (
      <div className="legend-item">
        <span className="legend-label">
          {data.state === 'not_computed'
            ? t('analysisMaps.chartNotComputed', { defaultValue: 'No field inventory yet — complete the Field inventory step.' })
            : t('analysisMaps.noData', { defaultValue: 'No data for this layer in this forest.' })}
        </span>
      </div>
    );
  }
  return <Rows pickable rows={data.legend.map((r) => ({ key: r.key, color: r.color, label: ne ? r.label_ne : r.label_en, right: `${r.count}${r.area_ha ? ` · ${r.area_ha.toLocaleString(undefined, { maximumFractionDigits: 1 })} ha` : ''}` }))} />;
}

function ChartRows({ id }: { id: AnalysisMapId }) {
  const store = useWorkspaceStore();
  const t = useT();
  const ne = String(i18n.language || '').startsWith('ne');
  const colourVersion = useSettledColours(id);
  const { data } = useFieldGlyphs(store.calculationId, chartSlug(id), store.geometryVersion, colourVersion);
  if (!data) return null;
  if (data.state !== 'ready') {
    return (
      <div className="legend-item">
        <span className="legend-label">
          {data.state === 'not_computed'
            ? t('analysisMaps.chartNotComputed', { defaultValue: 'No field inventory yet — complete the Field inventory step.' })
            : t('analysisMaps.noData', { defaultValue: 'No data for this layer in this forest.' })}
        </span>
      </div>
    );
  }
  return (
    <>
      <Rows rows={data.legend.map((c) => ({ key: String(c.index), color: c.color || 'transparent', label: ne ? c.label_ne : c.label_en, right: '' }))} />
      <div className="legend-item">
        <span className="legend-label">{t(`analysisMaps.howToRead.${id}`, { defaultValue: t('analysisMaps.chartHowToRead', { defaultValue: 'Bar height = timber stock (m³/ha); the label gives the share in trees of 40 cm and above.' }) })}</span>
      </div>
    </>
  );
}

export function AnalysisLegendSection() {
  const t = useT();
  const active = useWorkspaceStore((s) => s.activeAnalysisMap);
  const activeChart = useWorkspaceStore((s) => s.activeChart);
  const def = analysisMapDef(active);
  const chart = activeChart ? (
    <div className="legend-raster-group" data-testid="legend-chart">
      <div className="legend-section-title">{t('analysisMaps.charts', { defaultValue: 'Charts on the map' })}</div>
      <div className="legend-raster-name">{t(`analysisMaps.${activeChart}`, { defaultValue: analysisMapDef(activeChart)?.fallbackLabel })}</div>
      <ChartRows id={activeChart} />
    </div>
  ) : null;
  if (!active || !def) return chart;
  return (
    <>
      {chart}
    <div className="legend-raster-group" data-testid="legend-analysis-map">
      <div className="legend-section-title">{t('analysisMaps.title', { defaultValue: 'Analysis maps' })}</div>
      <div className="legend-raster-name">{t(def.labelKey, { defaultValue: def.fallbackLabel })}</div>
      {isFiMap(active) ? <FiRows id={active} /> : isDotsMap(active) ? <DotsRows id={active} /> : isHazardMap(active) ? <HazardRows id={active} /> : <SfmRows id={active} />}
    </div>
    </>
  );
}
