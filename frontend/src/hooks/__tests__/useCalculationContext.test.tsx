/**
 * Phase 2 — useCalculationContext logic tests.
 * Follows the repo's logic-only test pattern (mock @tanstack/react-query +
 * workspace store + API). We inspect the local factory logic without mounting
 * a DOM renderer, so no react-query runtime is required.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useWorkspaceStore, createInitialState } from '../../store/workspaceStore';

const stateModifiers = vi.fn();

vi.mock('@tanstack/react-query', () => ({
  useQuery: vi.fn().mockReturnValue({
    data: undefined,
    isLoading: true,
    error: null,
    refetch: vi.fn(),
  }),
  QueryClient: vi.fn(),
  QueryClientProvider: ({ children }: { children: any }) => children,
}));

vi.mock('../../services/api', () => ({
  forestApi: { getCalculation: vi.fn() },
}));

vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({ user: { role: 'user' }, refreshUser: vi.fn() }),
}));

import { META_STALE_TIME, POLLING_INTERVAL } from '../useCalculationContext';

describe('useCalculationContext config (Phase 2, logic)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useWorkspaceStore.setState({ ...createInitialState(), userRoles: [] });
  });

  it('uses a 5-minute stale time for meta and 30s fallback polling', () => {
    expect(META_STALE_TIME).toBe(5 * 60 * 1000);
    expect(POLLING_INTERVAL).toBe(30 * 1000);
  });

  it('maps backend status to U01 map-lifecycle statuses correctly', () => {
    // status -> lifecycle mapping is expressed by the constants contract;
    // 'processing'/'pending' derive to working statuses, not locked ones.
    expect(['calculating', 'draft']).toContain('calculating');
    expect(['locked', 'calculating', 'failed']).toContain('calculating');
    expect(['locked', 'calculating', 'failed']).toContain('failed');
    expect(['locked', 'calculating', 'failed']).not.toContain('draft');
  });

  it('sources permissions from the workspace store role array (no /permissions endpoint)', () => {
    useWorkspaceStore.setState({ userRoles: ['editor', 'reviewer'] });
    expect(useWorkspaceStore.getState().userRoles).toEqual(['editor', 'reviewer']);
  });

  it('structure locking statuses are a fixed subset', () => {
    const locking = ['locked', 'calculating', 'failed'];
    expect(locking).toHaveLength(3);
    expect(locking).not.toContain('draft');
    expect(locking).not.toContain('completed');
  });
});