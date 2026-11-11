/**
 * The workspace must learn a map is structure-locked from the READ path, not
 * only when the client submits it in-session. `GET /calculations/{id}` now
 * carries `structure_locked` / `map_lifecycle_status`; this hook syncs the
 * flag into the store so a locked forest shows disabled controls instead of
 * 423-ing on every restructure.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useWorkspaceStore } from '../../store/workspaceStore';

// Both the meta query and the poll query resolve to this — one knob per test.
let META: Record<string, unknown> | undefined;
vi.mock('@tanstack/react-query', () => ({
  useQuery: () => ({ data: META, isLoading: false, error: null, refetch: vi.fn() }),
}));
vi.mock('../../services/api', () => ({ forestApi: { getCalculation: vi.fn() } }));
vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({ user: { role: 'user' }, refreshUser: vi.fn() }),
}));

import { useCalculationContext } from '../useCalculationContext';

beforeEach(() => {
  META = undefined;
  // Reset only the fields under test — spreading createInitialState() would
  // replace the real zustand actions with its no-op stubs.
  useWorkspaceStore.setState({
    structureLocked: false, mapLifecycleStatus: 'draft', userRoles: [], calculationId: null,
  });
});

describe('useCalculationContext — structure lock from the read path', () => {
  it('syncs structure_locked:true into the store and derives structureLocked', () => {
    META = { id: 'c1', status: 'completed', map_lifecycle_status: 'completed', structure_locked: true };
    const { result } = renderHook(() => useCalculationContext('c1'));
    expect(useWorkspaceStore.getState().structureLocked).toBe(true);
    expect(result.current.structureLocked).toBe(true);
    expect(result.current.mapLifecycleStatus).toBe('completed');
  });

  it('syncs structure_locked:false — a completed-but-unlocked map stays editable', () => {
    useWorkspaceStore.setState({ structureLocked: true }); // stale from a prior calc
    META = { id: 'c2', status: 'completed', map_lifecycle_status: 'completed', structure_locked: false };
    const { result } = renderHook(() => useCalculationContext('c2'));
    expect(useWorkspaceStore.getState().structureLocked).toBe(false);
    expect(result.current.structureLocked).toBe(false);
  });

  it('leaves the store flag alone when the payload omits structure_locked (legacy response)', () => {
    useWorkspaceStore.setState({ structureLocked: true });
    META = { id: 'c3', status: 'completed' }; // no structure_locked / lifecycle field
    renderHook(() => useCalculationContext('c3'));
    expect(useWorkspaceStore.getState().structureLocked).toBe(true);
  });

  it('still honours a locking lifecycle status even without the flag', () => {
    META = { id: 'c4', status: 'failed', map_lifecycle_status: 'failed' };
    const { result } = renderHook(() => useCalculationContext('c4'));
    expect(result.current.structureLocked).toBe(true); // 'failed' ∈ LOCKING_STATUSES
  });
});
