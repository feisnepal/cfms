/**
 * "Analysis maps" — the Sustainable-FM (and, later, Hazard & Erosion) maps shown in the workspace
 * (SFM_HAZARD_WORKSPACE_LAYERS_PLAN.md).
 *
 * An SFM map is a COLOURING of the unit layers (Blocks / Compartments and their sub-units), not a layer of its own:
 * one renderer reads the `sfm_*` properties that `mergeSfmProps` put on each unit.
 *
 * The DEFAULT renderer is always computed here from the shared palettes, never stored — so a palette change reaches
 * every forest (the stale-seed trap noted for Stem Mapping). Only a colour the user changed is persisted, in the
 * ordinary `layer_renderers` under the key `analysis:<id>`; deleting that key is "Default colours".
 */
import { CATEGORICAL } from './semanticPalettes';
import { sampleRamp } from './colorRamps';
import { SFM_NO_TYPE } from './sfmFeatureProps';
import type { CategorizedRenderer, GraduatedRenderer, RendererSpec } from './layerRenderers';
import type { SfmBlockTypeInfo } from '../services/api';

export type AnalysisMapId =
  | 'sfm_type' | 'sfm_orientation' | 'sfm_stock'
  | 'hazard_soil' | 'hazard_lsi' | 'hazard_fs' | 'hazard_prone'
  | 'hazard_hh' | 'hazard_settle'
  | `hazard_f_${string}`
  | `fi_${string}`
  | `chart_${string}`;
export type AnalysisGroup = 'sfm' | 'hazard' | 'chart' | 'fi';

export interface AnalysisMapDef {
  id: AnalysisMapId;
  group: AnalysisGroup;
  /** i18n key of the row label */
  labelKey: string;
  fallbackLabel: string;
}

export const ANALYSIS_MAPS: AnalysisMapDef[] = [
  { id: 'sfm_type', group: 'sfm', labelKey: 'analysisMaps.sfm_type', fallbackLabel: 'Forest type' },
  { id: 'sfm_orientation', group: 'sfm', labelKey: 'analysisMaps.sfm_orientation', fallbackLabel: 'Orientation' },
  { id: 'sfm_stock', group: 'sfm', labelKey: 'analysisMaps.sfm_stock', fallbackLabel: 'Stock vs threshold' },
  { id: 'hazard_soil', group: 'hazard', labelKey: 'analysisMaps.hazard_soil', fallbackLabel: 'Soil loss' },
  { id: 'hazard_lsi', group: 'hazard', labelKey: 'analysisMaps.hazard_lsi', fallbackLabel: 'Landslide susceptibility (relative)' },
  { id: 'hazard_fs', group: 'hazard', labelKey: 'analysisMaps.hazard_fs', fallbackLabel: 'Slope stability (FS)' },
  { id: 'hazard_prone', group: 'hazard', labelKey: 'analysisMaps.hazard_prone', fallbackLabel: 'Relatively high-susceptibility area' },
  { id: 'hazard_hh', group: 'hazard', labelKey: 'analysisMaps.hazard_hh', fallbackLabel: 'Household vulnerability' },
  { id: 'hazard_settle', group: 'hazard', labelKey: 'analysisMaps.hazard_settle', fallbackLabel: 'Priority settlements' },
];

/**
 * Single-number field-inventory maps (growing stock, basal area, AAH, MAI, carbon, condition …): one dropdown in the panel,
 * each bound to the print map variable of the same name. The classes, colours and legend come from the server — the print
 * renderer's own colour function — so the workspace colouring and the placeholder cannot disagree.
 */
