/**
 * GD 2.3.2 — Purpose-driven attribute columns (review #6).
 *
 * When an imported/digitized layer is selected and its purpose is known, the
 * AttributeTable shows purpose-appropriate columns instead of a generic dump of
 * every property. Columns are ordered per purpose; unknown properties still
 * appear after the canonical set (tolerant of real-world CSV variance).
 */
import type { ColumnDef } from './layerRegistry';
import type { PurposeId } from './purposeGeometryRules';

interface PurposeFieldDef {
  key: string;
  label: string;
  labelKey?: string;
  width?: number | 'flex';
  align?: 'left' | 'right' | 'center';
}

/** Canonical purpose → column schema (mirrors `defaultPropertiesForPurpose`). */
export const PURPOSE_FIELD_DEFS: Record<PurposeId, readonly PurposeFieldDef[]> = {
  inventory: [
    { key: 'species', label: 'Species', labelKey: 'attributeTable.col.species', width: 'flex' },
    { key: 'dbh', label: 'DBH (cm)', labelKey: 'attributeTable.col.dbh', width: 90, align: 'right' },
    { key: 'height', label: 'Height (m)', labelKey: 'attributeTable.col.height', width: 100, align: 'right' },
    { key: 'gps_type', label: 'GPS Type', labelKey: 'attributeTable.col.gpsType', width: 100 },
  ],
  sample_plot: [
    { key: 'plot_size_m2', label: 'Plot Size (m²)', labelKey: 'attributeTable.col.plotSizeM2', width: 110, align: 'right' },
    { key: 'gps_type', label: 'GPS Type', labelKey: 'attributeTable.col.gpsType', width: 100 },
  ],
  user_group_boundary: [],
  boundary: [],
  blocks: [],
  sub_blocks: [],
  compartments: [],
  sub_compartments: [],
  roads: [
    { key: 'type', label: 'Type', labelKey: 'attributeTable.col.type', width: 110 },
  ],
  water: [
    { key: 'type', label: 'Type', labelKey: 'attributeTable.col.type', width: 110 },
  ],
  other: [],
  sub_areas: [],
};

const PURPOSE_FALLBACK: readonly PurposeFieldDef[] = [];

export function purposeFieldDefs(purpose: string): readonly PurposeFieldDef[] {
  return PURPOSE_FIELD_DEFS[purpose as PurposeId] ?? PURPOSE_FALLBACK;
}

/**
 * Build the canonical + dynamic column list for an imported/digitized layer.
 * Canonical purpose columns come first (in purpose order); any extra properties
 * present in the features follow, preserving schema-tolerance for CSV variance.
 */
export function purposeColumnsForFeatures(
  purpose: string,
  features: GeoJSON.Feature[],
  columnLabels?: Record<string, string>,
): ColumnDef[] {
  const canonical = purposeFieldDefs(purpose);
  const canonicalKeys = new Set(canonical.map((f) => f.key));

  const presentKeys = new Set<string>();
  features.forEach((f) => {
    if (f.properties) Object.keys(f.properties).forEach((k) => presentKeys.add(k));
  });

  const firstCol: ColumnDef = { key: '#', label: '#', labelKey: 'attributeTable.col.rowNumber', width: 40, align: 'center', getValue: (_, i) => i + 1 };

  const canonicalCols: ColumnDef[] = canonical
    .filter((f) => presentKeys.has(f.key))
    .map((f) => {
      const displayLabel = columnLabels?.[f.key] || f.label;
      return {
        key: f.key,
        label: displayLabel,
        labelKey: columnLabels?.[f.key] ? undefined : f.labelKey,
        width: f.width as ColumnDef['width'],
        align: f.align,
        editable: true,
        getValue: (feat) => feat.properties?.[f.key] ?? '-',
      };
    });

  const extraCols: ColumnDef[] = Array.from(presentKeys)
    .filter((k) => !canonicalKeys.has(k))
    .slice(0, 10)
    .map((k) => {
      const displayLabel = columnLabels?.[k] || k;
      return {
        key: k,
        label: displayLabel,
        width: 'flex' as const,
        editable: true,
        getValue: (feat) => feat.properties?.[k] ?? '-',
      };
    });

  return [firstCol, ...canonicalCols, ...extraCols];
}
