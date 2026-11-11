/**
 * Tabular upload pipelines — the SAME chain each dedicated tab runs, callable
 * from "Add data" (UPLOAD_EXPERIENCE_PLAN.md UP-4.1 / UP-4.3).
 *
 * The owner's rule (D4) is that a household list, a field inventory or a stem
 * mapping dropped into Add data must behave exactly as it does on its own tab —
 * same reads, same findings, same zero extra clicks. That only holds if Add data
 * calls the same endpoints in the same order, with the same defaults, as
 * `HouseholdInfo/FileUploadSection`, `FieldInventoryTab` and `TreeMappingTab`.
 *
 * So the chains live here once. The tabs still drive their own dialogs (column
 * mapping, sample sizes, boundary corrections); this module runs the part that
 * needs no question — and when a question IS unavoidable it says so plainly
 * instead of guessing.
 */

import { fieldInventoryApi, forestMetadataApi, inventoryApi, samplingApi, userGroupApi } from '../services/api';
import type { AcceptedCorrection, UploadFinding } from './uploadFindings';
import { autoMapFieldInventoryColumns } from './fieldInventoryAutoMapping';

/** Field-inventory plot sizes: the same defaults `useFieldInventoryData` starts with. */
export const DEFAULT_SAMPLE_SIZES = {
  regeneration_area_sqm: 10.0,
  sapling_area_sqm: 25.0,
  pole_area_sqm: 100.0,
  tree_area_sqm: 500.0,
};

/** Stem-mapping grid spacing: the same default `TreeMappingTab` starts with. */
export const DEFAULT_GRID_SPACING_M = 20;

/**
 * Raised when the pipeline can finish only after the user answers something the
 * Add-data flow cannot ask (which column is which, what to do about a boundary
 * correction). The dedicated tab asks those; the user is sent there by name.
 */
export type NeedsTabReason = 'columns' | 'boundary' | 'exists';

/** A tree file whose points fall outside the boundary: the server has stored the upload and prepared the corrections it proposes. */
export interface StemBoundaryFix {
  inventoryId: string;
  /** the server's boundary check, with `corrections` and `correction_summary` for the preview */
  boundaryCheck: any;
}

export class NeedsTheDedicatedTab extends Error {
  /** why: `columns` (which column is which), `boundary` (how to correct it), or `exists` (the forest already has this data, delete it first) */
  readonly reason: NeedsTabReason;
  /** the name of the data already there, for `exists` */
  readonly detail?: string;
  /** for `boundary`: what Add data needs to show the same correction preview as the tab, and to finish the import once it is accepted */
  readonly fix?: StemBoundaryFix;

  constructor(message: string, reason: NeedsTabReason = 'columns', detail?: string, fix?: StemBoundaryFix) {
    super(message);
    this.name = 'NeedsTheDedicatedTab';
    this.reason = reason;
    this.detail = detail;
    this.fix = fix;
  }
}

export interface TabularImportResult {
  purpose: 'households' | 'field_inventory' | 'stem_mapping' | 'sample_plots' | 'forest_metadata';
  findings: UploadFinding[];
  /** One-line result, for the state line / toast. */
  records_imported?: number;
  records_updated?: number;
  invalid_rows?: number;
  /** True when the server refused or found nothing usable. */
  failed?: boolean;
}

function findingsOf(res: any): UploadFinding[] {
  return Array.isArray(res?.findings) ? res.findings : [];
}

/** Household: choose the file and it imports (D1). No question to ask up front. */
export async function importHousehold(
  calculationId: string,
  file: File,
  opts: { replaceAll?: boolean } = {},
): Promise<TabularImportResult> {
  const res = await userGroupApi.uploadHouseholdData(calculationId, file, opts);
  return {
    purpose: 'households',
    findings: findingsOf(res),
    records_imported: res?.records_imported ?? 0,
    records_updated: res?.records_updated ?? 0,
    invalid_rows: res?.invalid_rows ?? 0,
    failed: res?.success === false,
  };
}

/**
 * Field inventory: the same chain as the tab - read the column names, work out which column is which, upload, and when the file is ready
 * process it. Only a file whose columns we recognise NOTHING in is handed to the tab; a file with problems still comes back with its findings
 * (the missing column named, the species suggestions ...), which the Add-data report shows.
 */
export async function importFieldInventory(
  calculationId: string,
  file: File,
  crsEpsg?: number | null,
  corrections?: AcceptedCorrection[] | null,
): Promise<TabularImportResult> {
  const preview = await fieldInventoryApi.previewMapping(file);
  const mapping = autoMapFieldInventoryColumns(preview?.csv_columns ?? []);
  if (Object.keys(mapping).length === 0) {
    throw new NeedsTheDedicatedTab('field_inventory');
  }
  const res = await fieldInventoryApi.upload(file, calculationId, mapping, DEFAULT_SAMPLE_SIZES, crsEpsg, corrections);
  const ready = Boolean(res?.summary?.ready_for_processing && res?.field_inventory_id);
  if (ready) {
    await fieldInventoryApi.process(res.field_inventory_id, file, crsEpsg, corrections);
  }
  return {
    purpose: 'field_inventory',
    findings: findingsOf(res),
    failed: !ready,
  };
}

