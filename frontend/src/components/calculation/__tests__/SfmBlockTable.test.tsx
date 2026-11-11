import { describe, it, expect, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SfmBlockTable from '../SfmBlockTable';
import type { SfmBlock, SfmZone } from '../../../services/api';

const zone = (over: Partial<SfmZone> = {}): SfmZone => ({
  sfm_zone: 'LOWLAND_SAL',
  inner_terai: false,
  dom_phys: 'Terai',
  slope_band: 1,
  slope_band_area_pct: { '1': 100 },
  mean_altitude_m: 200,
  ...over,
});

const block = (over: Partial<SfmBlock> = {}): SfmBlock => ({
  block_name: 'Block-1',
  area_ha: 50,
  inputs: {
    block_name: 'Block-1',
    area_ha: 50,
    dominant_species: [
      { scientific: 'Shorea robusta', local: 'Sal', genus: 'Shorea', group: 'SAL', share_pct: 82 },
    ],
    associate_species: [],
    dominant_group: 'SAL',
    codominant_group: null,
    seedlings_per_ha: 6000,
    saplings_per_ha: 2500,
    regen_adequate: true,
    growing_stock_m3_per_ha: 210,
    gs_ge40_m3_per_ha: 120,
    gs_ge40_m3: 6000,
    mother_trees_per_ha: null,
    crown_density_pct: 55,
    origin: 'natural',
    conversion_target: false,
    mean_altitude_m: 200,
    invasive_present: false,
    riparian: false,
    source: 'stem_mapping',
    unmapped_species: [],
  },
  proposed_type_no: 1,
  estimate_type_no: null,
  state: 'classified',
  plot_count: 6,
  land_class: 'forest',
  land_class_source: 'esa',
  land_class_suggestion: 'forest',
  override_land_class: null,
  confidence: 0.85,
  needs_review: false,
  reasons_ne: 'साल प्रधान · चुरे · → सि.नं. 1',
  reasons_en: 'SAL dominant · Chure Hillslopes · → type 1',
  override_type_no: null,
  override_crown_density_pct: null,
  override_origin: null,
  wc_accept: false,
  effective_type_no: 1,
  prescription: {
    type_no: 1,
    type_name_ne: 'साल',
    type_name_en: 'Sal',
    branch: 'adequate',
    method: 'selection_felling_cycle',
    orientation: 'Production',
    system_ne: 'छनौट प्रणाली',
    system_en: 'Selection system',
    felling_cycle_years: 10,
    regeneration_period_years: null,
    rotation_years: null,
    regen_method_ne: null,
    regen_method_en: null,
    mother_tree_target: null,
    yield_basis: 'growing_stock_pct_ge40',
    yield_pct: 2,
    gs_ge40_m3_per_ha: 120,
    yield_note_ne: '',
    yield_note_en: '',
    target_stems_per_ha: null,
    note_ne: '',
    note_en: '',
  },
  orientation: 'Production',
  working_circle_proposal: null,
  felling_series_id: 1,
  ...over,
});

describe('SfmBlockTable', () => {
  it('renders one row per block', () => {
    render(
      <SfmBlockTable
        blocks={[block(), block({ block_name: 'Block-2', effective_type_no: 2 })]}
        zoneByBlock={{ 'Block-1': zone(), 'Block-2': zone({ slope_band: 3 }) }}
        selectedBlock="Block-1"
        patchingBlock={null}
        lang="en"
        onSelect={vi.fn()}
        onPatch={vi.fn()}
      />,
    );
    expect(screen.getByText('Block-1')).toBeInTheDocument();
    expect(screen.getByText('Block-2')).toBeInTheDocument();
  });

  it('has no column titled "harvest"', () => {
    const { container } = render(
      <SfmBlockTable
        blocks={[block()]}
        zoneByBlock={{ 'Block-1': zone() }}
        selectedBlock={null}
        patchingBlock={null}
        lang="en"
        onSelect={vi.fn()}
        onPatch={vi.fn()}
      />,
    );
    const headers = Array.from(container.querySelectorAll('th')).map((th) =>
      (th.textContent || '').toLowerCase(),
    );
    expect(headers.some((h) => h.includes('harvest'))).toBe(false);
  });

  it('calls onPatch with override_type_no when the override Select changes', async () => {
    const onPatch = vi.fn();
    render(
      <SfmBlockTable
        blocks={[block()]}
        zoneByBlock={{ 'Block-1': zone() }}
        selectedBlock={null}
        patchingBlock={null}
        lang="en"
        onSelect={vi.fn()}
        onPatch={onPatch}
      />,
    );
    // two selects per row: the land class, then the type override
    const combobox = screen.getAllByRole('combobox')[1];
    await userEvent.click(combobox);
    const option = await screen.findByText('Type 7');
    await userEvent.click(option);
    expect(onPatch).toHaveBeenCalledWith('Block-1', { override_type_no: 7 });
  });

  it('row click selects the block, not the Select cell', async () => {
    const onSelect = vi.fn();
    render(
      <SfmBlockTable
        blocks={[block()]}
        zoneByBlock={{ 'Block-1': zone() }}
        selectedBlock={null}
        patchingBlock={null}
        lang="en"
        onSelect={onSelect}
        onPatch={vi.fn()}
      />,
    );
    await userEvent.click(screen.getByText('Block-1'));
    expect(onSelect).toHaveBeenCalledWith('Block-1');
  });
});


describe('SfmBlockTable: blocks without a type', () => {
  const base = block();
  const t = (over: Partial<SfmBlock>) => (
    <SfmBlockTable
      blocks={[{ ...base, ...over }]}
      zoneByBlock={{ 'Block-1': zone() }}
      selectedBlock={null}
      patchingBlock={null}
      lang="en"
      onSelect={vi.fn()}
      onPatch={vi.fn()}
    />
  );

  it('forest land without plots shows "inventory missing" and no type', () => {
    render(t({ state: 'inventory_missing', plot_count: 0, proposed_type_no: null, effective_type_no: null, estimate_type_no: 7 }));
    expect(screen.getByTestId('sfm-state-missing')).toBeTruthy();
  });

  it('non-forest land shows its land class, not a type', () => {
    render(t({ state: 'non_forest', land_class: 'grassland', proposed_type_no: null, effective_type_no: null }));
    expect(screen.getByTestId('sfm-state-non-forest')).toBeTruthy();
  });

  it('1-4 plots shows the type with a provisional mark', () => {
    render(t({ state: 'provisional', plot_count: 3 }));
    expect(screen.getByTestId('sfm-state-provisional')).toBeTruthy();
  });

  it('changing the land class patches land_class', async () => {
    const onPatch = vi.fn();
    render(
      <SfmBlockTable
        blocks={[{ ...base, land_class: 'forest', land_class_suggestion: 'forest' }]}
        zoneByBlock={{ 'Block-1': zone() }}
        selectedBlock={null}
        patchingBlock={null}
        lang="en"
        onSelect={vi.fn()}
        onPatch={onPatch}
      />,
    );
    await userEvent.click(screen.getAllByRole('combobox')[0]);
    await userEvent.click(await screen.findByText('Grassland'));
    expect(onPatch).toHaveBeenCalledWith('Block-1', { land_class: 'grassland' });
  });
});
