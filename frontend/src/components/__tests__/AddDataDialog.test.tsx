import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import AddDataDialog, { type ResolvedUpload } from '../AddDataDialog';
import type { UploadSchema } from '../../lib/classifyUpload';

const SCHEMA: UploadSchema = {
  schema_version: '1.0',
  purposes: [
    {
      id: 'forest_boundary',
      label_en: 'Forest boundary',
      label_ne: '',
      kind: 'spatial',
      order: 0,
      layer_name: 'forest_boundary',
      name_aliases: ['boundary'],
      geometry_types: ['POLYGON'],
    },
    {
      id: 'blocks',
      label_en: 'Blocks',
      label_ne: '',
      kind: 'spatial',
      order: 10,
      layer_name: 'blocks',
      name_aliases: ['block'],
      geometry_types: ['POLYGON'],
    },
    {
      id: 'trees',
      label_en: 'Trees',
      label_ne: '',
      kind: 'spatial_or_tabular',
      order: 40,
      layer_name: 'trees',
      name_aliases: ['inventory'],
      geometry_types: ['POINT'],
    },
    {
      id: 'field_inventory',
      label_en: 'Field inventory',
      label_ne: '',
      kind: 'tabular',
      order: 45,
      layer_name: 'field_inventory',
      name_aliases: ['fieldinventory'],
    },
    {
      id: 'households',
      label_en: 'Households',
      label_ne: '',
      kind: 'tabular',
      order: 50,
      layer_name: 'households',
      name_aliases: ['household', 'hh'],
    },
  ],
};

const getSchema = vi.fn();
const downloadWorkbook = vi.fn();
const classifyUpload = vi.fn();
const coordinateSystem = vi.fn();
vi.mock('../../services/api', () => ({
  uploadApi: {
    coordinateSystem: (file: File, calc?: string) => coordinateSystem(file, calc),
    getSchema: () => getSchema(),
    downloadWorkbook: (format: string) => downloadWorkbook(format),
    classifyUpload: (file: File) => classifyUpload(file),
  },
}));

// The dialog now runs the imports itself and shows their report in place (UP-4.3).
// Stub the runner so the test drives the finish state without real imports.
vi.mock('../BulkImportRunner', () => ({
  default: ({ items, onDone }: { items: ResolvedUpload[]; onDone: (f: unknown[]) => void }) => (
    <div data-testid="bulk-runner">
      <span data-testid="bulk-count">{items.length}</span>
      <span data-testid="bulk-items">{JSON.stringify(items.map((i) => ({ p: i.purposeId, c: i.crsEpsg ?? null, k: i.corrections ?? null })))}</span>
      <button onClick={() => onDone([])}>finish-clean</button>
      <button
        onClick={() =>
          onDone([
            {
              code: 'field_inventory.corrections_proposed', severity: 'error', title_en: '1 value was refused', title_ne: '', fix_en: 'Review', fix_ne: '',
              where: { file: 'plots.csv', rows: [4], proposals: [{ row: 4, column: 'pole_dbh_cm', stand: 'pole', measure: 'dbh', old: 50, new: 22.3, range: '10 to under 30 cm', belongs_to: 'tree' }] },
              found: '', expected: '', auto_fix: 'replace_random_in_class',
            },
          ])
        }
      >
        finish-refused
      </button>
      <button
        onClick={() =>
          onDone([
            {
              code: 'no_rows',
              severity: 'warning',
              title_en: 'No rows',
              title_ne: 'पङ्क्ति छैन',
              fix_en: 'Add rows',
              fix_ne: 'पङ्क्ति थप्नुहोस्',
              where: {},
              found: '',
              expected: '',
            },
          ])
        }
      >
        finish-warn
      </button>
    </div>
  ),
}));


function drop(_container: HTMLElement, files: File[]) {
  // antd Upload renders its <input type="file"> in the modal portal (document.body).
  const input = document.querySelector(
    '.ant-upload input[type="file"]',
  ) as HTMLInputElement;
  fireEvent.change(input, { target: { files } });
}

function file(name: string): File {
  return new File(['x'], name, { type: 'application/octet-stream' });
}

