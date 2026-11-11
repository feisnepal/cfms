import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

vi.mock('../../../i18n/hooks', () => ({ useT: () => (k: string, d?: string) => d ?? k }));

const get = vi.fn();
const save = vi.fn();
const preview = vi.fn();
const del = vi.fn();
vi.mock('../../../services/api', () => ({
  userGroupApi: {
    getHouseholdSummaryEntry: (...a: unknown[]) => get(...a),
    saveHouseholdSummaryEntry: (...a: unknown[]) => save(...a),
    previewHouseholdSummaryDemands: (...a: unknown[]) => preview(...a),
    deleteHouseholdSummaryEntry: (...a: unknown[]) => del(...a),
  },
}));

import HouseholdSummaryEntry from '../HouseholdSummaryEntry';

const saved = {
  total_households: 40, male_count: 90, female_count: 100, forest_occupation_households: 25,
  other_occupation_households: 10, cow_ox_count: 30, buffalo_count: 20, goat_sheep_count: 50,
  avg_land_area: 6, land_unit: 'ropani', demands_auto_calculated: true,
  caste_distribution: { दलित: 15, जनजाती: 25 }, prosperity_distribution: { मध्यम: 30, विपन्न: 10 },
};

describe('HouseholdSummaryEntry', () => {
  beforeEach(() => {
    get.mockReset().mockResolvedValue(null);
    save.mockReset().mockResolvedValue({ ...saved, warnings: [] });
    preview.mockReset().mockResolvedValue({ firewood_demand_bhari: 1, grass_demand_bhari: 2 });
    del.mockReset().mockResolvedValue(undefined);
  });

  it('shows the explanation and no Remove button for a forest with no saved summary', async () => {
    render(<HouseholdSummaryEntry calculationId="c1" onChanged={() => {}} />);
    expect(await screen.findByText('Enter household totals only')).toBeTruthy();
    expect(screen.queryByText('Remove summary')).toBeNull();
    expect(screen.getByText('Save summary')).toBeTruthy();
  });

  it('loads a saved summary, shows the caste/prosperity totals against the household count, and offers Remove', async () => {
    get.mockResolvedValue(saved);
    render(<HouseholdSummaryEntry calculationId="c1" onChanged={() => {}} />);
    expect(await screen.findByText('Remove summary')).toBeTruthy();
    // 15 + 25 and 30 + 10 both equal the 40 households
    await waitFor(() => expect(screen.getAllByText('40 / 40').length).toBe(2));
  });
});
