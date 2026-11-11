/**
 * Stem Mapping's default symbology: one colour + one size per DBH band, small
 * band -> small symbol, so a forest's stand structure reads at a glance
 * without anyone opening the Style Layer dialog first.
 *
 * Bands, on the raw numeric `dbh_cm` -- NOT `DbhClassRegistry`'s
 * "guideline_2061" classes (Seedling/Sapling/Pole/Tree, boundaries
 * 0/4/10/20/30/40/50/60), whose edges don't line up with these 10 cm bands
 * (though 30/40 below are deliberately the same guideline breakpoints).
 * `rendererColorFor`'s graduated mode is `value <= break`, so BREAKS are the
 * upper edge of every band except the last (open-ended).
 *
 * Colours (2026-09-05, user-specified) are grouped into 3 management-meaning
 * FAMILIES, not one continuous ramp: hue carries "what to do about this tree"
 * (green = still growing, leave it; yellow = watch; red family = felling
 * candidate), and shade *within* a family carries size, so a viewer reads
 * "safe / watch / harvestable" instantly and gets finer size detail from how
 * light or dark that colour is.
 */
import type { GraduatedRenderer } from './layerRenderers';

export const DBH_BAND_BREAKS = [10, 20, 30, 40, 50, 60, 70];

export const DBH_BAND_COLORS = [
  '#C8E6C9', // 1–10   pale mint green   — growing
  '#81C784', // 10–20  medium green      — growing
  '#388E3C', // 20–30  deep green        — growing, approaching watch zone
  '#FBC02D', // 30–40  amber             — watch / transition
  '#FF8A65', // 40–50  soft orange       — felling candidate, just crossed
  '#E53935', // 50–60  red               — felling candidate
  '#D81B60', // 60–70  deep pink/magenta — felling candidate, large
  '#880E4F', // >70    dark maroon       — felling candidate, oldest/largest
];

/**
 * The default "colour by DBH" renderer — seeded once per calculation
 * (useLayerRenderers) rather than left as an opt-in preset, because Stem
 * Mapping is supposed to show DBH structure out of the box. From that point
 * on it is ordinary renderer state: the Style Layer dialog can freely replace
 * or clear it per forest, same as any user-chosen renderer.
 */
export const DBH_CLASS_RENDERER: GraduatedRenderer = {
  mode: 'graduated',
  field: 'dbh_cm',
  method: 'equal',
  breaks: DBH_BAND_BREAKS,
  colors: DBH_BAND_COLORS,
  ramp: 'custom',
};

export function dbhBandIndex(dbhCm: number | null | undefined): number {
  if (dbhCm == null || !Number.isFinite(dbhCm)) return -1;
  for (let i = 0; i < DBH_BAND_BREAKS.length; i++) {
    if (dbhCm <= DBH_BAND_BREAKS[i]) return i;
  }
  return DBH_BAND_COLORS.length - 1;
}

// 2026-09-04: circles were "very large" — cut to a quarter (a 75% reduction)
// of the original 4..15.2 px range.
const MIN_RADIUS = 1;
const RADIUS_STEP = 0.4; // 8 bands -> 1..3.8 px

/** Canopy radius in px for a circleMarker — small DBH, small point. */
export function dbhClassRadius(dbhCm: number | null | undefined): number {
  const i = dbhBandIndex(dbhCm);
  return MIN_RADIUS + (i >= 0 ? i : 2) * RADIUS_STEP; // unrecognized reads mid-size
}
