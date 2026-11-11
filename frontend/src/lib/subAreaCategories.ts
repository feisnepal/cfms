/**
 * Single source of truth for sub-area categories (List A — official 13-value set).
 *
 * Mirrors the backend `SubAreaCategory` enum (backend/app/schemas/forest.py).
 * Consumed by the MapWorkspace picker/attribute-table, SubAreaManager and map
 * styling. The backend catalog endpoint
 * GET /api/forests/sub-area-categories is the runtime authority; this module is
 * the static seed used offline (kept in lockstep with the enum).
 */

export interface SubAreaCategoryDef {
  key: string;
  /** Legacy alias — equals `key`; kept so legacy tab `.value` refs keep working. */
  value: string;
  label: string;
  labelNp: string;
  /**
   * i18n key for the display label. Added additively (rule 4): `label`/`labelNp`
   * stay for callers that still read them directly, but any render path should
   * resolve this through `t()` so the label follows the active language.
   */
  labelKey: string;
  color: string;
  isExcluded: boolean;
  /** A strip (fire line), not a zone: drawn by the strip tool, never offered in a category picker. */
  isStrip?: boolean;
}

export const SUB_AREA_CATEGORIES: SubAreaCategoryDef[] = [
  { key: 'protected', value: 'protected', label: 'Protected Area', labelNp: 'संरक्षित क्षेत्र', labelKey: 'subAreaCategory.protected', color: '#ef4444', isExcluded: false },
  { key: 'plantation', value: 'plantation', label: 'Plantation', labelNp: 'बृक्षारोपण क्षेत्र', labelKey: 'subAreaCategory.plantation', color: '#10b981', isExcluded: false },
  { key: 'pro-poor', value: 'pro-poor', label: 'Pro-Poor Allocated', labelNp: 'गरिव तथा विपन्नको लागी छुट्याइएको क्षेत्र', labelKey: 'subAreaCategory.proPoor', color: '#f59e0b', isExcluded: false },
  { key: 'religious', value: 'religious', label: 'Religious Area', labelNp: 'धार्मीक क्षेत्र', labelKey: 'subAreaCategory.religious', color: '#8b5cf6', isExcluded: false },
  { key: 'biodiversity', value: 'biodiversity', label: 'Biodiversity', labelNp: 'जैविक विविधता क्षेत्र', labelKey: 'subAreaCategory.biodiversity', color: '#06b6d4', isExcluded: false },
  { key: 'tourist', value: 'tourist', label: 'Tourist Area', labelNp: 'पर्यटन क्षेत्र', labelKey: 'subAreaCategory.tourist', color: '#ec4899', isExcluded: false },
  { key: 'office', value: 'office', label: 'Office Complex', labelNp: 'कार्यालय परिसर', labelKey: 'subAreaCategory.office', color: '#6b7280', isExcluded: false },
  { key: 'private_land', value: 'private_land', label: 'Private Land (Excluded)', labelNp: 'निजि जग्गा (बहिस्कृत)', labelKey: 'subAreaCategory.privateLand', color: '#dc2626', isExcluded: true },
  { key: 'agroforestry', value: 'agroforestry', label: 'Agroforestry', labelNp: 'कृषिवन क्षेत्र', labelKey: 'subAreaCategory.agroforestry', color: '#84cc17', isExcluded: false },
  { key: 'tree_strata', value: 'tree_strata', label: 'Large Tree Area', labelNp: 'धेरै ठुला रूख भएको क्षेत्र', labelKey: 'subAreaCategory.treeStrata', color: '#15803d', isExcluded: false },
  { key: 'water_hole', value: 'water_hole', label: 'Water Hole', labelNp: 'पानी मूहान', labelKey: 'subAreaCategory.waterHole', color: '#0ea5e9', isExcluded: false },
  { key: 'wildlife_corridor', value: 'wildlife_corridor', label: 'Wildlife Corridor', labelNp: 'जैविक मार्ग', labelKey: 'subAreaCategory.wildlifeCorridor', color: '#a855f7', isExcluded: false },
  { key: 'encroached', value: 'encroached', label: 'Encroached', labelNp: 'अतीक्रमीत क्षेत्र', labelKey: 'subAreaCategory.encroached', color: '#78350f', isExcluded: false },
];

