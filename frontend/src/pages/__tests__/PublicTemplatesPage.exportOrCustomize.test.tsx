import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom';
import PublicTemplatesPage from '../PublicTemplatesPage';
import * as api from '../../services/api';
import { Modal } from 'antd';

vi.mock('../../features/yearly-plan/PlanCheck', () => ({
  usePlanCheck: () => ({ dialog: null, guard: (_c: string, go: () => void) => go() }),
}));

let superRole = false;
vi.mock('../../contexts/AuthContext', async (orig) => ({
  ...(await orig<typeof import('../../contexts/AuthContext')>()),
  useAuth: () => ({ user: { id: 'u1', role: superRole ? 'super_admin' : 'user' } }),
}));

vi.mock('../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../services/api')>();
  return {
    ...actual,
    operationalPlanApi: {
      ...actual.operationalPlanApi,
      listPublicTemplates: vi.fn(),
      listTemplates: vi.fn(),
      listTemplateCategories: vi.fn().mockResolvedValue([]),
      suggestKind: vi.fn().mockResolvedValue({ has_prior_plan: false }),
      planReplaceStatus: vi.fn().mockResolvedValue({ exists: false }),
      create: vi.fn().mockResolvedValue({ id: 'p1' }),
    },
  };
});

const mockOp = api.operationalPlanApi as unknown as {
  listPublicTemplates: ReturnType<typeof vi.fn>;
  listTemplates: ReturnType<typeof vi.fn>;
  create: ReturnType<typeof vi.fn>;
};

const Where = () => {
  const l = useLocation();
  return <div data-testid="where">{l.pathname + l.search}</div>;
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
  mockOp.create.mockResolvedValue({ id: 'p1' });
});

const renderPage = (entry = '/templates?calculation_id=cPre') =>
  render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/templates" element={<PublicTemplatesPage />} />
        <Route path="/calculations/:id" element={<Where />} />
      </Routes>
    </MemoryRouter>,
  );

describe('PublicTemplatesPage — Export now or Open in builder', () => {
  it('"Export now" creates the document when there is none and opens it with the export flag', async () => {
    renderPage();
    await screen.findByText('Brief FMP — New');
    fireEvent.click(screen.getAllByRole('button', { name: /export now/i })[0]);
    await waitFor(() => expect(screen.getByTestId('where').textContent).toBe('/calculations/cPre?surface=plan/mgmtplan&export=1'));
    expect(mockOp.create).toHaveBeenCalledTimes(1);
    expect(mockOp.create.mock.calls[0][7]).toBeFalsy(); // Export never replaces
  });

  it('"Open in builder" loads the template, replacing what is there, and opens the editor without exporting', async () => {
    renderPage();
    await screen.findByText('Brief FMP — New');
    fireEvent.click(screen.getAllByRole('button', { name: /open in builder/i })[0]);
    await waitFor(() => expect(screen.getByTestId('where').textContent).toBe('/calculations/cPre?surface=plan/mgmtplan'));
    expect(mockOp.create).toHaveBeenCalledTimes(1);
    expect(mockOp.create.mock.calls[0][7]).toBe(true); // replace
  });
});

describe('PublicTemplatesPage — My templates', () => {
  it('?scope=mine lists the signed-in user own templates, drafts included, and they can be used like any other', async () => {
    mockOp.listTemplates.mockResolvedValue({
      total: 1,
      templates: [{
        id: 'm1', name: 'My version', description: 'mine', status: 'draft',
        tags: [], sections_summary: [], variables_summary: [], plan_regime: 'brief_fmp', plan_stage: 'new',
      }],
    });
    renderPage('/templates?scope=mine&calculation_id=cPre');
    await screen.findByText('My version');
    expect(mockOp.listTemplates).toHaveBeenCalledWith('mine', undefined);
    expect(mockOp.listPublicTemplates).not.toHaveBeenCalled();
    fireEvent.click(screen.getAllByRole('button', { name: /open in builder/i })[0]);
    await waitFor(() => expect(mockOp.create).toHaveBeenCalledTimes(1));
    expect(mockOp.create.mock.calls[0][2]).toBe('m1');
  });
});

