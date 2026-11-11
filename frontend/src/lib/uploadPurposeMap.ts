/**
 * Which canonical upload purposes the map workspace can import, and how they map
 * to its legacy purpose ids.
 *
 * Keys are the canonical purpose ids from `schema.py` (`GET /uploads/schema`),
 * which is what {@link classifyFile} returns. Geometry and point layers flow
 * through ImportPurposeDialog's import / convert path. Tabular data routes to
 * the SAME pipeline its dedicated tab runs (see `lib/tabularImportPipelines.ts`,
 * UP-4.1/UP-4.3): `trees` (Tree Inventory) with a spreadsheet is the stem-mapping
 * pipeline, `households` and `field_inventory` are their own. Activities are a
 * drawn geometry layer, so `activities` maps to the `activity_features` builtin.
 */

/** Canonical schema purpose id → the workspace's legacy purpose id. */
export const CANON_TO_LEGACY_PURPOSE: Record<string, string> = {
  forest_boundary: 'boundary',
  blocks: 'blocks',
  sub_blocks: 'sub_blocks',
  compartments: 'compartments',
  sub_compartments: 'sub_compartments',
  sub_areas: 'sub_areas',
  sample_plots: 'sample_plot',
  trees: 'inventory',
  user_group_boundary: 'user_group_boundary',
  roads: 'roads',
  water: 'water',
  households: 'households',
  field_inventory: 'field_inventory',
  forest_metadata: 'forest_metadata',
  activities: 'activity_features',
};

/** The canonical purpose ids the workspace can import right now. */
export const WORKSPACE_IMPORTABLE_PURPOSES: ReadonlySet<string> = new Set(
  Object.keys(CANON_TO_LEGACY_PURPOSE),
);

/** True when the workspace has an import path for this canonical purpose. */
export function isWorkspaceImportable(purposeId: string | null | undefined): boolean {
  return !!purposeId && WORKSPACE_IMPORTABLE_PURPOSES.has(purposeId);
}