/**
 * Stem mapping: preview the columns; when every required column was recognised
 * with confidence (`needs_user_input: false`) there is nothing to confirm, so
 * confirm with the server's own mapping and process — no mapping dialog.
 * A boundary correction is a decision only the tab's dialog can make, so that
 * case hands back to the tab.
 */
export async function importStemMapping(
  calculationId: string,
  file: File,
  crsEpsg?: number | null,
): Promise<TabularImportResult> {
  const preview = await inventoryApi.previewColumnMapping(file);
  const mapping = preview?.mapping ?? {};
  if (!mapping || Object.keys(mapping).length === 0 || preview?.needs_user_input !== false) {
    throw new NeedsTheDedicatedTab('stem_mapping');
  }
  const result = await inventoryApi.confirmColumnMapping(
    file,
    mapping,
    false,
    DEFAULT_GRID_SPACING_M,
    calculationId,
    // the coordinate system the user chose in Add data; only a UTM zone is passed (degrees = the file as it is, which the backend recognises itself)
    crsEpsg && crsEpsg >= 32600 ? crsEpsg : undefined,
  );
  if (result?.exists) {
    // the forest already has a tree mapping: the server will not add a second one. This is not a question about columns - say what is there.
    throw new NeedsTheDedicatedTab('stem_mapping', 'exists', result?.filename ?? undefined);
  }
  const ready = Boolean(result?.summary?.ready_for_processing && result?.inventory_id);
  if (ready && result?.boundary_check?.needs_correction) {
    throw new NeedsTheDedicatedTab('stem_mapping', 'boundary', undefined, { inventoryId: result.inventory_id, boundaryCheck: result.boundary_check });
  }
  if (ready) {
    await inventoryApi.processInventory(result.inventory_id, file);
  }
  return {
    purpose: 'stem_mapping',
    findings: findingsOf(result),
    failed: ready ? false : true,
  };
}

/** The user accepted the proposed corrections: move the points that were outside, then process the tree file (what the Tree mapping tab does). */
export async function applyStemBoundaryCorrections(fix: StemBoundaryFix, file: File): Promise<TabularImportResult> {
  await inventoryApi.acceptCorrections(fix.inventoryId, file);
  await inventoryApi.processInventory(fix.inventoryId, file);
  return { purpose: 'stem_mapping', findings: [], failed: false };
}

/** The user turned the corrections down: remove the upload the server stored, so it does not stop the next one ("already exists"). Never throws. */
export async function discardStemMappingDraft(inventoryId: string): Promise<void> {
  try {
    await inventoryApi.deleteInventory(inventoryId);
  } catch (err) {
    console.warn('[tree import] could not remove the unprocessed upload', err);
  }
}

/**
 * Sample plots from a table (the Sample_Plots template): the server checks every row, places each plot in its block and stores the design. A refusal
 * (numbers that do not run 1..N, a plot outside the forest ...) comes back as findings naming the rows, through the shared finding-shaped error.
 */
export async function importSamplePlots(
  calculationId: string,
  file: File,
  crsEpsg?: number | null,
  renumber?: boolean,
): Promise<TabularImportResult> {
  const res = await samplingApi.importPlots(calculationId, file, crsEpsg && crsEpsg >= 32600 ? crsEpsg : undefined, renumber);
  return { purpose: 'sample_plots', findings: findingsOf(res), records_imported: res?.total_points ?? 0, failed: false };
}

/** Forest details (name, group, location, offices, national code, plan years) from the one-row template: choose the file and it fills the form. */
export async function importForestMetadata(calculationId: string, file: File): Promise<TabularImportResult> {
  const res = await forestMetadataApi.importFile(calculationId, file);
  return { purpose: 'forest_metadata', findings: findingsOf(res), records_imported: 1, failed: false };
}

/** Run the pipeline for a tabular purpose. */
export async function importTabular(
  purpose: string,
  calculationId: string,
  file: File,
  options?: { crsEpsg?: number | null; corrections?: AcceptedCorrection[] | null; renumber?: boolean },
): Promise<TabularImportResult> {
  if (purpose === 'households') return importHousehold(calculationId, file);
  if (purpose === 'field_inventory') return importFieldInventory(calculationId, file, options?.crsEpsg, options?.corrections);
  if (purpose === 'stem_mapping') return importStemMapping(calculationId, file, options?.crsEpsg);
  if (purpose === 'sample_plots') return importSamplePlots(calculationId, file, options?.crsEpsg, options?.renumber);
  if (purpose === 'forest_metadata') return importForestMetadata(calculationId, file);
  throw new Error(`Not a tabular purpose: ${purpose}`);
}
