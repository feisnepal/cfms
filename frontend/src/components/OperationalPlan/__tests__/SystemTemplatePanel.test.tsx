import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import SystemTemplatePanel from '../SystemTemplatePanel';
import * as api from '../../../services/api';

vi.mock('../../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../../services/api')>();
  return {
    ...actual,
    operationalPlanApi: {
      ...actual.operationalPlanApi,
      getSystemTemplate: vi.fn(),
      getByCalculation: vi.fn(),
      adoptSystemTemplateFromPlan: vi.fn(),
    },
    forestApi: { ...actual.forestApi, listCalculations: vi.fn() },
  };
});

const mockOp = api.operationalPlanApi as unknown as {
  getSystemTemplate: ReturnType<typeof vi.fn>;
  getByCalculation: ReturnType<typeof vi.fn>;
  adoptSystemTemplateFromPlan: ReturnType<typeof vi.fn>;
};
const mockForest = api.forestApi as unknown as { listCalculations: ReturnType<typeof vi.fn> };

beforeEach(() => {
  mockOp.getSystemTemplate.mockReset().mockResolvedValue({
    template: { id: 'sys1', name: 'System Template', published_version: 55 },
    versions: [{ version: 54, changelog: 'x', created_at: new Date().toISOString() }],
    seed_sync: { in_sync: true, missing_sections: [], unregistered_tokens: [] },
  });
  mockOp.getByCalculation.mockReset().mockResolvedValue({ id: 'plan1' });
  mockOp.adoptSystemTemplateFromPlan.mockReset().mockResolvedValue({
    diff: { added: ['नयाँ खण्ड'], removed: [], token_restored: ['क'], needs_review: ['नयाँ खण्ड'], kept: 20 },
    applied: false,
  });
  mockForest.listCalculations.mockReset().mockResolvedValue([
    { id: 'c1', forest_name: 'बृन्दाबन', status: 'completed' },
  ]);
});

const renderPanel = () =>
  render(<MemoryRouter><SystemTemplatePanel /></MemoryRouter>);

describe('SystemTemplatePanel', () => {
  it('shows the in-sync state and version history', async () => {
    renderPanel();
    await screen.findByText('System Template');
    expect(screen.getByText(/in sync/i)).toBeTruthy();
    expect(screen.getByText('v54')).toBeTruthy();
  });

  it('runs the adopt-from-plan dry run and shows the diff', async () => {
    renderPanel();
    await screen.findByText('System Template');

    fireEvent.mouseDown(screen.getByRole('combobox'));
    fireEvent.click(await screen.findByText('बृन्दाबन'));
    await waitFor(() => expect(mockOp.getByCalculation).toHaveBeenCalledWith('c1'));

    fireEvent.click(screen.getByRole('button', { name: /preview changes/i }));
    await waitFor(() =>
      expect(mockOp.adoptSystemTemplateFromPlan).toHaveBeenCalledWith('plan1', false),
    );
    // the "needs review" row renders the section title on its own
    expect(await screen.findByText('नयाँ खण्ड')).toBeTruthy();
    expect(screen.getByRole('button', { name: /apply/i })).toBeTruthy();
  });
});
