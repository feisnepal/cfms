/**
 * The regulation-species panel shows what the server sends, with the placeholder beside each result, and the all /
 * classified switch swaps the whole set (tokens included) without a second request.
 */
import React from 'react';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, afterEach } from 'vitest';

vi.mock('../../../i18n/hooks', () => ({ useT: () => (k: string) => k }));
vi.mock('react-chartjs-2', () => ({ Bar: () => <div data-testid="bar" /> }));
vi.mock('../../../utils/chartSetup', () => ({}));
const get = vi.fn();
vi.mock('../../../services/api', () => ({ fieldInventoryApi: { getRegulationSpecies: (...a: unknown[]) => get(...a) } }));

import { RegulationSpeciesPanel } from '../RegulationSpeciesPanel';

afterEach(() => {
  cleanup();
  get.mockReset();
});

const variant = (p: string, species: string) => ({
  prefix: p,
  narration: { token: `{{section:${p}_species_narration:full}}`, text: `narration ${p}` },
  tables: [
    ['species_regen_per_ha_table', 3], ['species_pole_per_ha_table', 3], ['species_tree_per_ha_table', 3],
    ['unit_species_regen_per_ha_table', 4], ['unit_species_pole_per_ha_table', 4], ['unit_species_tree_per_ha_table', 4],
  ].map(([b]) => ({
    key: `${p}_${b}`, token: `{{${p}_${b}}}`, label: `${p} ${b}`, headers: ['प्रजाती', 'संख्या_प्रति_हेक्टर'],
    rows: [{ प्रजाती: species, संख्या_प्रति_हेक्टर: 12.5 }, { प्रजाती: 'जम्मा', संख्या_प्रति_हेक्टर: 12.5 }],
  })),
  charts: [{ key: `${p}_species_tree_volume_bar`, token: `{{chart:${p}_species_tree_volume_bar}}`, title: 'c', y_label: 'y', labels: ['a'], values: [1] }],
});

const view = { region: 'hill', variants: { all: variant('fi_reg', 'अन्य प्रजाति (पहाड)'), classified: variant('fi_regc', 'Quercus spp') } };

describe('RegulationSpeciesPanel', () => {
  it('shows the all-categories set first, with its placeholders', async () => {
    get.mockResolvedValue(view);
    render(<RegulationSpeciesPanel fieldInventoryId="fi1" />);
    await waitFor(() => expect(screen.getByTestId('regulation-species-panel')).toBeTruthy());
    expect(get).toHaveBeenCalledWith('fi1');
    expect(screen.getByText('{{fi_reg_species_tree_per_ha_table}}')).toBeTruthy();
    expect(screen.getByText('{{section:fi_reg_species_narration:full}}')).toBeTruthy();
    expect(screen.getAllByText('अन्य प्रजाति (पहाड)').length).toBeGreaterThan(0);
    expect(screen.getByText('{{chart:fi_reg_species_tree_volume_bar}}')).toBeTruthy();
    expect(screen.queryByText('{{fi_regc_species_tree_per_ha_table}}')).toBeNull();
  });

  it('switches to the classified-only set and its own placeholders, with one request', async () => {
    get.mockResolvedValue(view);
    render(<RegulationSpeciesPanel fieldInventoryId="fi1" />);
    await waitFor(() => screen.getByTestId('regulation-species-panel'));
    fireEvent.click(screen.getByText('totalInventory.regSpClassified'));
    expect(screen.getByText('{{fi_regc_species_tree_per_ha_table}}')).toBeTruthy();
    expect(screen.queryByText('{{fi_reg_species_tree_per_ha_table}}')).toBeNull();
    expect(screen.queryByText('अन्य प्रजाति (पहाड)')).toBeNull();
    expect(get).toHaveBeenCalledTimes(1);
  });

  it('says so when the request fails, and stays empty while loading', async () => {
    get.mockRejectedValue(new Error('x'));
    render(<RegulationSpeciesPanel fieldInventoryId="fi1" />);
    expect(screen.queryByTestId('regulation-species-panel')).toBeNull();
    await waitFor(() => expect(screen.getByText('totalInventory.regSpLoadFailed')).toBeTruthy());
  });
});
