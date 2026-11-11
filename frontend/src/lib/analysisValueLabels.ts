/**
 * Plain-language text for the stored analysis values that are class codes or snake_case keys, so the attribute table says what a forest
 * manager reads ("Gentle (<19°)", "Pole trees (6–15 m)") and not what the analyser wrote (`1`, `pole_trees`). The stored values are
 * untouched; this only changes how a cell reads.
 *
 * Slope has ONE definition, the अनुसूची-१ bands (owner, 2026-10-11) -- the same as `core/constants.SLOPE_CLASS_BANDS` and the table's
 * "Slope Class" column (`SLOPE_BAND_LABEL`).
 */
const CLASS_TEXT = {
  slope: {
    gentle: 'Gentle (<19°)', moderate: 'Moderate (19–31°)', steep: 'Steep (31–45°)', very_steep: 'Very steep (>45°)',
  },
  // heights as the analyser bins them (analysis._canopy_from_rasterio)
  canopy: {
    non_forest: 'Non-forest (≤1 m)', regeneration: 'Regeneration (2–5 m)', pole_trees: 'Pole trees (6–15 m)', tree: 'Trees (>15 m)',
  },
  aspect: {
    N: 'North', NE: 'North-east', E: 'East', SE: 'South-east', S: 'South', SW: 'South-west', W: 'West', NW: 'North-west', Flat: 'Flat',
  },
  // score bands of core/soil_fertility.FertilityClass
  fertility: {
    high: 'High (score 80+)', good: 'Good (60–79)', moderate: 'Moderate (40–59)', low: 'Low (20–39)', very_low: 'Very low (<20)',
  },
} as const;

const SLOPE_BY_CODE: Record<string, string> = { '1': 'gentle', '2': 'moderate', '3': 'steep', '4': 'very_steep' };
const NO_DATA = 'Data Not Available';

const lookup = (table: Record<string, string>, key: string): string => table[key] ?? key;

/** "pole_trees 61.63%; tree 23.84%" -> each class name rewritten through `table`; `drop` classes (no data) are removed. */
function rewriteBreakdown(text: string, table: Record<string, string>): string {
  return text
    .split('; ')
    .map((part) => {
      const m = part.match(/^(.*?) ([\d.]+%)$/);
      if (!m) return part;
      return m[1] === NO_DATA ? `Not mapped ${m[2]}` : `${lookup(table, m[1])} ${m[2]}`;
    })
    .join('; ');
}

/** `an_*` key (without the prefix) + stored value -> the text the table shows. Anything not listed shows as stored. */
export function analysisDisplayValue(key: string, value: unknown): string | null {
  if (value == null || value === '') return null;
  const raw = String(value);
  switch (key) {
    case 'slope_min_code':
    case 'slope_max_code': {
      const cls = SLOPE_BY_CODE[raw];
      return cls ? CLASS_TEXT.slope[cls as keyof typeof CLASS_TEXT.slope] : raw;
    }
    case 'slope_dominant_class':
      return lookup(CLASS_TEXT.slope, raw);
    case 'slope_percentages':
      return rewriteBreakdown(raw, CLASS_TEXT.slope);
    case 'canopy_dominant_class':
      return lookup(CLASS_TEXT.canopy, raw);
    case 'canopy_percentages':
      return rewriteBreakdown(raw, CLASS_TEXT.canopy);
    case 'aspect_dominant':
      return lookup(CLASS_TEXT.aspect, raw);
    case 'aspect_percentages':
      return rewriteBreakdown(raw, CLASS_TEXT.aspect);
    case 'fertility_class':
      return lookup(CLASS_TEXT.fertility, raw.toLowerCase().replace(/[\s-]+/g, '_'));
    case 'forest_type_dominant':
    case 'landcover_dominant':
    case 'landcover_1984_dominant':
      return raw === NO_DATA ? 'Not mapped' : raw;
    case 'forest_type_percentages':
      return rewriteBreakdown(raw, {});
    case 'soil_texture_system':
      return raw.replace(/^USDA 12-class$/, 'USDA, 12 classes');
    case 'compaction_status':
      return raw === 'Unknown' ? 'Not assessed' : raw;
    default:
      return raw;
  }
}
