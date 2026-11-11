/**
 * A layer as the attribute table shows it, ready to be written to a file.
 *
 * An export used to carry a feature's raw properties, which are not what the table shows (the table has its own columns: computed ones,
 * formatted ones, translated headers). Here every table column becomes a field, headed as the table heads it, valued as the table values it,
 * and each feature also carries its look from the map (`_symbol`), so KML and GeoPackage can both draw it as the workspace does.
 */
import type { ColumnDef } from './layerRegistry';
import { symbolFor, type FeatureSymbol } from './layerSymbology';

export type ExportFeature = GeoJSON.Feature & { _symbol?: FeatureSymbol; _name?: string };

const EMPTY = new Set(['', '-', '—']);
const PLAIN_NUMBER = /^-?(0|[1-9]\d*)(\.\d+)?$/;

/** Columns that are the table's own furniture, not data. */
const isFurniture = (c: ColumnDef): boolean => c.key === '#' || c.key.startsWith('__');

/** The text a React node shows (the table draws some cells with `render`; the file wants what they say). */
function nodeText(node: any): string | null {
  if (node == null || typeof node === 'boolean') return null;
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) {
    const parts = node.map(nodeText).filter((p): p is string => p != null && p !== '');
    return parts.length ? parts.join('') : null;
  }
  if (typeof node === 'object' && node.props) {
    // a picker or input shows its value, not children
    if (node.props.children == null && node.props.value != null) return String(node.props.value);
    return nodeText(node.props.children);
  }
  return null;
}

/** What the table shows in this cell, as plain data. */
function cellValue(col: ColumnDef, feature: GeoJSON.Feature, index: number): unknown {
  let raw = col.getValue ? col.getValue(feature, index) : feature.properties?.[col.key];
  if (col.select) {
    // a choice column holds a code and shows the option's label
    const code = String(col.selectValue ? col.selectValue(feature) : (raw ?? ''));
    const hit = col.select.find((o) => String(o.value) === code);
    if (hit) return hit.label;
    if (code === '') return null;
  } else if (col.render && (raw == null || typeof raw !== 'object')) {
    const shown = nodeText(col.render(raw, feature));
    if (shown != null && shown !== '') raw = shown;
  }
  if (raw == null) return null;
  if (typeof raw === 'string') return EMPTY.has(raw.trim()) ? null : raw;
  if (typeof raw === 'number') return Number.isFinite(raw) ? raw : null;
  if (typeof raw === 'boolean') return raw;
  if (typeof raw === 'object') {
    const text = nodeText(raw);
    return text != null ? text : JSON.stringify(raw);
  }
  return String(raw);
}

/** A column whose every filled cell is a plain number written as text ("12.50") is written as numbers, so it sorts and sums in QGIS. */
function numeric(columnValues: unknown[]): boolean {
  const filled = columnValues.filter((v) => v != null);
  return filled.length > 0 && filled.every((v) => typeof v === 'string' && PLAIN_NUMBER.test(v));
}

export interface ExportViewOptions {
  columns: ColumnDef[];
  features: GeoJSON.Feature[];
  /** the heading the table shows for a column */
  header: (col: ColumnDef) => string;
  /** the map's key for this layer, to ask for each feature's look */
  layerKey: string;
  /** the layer's preset style when the map has not registered one */
  presetKey?: string;
}

export function buildExportFeatures(opts: ExportViewOptions): ExportFeature[] {
  const cols = opts.columns.filter((c) => !isFurniture(c));
  const table = opts.features.map((f, i) => cols.map((c) => cellValue(c, f, i)));
  cols.forEach((_, ci) => {
    const values = table.map((row) => row[ci]);
    if (numeric(values)) table.forEach((row) => { if (row[ci] != null) row[ci] = Number(row[ci]); });
  });
  const nameColumn = cols.findIndex((c) => c.key === 'name' || c.key === 'block_name' || c.key === 'compartment_name');
  return opts.features.map((f, i) => {
    const properties: Record<string, unknown> = {};
    cols.forEach((c, ci) => {
      const head = opts.header(c) || c.key;
      let key = head;
      for (let n = 2; key in properties; n += 1) key = `${head}_${n}`;
      properties[key] = table[i][ci];
    });
    const named = nameColumn >= 0 ? table[i][nameColumn] : null;
    return {
      type: 'Feature',
      geometry: f.geometry,
      properties,
      _name: typeof named === 'string' ? named : undefined,
      _symbol: symbolFor(opts.layerKey, f, opts.presetKey),
    };
  });
}
