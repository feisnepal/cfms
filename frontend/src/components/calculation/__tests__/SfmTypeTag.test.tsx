import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

vi.mock('../../../i18n/hooks', () => ({
  useT: () => (k: string, o?: unknown) => (k === 'sfm.typeNo' ? `Type ${(o as { n: number }).n}` : typeof o === 'string' ? o : k),
}));

const getForestTypes = vi.fn();
vi.mock('../../../services/api', () => ({ sfmApi: { getForestTypes: (...a: unknown[]) => getForestTypes(...a) } }));

import { SfmTypeTag } from '../SfmTypeTag';
import { SfmTypeReferenceProvider } from '../SfmTypeReference';
import { resetForestTypesCache } from '../../../lib/sfmForestTypes';

const type7 = {
  type_no: 7, name_ne: 'पहाडी साल वन', name_en: 'Hill Sal forest', orientation: 'Conservation',
  species_groups: ['SAL'], zone_triggers: ['HILL'], slope_band: null, origin: null,
  notes_ne: 'संरक्षणमुखी', notes_en: 'Conservation-oriented', is_active: true, sort_order: 7,
  branches: { adequate: {
    system_ne: 'छनौट प्रणाली', system_en: 'Selection system', felling_cycle_years: 10, regen_method_ne: 'प्राकृतिक', regen_method_en: 'Natural',
    rotation_years: null, regeneration_period_years: null, mother_trees_per_ha: null, note_ne: '', note_en: '',
    yield_rules: { basis: 'growing_stock_pct_ge40', steps: [{ pct: 1, gs_per_ha_min: 200, gs_per_ha_max: null }], target_stems_per_ha: null, note_ne: '', note_en: '' },
  } },
};

describe('SfmTypeTag', () => {
  beforeEach(() => { resetForestTypesCache(); getForestTypes.mockReset(); });

  it('is just its label until the types arrive, and stays that way if they never do (no broken tooltip)', async () => {
    getForestTypes.mockRejectedValue(new Error('offline'));
    render(<SfmTypeTag n={7} />);
    expect(screen.getByText('Type 7')).toBeTruthy();
    await waitFor(() => expect(getForestTypes).toHaveBeenCalled());
    expect(screen.getByText('Type 7')).toBeTruthy();
  });

  it('shows the name in both languages, the orientation, and the harvest step on hover', async () => {
    getForestTypes.mockResolvedValue([type7]);
    render(<SfmTypeTag n={7} block={{ reasons: ['Hill zone'], confidence: 0.75 }} />);
    // once the types load, the plain label is replaced by the hover target: re-query it
    await waitFor(() => expect(screen.getByTestId('sfm-type-tag-7').getAttribute('style') ?? '').toContain('help'));
    fireEvent.mouseEnter(screen.getByTestId('sfm-type-tag-7'));
    const card = await screen.findByTestId('sfm-type-card-7', undefined, { timeout: 2000 });
    expect(card.textContent).toContain('पहाडी साल वन');
    expect(card.textContent).toContain('Hill Sal forest');
    expect(card.textContent).toContain('Conservation');
    expect(card.textContent).toContain('sfm.ref.stepGe');   // the harvest step is inline
    expect(card.textContent).toContain('Hill zone');        // this block's own reasons
  });

  it('opens the reference panel on click when inside a provider', async () => {
    getForestTypes.mockResolvedValue([type7]);
    render(<SfmTypeReferenceProvider><SfmTypeTag n={7} /></SfmTypeReferenceProvider>);
    await waitFor(() => expect(screen.getByTestId('sfm-type-tag-7').getAttribute('role')).toBe('button'));
    fireEvent.click(screen.getByTestId('sfm-type-tag-7'));
    expect(await screen.findByText('sfm.ref.title', undefined, { timeout: 2000 })).toBeTruthy();
    expect(await screen.findByTestId('sfm-ref-detail-7', undefined, { timeout: 2000 })).toBeTruthy(); // focused type is expanded
  });
});

describe('SfmTypeTag card link', () => {
  it('"Click for the full details" opens the reference panel on that type', async () => {
    getForestTypes.mockResolvedValue([type7]);
    render(<SfmTypeReferenceProvider><SfmTypeTag n={7} /></SfmTypeReferenceProvider>);
    await waitFor(() => expect(screen.getByTestId('sfm-type-tag-7').getAttribute('role')).toBe('button'));
    fireEvent.mouseEnter(screen.getByTestId('sfm-type-tag-7'));
    fireEvent.click(await screen.findByTestId('sfm-type-card-open-7', undefined, { timeout: 2000 }));
    expect(await screen.findByTestId('sfm-ref-detail-7', undefined, { timeout: 2000 })).toBeTruthy();
  });
});
