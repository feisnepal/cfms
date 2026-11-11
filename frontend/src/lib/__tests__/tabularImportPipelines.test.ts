import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  DEFAULT_SAMPLE_SIZES,
  DEFAULT_GRID_SPACING_M,
  NeedsTheDedicatedTab,
  importFieldInventory,
  importHousehold,
  importStemMapping,
  importTabular,
} from '../tabularImportPipelines';

const uploadHouseholdData = vi.fn();
const previewMapping = vi.fn();
const upload = vi.fn();
const processFi = vi.fn();
const previewColumnMapping = vi.fn();
const confirmColumnMapping = vi.fn();
const processInventory = vi.fn();
const importPlots = vi.fn();
const importMetadata = vi.fn();

vi.mock('../../services/api', () => ({
  userGroupApi: { uploadHouseholdData: (...a: unknown[]) => uploadHouseholdData(...a) },
  fieldInventoryApi: {
    previewMapping: (...a: unknown[]) => previewMapping(...a),
    upload: (...a: unknown[]) => upload(...a),
    process: (...a: unknown[]) => processFi(...a),
  },
  forestMetadataApi: { importFile: (...a: unknown[]) => importMetadata(...a) },
  samplingApi: { importPlots: (...a: unknown[]) => importPlots(...a) },
  inventoryApi: {
    previewColumnMapping: (...a: unknown[]) => previewColumnMapping(...a),
    confirmColumnMapping: (...a: unknown[]) => confirmColumnMapping(...a),
    processInventory: (...a: unknown[]) => processInventory(...a),
  },
}));

function f(name: string): File {
  return new File(['x'], name);
}

