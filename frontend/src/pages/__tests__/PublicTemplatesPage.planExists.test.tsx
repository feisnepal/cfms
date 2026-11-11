import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom';
import PublicTemplatesPage from '../PublicTemplatesPage';
import * as api from '../../services/api';

vi.mock('../../features/yearly-plan/PlanCheck', () => ({
  usePlanCheck: () => ({ dialog: null, guard: (_c: string, go: () => void) => go() }),
}));
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
      getExportRequirementsForCalculation: vi.fn().mockResolvedValue({ ready: true, items: [] }),
      planReplaceStatus: vi.fn(),
      create: vi.fn(),
    },
  };
});

const op = api.operationalPlanApi as unknown as Record<string, ReturnType<typeof vi.fn>>;
const Where = () => {
  const l = useLocation();
  return <div data-testid="where">{l.pathname + l.search}</div>;
};
const blocked = {
  response: { data: { detail: { code: 'PLAN_EXISTS', plan_id: 'p9', template_name: 'Old template', can_replace: false, blocked_reason: 'The plan was submitted to an office, so it cannot be replaced.' } } },
};

beforeEach(() => {
  vi.clearAllMocks();
  op.planReplaceStatus.mockResolvedValue({ exists: false });
  op.create.mockResolvedValue({ id: 'p10' });
  op.listPublicTemplates.mockResolvedValue({
    templates: [{ id: 't1', name: 'Rambhadevi SFM Renew', description: 'd', tags: [], sections_summary: [], variables_summary: [], plan_regime: 'brief_fmp', plan_stage: 'new', published_version: 1 }],
    kinds: [],
  });
});

const renderPage = () =>
  render(
    <MemoryRouter initialEntries={['/templates?calculation_id=c1']}>
      <Routes>
        <Route path="/templates" element={<PublicTemplatesPage />} />
        <Route path="/calculations/:id" element={<Where />} />
      </Routes>
    </MemoryRouter>,
  );

// The forest already has a document: the two card actions stay answers, never questions (owner, 2026-10-18).
describe('PublicTemplatesPage — Export always ends in the document', () => {
  it('an existing document is exported as it is: nothing is created and no dialog appears', async () => {
    op.planReplaceStatus.mockResolvedValue({ exists: true, plan_id: 'p9', template_name: 'Old template' });
    renderPage();
    await screen.findByText('Rambhadevi SFM Renew');
    fireEvent.click(screen.getAllByRole('button', { name: /export now/i })[0]);
    await waitFor(() => expect(screen.getByTestId('where').textContent).toBe('/calculations/c1?surface=plan/mgmtplan&export=1'));
    expect(op.create).not.toHaveBeenCalled();
    expect(screen.queryByTestId('plan-exists')).toBeNull();
  });

  it('a document that turns up between the check and the create is still exported, not replaced', async () => {
    op.planReplaceStatus.mockResolvedValue({ exists: false });
    op.create.mockRejectedValueOnce(blocked);
    renderPage();
    await screen.findByText('Rambhadevi SFM Renew');
    fireEvent.click(screen.getAllByRole('button', { name: /export now/i })[0]);
    await waitFor(() => expect(screen.getByTestId('where').textContent).toBe('/calculations/c1?surface=plan/mgmtplan&export=1'));
    expect(op.create).toHaveBeenCalledTimes(1);
    expect(op.create.mock.calls[0][7]).toBeFalsy(); // never replaces
  });
});

describe('PublicTemplatesPage — Open in builder always ends in the builder', () => {
  it('loads the chosen template with replace=true, straight to the editor, with no dialog', async () => {
    op.planReplaceStatus.mockResolvedValue({ exists: true, plan_id: 'p9', template_name: 'Old template', can_replace: true, blocked_reason: null });
    renderPage();
    await screen.findByText('Rambhadevi SFM Renew');
    fireEvent.click(screen.getAllByRole('button', { name: /open in builder/i })[0]);
    await waitFor(() => expect(op.create).toHaveBeenCalledTimes(1));
    expect(op.create.mock.calls[0][7]).toBe(true); // replace
    await waitFor(() => expect(screen.getByTestId('where').textContent).toBe('/calculations/c1?surface=plan/mgmtplan'));
    expect(screen.queryByTestId('plan-exists')).toBeNull();
  });

  it('a document that cannot be replaced shows the reason and opens the document as it is', async () => {
    op.create.mockRejectedValueOnce(blocked);
    renderPage();
    await screen.findByText('Rambhadevi SFM Renew');
    fireEvent.click(screen.getAllByRole('button', { name: /open in builder/i })[0]);
    expect(await screen.findByText(/submitted to an office/i)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId('where').textContent).toBe('/calculations/c1?surface=plan/mgmtplan'));
    expect(op.create).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId('plan-exists')).toBeNull();
  });
});

describe('PublicTemplatesPage — the forest dialog says what the chosen action does', () => {
  it('explains Open in builder, including that it replaces the current document', async () => {
    (api as any).forestApi.listCalculations = vi.fn().mockResolvedValue([{ id: 'c9', forest_name: 'F', status: 'completed', created_at: '2026-10-10' }]);
    render(
      <MemoryRouter initialEntries={['/templates']}>
        <Routes><Route path="/templates" element={<PublicTemplatesPage />} /></Routes>
      </MemoryRouter>,
    );
    await screen.findByText('Rambhadevi SFM Renew');
    fireEvent.click(screen.getAllByRole('button', { name: /open in builder/i })[0]);
    const note = await screen.findByTestId('intent-note');
    expect(note.textContent).toMatch(/Open in builder.*replacing/s);
  });
});