describe('AddDataDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getSchema.mockResolvedValue(SCHEMA);
    classifyUpload.mockResolvedValue({ best: null });
    coordinateSystem.mockResolvedValue({ has_coordinates: false });
  });

  it('loads the schema and shows the dropzone', async () => {
    render(
      <AddDataDialog
        open
        calculationId="c1"
        hasBoundary
        onClose={vi.fn()}
      />,
    );
    await waitFor(() => expect(getSchema).toHaveBeenCalled());
    expect(await screen.findByText('Click or drag files here')).toBeInTheDocument();
  });

  it('surfaces a schema load failure', async () => {
    getSchema.mockRejectedValueOnce(new Error('boom'));
    render(
      <AddDataDialog
        open
        calculationId="c1"
        hasBoundary
        onClose={vi.fn()}
      />,
    );
    expect(
      await screen.findByText(/Could not load the upload schema/i),
    ).toBeInTheDocument();
  });

  it('classifies a dropped file, runs the import and shows its report in the dialog', async () => {
    const onClose = vi.fn();
    const { container } = render(
      <AddDataDialog
        open
        calculationId="c1"
        hasBoundary
        onClose={onClose}
      />,
    );
    await screen.findByText('Click or drag files here');

    drop(container, [file('brindaban-blocks.geojson')]);

    expect(await screen.findByText('matched by name')).toBeInTheDocument();
    expect(screen.getByText('brindaban-blocks.geojson')).toBeInTheDocument();

    const addBtn = screen.getByRole('button', { name: /Add \(1\)/ });
    await waitFor(() => expect(addBtn).toBeEnabled());
    fireEvent.click(addBtn);

    // The dialog runs the imports itself: the runner receives the resolved pair.
    expect(await screen.findByTestId('bulk-count')).toHaveTextContent('1');
    // Nothing closes before the report is shown.
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.click(screen.getByText('finish-warn'));
    expect(await screen.findByTestId('upload-report')).toBeInTheDocument();
    expect(screen.getByTestId('finding-no_rows')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Done' }));
    expect(onClose).toHaveBeenCalled();
  });

  it('shows a clean report when the import produced no findings', async () => {
    const { container } = render(
      <AddDataDialog
        open
        calculationId="c1"
        hasBoundary
        onClose={vi.fn()}
      />,
    );
    await screen.findByText('Click or drag files here');

    drop(container, [file('brindaban-blocks.geojson')]);
    await screen.findByText('matched by name');
    const addBtn = screen.getByRole('button', { name: /Add \(1\)/ });
    await waitFor(() => expect(addBtn).toBeEnabled());
    fireEvent.click(addBtn);

    fireEvent.click(await screen.findByText('finish-clean'));
    expect(await screen.findByText('Every file imported cleanly — nothing to fix.')).toBeInTheDocument();
    expect(screen.queryByTestId('upload-report')).not.toBeInTheDocument();
  });

  it('blocks submit until an unrecognized file is given a type', async () => {
    const { container } = render(
      <AddDataDialog
        open
        calculationId="c1"
        hasBoundary
        onClose={vi.fn()}
      />,
    );
    await screen.findByText('Click or drag files here');

    drop(container, [file('export_2026.csv')]);
    expect(await screen.findByText('not recognized')).toBeInTheDocument();

    // "Add" (no count) is disabled while the row has no resolved purpose
    const addBtn = screen.getByRole('button', { name: /^Add$/ });
    expect(addBtn).toBeDisabled();
  });

  it('blocks a file whose detected type has no workspace import path', async () => {
    const { container } = render(
      <AddDataDialog
        open
        calculationId="c1"
        hasBoundary
        onClose={vi.fn()}
        // A caller that imports only geometry: households then has no path here.
        importablePurposeIds={['blocks']}
      />,
    );
    await screen.findByText('Click or drag files here');

    // households classifies by name, but this caller has no import path for it
    drop(container, [file('blocks.geojson'), file('households.csv')]);
    expect(
      await screen.findByText(/uploaded from its own tab/i),
    ).toBeInTheDocument();

    // blocks resolved, households blocking → submit stays disabled
    expect(screen.getByRole('button', { name: /Add \(1\)/ })).toBeDisabled();

    // removing the households row unblocks it
    const removeBtns = screen.getAllByRole('button', { name: 'Remove' });
    fireEvent.click(removeBtns[1]);
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Add \(1\)/ })).toBeEnabled(),
    );
  });

  it('enforces the boundary-first gate when the forest has no boundary', async () => {
    const { container } = render(
      <AddDataDialog
        open
        calculationId="c1"
        hasBoundary={false}
        onClose={vi.fn()}
      />,
    );
    await screen.findByText('Click or drag files here');

    drop(container, [file('blocks.geojson')]);
    await screen.findByText('matched by name');

    expect(screen.getByText('This forest has no boundary yet')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Add \(1\)/ })).toBeDisabled();

    // adding a boundary file clears the gate
    drop(container, [file('forest_boundary.kml')]);
    await waitFor(() =>
      expect(
        screen.queryByText('This forest has no boundary yet'),
      ).not.toBeInTheDocument(),
    );
    expect(screen.getByRole('button', { name: /Add \(2\)/ })).toBeEnabled();
  });

  it('treats a lone unrecognised spatial file as the boundary when the forest has none', async () => {
    const { container } = render(<AddDataDialog open calculationId="c1" hasBoundary={false} onClose={vi.fn()} />);
    await screen.findByText('Click or drag files here');

    drop(container, [file('outer_limit.geojson')]);
    expect(await screen.findByText(/has no boundary yet, so this looks like it/)).toBeInTheDocument();
    expect(screen.queryByText('This forest has no boundary yet')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Add \(1\)/ })).toBeEnabled();
  });

  it('takes a spreadsheet the server reads as boundary points for the boundary', async () => {
    classifyUpload.mockResolvedValue({ best: 'forest_boundary', lat_col: 'lat', lon_col: 'lon' });
    const { container } = render(<AddDataDialog open calculationId="c1" hasBoundary={false} onClose={vi.fn()} />);
    await screen.findByText('Click or drag files here');

    drop(container, [file('outer_points.csv')]);
    expect(await screen.findByText('matched by content')).toBeInTheDocument();
    expect(screen.queryByText('This forest has no boundary yet')).not.toBeInTheDocument();
  });

  it('does not guess a boundary for a spreadsheet of coordinates the server cannot place', async () => {
    classifyUpload.mockResolvedValue({ best: null, lat_col: 'lat', lon_col: 'lon' });
    const { container } = render(<AddDataDialog open calculationId="c1" hasBoundary={false} onClose={vi.fn()} />);
    await screen.findByText('Click or drag files here');

    drop(container, [file('field_points.csv')]);
    expect(await screen.findByText('not recognized')).toBeInTheDocument();
    expect(screen.getByText('This forest has no boundary yet')).toBeInTheDocument();
  });

  it('treats a lone zipped shapefile and a lone GPX track alike', async () => {
    for (const name of ['limit.zip', 'walk.gpx', 'ring.kmz']) {
      const { container, unmount } = render(<AddDataDialog open calculationId="c1" hasBoundary={false} onClose={vi.fn()} />);
      await screen.findByText('Click or drag files here');
      drop(container, [file(name)]);
      expect(await screen.findByText(/has no boundary yet, so this looks like it/)).toBeInTheDocument();
      unmount();
    }
  });

  it('does not guess when the unrecognised file is not spatial', async () => {
    const { container } = render(<AddDataDialog open calculationId="c1" hasBoundary={false} onClose={vi.fn()} />);
    await screen.findByText('Click or drag files here');

    drop(container, [file('export_2026.csv')]);
    expect(await screen.findByText('not recognized')).toBeInTheDocument();
    expect(screen.getByText('This forest has no boundary yet')).toBeInTheDocument();
  });

  it('stops a file whose features all lie outside this forest', async () => {
    classifyUpload.mockResolvedValue({ best: 'trees', forest_overlap: { status: 'outside', features: 12, inside: 0, outside: 12, distance_km: 34.2 } });
    const { container } = render(<AddDataDialog open calculationId="c1" hasBoundary onClose={vi.fn()} />);
    await screen.findByText('Click or drag files here');

    drop(container, [file('plots_other_forest.csv')]);
    const note = await screen.findByTestId('outside-forest');
    expect(note).toHaveTextContent(/None of the 12 features/);
    expect(note).toHaveTextContent(/34\.2 km/);
    expect(screen.getByRole('button', { name: /^Add/ })).toBeDisabled();
    expect(classifyUpload).toHaveBeenCalled();
  });

  it('only warns when part of the file lies outside, and does not block', async () => {
    classifyUpload.mockResolvedValue({ best: 'trees', forest_overlap: { status: 'partial', features: 10, inside: 7, outside: 3, distance_km: 1.2 } });
    const { container } = render(<AddDataDialog open calculationId="c1" hasBoundary onClose={vi.fn()} />);
    await screen.findByText('Click or drag files here');

    drop(container, [file('plots_mixed.csv')]);
    expect(await screen.findByTestId('partly-outside-forest')).toHaveTextContent('3 of 10 features');
    expect(screen.getByRole('button', { name: /^Add/ })).toBeEnabled();
  });

  it('does not stop a boundary file for lying outside (it defines the forest)', async () => {
    classifyUpload.mockResolvedValue({ best: 'forest_boundary', forest_overlap: { status: 'outside', features: 1, inside: 0, outside: 1, distance_km: 5 } });
    const { container } = render(<AddDataDialog open calculationId="c1" hasBoundary onClose={vi.fn()} />);
    await screen.findByText('Click or drag files here');

    drop(container, [file('new_limit.geojson')]);
    await screen.findByText(/matched by content|not recognized/);
    expect(screen.queryByTestId('outside-forest')).not.toBeInTheDocument();
  });

  it('downloads the workbook in both forms', async () => {
    downloadWorkbook.mockResolvedValue(undefined);
    render(
      <AddDataDialog
        open
        calculationId="c1"
        hasBoundary
        onClose={vi.fn()}
      />,
    );
    await screen.findByText('Click or drag files here');

    fireEvent.click(screen.getByRole('button', { name: 'Excel (.xlsx)' }));
    fireEvent.click(screen.getByRole('button', { name: 'GeoPackage (.gpkg)' }));
    await waitFor(() => {
      expect(downloadWorkbook).toHaveBeenCalledWith('xlsx');
      expect(downloadWorkbook).toHaveBeenCalledWith('gpkg');
    });
  });

  it('identifies an unnamed file by its contents and lets it be submitted', async () => {
    classifyUpload.mockResolvedValue({ best: 'trees' });
    const { container } = render(
      <AddDataDialog
        open
        calculationId="c1"
        hasBoundary
        onClose={vi.fn()}
      />,
    );
    await screen.findByText('Click or drag files here');

    drop(container, [file('export_2026.csv')]);

    expect(await screen.findByText('matched by content')).toBeInTheDocument();
    const addBtn = screen.getByRole('button', { name: /Add \(1\)/ });
    await waitFor(() => expect(addBtn).toBeEnabled());
    fireEvent.click(addBtn);
    expect(await screen.findByTestId('bulk-count')).toHaveTextContent('1');
  });

  it('says what a file looks like when its contents disagree with the chosen type', async () => {
    classifyUpload.mockResolvedValue({ best: 'households' });
    const { container } = render(
      <AddDataDialog
        open
        calculationId="c1"
        hasBoundary
        onClose={vi.fn()}
      />,
    );
    await screen.findByText('Click or drag files here');

    // named as blocks (matched by name), but the contents look like households
    drop(container, [file('blocks.geojson')]);
    expect(await screen.findByText('This looks like Households.')).toBeInTheDocument();

    // accepting the suggestion re-points the row
    fireEvent.click(screen.getByRole('button', { name: 'Use Households' }));
    await waitFor(() =>
      expect(screen.queryByText('This looks like Households.')).not.toBeInTheDocument(),
    );
  });

  describe('coordinate system of a table (C2)', () => {
    const LABELS = { '4326': 'Degrees (WGS 84)', '32644': 'UTM zone 44N', '32645': 'UTM zone 45N' };

    async function dropTable(info: Record<string, unknown>) {
      classifyUpload.mockResolvedValue({ best: 'field_inventory' });
      coordinateSystem.mockResolvedValue({ has_coordinates: true, labels: LABELS, dominant: 'utm', candidates: [{ epsg: 32645, zone: 45, label: 'UTM zone 45N', inside_fraction: 1, near_forest: false }], ...info });
      const { container } = render(<AddDataDialog open calculationId="c1" hasBoundary onClose={vi.fn()} />);
      await screen.findByText('Click or drag files here');
      drop(container, [file('plots_utm.csv')]);
      return screen.findByTestId('coordinate-system');
    }

    it('pre-selects the detected system and sends it with the file', async () => {
      const box = await dropTable({ suggested_epsg: 32645, ambiguous: false });
      expect(box).toHaveTextContent('Coordinate system');
      expect(box).toHaveTextContent('UTM zone 45N');
      expect(box).toHaveTextContent('Detected from the numbers');
      const addBtn = screen.getByRole('button', { name: /Add \(1\)/ });
      await waitFor(() => expect(addBtn).toBeEnabled());
      fireEvent.click(addBtn);
      expect(JSON.parse((await screen.findByTestId('bulk-items')).textContent as string)).toEqual([{ p: 'field_inventory', c: 32645, k: null }]);
    });

    it('asks, and blocks the import, when the numbers fit both UTM zones', async () => {
      const box = await dropTable({ suggested_epsg: null, ambiguous: true });
      expect(box).toHaveTextContent('fit both UTM zones');
      expect(screen.getByRole('button', { name: /Add \(1\)/ })).toBeDisabled();
    });

    it('says so when the numbers fit neither zone inside Nepal', async () => {
      const box = await dropTable({ suggested_epsg: null, none_fit: true });
      expect(box).toHaveTextContent('do not land inside Nepal');
      expect(screen.getByRole('button', { name: /Add \(1\)/ })).toBeDisabled();
    });

    it('names the rows that have no coordinates or are in another form', async () => {
      const box = await dropTable({ suggested_epsg: 32645, missing_rows: [3, 7], strays: [[9, 'degrees']] });
      expect(box).toHaveTextContent('2 row(s) have no coordinates: 3, 7');
      expect(box).toHaveTextContent('1 row(s) are in a different form from the rest: 9');
    });

    it('asks the same question for a stem-mapping (tree) table, and sends the answer with it', async () => {
      classifyUpload.mockResolvedValue({ best: 'trees' });
      coordinateSystem.mockResolvedValue({ has_coordinates: true, labels: LABELS, dominant: 'utm', suggested_epsg: 32645, ambiguous: false, candidates: [{ epsg: 32645, zone: 45, label: 'UTM zone 45N', inside_fraction: 1, near_forest: false }] });
      const { container } = render(<AddDataDialog open calculationId="c1" hasBoundary onClose={vi.fn()} />);
      await screen.findByText('Click or drag files here');
      drop(container, [file('stems_utm.csv')]);
      const box = await screen.findByTestId('coordinate-system');
      expect(box).toHaveTextContent('UTM zone 45N');
      const addBtn = screen.getByRole('button', { name: /Add \(1\)/ });
      await waitFor(() => expect(addBtn).toBeEnabled());
      fireEvent.click(addBtn);
      expect(JSON.parse((await screen.findByTestId('bulk-items')).textContent as string)).toEqual([{ p: 'trees', c: 32645, k: null }]);
    });

    it('does not ask for a GIS tree layer: it carries its own coordinate system', async () => {
      classifyUpload.mockResolvedValue({ best: 'trees' });
      coordinateSystem.mockResolvedValue({ has_coordinates: false });
      const { container } = render(<AddDataDialog open calculationId="c1" hasBoundary onClose={vi.fn()} />);
      await screen.findByText('Click or drag files here');
      drop(container, [file('stems.geojson')]);
      await screen.findByText('stems.geojson');
      expect(screen.queryByTestId('coordinate-system')).not.toBeInTheDocument();
    });

    it('trusts a declaration that fits the numbers and says it was declared', async () => {
      const box = await dropTable({ suggested_epsg: 32645, declared_epsg: 32645, declared_ok: true, declared: { column: 'coordinate_system_epsg', epsg: 32645, values: [32645], mixed: false, unsupported: [], blank_rows: [] } });
      expect(box).toHaveTextContent('Declared in the file');
      expect(box).not.toHaveTextContent('Detected from the numbers');
      const addBtn = screen.getByRole('button', { name: /Add \(1\)/ });
      await waitFor(() => expect(addBtn).toBeEnabled());
    });

    it('does not trust a declaration the numbers contradict: it says what the numbers fit and blocks Add', async () => {
      const box = await dropTable({ suggested_epsg: 32645, declared_epsg: 4326, declared_ok: false, declared_fraction: 0, declared: { column: 'coordinate_system_epsg', epsg: 4326, values: [4326], mixed: false, unsupported: [], blank_rows: [] } });
      expect(await screen.findByTestId('declared-mismatch')).toHaveTextContent('declares Degrees (WGS 84), but the numbers fit UTM zone 45N');
      expect(box).not.toHaveTextContent('Declared in the file');
      expect(screen.getByRole('button', { name: /Add \(1\)/ })).toBeDisabled();
    });

    it('names a file that declares two systems, or one we cannot read yet, and blocks Add', async () => {
      const mixed = await dropTable({ suggested_epsg: 32645, declared: { column: 'coordinate_system_epsg', epsg: null, values: [4326, 32645], mixed: true, unsupported: [], blank_rows: [] } });
      expect(mixed).toHaveTextContent('more than one coordinate system (4326, 32645)');
      expect(screen.getByRole('button', { name: /Add \(1\)/ })).toBeDisabled();
    });

    it('names the rows that have coordinates but no declaration', async () => {
      const box = await dropTable({ suggested_epsg: 32645, declared: { column: 'coordinate_system_epsg', epsg: 32645, values: [32645], mixed: false, unsupported: [], blank_rows: [5, 9] } });
      expect(box).toHaveTextContent('2 row(s) have coordinates but no coordinate system: 5, 9');
    });

    it('shows nothing for a table without coordinates', async () => {
      classifyUpload.mockResolvedValue({ best: 'field_inventory' });
      coordinateSystem.mockResolvedValue({ has_coordinates: false });
      const { container } = render(<AddDataDialog open calculationId="c1" hasBoundary onClose={vi.fn()} />);
      await screen.findByText('Click or drag files here');
      drop(container, [file('plots.csv')]);
      await screen.findByText('plots.csv');
      await waitFor(() => expect(coordinateSystem).toHaveBeenCalled());
      expect(screen.queryByTestId('coordinate-system')).not.toBeInTheDocument();
    });
  });

  it('applies the proposed values: the refused file is imported again with them, and only that file', async () => {
    classifyUpload.mockResolvedValue({ best: 'field_inventory' });
    const { container } = render(<AddDataDialog open calculationId="c1" hasBoundary onClose={vi.fn()} />);
    await screen.findByText('Click or drag files here');
    drop(container, [file('plots.csv')]);
    const addBtn = await screen.findByRole('button', { name: /Add \(1\)/ });
    await waitFor(() => expect(addBtn).toBeEnabled());
    fireEvent.click(addBtn);
    expect(JSON.parse((await screen.findByTestId('bulk-items')).textContent as string)).toEqual([{ p: 'field_inventory', c: null, k: null }]);

    fireEvent.click(screen.getByText('finish-refused')); // the import refused the file and proposed a replacement
    fireEvent.click(await screen.findByTestId('apply-corrections'));

    const items = JSON.parse((await screen.findByTestId('bulk-items')).textContent as string);
    expect(items).toEqual([{ p: 'field_inventory', c: null, k: [{ row: 4, column: 'pole_dbh_cm', value: 22.3 }] }]);
  });
});