export const FI_MAPS: Array<{ id: AnalysisMapId; specKey: string; fallbackLabel: string }> = [
  { id: 'fi_growing_stock', specKey: 'unit__growing_stock', fallbackLabel: "Growing Stock Map (per ha)" },
  { id: 'fi_basal_area', specKey: 'unit__basal_area', fallbackLabel: "Basal Area Map" },
  { id: 'fi_aah', specKey: 'unit__aah', fallbackLabel: "AAH Map (m³/ha/yr)" },
  { id: 'fi_mai', specKey: 'unit__mai', fallbackLabel: "MAI Map (m³/ha/yr)" },
  { id: 'fi_mai_pct', specKey: 'unit__mai_percent', fallbackLabel: "MAI Percent Map" },
  { id: 'fi_carbon', specKey: 'unit__carbon', fallbackLabel: "Carbon Stock Map" },
  { id: 'fi_biomass', specKey: 'unit__biomass', fallbackLabel: "Biomass Map" },
  { id: 'fi_co2', specKey: 'unit__co2', fallbackLabel: "CO₂ Equivalent Map" },
  { id: 'fi_regeneration', specKey: 'unit__regeneration_stems', fallbackLabel: "Regeneration per ha Map" },
  { id: 'fi_pole', specKey: 'unit__pole_per_ha', fallbackLabel: "Poles per ha Map" },
  { id: 'fi_tree', specKey: 'unit__tree_per_ha', fallbackLabel: "Trees per ha Map" },
  { id: 'fi_stems', specKey: 'unit__stems_total', fallbackLabel: "Total Stems Map" },
  { id: 'fi_condition', specKey: 'unit__forest_condition', fallbackLabel: "Forest Condition Map" },
  { id: 'fi_regen_condition', specKey: 'unit__regeneration_condition', fallbackLabel: "Regeneration Condition Map" },
  { id: 'fi_working_circle', specKey: 'unit__working_circle', fallbackLabel: "Working-circle Map" },
  { id: 'fi_satellite', specKey: 'unit__satellite_stock', fallbackLabel: "Satellite Growing Stock Map" },
  { id: 'fi_field_vs_satellite', specKey: 'unit__field_vs_satellite', fallbackLabel: "Field vs Satellite Map" },
  { id: 'fi_pole_tree', specKey: 'unit__pole_tree_share', fallbackLabel: "Pole and Tree Map (tree share of the stock)" },
  { id: 'fi_condition_reason', specKey: 'unit__condition_reason', fallbackLabel: "Forest + Regeneration Condition (with reasons)" },
  { id: 'fi_condition_stocking', specKey: 'unit__condition_x_stocking', fallbackLabel: "Condition × Stocking Map" },
  { id: 'fi_species', specKey: 'unit__species_dominant', fallbackLabel: "Dominant Species Map" },
];
export const isFiMap = (id: AnalysisMapId | null | undefined): boolean => !!id && id.startsWith('fi_');
export const fiSpecKey = (id: AnalysisMapId): string | null => FI_MAPS.find((m) => m.id === id)?.specKey ?? null;

