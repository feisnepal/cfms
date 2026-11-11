import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import PublicTemplatesPage from '../PublicTemplatesPage';
import * as api from '../../services/api';

vi.mock('../../contexts/AuthContext', async (orig) => ({
  ...(await orig<typeof import('../../contexts/AuthContext')>()),
  useAuth: () => ({ user: { id: 'u1', role: 'user' } }),
}));

vi.mock('../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../services/api')>();
  return {
    ...actual,
    operationalPlanApi: {
      ...actual.operationalPlanApi,
      listPublicTemplates: vi.fn(),
      listTemplateCategories: vi.fn().mockResolvedValue([]),
      suggestKind: vi.fn().mockResolvedValue({ has_prior_plan: false }),
      previewTemplateWithForest: vi.fn().mockResolvedValue('<html><body>preview</body></html>'),
    },
    forestApi: {
      ...actual.forestApi,
      listCalculations: vi.fn().mockResolvedValue([
        { id: 'c1', forest_name: 'बृन्दाबन', status: 'completed' },
      ]),
    },
  };
});

const mockOp = api.operationalPlanApi as unknown as {
  listPublicTemplates: ReturnType<typeof vi.fn>;
  previewTemplateWithForest: ReturnType<typeof vi.fn>;
};

beforeEach(() => {
  vi.clearAllMocks();
  mockOp.listPublicTemplates.mockResolvedValue({
    templates: [{
      id: 't1', name: 'Brief FMP — New', description: 'A brief plan template.',
      tags: [], sections_summary: [], variables_summary: [],
      plan_regime: 'brief_fmp', plan_stage: 'new', published_version: 2,
    }],
    kinds: [],
  });
});

const renderPage = (entry = '/templates') =>
  render(<MemoryRouter initialEntries={[entry]}><PublicTemplatesPage /></MemoryRouter>);

describe('PublicTemplatesPage — Preview with my forest', () => {
  it('renders a template against a picked forest without creating a plan', async () => {
    renderPage();
    await screen.findByText('Brief FMP — New');

    fireEvent.click(screen.getAllByTestId(/^more-/)[0]);
    fireEvent.click(await screen.findByText(/preview with my forest/i));

    // the drawer's forest picker is the last combobox on the page
    const boxes = await screen.findAllByRole('combobox');
    fireEvent.mouseDown(boxes[boxes.length - 1]);
    fireEvent.click(await screen.findByText('बृन्दाबन'));

    await waitFor(() =>
      expect(mockOp.previewTemplateWithForest).toHaveBeenCalledWith('t1', 'c1', 'values'),
    );
  });

  it('uses the preselected calculation_id straight away', async () => {
    renderPage('/templates?calculation_id=cPre');
    await screen.findByText('Brief FMP — New');
    fireEvent.click(screen.getAllByTestId(/^more-/)[0]);
    fireEvent.click(await screen.findByText(/preview with my forest/i));
    await waitFor(() =>
      expect(mockOp.previewTemplateWithForest).toHaveBeenCalledWith('t1', 'cPre', 'values'),
    );
  });
});
