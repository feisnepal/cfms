import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { useResolvedParams, type ParamsApi } from '../useResolvedParams';

type FlatPatch = Record<string, unknown>;

const resp = (over = {}) => ({
  params: { a: 1 },
  provenance: { a: 'default' as const },
  customised: false,
  ...over,
});

function api(): ParamsApi<FlatPatch> {
  return {
    get: vi.fn().mockResolvedValue(resp()),
    patch: vi.fn().mockResolvedValue(resp({ customised: true, provenance: { a: 'forest' } })),
    reset: vi.fn().mockResolvedValue(resp()),
  };
}

beforeEach(() => vi.clearAllMocks());

describe('useResolvedParams', () => {
  it('loads on mount', async () => {
    const a = api();
    const { result } = renderHook(() => useResolvedParams(a, 'c1', () => ({})));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(a.get).toHaveBeenCalledWith('c1');
    expect(result.current.resp?.params).toEqual({ a: 1 });
    expect(result.current.dirty).toBe(false);
  });

  it('dirty tracks the patch (flat + nested-empty)', async () => {
    const a = api();
    const { result } = renderHook(() => useResolvedParams<FlatPatch>(a, 'c1', () => ({})));
    await waitFor(() => expect(result.current.loading).toBe(false));
    act(() => result.current.setPatch({ x: 5 }));
    expect(result.current.dirty).toBe(true);
    act(() => result.current.setPatch({ group: {} })); // nested-empty → not dirty
    expect(result.current.dirty).toBe(false);
  });

  it('save() PATCHes the current patch and stores the response', async () => {
    const a = api();
    const { result } = renderHook(() => useResolvedParams<FlatPatch>(a, 'c1', () => ({})));
    await waitFor(() => expect(result.current.loading).toBe(false));
    act(() => result.current.setPatch({ x: 5 }));
    await act(async () => {
      await result.current.save();
    });
    expect(a.patch).toHaveBeenCalledWith('c1', { x: 5 });
    expect(result.current.customised).toBe(true);
  });

  it('reset() DELETEs and clears the patch', async () => {
    const a = api();
    const { result } = renderHook(() => useResolvedParams<FlatPatch>(a, 'c1', () => ({})));
    await waitFor(() => expect(result.current.loading).toBe(false));
    act(() => result.current.setPatch({ x: 5 }));
    await act(async () => {
      await result.current.reset();
    });
    expect(a.reset).toHaveBeenCalledWith('c1');
    expect(result.current.dirty).toBe(false);
  });

  it('sets error on a failed load', async () => {
    const a = api();
    (a.get as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('boom'));
    const { result } = renderHook(() => useResolvedParams(a, 'c1', () => ({})));
    await waitFor(() => expect(result.current.error).toBe(true));
  });
});
