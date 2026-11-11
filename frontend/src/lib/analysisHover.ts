/**
 * What a user sees when they HOVER a block / compartment / sub-unit while an Analysis map is on: the same main fact the legend
 * gives for that unit — the map's name, the CLASS the unit falls in (with its legend colour) and its VALUE — so nobody has to
 * match a colour to the legend by eye.
 *
 * Pure: reads the merged feature properties (`sfm_*`, `hz_*`, `um_*`) the map already carries and the same renderers / legend rows
 * the legend uses, so the card and the legend can never disagree. The card is HTML for a Leaflet tooltip; EVERY dynamic piece
 * (unit name included) is escaped, and a colour must be a plain #rrggbb before it reaches a style attribute.
 */
import { analysisMapDef, resolveAnalysisRenderer, type AnalysisMapId } from './analysisMaps';
import { rendererColorFor, rendererLegendRows, type RendererSpec } from './layerRenderers';
import { SFM_NO_TYPE } from './sfmFeatureProps';
import { escapeHtml } from './sfmForestTypes';
import type { UnitMapLegendRow } from './unitMapProps';

type Tr = (key: string, opts?: Record<string, unknown>) => string;

export interface HoverFact {
  /** the map's name, e.g. "Growing Stock Map (per ha)" */
  map: string;
  /** the legend colour of the unit's class (null when the map has no per-unit class colour, e.g. hazard rasters) */
  swatch: string | null;
  /** the class, as the legend names it ("51.85 – 70.67", "Type-7", "Weak") */
  heading: string | null;
  /** the unit's value ("80 m³/ha") */
  value: string | null;
  /** further facts worth a glance */
  lines: string[];
}

export interface HoverOptions {
  lang: string;
  t: Tr;
  saved: Record<string, RendererSpec | undefined>;
  /** the active field-inventory map's legend rows (server), to name a unit's class */
  unitLegend?: UnitMapLegendRow[];
}

const num = (v: unknown): number | null => (v == null || v === '' ? null : Number.isFinite(Number(v)) ? Number(v) : null);
const pct = (v: unknown): string | null => (num(v) == null ? null : `${Math.round(num(v)!)}%`);
const sameColour = (a: string | null | undefined, b: string | null | undefined): boolean => !!a && !!b && a.toLowerCase() === b.toLowerCase();