describe('PublicTemplatesPage — delete or withdraw my template', () => {
  afterEach(() => Modal.destroyAll()); // a confirm dialog lives outside the rendered tree and would leak into the next test
  const mine = {
    total: 1,
    templates: [{
      id: 'm1', name: 'My version', description: 'mine', status: 'draft', created_by: 'u1',
      tags: [], sections_summary: [], variables_summary: [], plan_regime: 'brief_fmp', plan_stage: 'new',
    }],
  };

  it('asks first, says what a withdrawal means, and tells the user which one happened', async () => {
    mockOp.listTemplates.mockResolvedValue(mine);
    (api.operationalPlanApi as any).deleteTemplate = vi.fn().mockResolvedValue({ status: 'withdrawn', copies: 2 });
    renderPage('/templates?scope=mine&calculation_id=cPre');
    await screen.findByText('My version');
    fireEvent.click(screen.getAllByTestId(/^more-/)[0]);
    fireEvent.click(await screen.findByText('Delete'));
    expect(await screen.findByText(/withdrawn instead/i)).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole('button', { name: /^Delete$/ }).pop() as HTMLElement);
    await waitFor(() => expect((api.operationalPlanApi as any).deleteTemplate).toHaveBeenCalledWith('m1'));
    expect(await screen.findByText(/withdrawn\. Your name stays/i)).toBeInTheDocument();
  });

  it('offers no delete on someone else\'s published template', async () => {
    mockOp.listPublicTemplates.mockResolvedValue({
      templates: [{ id: 'p1', name: 'Theirs', description: '', status: 'published', created_by: 'someone-else',
        tags: [], sections_summary: [], variables_summary: [], plan_regime: 'brief_fmp', plan_stage: 'new' }],
      kinds: [],
    });
    renderPage('/templates?calculation_id=cPre');
    await screen.findByText('Theirs');
    fireEvent.click(screen.getAllByTestId(/^more-/)[0]);
    const menu = await waitFor(() => {
      const el = document.querySelector('.ant-dropdown:not(.ant-dropdown-hidden)') as HTMLElement | null;
      if (!el) throw new Error('menu not open');
      return el;
    });
    expect(within(menu).getByText(/details/i)).toBeInTheDocument();
    expect(within(menu).queryByText('Delete')).toBeNull();
  });
});

describe('PublicTemplatesPage — the super admin can delete for good', () => {
  afterEach(() => Modal.destroyAll());

  it('offers "Delete permanently" in the detail dialog, explains it, and asks the server for permanent deletion', async () => {
    superRole = true;
    (api.operationalPlanApi as any).deleteTemplate = vi.fn().mockResolvedValue({ status: 'deleted_permanently', copies: 1 });
    mockOp.listPublicTemplates.mockResolvedValue({
      templates: [{ id: 'p1', name: 'Shared one', description: 'd', status: 'published', created_by: 'someone-else',
        tags: [], sections_summary: [], variables_summary: [], plan_regime: 'brief_fmp', plan_stage: 'new' }],
      kinds: [],
    });
    renderPage('/templates?calculation_id=cPre');
    await screen.findByText('Shared one');
    fireEvent.click(screen.getAllByTestId(/^more-/)[0]);
    fireEvent.click(await screen.findByText(/details/i));
    fireEvent.click(await screen.findByTestId('delete-permanently'));
    expect(await screen.findByText(/removes the template for good/i)).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole('button', { name: /^Delete permanently$/ }).pop() as HTMLElement);
    await waitFor(() => expect((api.operationalPlanApi as any).deleteTemplate).toHaveBeenCalledWith('p1', { permanent: true }));
    superRole = false;
  });

  it('shows nothing of the kind to an ordinary user', async () => {
    superRole = false;
    mockOp.listPublicTemplates.mockResolvedValue({
      templates: [{ id: 'p1', name: 'Shared one', description: 'd', status: 'published', created_by: 'someone-else',
        tags: [], sections_summary: [], variables_summary: [], plan_regime: 'brief_fmp', plan_stage: 'new' }],
      kinds: [],
    });
    renderPage('/templates?calculation_id=cPre');
    await screen.findByText('Shared one');
    fireEvent.click(screen.getAllByTestId(/^more-/)[0]);
    fireEvent.click(await screen.findByText(/details/i));
    await screen.findAllByRole('dialog');
    expect(screen.queryAllByTestId('delete-permanently')).toHaveLength(0);
  });
});
