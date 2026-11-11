import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import MyTemplatesPage from '../MyTemplatesPage';
import * as api from '../../services/api';

vi.mock('../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../services/api')>();
  return {
    ...actual,
    operationalPlanApi: {
      ...actual.operationalPlanApi,
      listTemplates: vi.fn(),
      previewTemplateWithForest: vi.fn(),
    },
    forestApi: { ...actual.forestApi, listCalculations: vi.fn() },
  };
});

const mockOp = api.operationalPlanApi as unknown as {
  listTemplates: ReturnType<typeof vi.fn>;
  previewTemplateWithForest: ReturnType<typeof vi.fn>;
};
const mockForest = api.forestApi as unknown as {
  listCalculations: ReturnType<typeof vi.fn>;
};

beforeEach(() => {
  mockOp.listTemplates.mockReset().mockResolvedValue({
    templates: [
      { id: 't1', name: 'Brief FMP — New', description: 'x', status: 'draft', updated_at: new Date().toISOString() },
    ],
  });
  mockOp.previewTemplateWithForest.mockReset().mockResolvedValue('<html><body>rendered</body></html>');
  mockForest.listCalculations.mockReset().mockResolvedValue([
    { id: 'c1', forest_name: 'बृन्दाबन', status: 'completed' },
  ]);
});

const renderPage = () =>
  render(<MemoryRouter><MyTemplatesPage /></MemoryRouter>);

describe('MyTemplatesPage — Test with a forest', () => {
  it('renders a template against a picked forest without creating a plan', async () => {
    renderPage();
    await screen.findByText('Brief FMP — New');

    // the flask/experiment action button
    const testBtn = document.querySelector('.anticon-experiment')?.closest('button');
    expect(testBtn).toBeTruthy();
    fireEvent.click(testBtn as HTMLElement);

    // forest picker appears; choose the forest
    const combobox = await screen.findByRole('combobox');
    fireEvent.mouseDown(combobox);
    fireEvent.click(await screen.findByText('बृन्दाबन'));

    await waitFor(() =>
      expect(mockOp.previewTemplateWithForest).toHaveBeenCalledWith('t1', 'c1', 'values'),
    );
  });
});
