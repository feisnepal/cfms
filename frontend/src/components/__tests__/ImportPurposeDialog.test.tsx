import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, fireEvent, screen, waitFor } from '@testing-library/react';
import ImportPurposeDialog from '../ImportPurposeDialog';

vi.mock('../../services/api', () => ({
  forestApi: {
    updateBoundaryGeometry: vi.fn(),
    mergeForestBoundary: vi.fn(),
    convertImportedToBuiltin: vi.fn(),
  },
  compartmentApi: {
    getCompartmentTree: vi.fn(),
  },
  userGroupApi: {
    importExtent: vi.fn(),
  },
}));

const importLayerMock = vi.fn();
vi.mock('../../hooks/useImportLayer', () => ({
  useImportLayer: () => ({ importLayer: importLayerMock }),
}));

import { forestApi, compartmentApi, userGroupApi } from '../../services/api';

const POLYGON: GeoJSON.Feature = {
  type: 'Feature',
  geometry: {
    type: 'Polygon',
    coordinates: [[[80, 28], [81, 28], [81, 29], [80, 29], [80, 28]]],
  },
  properties: {},
};

function geoJsonFile(): File {
  return new File([JSON.stringify(POLYGON)], 'boundary.geojson', { type: 'application/geo+json' });
}

describe('ImportPurposeDialog — purpose-first "Add Geometry" (Phase 6)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('offers Field Inventory and Households for a spreadsheet, and preselects the one it was recognised as', () => {
    render(
      <ImportPurposeDialog
        file={new File(['x'], 'inventory_data.csv', { type: 'text/csv' })}
        calculationId="calc-1"
        fixedPurpose="field_inventory"
        onComplete={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    const fi = screen.getByText('Field Inventory').closest('button') as HTMLButtonElement;
    expect(fi).toBeTruthy();
    expect(fi.className).toContain('border-green-500'); // the selected one
    expect(screen.getByText('Households')).toBeTruthy();
    expect(screen.getByText('Sample Plot')).toBeTruthy();
  });

  it('does not offer the table-only purposes for a map file', () => {
    render(<ImportPurposeDialog file={geoJsonFile()} calculationId="calc-1" onComplete={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.queryByText('Field Inventory')).toBeNull();
    expect(screen.queryByText('Households')).toBeNull();
  });

  it('restrictToGeometry hides non-geometry purposes (only Boundary + Blocks offered)', () => {
    render(
      <ImportPurposeDialog
        file={geoJsonFile()}
        calculationId="calc-1"
        restrictToGeometry
        onComplete={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.getByText('Boundary')).toBeTruthy();
    expect(screen.getByText('Blocks')).toBeTruthy();
    expect(screen.queryByText('Tree Inventory')).toBeNull();
    expect(screen.queryByText('Sample Plot')).toBeNull();
    expect(screen.queryByText('Roads & Trails')).toBeNull();
  });

  it('offers all purposes when not restricted', () => {
    render(
      <ImportPurposeDialog
        file={geoJsonFile()}
        calculationId="calc-1"
        onComplete={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.getByText('Tree Inventory')).toBeTruthy();
    expect(screen.getByText('Sample Plot')).toBeTruthy();
    expect(screen.getByText('Roads & Trails')).toBeTruthy();
  });

  it('Forest-boundary purpose import routes to updateBoundaryGeometry (not an imported layer)', async () => {
    const onBoundarySaved = vi.fn();
    const onComplete = vi.fn();
    const mockUpdate = forestApi.updateBoundaryGeometry as unknown as ReturnType<typeof vi.fn>;
    mockUpdate.mockResolvedValueOnce({ success: true, area_hectares: 12.5 });

    render(
      <ImportPurposeDialog
        file={geoJsonFile()}
        calculationId="calc-1"
        restrictToGeometry
        onBoundarySaved={onBoundarySaved}
        onComplete={onComplete}
        onCancel={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /Import/i }));

    await waitFor(() => {
      expect(mockUpdate).toHaveBeenCalledTimes(1);
    });
    const [calcId, body] = mockUpdate.mock.calls[0];
    expect(calcId).toBe('calc-1');
    expect(body.area_hectares).toBe(0);
    expect(body.geometry).toBeTruthy();
    expect(body.geometry.type).toBe('Feature');

    expect(onBoundarySaved).toHaveBeenCalledTimes(1);
    expect(onComplete).toHaveBeenCalledTimes(1);
    const result = onComplete.mock.calls[0][0];
    expect(result.success).toBe(true);
  });

  it('user_group_boundary purpose imports the extent directly (no auxiliary layer)', async () => {
    const onComplete = vi.fn();
    const mockImport = userGroupApi.importExtent as unknown as ReturnType<typeof vi.fn>;
    mockImport.mockResolvedValueOnce({ extent_id: 9, message: 'ok' });

    render(
      <ImportPurposeDialog
        file={geoJsonFile()}
        calculationId="calc-1"
        fixedPurpose="user_group_boundary"
        onComplete={onComplete}
        onCancel={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /Import/i }));

    await waitFor(() => expect(mockImport).toHaveBeenCalledTimes(1));
    expect(mockImport.mock.calls[0][0]).toBe('calc-1');
    expect(mockImport.mock.calls[0][1]).toBeInstanceOf(File);
    expect(importLayerMock).not.toHaveBeenCalled(); // never goes through the generic layer path
    expect(onComplete).toHaveBeenCalledTimes(1);
    expect(onComplete.mock.calls[0][0]).toMatchObject({ success: true, purpose: 'user_group_boundary' });
  });

  it('user group import over an existing boundary asks first, and sends nothing when the user says no (decision D3)', async () => {
    const { useWorkspaceStore } = await import('../../store/workspaceStore');
    useWorkspaceStore.setState({ featureCounts: { user_group: 2 } } as never);
    const mockImport = userGroupApi.importExtent as unknown as ReturnType<typeof vi.fn>;
    mockImport.mockClear();
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(<ImportPurposeDialog file={geoJsonFile()} calculationId="calc-1" fixedPurpose="user_group_boundary" onComplete={vi.fn()} onCancel={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /Import/i }));
    await waitFor(() => expect(confirmSpy).toHaveBeenCalledTimes(1));
    try {
      expect(String(confirmSpy.mock.calls[0][0])).toContain('2 polygon'); // says what will be replaced
      expect(mockImport).not.toHaveBeenCalled();

      confirmSpy.mockReturnValue(true);
      mockImport.mockResolvedValueOnce({ extent_id: 9, message: 'ok' });
      fireEvent.click(screen.getByRole('button', { name: /Import/i }));
      await waitFor(() => expect(mockImport).toHaveBeenCalledTimes(1));
    } finally {
      confirmSpy.mockRestore(); // never leak the spy or the store into the next test
      useWorkspaceStore.setState({ featureCounts: {} } as never);
    }
  });

  it('a refused user group file shows what is wrong and how to fix it, not a bare message', async () => {
    const mockImport = userGroupApi.importExtent as unknown as ReturnType<typeof vi.fn>;
    mockImport.mockClear();
    mockImport.mockRejectedValueOnce({ response: { data: { detail: { code: 'user_group.too_large', message: 'm', message_np: 'n', findings: [{
      code: 'user_group.too_large', severity: 'error', title_en: 'The user group would cover 98,589 ha.', title_ne: 'न', fix_en: 'Draw or upload a smaller boundary.', fix_ne: 'स',
      where: {}, found: '', expected: '' }] } } } });
    render(<ImportPurposeDialog file={geoJsonFile()} calculationId="calc-1" fixedPurpose="user_group_boundary" onComplete={vi.fn()} onCancel={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /Import/i }));
    const box = await screen.findByTestId('finding-user_group.too_large');
    expect(box.textContent).toContain('98,589 ha');
    expect(box.textContent).toContain('smaller boundary');
  });

  it('sub_areas import is append-only: replaceExisting=false (no Replace UI)', async () => {
    const onComplete = vi.fn();
    importLayerMock.mockResolvedValueOnce({
      success: true,
      layerId: 42,
      layerName: 'Sub Areas 1',
      featureCount: 3,
      geometryTypes: ['Polygon'],
    });
    const mockConvert = forestApi.convertImportedToBuiltin as unknown as ReturnType<typeof vi.fn>;
    mockConvert.mockResolvedValueOnce({
      success: true,
      results: { sub_areas: [{ id: 'a' }] },
      importSummary: { imported: 3, clipped: 0, removed: 0, overlapped: 0, dropped_unclosed: 0 },
    });

    render(
      <ImportPurposeDialog
        file={geoJsonFile()}
        calculationId="calc-1"
        fixedPurpose="sub_areas"
        onComplete={onComplete}
        onCancel={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /Import/i }));

    await waitFor(() => {
      expect(importLayerMock).toHaveBeenCalledTimes(1);
    });
    const callArg = importLayerMock.mock.calls[0][0];
    expect(callArg).toMatchObject({ calculationId: 'calc-1', purpose: 'sub_areas' });
    // Append-only: never passes replaceExisting=true for sub_areas.
    expect(callArg.replaceExisting).toBe(false);
  });

  it('compartments import with existing derived compartments shows Replace confirm and converts on OK', async () => {
    const onComplete = vi.fn();
    importLayerMock.mockResolvedValueOnce({
      success: true,
      layerId: 55,
      layerName: 'Compartments 1',
      featureCount: 2,
      geometryTypes: ['Polygon'],
    });
    const mockConvert = forestApi.convertImportedToBuiltin as unknown as ReturnType<typeof vi.fn>;
    mockConvert.mockResolvedValueOnce({ success: true, created: 2, import_summary: { imported: 2 } });
    const mockTree = compartmentApi.getCompartmentTree as unknown as ReturnType<typeof vi.fn>;
    mockTree.mockResolvedValueOnce({ blocks: [{ id: 'comp-1' }, { id: 'comp-2' }], total_compartments: 2 });

    render(
      <ImportPurposeDialog
        file={geoJsonFile()}
        calculationId="calc-1"
        fixedPurpose="compartments"
        onComplete={onComplete}
        onCancel={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /Import/i }));

    // Overwrite confirm appears because derived compartments exist.
    await waitFor(() => {
      expect(screen.getByText(/Importing will replace all existing/)).toBeTruthy();
    });
    fireEvent.click(screen.getByRole('button', { name: /Overwrite/i }));

    await waitFor(() => {
      expect(mockConvert).toHaveBeenCalledTimes(1);
    });
    expect(mockConvert).toHaveBeenCalledWith('calc-1', 55, 'compartments', { confirm: true });
    expect(onComplete).toHaveBeenCalledWith(
      expect.objectContaining({ purpose: 'compartments', converted: true }),
    );
  });

  it('compartments import with no existing derived compartments converts directly (no Replace UI)', async () => {
    const onComplete = vi.fn();
    importLayerMock.mockResolvedValueOnce({
      success: true,
      layerId: 56,
      layerName: 'Compartments 2',
      featureCount: 2,
      geometryTypes: ['Polygon'],
    });
    const mockConvert = forestApi.convertImportedToBuiltin as unknown as ReturnType<typeof vi.fn>;
    mockConvert.mockResolvedValueOnce({ success: true, created: 2, import_summary: { imported: 2 } });
    const mockTree = compartmentApi.getCompartmentTree as unknown as ReturnType<typeof vi.fn>;
    mockTree.mockResolvedValueOnce({ blocks: [], total_compartments: 0 });

    render(
      <ImportPurposeDialog
        file={geoJsonFile()}
        calculationId="calc-1"
        fixedPurpose="compartments"
        onComplete={onComplete}
        onCancel={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /Import/i }));

    await waitFor(() => {
      expect(mockConvert).toHaveBeenCalledTimes(1);
    });
    expect(screen.queryByText(/Importing will replace all existing/)).toBeNull();
  });
});