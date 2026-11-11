/**
 * A tree table dropped into Import layer whose points fall outside the forest boundary: the dialog shows the same correction preview the
 * Tree mapping tab shows, instead of sending the user to that tab. Accepting moves the points and processes the file; declining removes the
 * unprocessed upload so it cannot block the next one.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import en from '../../i18n/locales/en.json';

vi.mock('../../services/api', () => ({
  forestApi: {},
  compartmentApi: {},
  userGroupApi: {},
  uploadApi: {},
  inventoryApi: {},
}));
vi.mock('../../hooks/useImportLayer', () => ({ useImportLayer: () => ({ importLayer: vi.fn(), isImporting: false }) }));

const importTabular = vi.fn();
const applyStemBoundaryCorrections = vi.fn();
const discardStemMappingDraft = vi.fn();
vi.mock('../../lib/tabularImportPipelines', async () => {
  const actual = await vi.importActual<typeof import('../../lib/tabularImportPipelines')>('../../lib/tabularImportPipelines');
  return {
    ...actual,
    importTabular: (...a: unknown[]) => importTabular(...a),
    applyStemBoundaryCorrections: (...a: unknown[]) => applyStemBoundaryCorrections(...a),
    discardStemMappingDraft: (...a: unknown[]) => discardStemMappingDraft(...a),
  };
});

import ImportPurposeDialog from '../ImportPurposeDialog';
import { NeedsTheDedicatedTab } from '../../lib/tabularImportPipelines';

const boundaryCheck = {
  total_points: 120,
  out_of_boundary_count: 14,
  out_of_boundary_percentage: 11.7,
  within_tolerance: true,
  needs_correction: true,
  corrections: [
    { row_number: 3, species: 'Shorea robusta', original_x: 85.1, original_y: 27.1, corrected_x: 85.2, corrected_y: 27.2, distance_moved_meters: 12.5 },
  ],
  correction_summary: { total_corrections: 14, max_distance: 40, min_distance: 2, avg_distance: 11 },
};
const boundaryFix = () => new NeedsTheDedicatedTab('stem_mapping', 'boundary', undefined, { inventoryId: 'inv-9', boundaryCheck });

const file = () => new File(['x'], 'trees.xlsx', { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });

function open(onComplete = vi.fn()) {
  render(<ImportPurposeDialog file={file()} calculationId="calc-1" fixedPurpose="inventory" onComplete={onComplete} onCancel={vi.fn()} />);
  fireEvent.click(screen.getByRole('button', { name: /^Import$/i }));
  return onComplete;
}

beforeEach(() => {
  vi.clearAllMocks();
  importTabular.mockRejectedValue(boundaryFix());
  applyStemBoundaryCorrections.mockResolvedValue({ purpose: 'stem_mapping', findings: [], failed: false });
  discardStemMappingDraft.mockResolvedValue(undefined);
});

describe('a tree file with points outside the boundary, dropped into Import layer', () => {
  it('shows the correction preview, not "open the Tree mapping tab"', async () => {
    open();
    expect(await screen.findByText(en.treeMapping.correction.title)).toBeInTheDocument();
    expect(screen.queryByText(/Open the .* tab and upload the file there/)).not.toBeInTheDocument();
    expect(applyStemBoundaryCorrections).not.toHaveBeenCalled(); // nothing is moved until the user says so
  });

  it('accepting applies the corrections to that upload, processes the file and completes the import', async () => {
    const onComplete = open();
    fireEvent.click(await screen.findByText(en.treeMapping.correction.accept));
    await waitFor(() => expect(applyStemBoundaryCorrections).toHaveBeenCalledTimes(1));
    const [fix, sent] = applyStemBoundaryCorrections.mock.calls[0];
    expect(fix.inventoryId).toBe('inv-9');
    expect(sent).toBeInstanceOf(File);
    await waitFor(() => expect(onComplete).toHaveBeenCalledTimes(1));
    expect(onComplete.mock.calls[0][0]).toMatchObject({ success: true, featureCount: 120, purpose: 'inventory' });
  });

  it('declining removes the unprocessed upload and says the upload was cancelled', async () => {
    const onComplete = open();
    fireEvent.click(await screen.findByText(en.treeMapping.correction.cancelUpload));
    await waitFor(() => expect(discardStemMappingDraft).toHaveBeenCalledWith('inv-9'));
    expect(applyStemBoundaryCorrections).not.toHaveBeenCalled();
    expect(onComplete).not.toHaveBeenCalled();
    expect(await screen.findByText(en.treeMapping.tab.msgUploadCancelled)).toBeInTheDocument();
  });

  it('a failed correction shows why and does not complete', async () => {
    applyStemBoundaryCorrections.mockRejectedValue(new Error('Corrections could not be applied'));
    const onComplete = open();
    fireEvent.click(await screen.findByText(en.treeMapping.correction.accept));
    expect(await screen.findByText('Corrections could not be applied')).toBeInTheDocument();
    expect(onComplete).not.toHaveBeenCalled();
  });

  it('the other reasons still say so in words (columns, and data already there)', async () => {
    importTabular.mockRejectedValue(new NeedsTheDedicatedTab('stem_mapping', 'exists', 'old_trees.xlsx'));
    const { unmount } = render(<ImportPurposeDialog file={file()} calculationId="calc-1" fixedPurpose="inventory" onComplete={vi.fn()} onCancel={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /^Import$/i }));
    expect(await screen.findByText(/already has .* \(old_trees\.xlsx\)/)).toBeInTheDocument();
    unmount();
    importTabular.mockRejectedValue(new NeedsTheDedicatedTab('stem_mapping', 'columns'));
    render(<ImportPurposeDialog file={file()} calculationId="calc-1" fixedPurpose="inventory" onComplete={vi.fn()} onCancel={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /^Import$/i }));
    expect(await screen.findByText(/which column is which/)).toBeInTheDocument();
  });
});
