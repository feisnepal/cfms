/**
 * Who may plan the forest's yearly activities (D9): only the owner. The plan routes answer 404 to anyone else,
 * so the screen asks once and hides what could not save.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';

vi.mock('../../../services/api', () => ({ yearlyPlanApi: { getHealth: vi.fn() } }));

import { yearlyPlanApi } from '../../../services/api';
import { usePlanAccess } from '../usePlanAccess';

const getHealth = (yearlyPlanApi as unknown as { getHealth: ReturnType<typeof vi.fn> }).getHealth;

beforeEach(() => vi.clearAllMocks());

describe('usePlanAccess', () => {
  it('is "owner" when the plan can be read', async () => {
    getHealth.mockResolvedValue({});
    const { result } = renderHook(() => usePlanAccess('c1'));
    expect(result.current).toBe('unknown'); // still asking: nothing is blocked
    await waitFor(() => expect(result.current).toBe('owner'));
  });

  it('is "notOwner" when the server answers 404 — a super-admin included (D9)', async () => {
    getHealth.mockRejectedValue({ response: { status: 404 } });
    const { result } = renderHook(() => usePlanAccess('c1'));
    await waitFor(() => expect(result.current).toBe('notOwner'));
  });

  it('stays "unknown" for any other failure, so a flaky connection never takes the controls away', async () => {
    getHealth.mockRejectedValue(Object.assign(new Error('offline'), { code: 'ERR_NETWORK', request: {} }));
    const { result } = renderHook(() => usePlanAccess('c1'));
    await waitFor(() => expect(getHealth).toHaveBeenCalled());
    expect(result.current).toBe('unknown');
  });

  it('asks nothing when it is switched off or there is no forest yet', () => {
    renderHook(() => usePlanAccess('c1', false));
    renderHook(() => usePlanAccess(undefined));
    expect(getHealth).not.toHaveBeenCalled();
  });
});
