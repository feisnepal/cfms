/** Types and small pure helpers for the Forest summary panel (plan: FOREST_SUMMARY_PANEL_PLAN.md).
 *  The server builds every number and the verdict; the panel only lays them out. */
import { ANALYSIS_MAPS, FI_MAPS, type AnalysisMapId } from './analysisMaps';
import { toNepaliDigit } from '../constants/nepaliLabels';

export type NumeralLang = 'en' | 'ne';

/** Write the digits of an already-formatted number, date or count in the language's own numerals: Devanagari in Nepali, Latin in
 *  English. Apply it to formatted numbers only, never to a whole sentence (a unit name such as B3 is data). */
export const localDigits = (text: string | number, lang: NumeralLang): string =>
  lang === 'ne' ? toNepaliDigit(String(text)) : String(text);

export type TileState = 'ready' | 'not_computed' | 'forest_only' | 'no_data';

export interface SummaryTile {
  key: string;
  value: number | null;
  unit: string;
  state: TileState;
  source_map: string | null;
  source_step: number | null;
  unit_count?: number | null;
  relative?: boolean;
  of?: number | null;
}

export interface SummaryTheme {
  key: string;
  headline: string;
  rows: SummaryTile[];
}

export interface ForestSummary {
  state: 'ready' | 'not_collected';
  area: 'forest' | 'user_group';
  verdict: string | null;
  tiles: SummaryTile[];
  themes: SummaryTheme[];
  basis: { collected_at?: string | null; hazard_method?: string | null; field_inventory?: boolean; hazard?: boolean } | null;
}

export interface DecisionItem {
  key: string;
  scope: string | null;
  who: string;
  step: number;
  choices: string[];
  state: 'open' | 'answered';
  choice: string | null;
  note: string | null;
  decided_at: string | null;
  decided_by: { id: string; name: string; kind: 'owner' | 'dfo' | 'super_admin' | 'user' } | null;
  block_name?: string;
  current?: string | null;
  suggested?: string | null;
}

export interface DecisionsResponse {
  locked: boolean;
  locked_reason: 'locked' | 'calculating' | null;
  open_count: number;
  items: DecisionItem[];
}

export const ORIENTATIONS = ['Production', 'Conservation', 'Protection'] as const;

const UNIT_LABELS: Record<string, string> = {
  'm3/ha': 'm³/ha',
  'm3/ha/yr': 'm³/ha/yr',
  'tC/ha': 'tC/ha',
  'tCO2e/ha': 'tCO₂e/ha',
  't/ha/yr': 't/ha/yr',
};
export const unitLabel = (unit: string): string => UNIT_LABELS[unit] ?? unit;

/** The translation key (forestSummary.units.<key>) of a tile's unit, so Nepali shows हे. and घन मि./हे. and English shows ha and m³/ha. */
const UNIT_KEYS: Record<string, string> = {
  ha: 'ha', 'm3/ha': 'm3_ha', 'tC/ha': 'tc_ha', 'tCO2e/ha': 'tco2e_ha', 'm3/ha/yr': 'm3_ha_yr', 't/ha/yr': 't_ha_yr',
  species: 'species', households: 'households', '%': 'pct',
};
export const unitKey = (unit: string): string | null => UNIT_KEYS[unit] ?? null;

export const formatValue = (value: number, lang: NumeralLang = 'en'): string =>
  localDigits(value.toLocaleString('en', { maximumFractionDigits: Math.abs(value) >= 100 ? 0 : 1 }), lang);

const MAP_IDS: ReadonlySet<string> = new Set<string>([...ANALYSIS_MAPS.map((m) => m.id), ...FI_MAPS.map((m) => m.id)]);

/** The Analysis map a tile opens, or null when its source is not an Analysis map (e.g. the area tile). */
export const analysisMapFor = (sourceMap: string | null): AnalysisMapId | null =>
  sourceMap && MAP_IDS.has(sourceMap) ? (sourceMap as AnalysisMapId) : null;

export interface PanelPosition {
  x: number;
  y: number;
}

/** Keep a floating panel inside its container: the header (`headerHeight`) must stay reachable, so the panel may extend
 *  below the container but never above it, and at least `grab` px of it stays inside horizontally. A container of size 0
 *  (not laid out yet) leaves the position alone. */
export function clampPosition(
  pos: PanelPosition,
  container: { width: number; height: number },
  panel: { width: number },
  headerHeight: number,
  grab = 48,
): PanelPosition {
  if (container.width <= 0 || container.height <= 0) return pos;
  const maxX = Math.max(0, container.width - Math.min(panel.width, grab));
  const minX = Math.min(0, grab - panel.width);
  const maxY = Math.max(0, container.height - headerHeight);
  return { x: Math.min(Math.max(pos.x, minX), maxX), y: Math.min(Math.max(pos.y, 0), maxY) };
}
