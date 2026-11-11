/**
 * Thematic views of a unit layer's attribute table (owner rule 2026-10-10): the same columns, grouped by the component that
 * fills them -- raster analysis (`an_*`), inventory analysis (`fi_*`), Sustainable FM (`sfm_*`), hazard & erosion (`hz_*`), the
 * carved classification (`dominant_*`, orientation) -- so a wide table can be read one subject at a time.
 */
import { ANALYSIS_GROUPS, analysisGroupOf, type AnalysisGroup } from './analysisFields';

export type AttributeTheme = 'all' | 'basic' | 'raster' | 'inventory' | 'sfm' | 'hazard' | 'classification';

export const ATTRIBUTE_THEMES: AttributeTheme[] = ['all', 'basic', 'raster', 'inventory', 'sfm', 'hazard', 'classification'];

/** Always shown, whatever the view: the row number and the unit's identity. */
const CORE_KEYS = new Set(['#', 'name']);

const CLASSIFICATION_KEYS = new Set(['management_orientation', 'suggested_orientation', 'orientation_justification_en']);

export function themeOfColumn(key: string): Exclude<AttributeTheme, 'all'> {
  if (key.startsWith('an_')) return 'raster';
  if (key.startsWith('fi_')) return 'inventory';
  if (key.startsWith('sfm_')) return 'sfm';
  if (key.startsWith('hz_')) return 'hazard';
  if (key.startsWith('dominant_') || CLASSIFICATION_KEYS.has(key)) return 'classification';
  return 'basic';
}

/**
 * The columns a view shows. `all` shows everything; any other view shows the core columns plus its own group. Under `raster`, a
 * `group` (a subject: terrain, climate, ...) narrows it further to that subject's analysis columns; `all` keeps every analysis column.
 */
export function columnsForTheme<T extends { key: string }>(columns: T[], theme: AttributeTheme, group: AnalysisGroup | 'all' = 'all'): T[] {
  if (theme === 'all') return columns;
  return columns.filter((c) => {
    if (c.key.startsWith('__') || CORE_KEYS.has(c.key)) return true;
    if (themeOfColumn(c.key) !== theme) return false;
    return theme !== 'raster' || group === 'all' || analysisGroupOf(c.key) === group;
  });
}

/** The subjects worth offering under "Raster analysis": those with at least one analysis column on this layer, in their set order. */
export function availableAnalysisGroups<T extends { key: string }>(columns: T[]): AnalysisGroup[] {
  const present = new Set(columns.filter((c) => themeOfColumn(c.key) === 'raster').map((c) => analysisGroupOf(c.key)));
  return ANALYSIS_GROUPS.filter((g) => present.has(g));
}

/** Views worth offering: those that have at least one column of their own on this layer. */
export function availableThemes<T extends { key: string }>(columns: T[]): AttributeTheme[] {
  const present = new Set(columns.map((c) => themeOfColumn(c.key)));
  return ATTRIBUTE_THEMES.filter((t) => t === 'all' || present.has(t));
}
