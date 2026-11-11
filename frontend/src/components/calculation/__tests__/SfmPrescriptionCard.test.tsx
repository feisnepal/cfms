import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import SfmPrescriptionCard from '../SfmPrescriptionCard';
import type { SfmBlock, SfmFellingSeries } from '../../../services/api';

const series: SfmFellingSeries = {
  id: 1,
  type_no: 1,
  branch: 'adequate',
  method: 'selection_felling_cycle',
  C: 10,
  R: null,
  N: 10,
  area_ha: 20,
  annual_felling_area_ha: 2,
  gs_ge40_m3_per_ha: 200,
  gs_ge40_m3: 4000,
  pct: 2,
  annual_harvest_m3: 80,
  note_ne: '',
  note_en: '',
};

const block: SfmBlock = {
  block_name: 'Block-1',
  area_ha: 20,
  inputs: {} as SfmBlock['inputs'],
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
  reasons_ne: '',
  reasons_en: '',
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
    gs_ge40_m3_per_ha: 200,
    yield_note_ne: '',
    yield_note_en: '',
    target_stems_per_ha: null,
    note_ne: '',
    note_en: 'Selection felling on a 10-year cycle.',
  },
  orientation: 'Production',
  working_circle_proposal: null,
  felling_series_id: 1,
};

describe('SfmPrescriptionCard', () => {
  it('shows the yield line: GS≥40 → pct% → annual harvest', () => {
    render(<SfmPrescriptionCard block={block} series={series} lang="en" />);
    // "200.0 m³/ha (≥40 cm) → 2% → 80.0 m³/yr"
    expect(screen.getByText(/200\.0.*2.*80\.0/)).toBeInTheDocument();
    expect(screen.getByText('Selection system')).toBeInTheDocument();
  });

  it('prompts to pick a block when nothing is selected', () => {
    render(<SfmPrescriptionCard block={null} series={null} lang="en" />);
    expect(screen.getByText('Select a block to see its prescription.')).toBeInTheDocument();
  });
});