export function analysisHoverFact(id: AnalysisMapId | null | undefined, p: Record<string, unknown>, o: HoverOptions): HoverFact | null {
  if (!id) return null;
  const def = analysisMapDef(id);
  if (!def) return null;
  const { t } = o;
  const ne = String(o.lang || '').startsWith('ne');
  const map = t(def.labelKey, { defaultValue: def.fallbackLabel });
  const fact = (f: Partial<HoverFact>): HoverFact => ({ map, swatch: null, heading: null, value: null, lines: [], ...f });

  if (id === 'sfm_type' || id === 'sfm_orientation' || id === 'sfm_stock') {
    if (p.sfm_type == null) return null; // a unit the SFM tab has not classified
    const spec = resolveAnalysisRenderer(id, o.saved);
    const colourFor = (v: unknown) => (spec ? rendererColorFor(spec, v) : null);
    const noType = p.sfm_type === SFM_NO_TYPE;
    const typeLabel = noType ? t(p.sfm_state === 'non_forest' ? 'sfm.state.nonForest' : 'sfm.state.noPlots') : t('sfm.ref.typeDash', { n: p.sfm_type });
    const plots = num(p.sfm_plot_count);
    const plotsLine = plots != null ? t('analysisMaps.hover.plots', { defaultValue: '{{n}} sample plots', n: plots }) : null;
    if (id === 'sfm_type') {
      return fact({
        swatch: colourFor(p.sfm_type),
        heading: typeLabel,
        value: p.sfm_slope_band ? String(p.sfm_slope_band) : null,
        lines: [plotsLine, p.sfm_state === 'provisional' ? t('analysisMaps.hover.provisional', { defaultValue: 'Provisional (few plots)' }) : null,
          p.sfm_orientation && p.sfm_orientation !== SFM_NO_TYPE ? String(p.sfm_orientation) : null].filter(Boolean) as string[],
      });
    }
    if (id === 'sfm_orientation') {
      const ori = p.sfm_orientation && p.sfm_orientation !== SFM_NO_TYPE ? String(p.sfm_orientation) : null;
      return fact({ swatch: colourFor(p.sfm_orientation ?? SFM_NO_TYPE), heading: ori ?? typeLabel, lines: ori ? [typeLabel, plotsLine].filter(Boolean) as string[] : [] });
    }
    const gs = num(p.sfm_gs);
    const colour = colourFor(gs);
    const row = spec && colour ? rendererLegendRows(spec).find((r) => sameColour(r.color, colour)) : null;
    return fact({
      swatch: gs == null ? null : colour,
      heading: row?.label ?? null,
      value: gs == null ? '—' : `${gs.toFixed(0)} m³/ha`,
      lines: [typeLabel, plotsLine].filter(Boolean) as string[],
    });
  }

  if (id.startsWith('fi_')) {
    if (p.um_color == null && p.um_text == null) return null; // no field-inventory summary for this unit
    const colour = typeof p.um_color === 'string' ? p.um_color : null;
    const row = o.unitLegend?.find((r) => sameColour(r.color, colour));
    const heading = row ? (ne ? row.label_ne : row.label_en) : null;
    const value = p.um_text ? String(p.um_text) : null;
    const why = ne ? p.um_reason_ne : p.um_reason; // the condition map says WHY, in numbers
    return fact({ swatch: colour, heading, value: !why && value && value !== heading ? value : null, lines: why ? String(why).split(/\r?\n/) : [] });
  }

  if (id === 'hazard_soil') {
    const mean = num(p.hz_soil_mean);
    if (mean == null) return null;
    const severe = pct(p.hz_soil_severe_pct);
    return fact({
      value: t('analysisMaps.hover.meanLoss', { defaultValue: '{{v}} t/ha/yr (mean)', v: mean.toFixed(1) }),
      lines: severe ? [t('analysisMaps.hover.severeShare', { defaultValue: '{{p}} of its area is Severe or worse', p: severe })] : [],
    });
  }
  if (id === 'hazard_lsi') {
    const cls = ne ? p.hz_lsi_class_ne : p.hz_lsi_class_en;
    if (!cls) return null;
    const high = pct(p.hz_lsi_high_pct);
    return fact({
      heading: String(cls),
      lines: [
        high ? t('analysisMaps.hover.highShare', { defaultValue: '{{p}} of its area is High or above', p: high }) : null,
        t('analysisMaps.relativeNote', { defaultValue: 'Classes are relative to this forest.' }),
      ].filter(Boolean) as string[],
    });
  }
  if (id === 'hazard_fs') {
    const unsafe = pct(p.hz_fs_unsafe_pct);
    if (!unsafe) return null;
    const unstable = pct(p.hz_fs_unstable_pct);
    return fact({
      value: t('analysisMaps.hover.unsafe', { defaultValue: '{{p}} unsafe (unstable + marginal)', p: unsafe }),
      lines: unstable ? [t('analysisMaps.hover.unstable', { defaultValue: '{{p}} unstable', p: unstable })] : [],
    });
  }
  if (id === 'hazard_prone') {
    const v = pct(p.hz_prone_pct);
    if (!v) return null;
    return fact({
      value: t('analysisMaps.hover.relHigh', { defaultValue: '{{p}} relatively high susceptibility', p: v }),
      lines: [t('analysisMaps.relativeNote', { defaultValue: 'Classes are relative to this forest.' })],
    });
  }
  return null; // factor layers, household dots: no per-unit fact
}

/** Field-inventory maps a second map can be compared on: the raw per-unit number, its unit and its label. */
const FI_COMPARE: Record<string, { prop: string; suffix: string; digits: number }> = {
  fi_growing_stock: { prop: 'fi_stock', suffix: 'm³/ha', digits: 1 },
  fi_basal_area: { prop: 'fi_basal_area', suffix: 'm²/ha', digits: 1 },
  fi_aah: { prop: 'fi_aah', suffix: 'm³/ha/yr', digits: 2 },
  fi_mai: { prop: 'fi_mai', suffix: 'm³/ha/yr', digits: 2 },
  fi_mai_pct: { prop: 'fi_mai_pct', suffix: '%', digits: 1 },
  fi_carbon: { prop: 'fi_carbon', suffix: 'tC/ha', digits: 1 },
  fi_biomass: { prop: 'fi_biomass', suffix: 't/ha', digits: 1 },
  fi_co2: { prop: 'fi_co2', suffix: 'tCO₂/ha', digits: 1 },
  fi_regeneration: { prop: 'fi_regeneration', suffix: '/ha', digits: 0 },
  fi_pole: { prop: 'fi_pole', suffix: '/ha', digits: 0 },
  fi_tree: { prop: 'fi_tree', suffix: '/ha', digits: 0 },
  fi_condition: { prop: 'fi_condition', suffix: '', digits: 0 },
  fi_regen_condition: { prop: 'fi_regen_condition', suffix: '', digits: 0 },
};

