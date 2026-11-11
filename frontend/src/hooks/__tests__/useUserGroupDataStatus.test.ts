/** What the user group step already has, as the User Group Boundary menu shows it (owner, 2026-10-11). */
import { describe, expect, it, vi, beforeEach } from 'vitest';

const getHouseholds = vi.fn();
const getHouseholdSummary = vi.fn();
const getAllCommittees = vi.fn();
vi.mock('../../services/api', () => ({
  userGroupApi: { getHouseholds: (...a: any[]) => getHouseholds(...a), getHouseholdSummary: (...a: any[]) => getHouseholdSummary(...a), getAllCommittees: (...a: any[]) => getAllCommittees(...a) },
}));

import { readUserGroupDataStatus } from '../useUserGroupDataStatus';

const notFound = Object.assign(new Error('404'), { response: { status: 404 } });

beforeEach(() => vi.clearAllMocks());

describe('readUserGroupDataStatus', () => {
  it('counts household rows, or a totals-only summary, as the household data', async () => {
    getAllCommittees.mockRejectedValue(notFound);
    getHouseholds.mockResolvedValue([{ id: 1 }]);
    expect((await readUserGroupDataStatus('c')).households).toBe(true);
    getHouseholds.mockResolvedValue([]);
    getHouseholdSummary.mockResolvedValue({ total_households: 120 });
    expect((await readUserGroupDataStatus('c')).households).toBe(true);
    getHouseholdSummary.mockRejectedValue(notFound);
    expect((await readUserGroupDataStatus('c')).households).toBe(false);
  });

  it('the executive committee is the main committee; the advisory and financial ones are the optional "other"', async () => {
    getHouseholds.mockResolvedValue([]);
    getHouseholdSummary.mockRejectedValue(notFound);
    getAllCommittees.mockResolvedValue({ main_committee: [{ name: 'a' }], advisory_committee: [], financial_committee: [] });
    expect(await readUserGroupDataStatus('c')).toEqual({ households: false, executive: true, other: false });
    getAllCommittees.mockResolvedValue({ main_committee: [], advisory_committee: [{ name: 'b' }], financial_committee: [] });
    expect(await readUserGroupDataStatus('c')).toEqual({ households: false, executive: false, other: true });
  });

  it('nothing entered (404s) reads as missing, not as an error', async () => {
    getHouseholds.mockRejectedValue(notFound);
    getAllCommittees.mockRejectedValue(notFound);
    expect(await readUserGroupDataStatus('c')).toEqual({ households: false, executive: false, other: false });
  });
});
