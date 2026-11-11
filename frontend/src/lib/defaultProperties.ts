/**
 * GD 2.2.5 — Default properties per purpose (review #6).
 *
 * Every new digitized feature is seeded with these defaults before buffering,
 * so the AttributeTable (Task 2.3.2) shows purpose-appropriate columns and the
 * backend bulk upsert receives a stable shape.
 */
import type { PurposeId } from './purposeGeometryRules';

export interface DefaultProperties {
  [key: string]: unknown;
}

const DEFAULTS: Record<PurposeId, DefaultProperties> = {
  inventory: { species: '', dbh: 0, height: 0, gps_type: 'manual' },
  sample_plot: { plot_size_m2: 0, gps_type: 'manual' },
  user_group_boundary: {},
  boundary: {},
  blocks: {},
  sub_blocks: {},
  compartments: {},
  sub_compartments: {},
  roads: { type: 'trail' },
  water: { type: 'stream' },
  other: {},
  sub_areas: {},
};

/** Defaults injected into every new feature's properties for the purpose. */
export function defaultPropertiesForPurpose(purpose: string): DefaultProperties {
  return { ...(DEFAULTS[purpose as PurposeId] ?? {}) };
}

/** True if the purpose has a defined default property schema. */
export function hasDefaultProperties(purpose: string): boolean {
  return Object.keys(DEFAULTS[purpose as PurposeId] ?? {}).length > 0;
}
