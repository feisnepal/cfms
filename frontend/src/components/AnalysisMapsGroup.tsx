/**
 * The "Analysis maps" group in the layer panel: ONE collapsed row (it names the active map while collapsed); expanded,
 * an "Off" choice plus the Sustainable-FM maps as radio rows. Only the active row carries its legend, the swatches to
 * change colours and the "Default colours" button, so inactive rows stay one line each.
 *
 * Colour edits are the ordinary `layer_renderers` entry `analysis:<id>`; the system default is computed, never stored
 * (lib/analysisMaps.ts).
 */
import { useState } from 'react';
import type L from 'leaflet';
import type { LayerTypeId } from '../lib/layerRegistry';
import { useInRouterContext, useNavigate } from 'react-router-dom';
import { useWorkspaceStore } from '../store/workspaceStore';
import { useT } from '../i18n/hooks';
import i18n from '../i18n';
import {
  ANALYSIS_MAPS,
  CHART_MAPS,
  chartSlug,
  FACTOR_MAPS,
  FI_MAPS,
  isFiMap,
  analysisMapDef,
  analysisRendererKey,
  dotsKind,
  withIndexColour,
  isDotsMap,
  isFactorMap,
  dynamicLegend,
  hasCustomColours,
  hazardLayerKey,
  isHazardMap,
  resolveAnalysisRenderer,
  type AnalysisMapId,
} from '../lib/analysisMaps';
import { rendererLegendRows, type RendererSpec } from '../lib/layerRenderers';
import { useHazardLegend } from '../hooks/useHazardLegend';
import { useHazardHouseholds } from '../hooks/useHazardHouseholds';
import { useSettledColours } from '../hooks/useSettledColours';
import { useFieldGlyphs } from '../hooks/useFieldGlyphs';
import { useUnitMapQuery } from '../hooks/useUnitMap';
import { PlaceholderIcon } from './PlaceholderIcon';
import { InventoryReportDialog } from './InventoryReportDialog';
import { COMPARABLE_MAPS } from '../lib/analysisHover';
import { rankUnits } from '../lib/unitRanking';
import { hasClassUnits, selectionFor, unitsOfClass, zoomToUnits } from '../lib/unitFocus';
import { DOT_RAMP } from './map/HouseholdDotsLayer';

/** A spec with the colour of legend row `i` replaced (categorized: class i; graduated: bucket i). */
export function withColour(spec: RendererSpec, i: number, colour: string): RendererSpec {
  if (spec.mode === 'categorized') {
    if (i >= spec.classes.length) return { ...spec, otherColor: colour };
    return { ...spec, classes: spec.classes.map((c, k) => (k === i ? { ...c, color: colour } : c)) };
  }
  return { ...spec, colors: spec.colors.map((c, k) => (k === i ? colour : c)), ramp: 'custom' };
}

/** The tab link. `useNavigate` needs a Router, and the panel is also rendered without one (tests, embeds): there the
 *  link is simply not offered. */
function OpenSfmLink({ calculationId, children, surface = 'analysis/sustainablefm' }: { calculationId?: string; children: string; surface?: string }) {
  const navigate = useNavigate();
  return (
    <button
      type="button"
      className="analysis-link"
      disabled={!calculationId}
      onClick={() => calculationId && navigate(`/calculations/${calculationId}?surface=${surface}`)}
    >
      {children}
    </button>
  );
}

const fmtHa = (n: number): string => n.toLocaleString(undefined, { maximumFractionDigits: 1 });
const fmtNum = (n: number): string => n.toLocaleString(undefined, { maximumFractionDigits: 2 });

function AreaChoice() {
  const t = useT();
  const store = useWorkspaceStore();
  return (
    <div className="analysis-area" role="radiogroup" aria-label={t('analysisMaps.area', { defaultValue: 'Area' })}>
      {(['forest', 'user_group'] as const).map((a) => (
        <label key={a} className="analysis-area-opt">
          <input type="radio" name="analysis-area" checked={store.analysisArea === a} onChange={() => store.setAnalysisArea(a)} />
          {a === 'forest' ? t('analysisMaps.areaForest', { defaultValue: 'Forest' }) : t('analysisMaps.areaUserGroup', { defaultValue: 'User group' })}
        </label>
      ))}
    </div>
  );
}