/** Charts drawn over the map (an overlay checkbox, not one of the exclusive colourings). */
export interface ChartDef {
  id: AnalysisMapId;
  /** the URL slug of `/field-glyphs/{slug}` */
  slug: string;
  /** the print map variable it stands for (placeholder) */
  specKey: string;
  fallbackLabel: string;
}
export const CHART_MAPS: ChartDef[] = [
  { id: 'chart_timber', slug: 'timber-by-size', specKey: 'unit__dbh_class_stock__stackbar', fallbackLabel: "Timber by size class" },
  { id: 'chart_dbh_stems', slug: 'dbh-stems', specKey: 'unit__dbh_class_count__stackbar', fallbackLabel: "Stems by size class (bars)" },
  { id: 'chart_dbh_gs_mai_aah', slug: 'dbh-gs-mai-aah', specKey: 'unit__dbh_gs_mai_aah__stackbar', fallbackLabel: "GS · MAI · AAH by size class (10 cm+)" },
  { id: 'chart_dbh_pie', slug: 'dbh-pie', specKey: 'unit__dbh_class_count__pie', fallbackLabel: "Stems by size class (pie)" },
  { id: 'chart_reverse_j', slug: 'reverse-j', specKey: 'unit__dbh_class_count__sparkline', fallbackLabel: "Size-class curve (reverse-J check)" },
  { id: 'chart_dbh_waffle', slug: 'dbh-waffle', specKey: 'unit__dbh_composition__waffle', fallbackLabel: "Size-class waffle" },
  { id: 'chart_regen_pole_tree', slug: 'regen-pole-tree', specKey: 'unit__regen_pole_tree__ternary', fallbackLabel: "Regeneration : poles : trees" },
  { id: 'chart_health', slug: 'health-radar', specKey: 'unit__health_fingerprint', fallbackLabel: "Health fingerprint (radar)" },
  { id: 'chart_timber_firewood', slug: 'timber-firewood', specKey: 'unit__timber_firewood__stackbar', fallbackLabel: "Timber vs firewood" },
  { id: 'chart_biomass', slug: 'biomass-split', specKey: 'unit__agb_bgb__stackbar', fallbackLabel: "Above- vs below-ground biomass" },
  { id: 'chart_species', slug: 'species-pie', specKey: 'unit__species_composition__pie', fallbackLabel: "Species composition (pie)" },
];
export const chartSlug = (id: AnalysisMapId | null | undefined): string | null => CHART_MAPS.find((c) => c.id === id)?.slug ?? null;
export const isChartMap = (id: AnalysisMapId | null | undefined): boolean => !!id && id.startsWith('chart_');

/** The RUSLE and landslide FACTOR layers of the original tab: one dropdown in the panel, not fourteen rows. */
export const FACTOR_MAPS: Array<{ id: AnalysisMapId; key: string; fallbackLabel: string }> = [
  { id: 'hazard_f_soil_r', key: 'f_soil_r', fallbackLabel: "RUSLE factor — Rainfall erosivity (R)" },
  { id: 'hazard_f_soil_k', key: 'f_soil_k', fallbackLabel: "RUSLE factor — Soil erodibility (K)" },
  { id: 'hazard_f_soil_ls', key: 'f_soil_ls', fallbackLabel: "RUSLE factor — Slope length & steepness (LS)" },
  { id: 'hazard_f_soil_c', key: 'f_soil_c', fallbackLabel: "RUSLE factor — Cover management (C)" },
  { id: 'hazard_f_lsi_slope', key: 'f_lsi_slope', fallbackLabel: "LSI factor — Slope angle" },
  { id: 'hazard_f_lsi_lithology', key: 'f_lsi_lithology', fallbackLabel: "LSI factor — Lithology" },
  { id: 'hazard_f_lsi_curvature_twi', key: 'f_lsi_curvature_twi', fallbackLabel: "LSI factor — Curvature / wetness (TWI)" },
  { id: 'hazard_f_lsi_dist_drainage', key: 'f_lsi_dist_drainage', fallbackLabel: "LSI factor — Distance to drainage" },
  { id: 'hazard_f_lsi_dist_road', key: 'f_lsi_dist_road', fallbackLabel: "LSI factor — Distance to road" },
  { id: 'hazard_f_lsi_landcover', key: 'f_lsi_landcover', fallbackLabel: "LSI factor — Land cover" },
  { id: 'hazard_f_lsi_landcover_change', key: 'f_lsi_landcover_change', fallbackLabel: "LSI factor — Land-cover change (1984–)" },
  { id: 'hazard_f_lsi_aspect', key: 'f_lsi_aspect', fallbackLabel: "LSI factor — Aspect" },
  { id: 'hazard_f_lsi_rainfall', key: 'f_lsi_rainfall', fallbackLabel: "LSI factor — Rainfall" },
  { id: 'hazard_f_lsi_soil_texture', key: 'f_lsi_soil_texture', fallbackLabel: "LSI factor — Soil texture" },
];

