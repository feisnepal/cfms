import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, fireEvent, screen, waitFor } from '@testing-library/react';
import ImportPurposeDialog from '../ImportPurposeDialog';
import BoundaryPointFlowModal from '../BoundaryPointFlowModal';
import LayerContextMenu from '../LayerContextMenu';

vi.mock('react-leaflet', () => ({
  MapContainer: ({ children }: { children: React.ReactNode }) => <div data-testid="preview-map">{children}</div>,
  TileLayer: () => <div data-testid="tile-layer" />,
  CircleMarker: ({ center }: { center: [number, number] }) => <div data-testid="ghost-marker" data-center={center.join(',')} />,
  Polyline: () => <div data-testid="ghost-polyline" />,
  useMap: () => ({
    fitBounds: vi.fn(),
    setView: vi.fn(),
    getZoom: vi.fn(),
  }),
}));

vi.mock('../../hooks/useContextMenuUndoRedo', () => ({
  useContextMenuUndoRedo: () => ({
    canUndo: false,
    canRedo: false,
    undo: vi.fn(),
    redo: vi.fn(),
    pushOp: vi.fn(),
    pushAndExecute: vi.fn(),
  }),
}));

vi.mock('../../services/api', () => ({
  forestApi: {
    updateBoundaryGeometry: vi.fn(),
    mergeForestBoundary: vi.fn(),
    convertImportedToBuiltin: vi.fn(),
    previewBoundaryMapping: vi.fn(),
    updateBoundaryFromPoints: vi.fn(),
  },
  compartmentApi: {
    getCompartmentTree: vi.fn(),
  },
}));

vi.mock('../../hooks/useImportLayer', () => ({
  useImportLayer: () => ({ importLayer: vi.fn(), isImporting: false, progress: 0, progressMessage: '', reset: vi.fn() }),
}));

vi.mock('../../lib/parseBoundaryFile', () => ({
  parseBoundaryFile: vi.fn(),
  BOUNDARY_PARSE_EXTS: new Set(['geojson', 'json', 'kml', 'kmz', 'shp', 'zip', 'gpkg']),
}));

import { forestApi } from '../../services/api';
import { parseBoundaryFile } from '../../lib/parseBoundaryFile';

const POLYGON: GeoJSON.Feature = {
  type: 'Feature',
  geometry: {
    type: 'Polygon',
    coordinates: [[[80, 28], [81, 28], [81, 29], [80, 29], [80, 28]]],
  },
  properties: {},
};

function csvFile(): File {
  return new File(['longitude,latitude\n83.5,27.5\n83.6,27.6'], 'points.csv', { type: 'text/csv' });
}

function geoJsonFile(): File {
  return new File([JSON.stringify(POLYGON)], 'boundary.geojson', { type: 'application/geo+json' });
}

const MAPPED_PREVIEW = {
  success: true,
  filename: 'points.csv',
  total_rows: 2,
  csv_columns: ['longitude', 'latitude'],
  sample_data: [{ longitude: 83.5, latitude: 27.5 }],
  mapping: { longitude: 'LONGITUDE', latitude: 'LATITUDE' },
  confidence: { longitude: 100, latitude: 100 },
  unmapped_columns: [],
  missing_required: [],
  duplicates: {},
  needs_user_input: false,
  required_columns: ['LONGITUDE', 'LATITUDE'],
  optional_columns: [],
  detected_crs: 4326,
  points_4326: [{ lng: 83.5, lat: 27.5 }, { lng: 83.6, lat: 27.6 }],
};

const NEEDS_INPUT_PREVIEW = {
  ...MAPPED_PREVIEW,
  mapping: {},
  confidence: {},
  unmapped_columns: ['longitude', 'latitude'],
  needs_user_input: true,
  detected_crs: null,
  points_4326: [],
};

describe('BoundaryPointFlow — routing in ImportPurposeDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('csv + boundary purpose routes to the point-flow preview (NOT parseBoundaryFile)', async () => {
    const mockPreview = forestApi.previewBoundaryMapping as unknown as ReturnType<typeof vi.fn>;
    mockPreview.mockResolvedValueOnce(MAPPED_PREVIEW);

    render(
      <ImportPurposeDialog
        file={csvFile()}
        calculationId="calc-1"
        fixedPurpose="boundary"
        onComplete={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /Import/i }));

    await waitFor(() => {
      expect(mockPreview).toHaveBeenCalledTimes(1);
    });
    expect(mockPreview).toHaveBeenCalledWith('calc-1', expect.any(File));
    expect(parseBoundaryFile).not.toHaveBeenCalled();
    // The ImportPurposeDialog body must not linger behind the preview modal.
    await waitFor(() => {
      expect(screen.queryByText(/Import Layer/)).toBeNull();
    });
    expect(screen.queryByRole('button', { name: /^Import$/ })).toBeNull();
  });

  it('geojson + boundary purpose keeps the existing parseBoundaryFile path', async () => {
    const mockParse = parseBoundaryFile as unknown as ReturnType<typeof vi.fn>;
    mockParse.mockResolvedValueOnce(POLYGON);
    const mockUpdate = forestApi.updateBoundaryGeometry as unknown as ReturnType<typeof vi.fn>;
    mockUpdate.mockResolvedValueOnce({ success: true, area_hectares: 12.5 });

    render(
      <ImportPurposeDialog
        file={geoJsonFile()}
        calculationId="calc-1"
        fixedPurpose="boundary"
        onComplete={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /Import/i }));

    await waitFor(() => {
      expect(mockParse).toHaveBeenCalledTimes(1);
    });
    expect(forestApi.previewBoundaryMapping).not.toHaveBeenCalled();
  });
});