/**
 * Strips are laid ACROSS the zones above and may overlap them, so they are not in SUB_AREA_CATEGORIES (the pickers, the
 * import auto-detect and the paste dialog all read that list). They are looked up wherever a category must be RENDERED.
 * Mirrors backend `app/core/sub_area_kinds.py` (STRIP_CATALOG); a backend test keeps the two in step.
 */
export const STRIP_CATEGORIES: SubAreaCategoryDef[] = [
  { key: 'fire_line', value: 'fire_line', label: 'Fire line', labelNp: 'अग्नी रेखा', labelKey: 'subAreaCategory.fireLine', color: '#c62828', isExcluded: false, isStrip: true },
  { key: 'river_bank', value: 'river_bank', label: 'River bank', labelNp: 'खोला किनार', labelKey: 'subAreaCategory.riverBank', color: '#1e40af', isExcluded: false, isStrip: true },
];

/** Every category that can appear on a sub-area entry: the zones plus the strips. */
export const ALL_SUB_AREA_CATEGORIES: SubAreaCategoryDef[] = [...SUB_AREA_CATEGORIES, ...STRIP_CATEGORIES];

export function isStripCategory(key: string): boolean {
  return STRIP_CATEGORIES.some((c) => c.key === key);
}

export function getSubAreaCategory(key: string): SubAreaCategoryDef | undefined {
  return ALL_SUB_AREA_CATEGORIES.find((c) => c.key === key || c.value === key);
}

export function subAreaCategoryColor(key: string): string {
  return getSubAreaCategory(key)?.color ?? '#808080';
}

export function isExcludedCategory(key: string): boolean {
  return getSubAreaCategory(key)?.isExcluded ?? false;
}

export function getCategoryLabel(key: string, lang: 'en' | 'np' = 'en'): string {
  const cat = getSubAreaCategory(key);
  if (!cat) return key;
  return lang === 'np' ? cat.labelNp : cat.label;
}

/** i18n key for a category's display label; falls back to the raw key. */
export function subAreaCategoryLabelKey(key: string): string {
  return getSubAreaCategory(key)?.labelKey ?? '';
}

/** Options shape for antd/select dropdowns. */
export function subAreaCategoryOptions(): Array<{ value: string; label: string; labelNp: string; labelKey: string; color: string; isExcluded: boolean }> {
  return SUB_AREA_CATEGORIES.map((c) => ({
    value: c.key,
    label: c.label,
    labelNp: c.labelNp,
    labelKey: c.labelKey,
    color: c.color,
    isExcluded: c.isExcluded,
  }));
}

/** Alias lookup for import auto-detect (R3): matches known column values (EN/NP labels, key, legacy keys). */
export function subAreaCategoryByAlias(alias: string): SubAreaCategoryDef | undefined {
  if (!alias) return undefined;
  const normalized = String(alias).trim().toLowerCase();
  return SUB_AREA_CATEGORIES.find(
    (c) =>
      c.key.toLowerCase() === normalized ||
      c.label.toLowerCase() === normalized ||
      c.labelNp === String(alias).trim() ||
      // legacy List B keys map to nearest official category
      (LEGACY_ALIAS_MAP[normalized] && c.key === LEGACY_ALIAS_MAP[normalized]),
  );
}

/** Mapping from the retired List B keys to official List A keys (D1). */
const LEGACY_ALIAS_MAP: Record<string, string> = {
  road: 'office',
  stream: 'water_hole',
  river: 'water_hole',
  degraded: 'protected',
  settlement: 'office',
  agriculture: 'agroforestry',
  water_body: 'water_hole',
  cliff: 'protected',
  wetland: 'water_hole',
  grassland: 'protected',
  shrubland: 'protected',
  conservation: 'biodiversity',
  other: 'protected',
};
