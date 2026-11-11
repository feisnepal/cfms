/**
 * P2 of the yearly-activities plan: the activity-features table edits a place's name, years and symbol
 * (YEARLY_ACTIVITIES_WORKSPACE_PLAN §4.6, Table A). Row delete already exists for every layer.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within, fireEvent } from '@testing-library/react';
import { AttributeTable } from '../AttributeTable';
import { useWorkspaceStore } from '../../store/workspaceStore';

vi.mock('../../i18n/hooks', () => ({ useT: () => (k: string, o?: Record<string, unknown>) => (o?.n !== undefined ? `${k}:${o.n}` : k) }));
vi.mock('../SymbolPicker', () => ({ default: () => null }));

const FEATS: GeoJSON.Feature[] = [
  {
    type: 'Feature',
    geometry: { type: 'Point', coordinates: [85, 27] },
    properties: { id: 'f1', name: 'Nursery A', years: [1, 2, 3, 7], kind: 'nursery', activity_name: 'Build a nursery', display_label: 'Nursery A · Years 1–3, 7' },
  },
  {
    type: 'Feature',
    geometry: { type: 'LineString', coordinates: [[85, 27], [85.1, 27.1]] },
    properties: { id: 'f2', name: 'Fire line', years: [2], kind: '', activity_name: 'Fire line construction', display_label: 'Fire line · Year 2' },
  },
];

function seedStore() {
  useWorkspaceStore.setState({
    activeLayerId: 'activity_features',
    activeImportedLayerId: null,
    calculationId: 'c1',
    customLayerStyles: {},
    columnVisibility: {},
    columnOrder: {},
    columnWidths: {},
    columnLabels: {},
    importedLayers: [],
    selection: { layerId: null, featureIds: [] },
    editHistory: [],
    editFuture: [],
  } as never);
}

const rowsOf = () => screen.getAllByRole('row').filter((r) => r.className.includes('table-row'));

describe('activity-features table — editing', () => {
  beforeEach(seedStore);

  it('shows the Name column by default and saves a renamed place through onSaveProperty', () => {
    const onSave = vi.fn();
    render(<AttributeTable isLoading={false} error={null} onRetry={() => {}} features={FEATS} onSaveProperty={onSave} />);
    const cell = within(rowsOf()[0]).getByText('Nursery A');
    fireEvent.doubleClick(cell.closest('[role="gridcell"]') as HTMLElement);
    const input = within(rowsOf()[0]).getByDisplayValue('Nursery A');
    fireEvent.change(input, { target: { value: 'Nursery B' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ properties: expect.objectContaining({ id: 'f1' }) }), 'name', 'Nursery B');
  });

  it('the Symbol column is a drop-down of the map symbols with the current one chosen', () => {
    const onSave = vi.fn();
    render(<AttributeTable isLoading={false} error={null} onRetry={() => {}} features={FEATS} onSaveProperty={onSave} />);
    const select = within(rowsOf()[0]).getByRole('combobox') as HTMLSelectElement;
    expect(select.value).toBe('nursery');
    expect(within(select).getByRole('option', { name: /Fire line/ })).toBeInTheDocument();
    fireEvent.change(select, { target: { value: 'road' } });
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ properties: expect.objectContaining({ id: 'f1' }) }), 'kind', 'road');
    // a place with no symbol shows the "-" choice
    expect((within(rowsOf()[1]).getByRole('combobox') as HTMLSelectElement).value).toBe('');
  });

  it('the Years cell shows the years and opens a chooser; Apply saves the new set', () => {
    const onSave = vi.fn();
    render(<AttributeTable isLoading={false} error={null} onRetry={() => {}} features={FEATS} onSaveProperty={onSave} />);
    const yearsCell = within(rowsOf()[0]).getByTestId('years-cell');
    expect(yearsCell.textContent).toContain('1–3, 7');
    fireEvent.click(yearsCell);
    const chooser = screen.getByTestId('years-chooser');
    expect(within(chooser).getByTestId('year-chip-1')).toHaveAttribute('aria-pressed', 'true');
    expect(within(chooser).getByTestId('year-chip-4')).toHaveAttribute('aria-pressed', 'false');
    fireEvent.click(within(chooser).getByTestId('year-chip-4'));
    fireEvent.click(within(chooser).getByTestId('year-chip-7'));
    fireEvent.click(within(chooser).getByTestId('years-apply'));
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ properties: expect.objectContaining({ id: 'f1' }) }), 'years', '1,2,3,4');
  });

  it('the chooser will not apply with no year chosen, and Cancel changes nothing', () => {
    const onSave = vi.fn();
    render(<AttributeTable isLoading={false} error={null} onRetry={() => {}} features={FEATS} onSaveProperty={onSave} />);
    fireEvent.click(within(rowsOf()[1]).getByTestId('years-cell'));
    const chooser = screen.getByTestId('years-chooser');
    fireEvent.click(within(chooser).getByTestId('year-chip-2')); // untick the only year
    expect(within(chooser).getByTestId('years-apply')).toBeDisabled();
    expect(within(chooser).getByRole('alert').textContent).toContain('yearlyPlan.table.yearsPick');
    fireEvent.click(within(chooser).getByTestId('years-cancel'));
    expect(onSave).not.toHaveBeenCalled();
  });

  it('applying the years a place already has does not save anything', () => {
    const onSave = vi.fn();
    render(<AttributeTable isLoading={false} error={null} onRetry={() => {}} features={FEATS} onSaveProperty={onSave} />);
    fireEvent.click(within(rowsOf()[1]).getByTestId('years-cell'));
    fireEvent.click(within(screen.getByTestId('years-chooser')).getByTestId('years-apply'));
    expect(onSave).not.toHaveBeenCalled();
  });

  it('without a save handler the years cannot be edited', () => {
    render(<AttributeTable isLoading={false} error={null} onRetry={() => {}} features={FEATS} />);
    expect(within(rowsOf()[0]).getByTestId('years-cell')).toBeDisabled();
  });

  it('deleting a place still goes through the row menu', () => {
    const onDelete = vi.fn();
    render(<AttributeTable isLoading={false} error={null} onRetry={() => {}} features={FEATS} onDeleteFeature={onDelete} onZoomToFeature={() => {}} />);
    fireEvent.click(within(rowsOf()[0]).getByRole('button', { name: 'attributeTable.rowActions' }));
    fireEvent.click(screen.getByRole('menuitem', { name: /deleteFeature/ }));
    expect(onDelete).toHaveBeenCalledWith(expect.objectContaining({ properties: expect.objectContaining({ id: 'f1' }) }), 0);
  });
});
