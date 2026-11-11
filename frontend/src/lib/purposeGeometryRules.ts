/**
 * Purpose → geometry rules — frontend mirror of the backend SSOT.
 *
 * Backend canonical source: `backend/app/services/purpose_geometry_rules.py`
 * (which derives from `file_processor.process_geometry_list`).
 *
 * Parity contract (enforced by `__tests__/purposeGeometryRules.test.ts`):
 *   every geometry type listed here for a purpose must be accepted by the
 *   backend `process_geometry_list` as a complete drawn feature. When changing
 *   either side, update both + the parity test.
 */

export type PurposeId =
  | 'inventory'
  | 'sample_plot'
  | 'user_group_boundary'
  | 'boundary'
  | 'blocks'
  | 'sub_blocks'
  | 'compartments'
  | 'sub_compartments'
  | 'roads'
  | 'water'
  | 'other'
  | 'sub_areas';

export interface PurposeInfo {
  id: PurposeId;
  label: string;
  labelNp: string;
  desc: string;
  /**
   * i18n keys for the display label and description. Added additively (rule 4):
   * `label`/`labelNp`/`desc` stay for the backend-parity test and non-render
   * callers, but every render path resolves these through `t()` instead — the
   * dialogs previously rendered `label` unconditionally, so a Nepali user saw
   * English purposes even though `labelNp` was right there.
   */
  labelKey: string;
  descKey: string;
}

/** Single source of truth for the 8 purposes (imported from ImportPurposeDialog). */
export const PURPOSES: readonly PurposeInfo[] = [
  { id: 'inventory', label: 'Tree Inventory', labelNp: 'रूख सूची', desc: 'GPS points of individual trees', labelKey: 'purpose.inventory', descKey: 'purposeDesc.inventory' },
  { id: 'sample_plot', label: 'Sample Plot', labelNp: 'नमुना प्लट', desc: 'Sample plot polygons or points', labelKey: 'purpose.sample_plot', descKey: 'purposeDesc.sample_plot' },
  { id: 'user_group_boundary', label: 'User Group Boundary', labelNp: 'उपभोक्ता समूह सीमा', desc: 'User group forest boundary', labelKey: 'purpose.user_group_boundary', descKey: 'purposeDesc.user_group_boundary' },
  { id: 'boundary', label: 'Boundary', labelNp: 'सीमा', desc: 'Forest boundary polygon', labelKey: 'purpose.boundary', descKey: 'purposeDesc.boundary' },
  { id: 'blocks', label: 'Blocks', labelNp: 'ब्लक', desc: 'Block/compartment boundaries', labelKey: 'purpose.blocks', descKey: 'purposeDesc.blocks' },
  { id: 'sub_blocks', label: 'Sub-Blocks', labelNp: 'उप-ब्लक', desc: 'Sub-block polygons (contained in blocks)', labelKey: 'purpose.sub_blocks', descKey: 'purposeDesc.sub_blocks' },
  { id: 'compartments', label: 'Compartments', labelNp: 'कम्पार्टमेन्ट', desc: 'Compartment polygons (replaces derived splits)', labelKey: 'purpose.compartments', descKey: 'purposeDesc.compartments' },
  { id: 'sub_compartments', label: 'Sub-Compartments', labelNp: 'उप-कम्पार्टमेन्ट', desc: 'Sub-compartment polygons (contained in compartments)', labelKey: 'purpose.sub_compartments', descKey: 'purposeDesc.sub_compartments' },
  { id: 'roads', label: 'Roads & Trails', labelNp: 'सडक र पदमार्ग', desc: 'Linear features', labelKey: 'purpose.roads', descKey: 'purposeDesc.roads' },
  { id: 'water', label: 'Water Features', labelNp: 'जल स्रोत', desc: 'Rivers, ponds, streams', labelKey: 'purpose.water', descKey: 'purposeDesc.water' },
  { id: 'sub_areas', label: 'Sub-Areas', labelNp: 'उप-क्षेत्र', desc: 'Sub-area polygons (protected, plantation, etc.)', labelKey: 'purpose.sub_areas', descKey: 'purposeDesc.sub_areas' },
  { id: 'other', label: 'Other', labelNp: 'अन्य', desc: 'Custom layer', labelKey: 'purpose.other', descKey: 'purposeDesc.other' },
] as const;

export type GeometryType = 'Point' | 'LineString' | 'Polygon';
export type DrawMode = 'point' | 'line' | 'polygon';