describe('BoundaryPointFlowModal — a station with one mistyped digit', () => {
  const ISSUE = {
    row: 17, point: { lng: 85.484728, lat: 27.41 }, detour_m: 11293, typical_leg_m: 248, typed: { x: '85.484728', y: '27.410000' },
    repairs: [{ axis: 'x' as const, kind: 'digit', typed_from: '85.484728', typed_to: '85.424728', point: { lng: 85.424728, lat: 27.41 }, moved_m: 5943 }],
  };

  it('names the row, says what the digit most likely is, and marks the station and its repair on the map', async () => {
    render(
      <BoundaryPointFlowModal file={csvFile()} preview={{ ...MAPPED_PREVIEW, station_issues: [ISSUE] }} calculationId="calc-1" onComplete={vi.fn()} onCancel={vi.fn()} />,
    );
    const box = await screen.findByTestId('station-issues');
    expect(box.textContent).toContain('1 station(s) look mistyped');
    expect(box.textContent).toContain('Row 17 lies 11,293 m off the walk');
    expect(box.textContent).toContain('85.484728 should be 85.424728');
    // the two ordinary points + the orange ring on the suspect + the repair point
    expect(screen.getAllByTestId('ghost-marker')).toHaveLength(MAPPED_PREVIEW.points_4326.length + 2);
  });

  it('says so plainly when no single digit fits', async () => {
    render(
      <BoundaryPointFlowModal file={csvFile()} preview={{ ...MAPPED_PREVIEW, station_issues: [{ ...ISSUE, repairs: [] }] }} calculationId="calc-1" onComplete={vi.fn()} onCancel={vi.fn()} />,
    );
    expect((await screen.findByTestId('station-issues')).textContent).toContain('No single-digit correction fits');
  });

  it('shows nothing when the stations are fine', async () => {
    render(<BoundaryPointFlowModal file={csvFile()} preview={{ ...MAPPED_PREVIEW, station_issues: [] }} calculationId="calc-1" onComplete={vi.fn()} onCancel={vi.fn()} />);
    await screen.findByRole('button', { name: /Create Boundary/i });
    expect(screen.queryByTestId('station-issues')).toBeNull();
  });
});

describe('BoundaryPointFlowModal — two-step flow', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('needs_user_input renders ColumnMappingPreview, confirm re-previews with mapping', async () => {
    const mockPreview = forestApi.previewBoundaryMapping as unknown as ReturnType<typeof vi.fn>;
    mockPreview.mockResolvedValueOnce(MAPPED_PREVIEW);

    render(
      <BoundaryPointFlowModal
        file={csvFile()}
        preview={NEEDS_INPUT_PREVIEW}
        calculationId="calc-1"
        onComplete={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByText('Column Mapping Confirmation')).toBeTruthy();

    const selects = screen.getAllByRole('combobox');
    expect(selects.length).toBeGreaterThanOrEqual(2);
    fireEvent.change(selects[0], { target: { value: 'LONGITUDE' } });
    fireEvent.change(selects[1], { target: { value: 'LATITUDE' } });

    const confirmBtn = screen.getByRole('button', { name: /Confirm & Upload/i });
    expect((confirmBtn as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(mockPreview).toHaveBeenCalledTimes(1);
    });
    const [calcId, file, opts] = mockPreview.mock.calls[0];
    expect(calcId).toBe('calc-1');
    expect(opts.mapping).toBeDefined();
  });

  it('auto-mapped preview goes straight to geometry and confirm calls updateBoundaryFromPoints', async () => {
    const mockUpdate = forestApi.updateBoundaryFromPoints as unknown as ReturnType<typeof vi.fn>;
    mockUpdate.mockResolvedValueOnce({ success: true });

    const onComplete = vi.fn();
    render(
      <BoundaryPointFlowModal
        file={csvFile()}
        preview={MAPPED_PREVIEW}
        calculationId="calc-1"
        onComplete={onComplete}
        onCancel={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Create Boundary/i })).toBeTruthy();
    });

    fireEvent.click(screen.getByRole('button', { name: /Create Boundary/i }));

    await waitFor(() => {
      expect(mockUpdate).toHaveBeenCalledTimes(1);
    });
    const [calcId, points, method] = mockUpdate.mock.calls[0];
    expect(calcId).toBe('calc-1');
    expect(points).toEqual(MAPPED_PREVIEW.points_4326);
    expect(method).toBe('ordered');
    expect(onComplete).toHaveBeenCalledTimes(1);
  });

  it('renders a ghost preview with a marker per 4326 point', async () => {
    render(
      <BoundaryPointFlowModal
        file={csvFile()}
        preview={MAPPED_PREVIEW}
        calculationId="calc-1"
        onComplete={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(screen.getAllByTestId('ghost-marker').length).toBe(2);
    });
  });
});

describe('LayerContextMenu — Forest Boundary point-file entry', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows "Create Boundary from Point File" on the boundary row and fires onImportLayer', () => {
    const onImportLayer = vi.fn();
    render(
      <LayerContextMenu
        layerId="boundary"
        layerType="builtin"
        layerName="Forest Boundary"
        visible
        labelsShown={false}
        featureCount={1}
        editable
        locked={false}
        position={{ x: 10, y: 10 }}
        onClose={vi.fn()}
        map={null}
        onImportLayer={onImportLayer}
      />,
    );

    const item = screen.getByRole('menuitem', { name: /Create Boundary from Point File/i });
    expect(item).toBeTruthy();
    fireEvent.click(item);
    expect(onImportLayer).toHaveBeenCalledWith('boundary', 'boundary');
  });
});
