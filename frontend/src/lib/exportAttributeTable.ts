/**
 * Export the attribute table's current (filtered + sorted + visible-column)
 * view. WORKSPACE_LAYER_STYLING_PLAN.md P2.5.
 */
import type { ColumnDef } from './layerRegistry';

function cell(col: ColumnDef, feature: GeoJSON.Feature, index: number): string {
  const raw = col.getValue ? col.getValue(feature, index) : feature.properties?.[col.key];
  if (raw == null) return '';
  return typeof raw === 'object' ? JSON.stringify(raw) : String(raw);
}

const escapeCsv = (v: string) => (/[",\r\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v);

function header(col: ColumnDef): string {
  return col.label || col.key;
}

/** RFC-4180 CSV of the visible data columns (action / row-number columns dropped). */
export function tableToCsv(columns: ColumnDef[], features: GeoJSON.Feature[]): string {
  const cols = columns.filter((c) => c.key !== '#' && !c.key.startsWith('__'));
  const rows = [cols.map((c) => escapeCsv(header(c))).join(',')];
  features.forEach((f, i) => rows.push(cols.map((c) => escapeCsv(cell(c, f, i))).join(',')));
  return rows.join('\r\n');
}

/** Tab-separated — what a spreadsheet expects from the clipboard. */
export function tableToTsv(columns: ColumnDef[], features: GeoJSON.Feature[]): string {
  const cols = columns.filter((c) => c.key !== '#' && !c.key.startsWith('__'));
  const clean = (v: string) => v.replace(/[\t\r\n]/g, ' ');
  const rows = [cols.map((c) => clean(header(c))).join('\t')];
  features.forEach((f, i) => rows.push(cols.map((c) => clean(cell(c, f, i))).join('\t')));
  return rows.join('\r\n');
}

/** GeoJSON FeatureCollection of exactly the features in view (geometry kept). */
export function tableToGeoJson(features: GeoJSON.Feature[]): string {
  return JSON.stringify({ type: 'FeatureCollection', features }, null, 2);
}

/** Trigger a client-side download. The workspace runs on claude.ai's sandbox for
 *  artifacts, but this component is the app itself, so a plain anchor is fine. */
export function downloadText(filename: string, mime: string, text: string): void {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { document.body.removeChild(a); URL.revokeObjectURL(url); }, 1000);
}