const GEOM_TYPE_TO_MODE: Record<GeometryType, DrawMode> = {
  Point: 'point',
  LineString: 'line',
  Polygon: 'polygon',
};

/**
 * Allowed GeoJSON geometry types per purpose (mirrors backend
 * `PURPOSE_ALLOWED_GEOMETRY_TYPES`).
 */
export const PURPOSE_ALLOWED_GEOMETRY_TYPES: Record<PurposeId, readonly GeometryType[]> = {
  inventory: ['Point'],
  sample_plot: ['Point'],
  user_group_boundary: ['Polygon'],
  boundary: ['Polygon'],
  blocks: ['Polygon'],
  sub_blocks: ['Polygon'],
  compartments: ['Polygon'],
  sub_compartments: ['Polygon'],
  roads: ['LineString'],
  water: ['LineString', 'Polygon'],
  sub_areas: ['Polygon'],
  other: ['Point', 'LineString', 'Polygon'],
};

/** All draw modes offered by the toolbar (independent of purpose). */
export const DRAW_MODES: readonly DrawMode[] = ['point', 'line', 'polygon'];

export function allowedGeometryTypes(purpose: string): readonly GeometryType[] {
  return PURPOSE_ALLOWED_GEOMETRY_TYPES[purpose as PurposeId] ?? [];
}

/** Draw modes a purpose accepts — used by the toolbar to filter buttons. */
export function geometryTypesForPurpose(purpose: string): readonly DrawMode[] {
  return allowedGeometryTypes(purpose).map((g) => GEOM_TYPE_TO_MODE[g]);
}

/** The first draw mode a purpose offers — used to arm the toolbar when a
 * digitize layer (draft or append) is activated. */
export function firstDrawModeForPurpose(purpose: string): 'draw_point' | 'draw_line' | 'draw_polygon' | null {
  const first = geometryTypesForPurpose(purpose)[0];
  if (!first) return null;
  return first === 'point' ? 'draw_point' : first === 'line' ? 'draw_line' : 'draw_polygon';
}

/** True if the given geometry type may be drawn for the purpose. */
export function isGeometryTypeAllowed(purpose: string, geometryType: GeometryType): boolean {
  return allowedGeometryTypes(purpose).includes(geometryType);
}

/** True if the given draw mode is offered for the purpose. */
export function isDrawModeAllowed(purpose: string, mode: DrawMode): boolean {
  return geometryTypesForPurpose(purpose).includes(mode);
}

export function purposeLabel(purpose: string): string {
  return PURPOSES.find((p) => p.id === purpose)?.label ?? purpose;
}

export function purposeLabelNp(purpose: string): string {
  return PURPOSES.find((p) => p.id === purpose)?.labelNp ?? purpose;
}

/** i18n key for a purpose's label; empty when the purpose is unknown. */
export function purposeLabelKey(purpose: string): string {
  return PURPOSES.find((p) => p.id === purpose)?.labelKey ?? '';
}

/** i18n key for a purpose's description; empty when the purpose is unknown. */
export function purposeDescKey(purpose: string): string {
  return PURPOSES.find((p) => p.id === purpose)?.descKey ?? '';
}

/** Auto-assigned layer name for a given purpose when the user omits a name.
 * Driven by `layer_consolidation.md` §3.3 (user: name assigned automatically
 * by purpose). Returns a label; callers append an incrementing index where
 * relevant so multiple same-purpose layers stay unique (e.g. "Block 1"). */
export function autoNameForPurpose(purpose: string): string | null {
  switch (purpose) {
    case 'boundary':
      return 'Forest Boundary';
    case 'blocks':
      return 'Block';
    case 'sub_blocks':
      return 'Sub-Block';
    case 'compartments':
      return 'Compartment';
    case 'sub_compartments':
      return 'Sub-Compartment';
    case 'sub_areas':
      return 'Sub-Area';
    default:
      return null;
  }
}

/** Next available incremental name for a purpose, e.g. `Block 2`, based on the
 * names already in use (case-insensitive). Falls back to `name 1` when none. */
export function nextPurposeName(
  purpose: string,
  namesInUse: string[],
): string {
  const base = autoNameForPurpose(purpose) ?? 'Layer';
  const pattern = new RegExp(`^${base}\\s+(\\d+)$`, 'i');
  let max = 0;
  for (const n of namesInUse) {
    const m = n.match(pattern);
    if (m) max = Math.max(max, parseInt(m[1], 10));
  }
  return `${base} ${max + 1}`;
}
