import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import TemplatesLandingPage from '../TemplatesLandingPage';
import { AuthContext } from '../../contexts/AuthContext';
import * as api from '../../services/api';

vi.mock('../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../services/api')>();
  const stub = () => vi.fn().mockResolvedValue({ templates: [], kinds: [] });
  return {
    ...actual,
    operationalPlanApi: {
      ...actual.operationalPlanApi,
      listPublicTemplates: stub(),
      listTemplateCategories: vi.fn().mockResolvedValue([]),
      listTemplates: vi.fn().mockResolvedValue({ templates: [] }),
      getSystemTemplate: vi.fn().mockResolvedValue({
        template: { id: 's', name: 'System Template' },
        versions: [],
        seed_sync: { in_sync: true, missing_sections: [], unregistered_tokens: [] },
      }),
      suggestKind: vi.fn().mockResolvedValue({ has_prior_plan: false }),
    },
    forestApi: { ...actual.forestApi, listCalculations: vi.fn().mockResolvedValue([]) },
  };
});

const withRole = (role: string | undefined, entry = '/templates') =>
  render(
    <AuthContext.Provider value={{ user: role ? { role } : null } as never}>
      <MemoryRouter initialEntries={[entry]}>
        <TemplatesLandingPage />
      </MemoryRouter>
    </AuthContext.Provider>,
  );

beforeEach(() => vi.clearAllMocks());

describe('TemplatesLandingPage', () => {
  it('a plain user sees only Browse & Use', async () => {
    withRole('user');
    expect(await screen.findByRole('tab', { name: /browse & use/i })).toBeTruthy();
    expect(screen.queryByRole('tab', { name: /manage/i })).toBeNull();
  });

  it('a designer sees the Manage tab', async () => {
    withRole('template_designer');
    expect(await screen.findByRole('tab', { name: /manage/i })).toBeTruthy();
  });

  it('super admin landing on ?tab=manage&sub=admin renders admin tools', async () => {
    withRole('super_admin', '/templates?tab=manage&sub=admin');
    // the AdminTemplatesPage opens on its system-template tab (there is no approval queue)
    expect(await screen.findByText(/system template/i)).toBeTruthy();
  });
});