/** Household vulnerability / priority settlements: a score gradient over the dots, counts, the basis of the points. */
function DotsDetail({ id, calculationId, inRouter }: { id: AnalysisMapId; calculationId?: string; inRouter: boolean }) {
  const t = useT();
  const store = useWorkspaceStore();
  const { data, isLoading, isError } = useHazardHouseholds(calculationId, dotsKind(id), store.analysisArea, store.geometryVersion);
  const ramp = DOT_RAMP();
  return (
    <div className="analysis-map-detail" data-testid={`analysis-detail-${id}`}>
      <AreaChoice />
      {isLoading && <div role="status">{t('analysisMaps.loading', { defaultValue: 'Loading…' })}</div>}
      {isError && <div className="analysis-map-missing" role="status">{t('analysisMaps.legendFailed', { defaultValue: 'Legend unavailable.' })}</div>}
      {data && data.state !== 'ready' && (
        <div className="analysis-map-missing" role="status">
          {data.state === 'not_computed'
            ? t('analysisMaps.dotsNotComputed', { defaultValue: 'Needs the soil-loss, landslide and stability maps first — open the Hazard & Erosion tab.' })
            : data.state === 'no_user_group'
              ? t('analysisMaps.noUserGroup', { defaultValue: 'No user group boundary yet — draw it in the User group step.' })
              : t('analysisMaps.dotsNoData', { defaultValue: 'No placed households in this area.' })}
          {data.state === 'not_computed' && inRouter && (
            <OpenSfmLink calculationId={calculationId} surface="analysis/hazarderosion">
              {t('analysisMaps.openHazardTab', { defaultValue: 'Open in Hazard & Erosion tab' })}
            </OpenSfmLink>
          )}
        </div>
      )}
      {data?.state === 'ready' && (
        <>
          <label className="analysis-opacity">
            {t('analysisMaps.opacity', { defaultValue: 'Opacity' })}
            <input
              type="range" min={10} max={100} step={5}
              value={Math.round(store.analysisOpacity * 100)}
              onChange={(e) => store.setAnalysisOpacity(Number(e.target.value) / 100)}
              aria-label={t('analysisMaps.opacity', { defaultValue: 'Opacity' })}
            />
          </label>
          <div className="analysis-gradient" data-testid="analysis-dots-legend">
            <span>{data.min.toFixed(2)}</span>
            <span className="analysis-gradient-bar" style={{ background: `linear-gradient(to right, ${ramp.join(',')})` }} aria-hidden="true" />
            <span>{data.max.toFixed(2)}</span>
          </div>
          <div className="analysis-note">
            {data.kind === 'settlements'
              ? t('analysisMaps.settlementsCount', { defaultValue: '{{n}} settlements (dot size = households)', n: data.count })
              : t('analysisMaps.householdsCount', { defaultValue: '{{n}} households · {{p}} priority', n: data.count, p: data.n_priority })}
            {data.basis === 'buildings' && ` · ${t('analysisMaps.buildingBasis', { defaultValue: 'one stand-in per building footprint' })}`}
          </div>
        </>
      )}
    </div>
  );
}