/** Maps that can be the SECOND one in a comparison: those with a per-unit fact that does not depend on being the active map. */
export const COMPARABLE_MAPS: AnalysisMapId[] = [
  'sfm_type', 'sfm_orientation', 'sfm_stock', 'hazard_soil', 'hazard_lsi', 'hazard_fs', 'hazard_prone',
  ...(Object.keys(FI_COMPARE) as AnalysisMapId[]),
];

/**
 * The fact for the map being COMPARED with the active one. SFM and hazard facts are the very same as when that map is active;
 * a field-inventory map reads its raw number (its class colour exists only for the active map).
 */
export function compareFact(id: AnalysisMapId | null | undefined, p: Record<string, unknown>, o: HoverOptions): HoverFact | null {
  if (!id) return null;
  const cfg = FI_COMPARE[id];
  if (!cfg) return analysisHoverFact(id, p, o);
  const raw = p[cfg.prop];
  if (raw == null || raw === '') return null;
  const def = analysisMapDef(id)!;
  const n = Number(raw);
  const value = Number.isFinite(n) && cfg.suffix !== ''
    ? `${n.toLocaleString(undefined, { maximumFractionDigits: cfg.digits })} ${cfg.suffix}`
    : String(raw);
  return { map: o.t(def.labelKey, { defaultValue: def.fallbackLabel }), swatch: null, heading: null, value, lines: [] };
}

const safeColour = (c: string | null): string | null => (c && /^#[0-9a-fA-F]{6}$/.test(c) ? c : null);

/** The card, as HTML for a Leaflet tooltip. Everything dynamic is escaped. */
export function hoverFactHtml(unitName: string, f: HoverFact, compare?: HoverFact | null): string {
  const sw = safeColour(f.swatch);
  const swatch = sw ? `<span style="display:inline-block;width:10px;height:10px;background:${sw};border:1px solid #666;margin-right:5px;vertical-align:-1px"></span>` : '';
  const main = [f.heading ? `<b>${escapeHtml(f.heading)}</b>` : '', f.value ? escapeHtml(f.value) : ''].filter(Boolean).join(' · ');
  const lines = f.lines.map((l) => `<div style="opacity:.8">${escapeHtml(l)}</div>`).join('');
  return (
    `<div class="analysis-hover" style="font-size:11px;line-height:1.35;max-width:250px">` +
    `<div style="font-weight:700">${escapeHtml(unitName)}</div>` +
    `<div style="opacity:.6">${escapeHtml(f.map)}</div>` +
    (main ? `<div style="margin-top:2px">${swatch}${main}</div>` : '') +
    lines +
    (compare ? compareBlock(compare) : '') +
    `</div>`
  );
}

/** The second map's fact, under a thin rule: its name, then class / value. */
function compareBlock(f: HoverFact): string {
  const main = [f.heading ? `<b>${escapeHtml(f.heading)}</b>` : '', f.value ? escapeHtml(f.value) : ''].filter(Boolean).join(' · ');
  const sw = safeColour(f.swatch);
  const swatch = sw ? `<span style="display:inline-block;width:10px;height:10px;background:${sw};border:1px solid #666;margin-right:5px;vertical-align:-1px"></span>` : '';
  const lines = f.lines.map((l) => `<div style="opacity:.8">${escapeHtml(l)}</div>`).join('');
  return `<div style="margin-top:5px;padding-top:4px;border-top:1px solid #bbb"><div style="opacity:.6">${escapeHtml(f.map)}</div>${main ? `<div>${swatch}${main}</div>` : ''}${lines}</div>`;
}
