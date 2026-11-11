import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AttributeTable } from '../AttributeTable';
import { useWorkspaceStore, createInitialState } from '../../store/workspaceStore';

vi.mock('../../i18n/hooks', () => ({ useT: () => (k: string) => k }));
vi.mock('../SymbolPicker', () => ({ default: () => null }));

const FEATS = [
  { type: 'Feature' as const, geometry: { type: 'Polygon' as const, coordinates: [] }, properties: { id: 'b1', name: 'Block A' } },
  { type: 'Feature' as const, geometry: { type: 'Polygon' as const, coordinates: [] }, properties: { id: 'b2', name: 'Block B' } },
];

describe('AttributeTable — row = zoom (WORKSPACE_LAYER_STYLING_PLAN.md P0.6)', () => {
  beforeEach(() => {
    useWorkspaceStore.setState({ ...createInitialState(), activeLayerId: 'blocks', calculationId: 'c1' } as never);
  });

  it('pressing Enter on a row zooms to that feature', async () => {
    const onZoom = vi.fn();
    render(
      <AttributeTable isLoading={false} error={null} onRetry={() => {}} features={FEATS} onZoomToFeature={onZoom} />,
    );
    const rows = screen.getAllByRole('row').filter((r) => r.className.includes('table-row'));
    rows[0].focus();
    await userEvent.keyboard('{Enter}');
    expect(onZoom).toHaveBeenCalledWith(expect.objectContaining({ properties: expect.objectContaining({ id: 'b1' }) }));
  });

  it('double-clicking a non-editable part of the row zooms', async () => {
    const onZoom = vi.fn();
    render(
      <AttributeTable isLoading={false} error={null} onRetry={() => {}} features={FEATS} onZoomToFeature={onZoom} />,
    );
    const rows = screen.getAllByRole('row').filter((r) => r.className.includes('table-row'));
    await userEvent.dblClick(rows[0]);
    expect(onZoom).toHaveBeenCalledWith(expect.objectContaining({ properties: expect.objectContaining({ id: 'b1' }) }));
  });

  it('double-clicking an editable cell does NOT zoom (it starts an edit instead)', async () => {
    const onZoom = vi.fn();
    render(
      <AttributeTable isLoading={false} error={null} onRetry={() => {}} features={FEATS} onZoomToFeature={onZoom} />,
    );
    // the Name cell is editable
    await userEvent.dblClick(screen.getByText('Block A'));
    expect(onZoom).not.toHaveBeenCalled();
  });

  it('Space selects but does not zoom', async () => {
    const onZoom = vi.fn();
    render(
      <AttributeTable isLoading={false} error={null} onRetry={() => {}} features={FEATS} onZoomToFeature={onZoom} />,
    );
    const rows = screen.getAllByRole('row').filter((r) => r.className.includes('table-row'));
    rows[1].focus();
    await userEvent.keyboard(' ');
    expect(onZoom).not.toHaveBeenCalled();
  });
});
