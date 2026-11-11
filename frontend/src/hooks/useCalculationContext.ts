/**
 * useCalculationContext — shared calculation meta + permission context hook.
 *
 * Reality-aligned implementation (Phase 2, Tabbed Calculation Detail plan):
 *  - Calc meta fetched via the real `forestApi.getCalculation` (not a generic
 *    `/api/v1` fetch) with 5xx/network-only retry + exponential backoff.
 *  - Permissions come from the authenticated user's roles (U07 `roleMapping` +
 *    `workspaceStore.userRoles`), since no calc-scoped `/permissions` endpoint
 *    exists in the backend.
 *  - No WebSocket: the backend has no `/ws/calculations/{id}` stream. Live state
 *    is driven by the U01 `mapLifecycleStatus` in the workspace store plus a
 *    30s fallback poll of calc meta.
 *  - `structureLocked` derived per plan: calc flag OR lifecycle status.
 */
import { useEffect, useCallback, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { forestApi } from '../services/api';
import { useWorkspaceStore } from '../store/workspaceStore';
import { useAuth } from '../contexts/AuthContext';

export const META_STALE_TIME = 5 * 60 * 1000;
export const POLLING_INTERVAL = 30 * 1000;

const LOCKING_STATUSES = ['locked', 'calculating', 'failed'];

export interface CalculationContextValue {
  calculationId: string | null;
  calculation: any;
  permissions: string[];
  mapLifecycleStatus: string;
  structureLocked: boolean;
  isLoading: boolean;
  error: Error | null;
  refetchMeta: () => Promise<void>;
  refetchPermissions: () => Promise<void>;
}

/**
 * Provides the current calculation context.
 * - `calculationId`: the active calc id from the workspace store (kept for
 *   backward compatibility with `useMapCompositions`).
 */
export function useCalculationContext(calculationId?: string): CalculationContextValue {
  const storeCalcId = useWorkspaceStore((s) => s.calculationId);
  const id = calculationId ?? storeCalcId;

  const setCalculationId = useWorkspaceStore((s) => s.setCalculationId);
  const setMapLifecycleStatus = useWorkspaceStore((s) => s.setMapLifecycleStatus);
  const setStructureLocked = useWorkspaceStore((s) => s.setStructureLocked);
  const storeLifecycle = useWorkspaceStore((s) => s.mapLifecycleStatus);
  const storeLocked = useWorkspaceStore((s) => s.structureLocked);
  const storeRoles = useWorkspaceStore((s) => s.userRoles);

  const { user, refreshUser } = useAuth();

  // Sync Zustand store
  useEffect(() => {
    if (id) setCalculationId(id);
  }, [id, setCalculationId]);

  // Fetch calculation meta with retry + stale-while-revalidate
  const {
    data: calculation,
    isLoading: calcLoading,
    error: calcError,
    refetch: refetchCalc,
  } = useQuery({
    queryKey: ['calculation', id],
    queryFn: async () => {
      if (!id) throw new Error('No calculation id');
      return forestApi.getCalculation(id);
    },
    enabled: !!id,
    retry: (failureCount, error: any) => {
      // Only retry server errors (5xx) and network errors, not 4xx
      const status = error?.response?.status || error?.status;
      if (status && status >= 400 && status < 500) return false;
      return failureCount < 3;
    },
    retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 10000),
    staleTime: META_STALE_TIME,
    refetchOnWindowFocus: false, // CRITICAL: don't lose draft state on tab switch
  });

  // 30s fallback polling — backend has no WebSocket stream for status updates.
  const { data: polledMeta } = useQuery({
    queryKey: ['calculation', id, 'poll'],
    queryFn: async () => {
      if (!id) throw new Error('No calculation id');
      return forestApi.getCalculation(id);
    },
    enabled: !!id,
    refetchInterval: POLLING_INTERVAL,
    staleTime: POLLING_INTERVAL,
    refetchOnWindowFocus: false,
    retry: 1,
  });

  // Sync lifecycle status into the workspace store (U01) so the whole UI
  // reads one source of truth. Prefer the real `map_lifecycle_status` field
  // (accurate for submitted/locked; drives the header actions) and fall back
  // to the legacy status→lifecycle mapping for older responses.
  useEffect(() => {
    const meta = polledMeta ?? calculation;
    if (!meta) return;
    const status =
      meta.map_lifecycle_status ||
      (meta.status ? mapBackendStatusToLifecycle(meta.status) : '');
    if (status && status !== storeLifecycle) setMapLifecycleStatus(status);
    // The server flag is authoritative — sync it so an already-locked forest
    // shows disabled controls (with a reason) instead of firing 423s on every
    // restructure. Only act when the field is actually present in the payload.
    if (typeof meta.structure_locked === 'boolean' && meta.structure_locked !== storeLocked) {
      setStructureLocked(meta.structure_locked);
    }
  }, [polledMeta, calculation, storeLifecycle, storeLocked, setMapLifecycleStatus, setStructureLocked]);

  // Permissions derive from the authenticated user's roles (no /permissions
  // endpoint in the backend). Reuse the store's U07 role array.
  const permissions = storeRoles;

  // Derived state
  const mapLifecycleStatus = storeLifecycle || 'draft';
  const structureLocked = storeLocked || LOCKING_STATUSES.includes(mapLifecycleStatus);

  const refetchMeta = useCallback(async () => {
    await refetchCalc();
  }, [refetchCalc]);

  const refetchPermissions = useCallback(async () => {
    await refreshUser();
  }, [refreshUser]);

  return {
    calculationId: id,
    calculation,
    permissions,
    mapLifecycleStatus,
    structureLocked,
    isLoading: calcLoading,
    error: (calcError as Error) || null,
    refetchMeta,
    refetchPermissions,
  };
}

/** Maps a calculation `status` to the U01 map-lifecycle status used across the UI. */
function mapBackendStatusToLifecycle(status: string): string {
  switch (status) {
    case 'processing':
      return 'calculating';
    case 'failed':
      return 'failed';
    case 'completed':
      return 'completed';
    case 'pending':
      return 'draft';
    default:
      return 'draft';
  }
}

// Re-export the network status banner (plan: hook exposes it for connection UI).
export { NetworkStatusBanner } from '../components/NetworkStatusBanner';
