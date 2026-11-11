/**
 * Name-based upload classification — "the system identifies which upload is for what".
 *
 * Phase 1 of UNIFIED_UPLOAD_PLAN.md §4.3, signal #1 only: a file (or a workbook
 * sheet, or a shapefile inside a zip) is matched to a canonical upload purpose
 * by its name, checked against each purpose's `layer_name` + `name_aliases` from
 * the backend schema (`GET /uploads/schema`). Column-fingerprint and
 * geometry-shape signals are Phase 2.
 *
 * Pure and dependency-light except the two workbook/zip readers, which use
 * jszip (already a dependency) to list sheet / entry names client-side.
 */

import JSZip from 'jszip';

export interface UploadPurpose {
  id: string;
  label_en: string;
  label_ne: string;
  kind: 'spatial' | 'tabular' | 'spatial_or_tabular';
  order: number;
  layer_name: string;
  name_aliases?: string[];
  geometry_types?: string[];
  required_in_bundle?: boolean;
  columns?: { name: string; required?: boolean }[];
}

export interface UploadSchema {
  schema_version: string;
  purposes: UploadPurpose[];
}

export type ClassifyVia = 'name' | 'sheet' | 'zip-entry' | 'content' | 'guess' | 'none';

export interface Classification {
  /** Canonical purpose id, or null when the name matched nothing. */
  purposeId: string | null;
  via: ClassifyVia;
  /** For a multi-sheet workbook / multi-layer bundle: what was found inside. */
  sheets?: { name: string; purposeId: string | null }[];
}

const WORKBOOK_EXT = new Set(['xlsx', 'xls']);

export function fileExt(filename: string): string {
  const m = /\.([a-z0-9]+)$/i.exec(filename.trim());
  return m ? m[1].toLowerCase() : '';
}

export function stripExt(filename: string): string {
  return filename.replace(/\.[a-z0-9]+$/i, '');
}

export function isWorkbook(filename: string): boolean {
  return WORKBOOK_EXT.has(fileExt(filename));
}

export function isZipBundle(filename: string): boolean {
  return fileExt(filename) === 'zip';
}

/** lowercase, alphanumerics only — so "Forest Boundary", "forest_boundary" and
 *  "forest-boundary" all collapse to the same key. */
export function normalizeName(s: string): string {
  return (s || '').toLowerCase().replace(/[^a-z0-9]+/g, '');
}

function keySet(p: UploadPurpose): Set<string> {
  const keys = [p.layer_name, ...(p.name_aliases ?? [])].map(normalizeName);
  return new Set(keys.filter(Boolean));
}

/**
 * Match a bare name (filename without extension, or a sheet name) to a purpose.
 * Whole-string matches win over token matches, and among token matches the
 * lower-`order` purpose wins — so `user_group_boundary` beats `forest_boundary`
 * on "user_group_boundary" even though the token "boundary" is in both.
 */
export function matchName(
  bareName: string,
  purposes: UploadPurpose[],
): string | null {
  const ordered = [...purposes].sort((a, b) => a.order - b.order);
  const whole = normalizeName(bareName);
  if (whole) {
    for (const p of ordered) {
      if (keySet(p).has(whole)) return p.id;
    }
  }
  const tokens = bareName
    .split(/[^a-z0-9]+/i)
    .map(normalizeName)
    .filter((tok) => tok.length >= 3);
  for (const p of ordered) {
    const ks = keySet(p);
    if (tokens.some((tok) => ks.has(tok))) return p.id;
  }
  return null;
}

/** Read the sheet names from an .xlsx / .xls workbook, in workbook order. */
export async function readWorkbookSheets(file: File | Blob): Promise<string[]> {
  const zip = await JSZip.loadAsync(await file.arrayBuffer());
  const wb = zip.file('xl/workbook.xml');
  if (!wb) return [];
  const xml = await wb.async('string');
  const names: string[] = [];
  const re = /<sheet[^>]*\bname="([^"]+)"/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(xml))) {
    names.push(decodeXmlEntities(m[1]));
  }
  return names;
}

/** Read the distinct layer basenames inside a shapefile zip bundle. */
export async function readZipLayers(file: File | Blob): Promise<string[]> {
  const zip = await JSZip.loadAsync(await file.arrayBuffer());
  const layers = new Set<string>();
  zip.forEach((relPath) => {
    const m = /(^|\/)([^/]+)\.shp$/i.exec(relPath);
    if (m) layers.add(m[2]);
  });
  return [...layers];
}

function decodeXmlEntities(s: string): string {
  return s
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'");
}

/**
 * Classify one dropped file by name. For a workbook / zip bundle this also reads
 * the sheet / layer names and classifies each — the returned `purposeId` is then
 * the single inner match when there is exactly one, else null (a real bundle,
 * routed sheet-by-sheet on the server in Phase 2).
 */
export async function classifyFile(
  file: File,
  schema: UploadSchema,
): Promise<Classification> {
  const purposes = schema.purposes;

  if (isWorkbook(file.name)) {
    let sheetNames: string[] = [];
    try {
      sheetNames = await readWorkbookSheets(file);
    } catch {
      sheetNames = [];
    }
    const meaningful = sheetNames.filter(
      (n) => normalizeName(n) && normalizeName(n) !== 'instructions',
    );
    const sheets = meaningful.map((name) => ({
      name,
      purposeId: matchName(name, purposes),
    }));
    const matched = sheets.filter((s) => s.purposeId);
    return {
      purposeId: matched.length === 1 ? matched[0].purposeId : null,
      via: 'sheet',
      sheets,
    };
  }

  if (isZipBundle(file.name)) {
    let layers: string[] = [];
    try {
      layers = await readZipLayers(file);
    } catch {
      layers = [];
    }
    if (layers.length) {
      const sheets = layers.map((name) => ({
        name,
        purposeId: matchName(name, purposes),
      }));
      const matched = sheets.filter((s) => s.purposeId);
      if (matched.length) {
        return {
          purposeId: matched.length === 1 ? matched[0].purposeId : null,
          via: 'zip-entry',
          sheets,
        };
      }
    }
    // fall through: classify by the zip's own name
  }

  const byFileName = matchName(stripExt(file.name), purposes);
  if (byFileName) return { purposeId: byFileName, via: 'name' };

  return { purposeId: null, via: 'none' };
}

/** Does this purpose (or the bundle) satisfy the boundary-first gate? */
export function isBoundaryPurpose(purposeId: string | null): boolean {
  return purposeId === 'forest_boundary';
}