describe('tabularImportPipelines', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('sample plots: sends the file, a UTM zone (not degrees) and the renumber choice', async () => {
    importPlots.mockResolvedValue({ total_points: 12, findings: [{ code: 'sample_plots.renumbered' }] });
    const file = f('plots.xlsx');
    const res = await importTabular('sample_plots', 'c1', file, { crsEpsg: 32645, renumber: true });
    expect(importPlots).toHaveBeenCalledWith('c1', file, 32645, true);
    expect(res).toMatchObject({ purpose: 'sample_plots', records_imported: 12, failed: false });
    await importTabular('sample_plots', 'c1', file, { crsEpsg: 4326 });
    expect(importPlots).toHaveBeenLastCalledWith('c1', file, undefined, undefined);
  });

  it('forest details: sends the file and carries the findings through', async () => {
    importMetadata.mockResolvedValue({ findings: [{ code: 'forest_metadata.imported' }] });
    const file = f('meta.xlsx');
    const res = await importTabular('forest_metadata', 'c1', file);
    expect(importMetadata).toHaveBeenCalledWith('c1', file);
    expect(res).toMatchObject({ purpose: 'forest_metadata', failed: false });
    expect(res.findings).toHaveLength(1);
  });

  it('households: uploads and carries findings through', async () => {
    uploadHouseholdData.mockResolvedValue({
      records_imported: 3,
      records_updated: 1,
      findings: [{ code: 'households.partial' }],
    });
    const res = await importHousehold('c1', f('households.xlsx'));
    expect(uploadHouseholdData).toHaveBeenCalledWith('c1', expect.any(File), {});
    expect(res).toMatchObject({ purpose: 'households', records_imported: 3, records_updated: 1 });
    expect(res.findings).toHaveLength(1);
    expect(res.failed).toBe(false);
  });

  const REAL_HEADER = [
    'block_name', 'sample_plot_number', 'longitude', 'latitude',
    'tree_species_scientific', 'tree_dbh_cm', 'tree_height_m', 'tree_class',
  ];

  it('field inventory: maps the columns itself, uploads with the tab defaults and processes a ready file', async () => {
    previewMapping.mockResolvedValue({ csv_columns: REAL_HEADER });
    upload.mockResolvedValue({ summary: { ready_for_processing: true }, field_inventory_id: 'fi-1', findings: [] });
    const res = await importFieldInventory('c1', f('fi.xlsx'));
    expect(upload).toHaveBeenCalledWith(
      expect.any(File),
      'c1',
      expect.objectContaining({
        block_name: 'block_name',
        sample_plot_number: 'sample_plot_number',
        longitude: 'longitude',
        latitude: 'latitude',
        tree_species_scientific: 'tree_species_scientific',
        tree_dbh_cm: 'tree_dbh_cm',
        tree_height_m: 'tree_height_m',
        tree_class: 'tree_class',
      }),
      DEFAULT_SAMPLE_SIZES,
      undefined, // no coordinate system chosen: the file as it is
      undefined, // no corrections accepted
    );
    expect(processFi).toHaveBeenCalledWith('fi-1', expect.any(File), undefined, undefined);
    expect(res).toMatchObject({ purpose: 'field_inventory', failed: false });
  });

  it('field inventory: the coordinate system chosen in Add data goes to BOTH the upload and the process call', async () => {
    previewMapping.mockResolvedValue({ csv_columns: REAL_HEADER });
    upload.mockResolvedValue({ summary: { ready_for_processing: true }, field_inventory_id: 'fi-1', findings: [] });
    await importFieldInventory('c1', f('fi.csv'), 32645);
    expect(upload).toHaveBeenCalledWith(expect.any(File), 'c1', expect.any(Object), DEFAULT_SAMPLE_SIZES, 32645, undefined);
    expect(processFi).toHaveBeenCalledWith('fi-1', expect.any(File), 32645, undefined); // the two reads must agree
  });

  it('field inventory: the accepted corrections go to BOTH the upload and the process call', async () => {
    previewMapping.mockResolvedValue({ csv_columns: REAL_HEADER });
    upload.mockResolvedValue({ summary: { ready_for_processing: true }, field_inventory_id: 'fi-1', findings: [] });
    const corrections = [{ row: 4, column: 'pole_dbh_cm', value: 22.3 }];
    await importFieldInventory('c1', f('fi.csv'), null, corrections);
    expect(upload).toHaveBeenCalledWith(expect.any(File), 'c1', expect.any(Object), DEFAULT_SAMPLE_SIZES, null, corrections);
    expect(processFi).toHaveBeenCalledWith('fi-1', expect.any(File), null, corrections);
  });

  it('field inventory: a file with problems is NOT processed but comes back with its findings', async () => {
    previewMapping.mockResolvedValue({ csv_columns: REAL_HEADER });
    upload.mockResolvedValue({ summary: { ready_for_processing: false }, findings: [{ code: 'field_inventory.required_column_missing' }] });
    const res = await importFieldInventory('c1', f('fi.xlsx'));
    expect(processFi).not.toHaveBeenCalled();
    expect(res.failed).toBe(true);
    expect(res.findings).toHaveLength(1);
  });

  it('field inventory: a file with no recognisable column goes to the tab, nothing uploaded', async () => {
    previewMapping.mockResolvedValue({ csv_columns: ['foo', 'bar'] });
    await expect(importFieldInventory('c1', f('fi.xlsx'))).rejects.toBeInstanceOf(NeedsTheDedicatedTab);
    expect(upload).not.toHaveBeenCalled();
  });

  it('stem mapping: the coordinate system chosen in Add data is passed (a UTM zone), degrees are left to the backend', async () => {
    previewColumnMapping.mockResolvedValue({ needs_user_input: false, mapping: { species: 'sp' } });
    confirmColumnMapping.mockResolvedValue({ inventory_id: 'inv-1', summary: { ready_for_processing: true }, boundary_check: { needs_correction: false } });
    processInventory.mockResolvedValue({});
    await importStemMapping('c1', f('trees.csv'), 32645);
    expect(confirmColumnMapping).toHaveBeenLastCalledWith(expect.any(File), { species: 'sp' }, false, DEFAULT_GRID_SPACING_M, 'c1', 32645);
    await importStemMapping('c1', f('trees.csv'), 4326);
    expect(confirmColumnMapping).toHaveBeenLastCalledWith(expect.any(File), { species: 'sp' }, false, DEFAULT_GRID_SPACING_M, 'c1', undefined);
  });

  it('stem mapping: auto-continues with the server mapping and processes', async () => {
    previewColumnMapping.mockResolvedValue({
      needs_user_input: false,
      mapping: { species: 'sp' },
    });
    confirmColumnMapping.mockResolvedValue({
      inventory_id: 'inv-1',
      summary: { ready_for_processing: true },
      boundary_check: { needs_correction: false },
    });
    processInventory.mockResolvedValue({});
    const res = await importStemMapping('c1', f('trees.csv'));
    expect(confirmColumnMapping).toHaveBeenCalledWith(
      expect.any(File),
      { species: 'sp' },
      false,
      DEFAULT_GRID_SPACING_M,
      'c1',
      undefined,
    );
    expect(processInventory).toHaveBeenCalledWith('inv-1', expect.any(File));
    expect(res.failed).toBe(false);
  });

  it('stem mapping: ambiguous columns → needs the dedicated tab, no upload', async () => {
    previewColumnMapping.mockResolvedValue({ needs_user_input: true, mapping: { species: 'sp' } });
    await expect(importStemMapping('c1', f('trees.csv'))).rejects.toBeInstanceOf(
      NeedsTheDedicatedTab,
    );
    expect(confirmColumnMapping).not.toHaveBeenCalled();
  });

  it('stem mapping: a boundary correction → needs the dedicated tab, no processing', async () => {
    previewColumnMapping.mockResolvedValue({ needs_user_input: false, mapping: { species: 'sp' } });
    confirmColumnMapping.mockResolvedValue({
      inventory_id: 'inv-1',
      summary: { ready_for_processing: true },
      boundary_check: { needs_correction: true },
    });
    await expect(importStemMapping('c1', f('trees.csv'))).rejects.toBeInstanceOf(
      NeedsTheDedicatedTab,
    );
    expect(processInventory).not.toHaveBeenCalled();
  });

  it('stem mapping: says WHY it hands back to the tab - which column, the boundary, or data that is already there', async () => {
    previewColumnMapping.mockResolvedValue({ needs_user_input: true, mapping: { species: 'sp' } });
    await expect(importStemMapping('c1', f('trees.csv'))).rejects.toMatchObject({ reason: 'columns' });

    previewColumnMapping.mockResolvedValue({ needs_user_input: false, mapping: { species: 'sp' } });
    confirmColumnMapping.mockResolvedValue({ inventory_id: 'inv-1', summary: { ready_for_processing: true }, boundary_check: { needs_correction: true } });
    await expect(importStemMapping('c1', f('trees.csv'))).rejects.toMatchObject({ reason: 'boundary' });

    // the forest already has a tree mapping: not a question about columns, and the file that is there is named
    confirmColumnMapping.mockResolvedValue({ exists: true, filename: 'old_trees.xlsx', summary: { ready_for_processing: false } });
    await expect(importStemMapping('c1', f('trees.csv'))).rejects.toMatchObject({ reason: 'exists', detail: 'old_trees.xlsx' });
    expect(processInventory).not.toHaveBeenCalled();
  });

  it('importTabular dispatches each tabular purpose', async () => {
    uploadHouseholdData.mockResolvedValue({ findings: [] });
    await expect(importTabular('households', 'c1', f('h.xlsx'))).resolves.toMatchObject({
      purpose: 'households',
    });
    await expect(importTabular('nope', 'c1', f('h.xlsx'))).rejects.toThrow();
  });
});
