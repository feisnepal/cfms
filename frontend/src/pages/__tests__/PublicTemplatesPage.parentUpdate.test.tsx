import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
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
      listTemplates: vi.fn(),
      listTemplateCategories: vi.fn().mockResolvedValue([]),
      templateParentStatus: vi.fn(),
      addParentUpdates: vi.fn(),
    },
  };
});

const op = api.operationalPlanApi as unknown as Record<string, ReturnType<typeof vi.fn>>;
const mine = (id: string, name: string) => ({
  id, name, description: 'd', tags: [], sections_summary: [], variables_summary: [], status: 'draft',
  plan_regime: 'brief_fmp', plan_stage: 'new', created_by: 'u1', source_template_id: 'orig',
});

beforeEach(() => {
  vi.clearAllMocks();
  op.listTemplateCategories.mockResolvedValue([]);
  op.listTemplates.mockResolvedValue({ templates: [mine('c1', 'My copy'), mine('c2', 'Up to date copy')], kinds: [] });
  op.templateParentStatus.mockImplementation(async (id: string) =>
    id === 'c1' ? { has_parent: true, update_available: true, added: ['Fire lines'] } : { has_parent: true, update_available: false, added: [] });
  op.addParentUpdates.mockResolvedValue({ added: ['Fire lines'], version: 2 });
});

describe('PublicTemplatesPage — original updated', () => {
  it('tags only the copy whose original has new sections, and adds them after a confirmation', async () => {
    render(
      <MemoryRouter initialEntries={['/templates?scope=mine']}>
        <Routes><Route path="/templates" element={<PublicTemplatesPage />} /></Routes>
      </MemoryRouter>,
    );
    await screen.findByText('My copy');
    await screen.findByText(/original updated/i);
    expect(screen.getAllByText(/original updated/i)).toHaveLength(1);

    fireEvent.click(screen.getByTestId('more-c1'));
    fireEvent.click(await screen.findByTestId('parent-c1'));
    await screen.findByText('Fire lines');
    fireEvent.click(screen.getByRole('button', { name: /add them/i }));
    await waitFor(() => expect(op.addParentUpdates).toHaveBeenCalledWith('c1'));
  });
});