export const isFactorMap = (id: AnalysisMapId | null | undefined): boolean => !!id && id.startsWith('hazard_f_');
/** Household / settlement dots (points), as opposed to raster tiles. */
export const isDotsMap = (id: AnalysisMapId | null | undefined): boolean => id === 'hazard_hh' || id === 'hazard_settle';
export const dotsKind = (id: AnalysisMapId): 'households' | 'settlements' => (id === 'hazard_settle' ? 'settlements' : 'households');
/** The definition behind any id, including the factor layers. */
export function analysisMapDef(id: AnalysisMapId | null | undefined): AnalysisMapDef | undefined {
  if (!id) return undefined;
  const hit = ANALYSIS_MAPS.find((m) => m.id === id);
  if (hit) return hit;
  const ch = CHART_MAPS.find((m) => m.id === id);
  if (ch) return { id, group: 'chart', labelKey: `analysisMaps.${id}`, fallbackLabel: ch.fallbackLabel };
  const f = FACTOR_MAPS.find((m) => m.id === id);
  if (f) return { id, group: 'hazard', labelKey: `analysisMaps.${id}`, fallbackLabel: f.fallbackLabel };
  const fi = FI_MAPS.find((m) => m.id === id);
  return fi ? { id, group: 'fi', labelKey: `analysisMaps.${id}`, fallbackLabel: fi.fallbackLabel } : undefined;
}

/** SFM maps colour the unit polygons; hazard maps are raster tiles from the backend's cached grids. */
export const isHazardMap = (id: AnalysisMapId | null | undefined): boolean => !!id && id.startsWith('hazard_');
export const isSfmMap = (id: AnalysisMapId | null | undefined): boolean => !!id && id.startsWith('sfm_');
/** The backend layer key behind a hazard map (`/hazard-tiles/{key}/…`). */
export const hazardLayerKey = (id: AnalysisMapId): string => id.replace(/^hazard_/, '');

export const analysisRendererKey = (id: AnalysisMapId): string => `analysis:${id}`;

/** The harvest-% step edges the print map uses (m³/ha, ≥40 cm stock). */
export const SFM_STOCK_BREAKS = [150, 200];
const NO_TYPE_COLOUR = '#bdbdbd';

function typeRenderer(): CategorizedRenderer {
  const scheme = CATEGORICAL.sfm_forest_type;
  return {
    mode: 'categorized',
    field: 'sfm_type',
    classes: [
      ...Object.keys(scheme).map((n) => ({ value: n, color: scheme[n], label: `Type-${n}` })),
      { value: SFM_NO_TYPE, color: NO_TYPE_COLOUR, label: 'No type (non-forest / no plots)' },
    ],
    otherColor: NO_TYPE_COLOUR,
  };
}

function orientationRenderer(): CategorizedRenderer {
  const scheme = CATEGORICAL.sfm_orientation;
  return {
    mode: 'categorized',
    field: 'sfm_orientation',
    classes: [
      ...Object.keys(scheme).map((k) => ({ value: k, color: scheme[k], label: k })),
      { value: SFM_NO_TYPE, color: NO_TYPE_COLOUR, label: 'No orientation' },
    ],
    otherColor: NO_TYPE_COLOUR,
  };
}

function stockRenderer(): GraduatedRenderer {
  return {
    mode: 'graduated',
    field: 'sfm_gs',
    method: 'equal',
    breaks: [...SFM_STOCK_BREAKS],
    colors: sampleRamp('spectral', SFM_STOCK_BREAKS.length + 1),
    ramp: 'spectral',
  };
}

/** What the system draws, ignoring anything the user changed. */
export function defaultAnalysisRenderer(id: AnalysisMapId): RendererSpec | null {
  if (isHazardMap(id) || isChartMap(id) || isFiMap(id)) return null; // drawn as tiles / dots / glyphs / server colours
  switch (id) {
    case 'sfm_type': return typeRenderer();
    case 'sfm_orientation': return orientationRenderer();
    case 'sfm_stock': return stockRenderer();
  }
  return null;
}