/** Active hazard map: opacity, the dynamic legend (classes this forest has, area, share) and the tab link. */
function HazardDetail({ id, calculationId, inRouter, map }: { id: AnalysisMapId; calculationId?: string; inRouter: boolean; map?: L.Map | null }) {
  const t = useT();
  const store = useWorkspaceStore();
  const ne = String(i18n.language || '').startsWith('ne');
  const colourVersion = useSettledColours(id);
  const { data, isLoading, isError } = useHazardLegend(calculationId, hazardLayerKey(id), store.geometryVersion, store.analysisArea, colourVersion);
  const savedColours = store.layerRenderers as Record<string, RendererSpec | undefined>;
  const customColours = hasCustomColours(id, savedColours);
  if (isDotsMap(id)) return <DotsDetail id={id} calculationId={calculationId} inRouter={inRouter} />;
  const link = inRouter && (
    <OpenSfmLink calculationId={calculationId} surface="analysis/hazarderosion">
      {t('analysisMaps.openHazardTab', { defaultValue: 'Open in Hazard & Erosion tab' })}
    </OpenSfmLink>
  );
  return (
    <div className="analysis-map-detail" data-testid={`analysis-detail-${id}`}>
      <AreaChoice />
      {isLoading && <div role="status">{t('analysisMaps.loading', { defaultValue: 'Loading…' })}</div>}
      {isError && <div className="analysis-map-missing" role="status">{t('analysisMaps.legendFailed', { defaultValue: 'Legend unavailable.' })}</div>}
      {data?.state === 'not_computed' && (
        <div className="analysis-map-missing" role="status">
          {t('analysisMaps.hazardNotComputed', { defaultValue: 'Not computed yet — open the Hazard & Erosion tab.' })} {link}
        </div>
      )}
      {data?.state === 'no_user_group' && (
        <div className="analysis-map-missing" role="status">
          {t('analysisMaps.noUserGroup', { defaultValue: 'No user group boundary yet — draw it in the User group step.' })}
        </div>
      )}
      {data?.state === 'no_data' && (
        <div className="analysis-map-missing" role="status">
          {t('analysisMaps.noData', { defaultValue: 'No data for this layer in this forest.' })}
        </div>
      )}
      {data?.state === 'ready' && (
        <>
          <label className="analysis-opacity">
            {t('analysisMaps.opacity', { defaultValue: 'Opacity' })}
            <input
              type="range" min={10} max={100} step={5}
              value={Math.round(store.analysisOpacity * 100)}
              onChange={(e) => store.setAnalysisOpacity(Number(e.target.value) / 100)}
              aria-label={t('analysisMaps.opacity', { defaultValue: 'Opacity' })}
            />
          </label>
          <ul className="analysis-legend" data-testid="analysis-legend">
            {data.classes.map((c) => (
              <li key={c.index}>
                <input
                  type="color"
                  className="analysis-swatch"
                  value={/^#[0-9a-f]{6}$/i.test(c.color) ? c.color : '#bdbdbd'}
                  aria-label={t('analysisMaps.changeColour', { defaultValue: 'Change colour: {{label}}', label: (ne ? c.label_ne : c.label_en) || String(c.index) })}
                  onChange={(e) => store.setLayerRenderer(analysisRendererKey(id), withIndexColour(savedColours[analysisRendererKey(id)], c.index, e.target.value) as unknown as RendererSpec)}
                />
                <span>{(ne ? c.label_ne : c.label_en) || (c.to == null ? `≥${fmtNum(c.from)}` : `${fmtNum(c.from)}–${fmtNum(c.to)}`)}</span>
                <span className="analysis-count">{c.area_ha.toLocaleString(undefined, { maximumFractionDigits: 1 })} ha · {c.share_pct.toLocaleString(undefined, { maximumFractionDigits: 1 })}%</span>
              </li>
            ))}
          </ul>
          <RankingList id={id} map={map} />
          {data.relative && (
            <div className="analysis-note">{t('analysisMaps.relativeNote', { defaultValue: 'Classes are relative to this forest.' })}</div>
          )}
          <div className="analysis-actions">
            <button
              type="button"
              className="analysis-link"
              disabled={!customColours}
              onClick={() => store.setLayerRenderer(analysisRendererKey(id), null)}
              data-testid="analysis-default-colours"
            >
              {t('analysisMaps.defaultColours', { defaultValue: 'Default colours' })}
            </button>
            {link}
          </div>
          {customColours && (
            <div className="analysis-note" data-testid="analysis-colours-note">
              {t('analysisMaps.coloursUsedInHazard', { defaultValue: 'Your colours are also used in the Hazard & Erosion tab and the Operational Plan document.' })}
            </div>
          )}
        </>
      )}
    </div>
  );
}

/** The units in the isolated class: how many, and one click to select them in the attribute table or zoom to them. */
function ClassActions({ id, map }: { id: AnalysisMapId; map?: L.Map | null }) {
  const t = useT();
  const store = useWorkspaceStore();
  if (!store.analysisHighlight || !hasClassUnits(id)) return null;
  const names = unitsOfClass(id, store.analysisHighlight, { unitMap: store.unitMap, sfmBlockTypes: store.sfmBlockTypes, saved: store.layerRenderers as Record<string, RendererSpec | undefined> });
  if (names.length === 0) return null;
  return (
    <div className="analysis-class-actions" data-testid="analysis-class-actions">
      <span>{t('analysisMaps.classUnits', { defaultValue: '{{n}} units in this class', n: names.length })}</span>
      <button
        type="button"
        className="analysis-link"
        onClick={() => {
          const sel = selectionFor(names);
          if (sel) {
            store.setActiveLayer(sel.layerId as LayerTypeId); // the table shows this layer, with the units selected
            store.selectFeatures(sel.layerId, sel.ids);
          }
        }}
      >
        {t('analysisMaps.selectInTable', { defaultValue: 'Select in table' })}
      </button>
      <button type="button" className="analysis-link" onClick={() => zoomToUnits(map, names)}>
        {t('analysisMaps.zoomToClass', { defaultValue: 'Zoom to' })}
      </button>
    </div>
  );
}

/** Top and bottom units of the active map (maps whose per-unit fact is a number); click a unit to zoom to it and select it. */
function RankingList({ id, map }: { id: AnalysisMapId; map?: L.Map | null }) {
  const t = useT();
  const store = useWorkspaceStore();
  const r = rankUnits(id, { sfmBlockTypes: store.sfmBlockTypes, unitMap: store.unitMap, hazardUnits: store.hazardUnits });
  if (!r) return null;
  const go = (name: string) => {
    zoomToUnits(map, [name]);
    const sel = selectionFor([name]);
    if (sel) {
      store.setActiveLayer(sel.layerId as LayerTypeId);
      store.selectFeatures(sel.layerId, sel.ids);
    }
  };
  const list = (items: typeof r.top, title: string) => (
    <div className="analysis-rank-block">
      <div className="analysis-rank-title">{title}</div>
      <ol className="analysis-rank">
        {items.map((u) => (
          <li key={u.name}>
            <button type="button" className="analysis-link" onClick={() => go(u.name)} title={t('analysisMaps.rank.go', { defaultValue: 'Zoom to this unit' })}>{u.name}</button>
            <span className="analysis-count">{u.text}</span>
          </li>
        ))}
      </ol>
    </div>
  );
  return (
    <div className="analysis-ranking" data-testid="analysis-ranking">
      {r.bottom.length === 0
        ? list(r.top, t('analysisMaps.rank.all', { defaultValue: 'Units, highest first' }))
        : <>
            {list(r.top, t(r.highIsWorse ? 'analysisMaps.rank.worst' : 'analysisMaps.rank.top'))}
            {list(r.bottom, t('analysisMaps.rank.bottom', { defaultValue: 'Lowest' }))}
          </>}
    </div>
  );
}

/** Compare with a second map: its fact is added under the first on every hover card; the colouring does not change. */
function CompareSection() {
  const t = useT();
  const store = useWorkspaceStore();
  if (!store.activeAnalysisMap) return null;
  const options = COMPARABLE_MAPS.filter((m) => m !== store.activeAnalysisMap);
  return (
    <label className="analysis-row analysis-factor-row" data-testid="analysis-compare">
      <span>{t('analysisMaps.compareWith', { defaultValue: 'Compare with' })}</span>
      <select
        value={store.compareMap ?? ''}
        aria-label={t('analysisMaps.compareWith', { defaultValue: 'Compare with' })}
        onChange={(e) => store.setCompareMap(e.target.value ? (e.target.value as AnalysisMapId) : null)}
      >
        <option value="">—</option>
        {options.map((m) => (
          <option key={m} value={m}>{t(`analysisMaps.${m}`, { defaultValue: analysisMapDef(m)?.fallbackLabel })}</option>
        ))}
      </select>
    </label>
  );
}

/** A legend class's name as a button: click to isolate that class's units on the map, click again to show all. */
function ClassButton({ color, label }: { color: string; label: string }) {
  const t = useT();
  const active = useWorkspaceStore((s) => s.analysisHighlight);
  const store = useWorkspaceStore();
  const on = !!active && active === color.toLowerCase();
  return (
    <button
      type="button"
      className={`analysis-class-btn${on ? ' analysis-class-btn-on' : ''}`}
      aria-pressed={on}
      title={t('analysisMaps.isolateClass', { defaultValue: 'Show only the units in this class on the map (click again to show all)' })}
      onClick={() => store.toggleAnalysisHighlight(color)}
    >
      {label}
    </button>
  );
}

/** A single-number field-inventory map: the server's classes/colours as a dynamic legend (only classes in use, with unit counts),
 *  editable swatches (not for the bivariate one), reset, and where the colours are used. */
function FiDetail({ id, calculationId, map }: { id: AnalysisMapId; calculationId?: string; map?: L.Map | null }) {
  const t = useT();
  const store = useWorkspaceStore();
  const ne = String(i18n.language || '').startsWith('ne');
  const colourVersion = useSettledColours(id);
  const { data, isLoading, isError } = useUnitMapQuery(calculationId, id, store.geometryVersion, colourVersion);
  const saved = store.layerRenderers as Record<string, RendererSpec | undefined>;
  const custom = hasCustomColours(id, saved);
  return (
    <div className="analysis-map-detail" data-testid={`analysis-detail-${id}`}>
      {isLoading && <div role="status">{t('analysisMaps.loading', { defaultValue: 'Loading…' })}</div>}
      {isError && <div className="analysis-map-missing" role="status">{t('analysisMaps.legendFailed', { defaultValue: 'Legend unavailable.' })}</div>}
      {data && data.state !== 'ready' && (
        <div className="analysis-map-missing" role="status">
          {data.state === 'not_computed'
            ? t('analysisMaps.chartNotComputed', { defaultValue: 'No field inventory yet — complete the Field inventory step.' })
            : t('analysisMaps.noData', { defaultValue: 'No data for this layer in this forest.' })}
        </div>
      )}
      {data?.state === 'ready' && (
        <>
          <ul className="analysis-legend" data-testid="analysis-legend">
            {data.legend.map((r) => (
              <li key={r.key}>
                {r.editable ? (
                  <input
                    type="color"
                    className="analysis-swatch"
                    value={/^#[0-9a-f]{6}$/i.test(r.color) ? r.color : '#bdbdbd'}
                    aria-label={t('analysisMaps.changeColour', { defaultValue: 'Change colour: {{label}}', label: ne ? r.label_ne : r.label_en })}
                    onChange={(e) => store.setLayerRenderer(analysisRendererKey(id), withIndexColour(saved[analysisRendererKey(id)], r.key, e.target.value) as unknown as RendererSpec)}
                  />
                ) : (
                  <span className="analysis-swatch" style={{ background: r.color }} aria-hidden="true" />
                )}
                <ClassButton color={r.color} label={ne ? r.label_ne : r.label_en} />
                <span className="analysis-count">{r.count}{r.area_ha ? ` · ${fmtHa(r.area_ha)} ha` : ''}</span>
              </li>
            ))}
          </ul>
          <ClassActions id={id} map={map} />
          <RankingList id={id} map={map} />
          <div className="analysis-actions">
            <button
              type="button"
              className="analysis-link"
              disabled={!custom}
              onClick={() => store.setLayerRenderer(analysisRendererKey(id), null)}
              data-testid="analysis-default-colours"
            >
              {t('analysisMaps.defaultColours', { defaultValue: 'Default colours' })}
            </button>
          </div>
          {custom && (
            <div className="analysis-note" data-testid="analysis-colours-note">
              {t('analysisMaps.coloursUsedInPlan', { defaultValue: 'Your colours are also used in the Operational Plan document.' })}
            </div>
          )}
        </>
      )}
    </div>
  );
}

/** The chart overlay: one chart at a time, chosen from a dropdown, drawn over whatever colouring is on. */
function ChartsSection({ calculationId }: { calculationId?: string }) {
  const t = useT();
  const store = useWorkspaceStore();
  const active = store.activeChart;
  return (
    <div data-testid="analysis-charts">
      <div className="analysis-heading">{t('analysisMaps.charts', { defaultValue: 'Charts on the map' })}</div>
      <label className="analysis-row analysis-factor-row">
        <span>{t('analysisMaps.chartPick', { defaultValue: 'Chart' })}</span>
        <select
          value={active ?? ''}
          aria-label={t('analysisMaps.chartPick', { defaultValue: 'Chart' })}
          onChange={(e) => store.setActiveChart(e.target.value ? (e.target.value as AnalysisMapId) : null)}
        >
          <option value="">—</option>
          {CHART_MAPS.map((c) => (
            <option key={c.id} value={c.id}>{t(`analysisMaps.${c.id}`, { defaultValue: c.fallbackLabel })}</option>
          ))}
        </select>
      </label>
      {active && (
        <>
          <div className="analysis-row-line" style={{ justifyContent: 'flex-end' }}>
            <PlaceholderIcon id={active} calculationId={calculationId} />
          </div>
          <ChartDetail id={active} calculationId={calculationId} />
        </>
      )}
    </div>
  );
}

/** The chart's dynamic legend (only the classes this forest has), editable colours where the print map's are editable, reset,
 *  and how to read it. */
function ChartDetail({ id, calculationId }: { id: AnalysisMapId; calculationId?: string }) {
  const t = useT();
  const store = useWorkspaceStore();
  const ne = String(i18n.language || '').startsWith('ne');
  const colourVersion = useSettledColours(id);
  const { data, isLoading, isError } = useFieldGlyphs(calculationId, chartSlug(id), store.geometryVersion, colourVersion);
  const saved = store.layerRenderers as Record<string, RendererSpec | undefined>;
  const custom = hasCustomColours(id, saved);
  const editable = data?.state === 'ready' && data.editable !== false;
  return (
    <div className="analysis-map-detail" data-testid={`analysis-detail-${id}`}>
      {isLoading && <div role="status">{t('analysisMaps.loading', { defaultValue: 'Loading…' })}</div>}
      {isError && <div className="analysis-map-missing" role="status">{t('analysisMaps.legendFailed', { defaultValue: 'Legend unavailable.' })}</div>}
      {data && data.state !== 'ready' && (
        <div className="analysis-map-missing" role="status">
          {data.state === 'not_computed'
            ? t('analysisMaps.chartNotComputed', { defaultValue: 'No field inventory yet — complete the Field inventory step.' })
            : t('analysisMaps.noData', { defaultValue: 'No data for this layer in this forest.' })}
        </div>
      )}
      {data?.state === 'ready' && (
        <>
          <ul className="analysis-legend" data-testid="analysis-legend">
            {data.legend.map((c) => (
              <li key={c.index}>
                {editable && c.color ? (
                  <input
                    type="color"
                    className="analysis-swatch"
                    value={/^#[0-9a-f]{6}$/i.test(c.color) ? c.color : '#bdbdbd'}
                    aria-label={t('analysisMaps.changeColour', { defaultValue: 'Change colour: {{label}}', label: ne ? c.label_ne : c.label_en })}
                    onChange={(e) => store.setLayerRenderer(analysisRendererKey(id), withIndexColour(saved[analysisRendererKey(id)], c.override_key ?? c.index, e.target.value) as unknown as RendererSpec)}
                  />
                ) : c.color ? (
                  <span className="analysis-swatch" style={{ background: c.color }} aria-hidden="true" />
                ) : null}
                <span>{ne ? c.label_ne : c.label_en}</span>
              </li>
            ))}
          </ul>
          <div className="analysis-note">{t(`analysisMaps.howToRead.${id}`, { defaultValue: t('analysisMaps.chartHowToRead', { defaultValue: 'Bar height = timber stock (m³/ha); the label gives the share in trees of 40 cm and above.' }) })}</div>
          {editable && (
            <div className="analysis-actions">
              <button
                type="button"
                className="analysis-link"
                disabled={!custom}
                onClick={() => store.setLayerRenderer(analysisRendererKey(id), null)}
                data-testid="analysis-default-colours"
              >
                {t('analysisMaps.defaultColours', { defaultValue: 'Default colours' })}
              </button>
            </div>
          )}
          {custom && (
            <div className="analysis-note" data-testid="analysis-colours-note">
              {t('analysisMaps.coloursUsedInDocument', { defaultValue: 'Your colours are also used in the Sustainable FM tab and the Operational Plan document.' })}
            </div>
          )}
        </>
      )}
    </div>
  );
}

export function AnalysisMapsGroup({ calculationId, map = null }: { calculationId?: string; map?: L.Map | null }) {
  const t = useT();
  const inRouter = useInRouterContext();
  const store = useWorkspaceStore();
  const [open, setOpen] = useState(false);
  const [reportOpen, setReportOpen] = useState(false);
  const active = store.activeAnalysisMap;
  const saved = store.layerRenderers as Record<string, RendererSpec | undefined>;
  const activeDef = analysisMapDef(active);
  const noSfm = Object.keys(store.sfmBlockTypes ?? {}).length === 0;

  const label = (id: AnalysisMapId) => {
    const d = analysisMapDef(id)!;
    return t(d.labelKey, { defaultValue: d.fallbackLabel });
  };

  const renderActiveDetail = (id: AnalysisMapId) => {
    const spec = resolveAnalysisRenderer(id, saved);
    if (!spec) return null;
    const entries = dynamicLegend(spec, rendererLegendRows(spec), store.sfmBlockTypes ?? {});
    const custom = hasCustomColours(id, saved);
    return (
      <div className="analysis-map-detail" data-testid={`analysis-detail-${id}`}>
        {noSfm && (
          <div className="analysis-map-missing" role="status">
            {t('analysisMaps.notComputed', { defaultValue: 'Not computed yet — open the Sustainable FM tab.' })}{' '}
            {inRouter && (
              <OpenSfmLink calculationId={calculationId}>{t('analysisMaps.openSfm', { defaultValue: 'Open' })}</OpenSfmLink>
            )}
          </div>
        )}
        <ul className="analysis-legend" data-testid="analysis-legend">
          {entries.map((r) => (
            <li key={`${r.label}-${r.index}`}>
              <input
                type="color"
                className="analysis-swatch"
                value={/^#[0-9a-f]{6}$/i.test(r.color) ? r.color : '#bdbdbd'}
                aria-label={t('analysisMaps.changeColour', { defaultValue: 'Change colour: {{label}}', label: r.label })}
                onChange={(e) => store.setLayerRenderer(analysisRendererKey(id), withColour(spec, r.index, e.target.value))}
              />
              <ClassButton color={r.color} label={r.label} />
              <span className="analysis-count">{r.count}{r.areaHa > 0 ? ` · ${fmtHa(r.areaHa)} ha` : ''}</span>
            </li>
          ))}
        </ul>
        <ClassActions id={id} map={map} />
        <RankingList id={id} map={map} />
        <div className="analysis-actions">
          <button
            type="button"
            className="analysis-link"
            disabled={!custom}
            onClick={() => store.setLayerRenderer(analysisRendererKey(id), null)}
            data-testid="analysis-default-colours"
          >
            {t('analysisMaps.defaultColours', { defaultValue: 'Default colours' })}
          </button>
          {inRouter && (
            <OpenSfmLink calculationId={calculationId}>
              {t('analysisMaps.openSfmTab', { defaultValue: 'Open in Sustainable FM tab' })}
            </OpenSfmLink>
          )}
        </div>
        {custom && (
          <div className="analysis-note" data-testid="analysis-colours-note">
            {t('analysisMaps.coloursUsedInDocument', { defaultValue: 'Your colours are also used in the Sustainable FM tab and the Operational Plan document.' })}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="analysis-maps" data-testid="analysis-maps-group">
      <button
        type="button"
        className="analysis-maps-header"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <span aria-hidden="true">{open ? '▾' : '▸'}</span> <span aria-hidden="true">🗺</span>{' '}
        {t('analysisMaps.title', { defaultValue: 'Analysis maps' })}
        {activeDef && <span className="analysis-maps-active"> · {label(activeDef.id)}</span>}
      </button>
      {open && (
        <>
        <div role="radiogroup" aria-label={t('analysisMaps.title', { defaultValue: 'Analysis maps' })}>
          <label className="analysis-row">
            <input type="radio" name="analysis-map" checked={active == null} onChange={() => store.setActiveAnalysisMap(null)} />
            {t('analysisMaps.off', { defaultValue: 'Off' })}
          </label>
          <div className="analysis-heading">{t('analysisMaps.sfm', { defaultValue: 'Sustainable forest management' })}</div>
          {ANALYSIS_MAPS.filter((m) => m.group === 'sfm').map((m) => (
            <div key={m.id}>
              <div className="analysis-row-line">
                <label className="analysis-row">
                  <input
                    type="radio"
                    name="analysis-map"
                    checked={active === m.id}
                    onChange={() => store.setActiveAnalysisMap(m.id)}
                  />
                  {label(m.id)}
                </label>
                <PlaceholderIcon id={m.id} calculationId={calculationId} />
              </div>
              {active === m.id && renderActiveDetail(m.id)}
            </div>
          ))}
          <div className="analysis-heading">{t('analysisMaps.hazard', { defaultValue: 'Hazard & erosion' })}</div>
          {ANALYSIS_MAPS.filter((m) => m.group === 'hazard').map((m) => (
            <div key={m.id}>
              <div className="analysis-row-line">
                <label className="analysis-row">
                  <input type="radio" name="analysis-map" checked={active === m.id} onChange={() => store.setActiveAnalysisMap(m.id)} />
                  {label(m.id)}
                </label>
                <PlaceholderIcon id={m.id} calculationId={calculationId} />
              </div>
              {active === m.id && <HazardDetail id={m.id} calculationId={calculationId} inRouter={inRouter} map={map} />}
            </div>
          ))}
          <label className="analysis-row analysis-factor-row">
            <span>{t('analysisMaps.factors', { defaultValue: 'Factor layers' })}</span>
            <select
              value={isFactorMap(active) ? active! : ''}
              aria-label={t('analysisMaps.factors', { defaultValue: 'Factor layers' })}
              onChange={(e) => store.setActiveAnalysisMap(e.target.value ? (e.target.value as AnalysisMapId) : null)}
            >
              <option value="">—</option>
              {FACTOR_MAPS.map((f) => (
                <option key={f.id} value={f.id}>{label(f.id)}</option>
              ))}
            </select>
          </label>
          {isFactorMap(active) && (
            <>
              <div className="analysis-row-line" style={{ justifyContent: 'flex-end' }}>
                <PlaceholderIcon id={active!} calculationId={calculationId} />
              </div>
              <HazardDetail id={active!} calculationId={calculationId} inRouter={inRouter} />
            </>
          )}
          <div className="analysis-heading">{t('analysisMaps.fieldInventory', { defaultValue: 'Field inventory' })}</div>
          <button type="button" className="analysis-link-button" data-testid="open-inventory-report" onClick={() => setReportOpen(true)}>
            {t('inventoryReport.open', { defaultValue: 'Inventory by sub-unit…' })}
          </button>
          {reportOpen && calculationId && (
            <InventoryReportDialog calculationId={calculationId} open={reportOpen} onClose={() => setReportOpen(false)} geometryVersion={store.geometryVersion} />
          )}
          <label className="analysis-row analysis-factor-row">
            <span>{t('analysisMaps.colourByValue', { defaultValue: 'Colour units by' })}</span>
            <select
              value={isFiMap(active) ? active! : ''}
              aria-label={t('analysisMaps.fieldInventory', { defaultValue: 'Field inventory' })}
              onChange={(e) => store.setActiveAnalysisMap(e.target.value ? (e.target.value as AnalysisMapId) : null)}
            >
              <option value="">—</option>
              {FI_MAPS.map((f) => (
                <option key={f.id} value={f.id}>{label(f.id)}</option>
              ))}
            </select>
          </label>
          {isFiMap(active) && (
            <>
              <div className="analysis-row-line" style={{ justifyContent: 'flex-end' }}>
                <PlaceholderIcon id={active!} calculationId={calculationId} />
              </div>
              <FiDetail id={active!} calculationId={calculationId} map={map} />
            </>
          )}
        </div>
        <CompareSection />
        <ChartsSection calculationId={calculationId} />
        </>
      )}
    </div>
  );
}
