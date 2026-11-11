import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import BulkImportRunner from '../BulkImportRunner';
import type { ResolvedUpload } from '../AddDataDialog';

const refreshAll = vi.fn();
vi.mock('../../store/workspaceStore', () => ({
  useWorkspaceStore: () => ({
    refreshAll,
    bumpGeometryVersion: vi.fn(),
  }),
}));

interface StubProps {
  file: File;
  fixedPurpose?: string;
  restrictToGeometry?: boolean;
  onComplete: () => void;
  onCancel: () => void;
  onFindings?: (findings: unknown[]) => void;
}
const dialogProps: StubProps[] = [];
vi.mock('../ImportPurposeDialog', () => ({
  default: (props: StubProps) => {
    dialogProps.push(props);
    return (
      <div data-testid="import-dialog">
        <span data-testid="dlg-file">{props.file.name}</span>
        <span data-testid="dlg-purpose">{props.fixedPurpose}</span>
        <span data-testid="dlg-restrict">{String(props.restrictToGeometry)}</span>
        <button onClick={props.onComplete}>complete</button>
        <button onClick={props.onCancel}>cancel</button>
        <button onClick={() => props.onFindings?.([{ code: 'no_rows', severity: 'warning' }])}>
          finding
        </button>
      </div>
    );
  },
}));

function f(name: string): File {
  return new File(['x'], name);
}
function item(name: string, purposeId: string): ResolvedUpload {
  return { file: f(name), purposeId };
}

describe('BulkImportRunner', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    dialogProps.length = 0;
  });

  it('maps canonical purposes to legacy ids and walks the queue', async () => {
    const onDone = vi.fn();
    render(
      <BulkImportRunner
        items={[item('blocks.geojson', 'blocks'), item('trees.csv', 'trees')]}
        calculationId="c1"
        hasBoundary
        onDone={onDone}
      />,
    );

    expect(screen.getByTestId('dlg-file')).toHaveTextContent('blocks.geojson');
    expect(screen.getByTestId('dlg-purpose')).toHaveTextContent('blocks');

    fireEvent.click(screen.getByText('complete'));

    await waitFor(() =>
      expect(screen.getByTestId('dlg-file')).toHaveTextContent('trees.csv'),
    );
    // canonical "trees" → legacy "inventory"
    expect(screen.getByTestId('dlg-purpose')).toHaveTextContent('inventory');

    fireEvent.click(screen.getByText('complete'));

    await waitFor(() => {
      expect(onDone).toHaveBeenCalled();
      expect(refreshAll).toHaveBeenCalled();
    });
    expect(screen.queryByTestId('import-dialog')).not.toBeInTheDocument();
  });

  it('gathers each file’s findings and hands them to onDone', async () => {
    const onDone = vi.fn();
    render(
      <BulkImportRunner
        items={[item('blocks.geojson', 'blocks')]}
        calculationId="c1"
        hasBoundary
        onDone={onDone}
      />,
    );
    fireEvent.click(screen.getByText('finding'));
    fireEvent.click(screen.getByText('complete'));

    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(onDone.mock.calls[0][0]).toEqual([{ code: 'no_rows', severity: 'warning' }]);
  });

  it('announces what was imported when the queue finishes, so open tabs reload', async () => {
    const { onDataImported } = await import('../../lib/uploadEvents');
    const seen = vi.fn();
    const off = onDataImported(seen);
    render(
      <BulkImportRunner items={[item('fi.csv', 'field_inventory')]} calculationId="c1" hasBoundary onDone={vi.fn()} />,
    );
    fireEvent.click(screen.getByText('complete'));
    await waitFor(() => expect(seen).toHaveBeenCalledWith({ purposes: ['field_inventory'] }));
    off();
  });

  it('skips purposes with no workspace path and finishes', async () => {
    const onDone = vi.fn();
    render(
      <BulkImportRunner
        items={[item('mystery.csv', 'no_such_purpose')]}
        calculationId="c1"
        hasBoundary
        onDone={onDone}
      />,
    );
    // nothing supported → no dialog, done immediately
    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(screen.queryByTestId('import-dialog')).not.toBeInTheDocument();
  });

  it('routes trees to the inventory pipeline and households to its own purpose', async () => {
    render(
      <BulkImportRunner
        items={[item('tree_mapping.csv', 'trees'), item('households.xlsx', 'households')]}
        calculationId="c1"
        hasBoundary
        onDone={vi.fn()}
      />,
    );
    // canonical "trees" → legacy "inventory" dialog purpose
    expect(screen.getByTestId('dlg-file')).toHaveTextContent('tree_mapping.csv');
    expect(screen.getByTestId('dlg-purpose')).toHaveTextContent('inventory');

    fireEvent.click(screen.getByText('complete'));

    await waitFor(() =>
      expect(screen.getByTestId('dlg-file')).toHaveTextContent('households.xlsx'),
    );
    expect(screen.getByTestId('dlg-purpose')).toHaveTextContent('households');
  });

  it('processes the boundary file first and restricts only that one', async () => {
    render(
      <BulkImportRunner
        items={[
          item('blocks.geojson', 'blocks'),
          item('boundary.kml', 'forest_boundary'),
        ]}
        calculationId="c1"
        hasBoundary={false}
        onDone={vi.fn()}
      />,
    );

    // boundary sorted to the front, restricted
    expect(screen.getByTestId('dlg-file')).toHaveTextContent('boundary.kml');
    expect(screen.getByTestId('dlg-purpose')).toHaveTextContent('boundary');
    expect(screen.getByTestId('dlg-restrict')).toHaveTextContent('true');

    fireEvent.click(screen.getByText('complete'));

    await waitFor(() =>
      expect(screen.getByTestId('dlg-file')).toHaveTextContent('blocks.geojson'),
    );
    expect(screen.getByTestId('dlg-restrict')).toHaveTextContent('false');
  });

  it('cancel on a file skips just that one', async () => {
    const onDone = vi.fn();
    render(
      <BulkImportRunner
        items={[item('blocks.geojson', 'blocks'), item('roads.geojson', 'roads')]}
        calculationId="c1"
        hasBoundary
        onDone={onDone}
      />,
    );
    fireEvent.click(screen.getByText('cancel'));
    await waitFor(() =>
      expect(screen.getByTestId('dlg-file')).toHaveTextContent('roads.geojson'),
    );
    expect(onDone).not.toHaveBeenCalled();
  });
});