/** The renderer to draw: the user's saved colours if any, else the default. */
export function resolveAnalysisRenderer(
  id: AnalysisMapId | null | undefined,
  saved: Record<string, RendererSpec | undefined>,
): RendererSpec | null {
  if (!id) return null;
  return saved[analysisRendererKey(id)] ?? defaultAnalysisRenderer(id);
}

/**
 * Saved colours of a HAZARD map (drawn by the server): only the classes the user changed, by class index. Stored in
 * `layer_renderers['analysis:<id>']` like the SFM renderers; the server (print maps AND tiles) lays them over the defaults.
 */
export interface IndexedColours {
  mode: 'indexed';
  colors: Record<string, string>;
}

export const withIndexColour = (saved: unknown, index: number | string, hex: string): IndexedColours => ({
  mode: 'indexed',
  colors: { ...((saved as IndexedColours | undefined)?.mode === 'indexed' ? (saved as IndexedColours).colors : {}), [String(index)]: hex },
});

/**
 * The PLACEHOLDER of a workspace map: the map-variable token it stands for on the Map-variables page. The page's map is the
 * reference; the workspace map starts with its default colours, and the user's symbology never edits that default.
 * `null` = no placeholder (none today). A backend test checks every token against the spec registry.
 */
export function placeholderToken(id: AnalysisMapId | null | undefined): string | null {
  if (!id) return null;
  const direct: Record<string, string> = {
    sfm_type: 'sfm__forest_type',
    sfm_orientation: 'sfm__orientation',
    sfm_stock: 'sfm__gs_vs_threshold',
    hazard_soil: 'soil__annual_loss',
    hazard_lsi: 'hazard__landslide_susceptibility',
    hazard_fs: 'hazard__factor_of_safety',
    hazard_prone: 'hazard__landslide_prone_area',
    hazard_hh: 'hh__vulnerability',
    hazard_settle: 'hh__priority_settlements',
  };
  if (direct[id]) return `thememap:${direct[id]}`;
  if (id.startsWith('hazard_f_soil_')) return `thememap:soil__factor_${id.slice('hazard_f_soil_'.length)}`;
  if (id.startsWith('hazard_f_lsi_')) return `thememap:hazard__lsi_factor_${id.slice('hazard_f_lsi_'.length)}`;
  const fi = FI_MAPS.find((m) => m.id === id);
  if (fi) return `thememap:${fi.specKey}`;
  const ch = CHART_MAPS.find((m) => m.id === id);
  if (ch) return `thememap:${ch.specKey}`;
  return null;
}

/** True when the user has changed this map's colours (drives the "Default colours" button). */
export const hasCustomColours = (id: AnalysisMapId, saved: Record<string, RendererSpec | undefined>): boolean =>
  !!saved[analysisRendererKey(id)];

export const isUnitLayerId = (layerId: string): boolean =>
  layerId === 'blocks' || layerId === 'sub_blocks' || layerId === 'compartments' || layerId === 'sub_compartments';

export interface LegendEntry {
  /** index into `rendererLegendRows(spec)`, so a swatch edit changes the right class */
  index: number;
  color: string;
  label: string;
  /** how many units fall in this class */
  count: number;
  /** the area those units cover, in hectares (0 when areas are not known) */
  areaHa: number;
}

/**
 * The DYNAMIC legend: only the classes this forest actually has, each with its unit count — a forest with three forest
 * types lists three, not all fourteen. The "other" row is never listed (an unclassified unit is not a class).
 */
