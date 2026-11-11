/**
 * What the user group step already has, for the User Group Boundary layer menu (owner, 2026-10-11): household information (a list OR a
 * totals-only summary) and the executive committee are mandatory, the advisory and financial committees optional. Read once when the
 * workspace opens and again whenever the data dialog closes, and kept in the workspace store so the menu can show done / missing.
 */
import { useCallback, useEffect } from 'react';
import * as api from '../services/api';
import { useWorkspaceStore, type UserGroupDataStatus } from '../store/workspaceStore';

export async function readUserGroupDataStatus(calculationId: string): Promise<UserGroupDataStatus> {
  let households = false;
  try {
    households = (await api.userGroupApi.getHouseholds(calculationId)).length > 0;
    if (!households) {
      await api.userGroupApi.getHouseholdSummary(calculationId); // 404 = no totals either
      households = true;
    }
  } catch {
    // 404 / offline: nothing entered (or not readable): shown as missing, which is the safe reminder
  }
  let executive = false;
  let other = false;
  try {
    const c: any = await api.userGroupApi.getAllCommittees(calculationId);
    executive = (c?.main_committee ?? []).length > 0;
    other = (c?.advisory_committee ?? []).length + (c?.financial_committee ?? []).length > 0;
  } catch {
    // 404: no committees yet
  }
  return { households, executive, other };
}

export function useUserGroupDataStatus(calculationId: string | null | undefined): () => Promise<void> {
  const setStatus = useWorkspaceStore((s) => s.setUserGroupData);
  const refresh = useCallback(async () => {
    if (!calculationId) return;
    setStatus(await readUserGroupDataStatus(calculationId));
  }, [calculationId, setStatus]);
  useEffect(() => {
    void refresh();
  }, [refresh]);
  return refresh;
}