export function dynamicLegend(
  spec: RendererSpec,
  rows: Array<{ color: string; label: string }>,
  info: Record<string, SfmBlockTypeInfo>,
): LegendEntry[] {
  const counts = new Array<number>(rows.length).fill(0);
  const areas = new Array<number>(rows.length).fill(0);
  for (const v of Object.values(info)) {
    const value =
      spec.field === 'sfm_type' ? (v.type_no != null ? String(v.type_no) : SFM_NO_TYPE)
      : spec.field === 'sfm_orientation' ? (v.orientation ?? SFM_NO_TYPE)
      : v.gs_ge40_m3_per_ha ?? null;
    if (spec.mode === 'categorized') {
      const i = spec.classes.findIndex((c) => c.value === String(value));
      if (i >= 0) {
        counts[i] += 1;
        areas[i] += Number(v.area_ha) || 0;
      }
    } else if (value != null) {
      let i = spec.breaks.findIndex((b) => Number(value) <= b); // same rule as rendererColorFor
      if (i < 0) i = spec.colors.length - 1;
      counts[i] += 1;
      areas[i] += Number(v.area_ha) || 0;
    } // a unit with no stock is simply not in any bucket
  }
  const n = spec.mode === 'categorized' ? spec.classes.length : spec.colors.length;
  return rows
    .slice(0, n)
    .map((r, index) => ({ index, color: r.color, label: r.label, count: counts[index], areaHa: areas[index] }))
    .filter((e) => e.count > 0);
}

type Tr = (key: string, opts?: Record<string, unknown>) => string;

/**
 * The line a unit's map label carries under its name while an analysis map is on: the MAIN SUMMARY of that map for
 * that unit (the same line the print maps put there). ``null`` = nothing to say, so the label stays the name alone.
 * Reads the merged `sfm_*` / `hz_*` feature properties, so the label, the colour and the table cannot disagree.
 */
export function analysisLabelLine(
  id: AnalysisMapId | null | undefined,
  p: Record<string, unknown>,
  lang: string,
  t: Tr,
): string | null {
  if (!id) return null;
  const num = (k: string): number | null => (p[k] == null || p[k] === '' ? null : Number(p[k]));
  const ne = String(lang || '').startsWith('ne');
  switch (id) {
    case 'sfm_type': {
      if (p.sfm_type == null) return null;
      if (p.sfm_type === SFM_NO_TYPE) return t(p.sfm_state === 'non_forest' ? 'sfm.state.nonForest' : 'sfm.state.noPlots');
      const band = p.sfm_slope_band ? ` · ${p.sfm_slope_band}` : '';
      const plots = p.sfm_state === 'provisional' ? ` · ${num('sfm_plot_count') ?? 0} ${t('analysisMaps.label.plots', { defaultValue: 'plots' })}` : '';
      return `${t('sfm.ref.typeDash', { n: p.sfm_type })}${band}${plots}`;
    }
    case 'sfm_orientation':
      if (p.sfm_type == null) return null;
      return p.sfm_orientation && p.sfm_orientation !== SFM_NO_TYPE
        ? String(p.sfm_orientation)
        : t(p.sfm_state === 'non_forest' ? 'sfm.state.nonForest' : 'sfm.state.noPlots');
    case 'sfm_stock': {
      if (p.sfm_type == null) return null;
      const gs = num('sfm_gs');
      return gs == null ? '—' : `${gs.toFixed(0)} m³/ha`;
    }
    case 'hazard_soil': {
      const v = num('hz_soil_mean');
      return v == null ? null : `${v.toFixed(0)} t/ha/yr`;
    }
    case 'hazard_lsi': {
      const c = ne ? p.hz_lsi_class_ne : p.hz_lsi_class_en;
      return c ? String(c) : null;
    }
    case 'hazard_fs': {
      const v = num('hz_fs_unsafe_pct');
      return v == null ? null : `${v.toFixed(0)}% ${t('analysisMaps.label.unsafe', { defaultValue: 'unsafe' })}`;
    }
    case 'hazard_prone': {
      const v = num('hz_prone_pct');
      return v == null ? null : `${v.toFixed(0)}% ${t('analysisMaps.label.high', { defaultValue: 'high' })}`;
    }
    default:
      // a field-inventory map labels each unit with its value (server-formatted, with the unit); the factor layers and the
      // household dots carry no per-unit summary
      return isFiMap(id) && p.um_text ? String(p.um_text) : null;
  }
}
