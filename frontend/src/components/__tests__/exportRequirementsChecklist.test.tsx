import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ExportRequirementsChecklist } from '../ExportRequirementsChecklist';
import { requirementUrl, REQUIREMENT_LINKS } from '../../lib/exportRequirementLinks';

const KEYS = ['raster', 'sampling', 'field_inventory', 'biodiversity', 'households', 'yearly_activities', 'cba', 'committee', 'metadata'];
const data = {
  ready: false,
  items: KEYS.map((key, n) => ({
    key, done: n % 2 === 0, label_en: `L-${key}`, label_ne: `N-${key}`, hint_en: `H-${key}`, hint_ne: `H-${key}`, detail: {},
  })),
};

describe('export requirement shortcuts', () => {
  it('every backend requirement key has a destination', () => {
    for (const k of KEYS) expect(REQUIREMENT_LINKS[k], k).toBeTruthy();
  });

  it('builds the surface, pane and dialog parameters', () => {
    expect(requirementUrl('c1', 'sampling')).toBe('/calculations/c1?surface=field%2Fsampling');
    expect(requirementUrl('c1', 'yearly_activities')).toBe('/calculations/c1?surface=plan%2Fyearly');
    expect(requirementUrl('c1', 'committee')).toBe('/calculations/c1?surface=base%2Funified&open=committee');
    expect(requirementUrl('c1', 'nope')).toBeNull();
    expect(requirementUrl('', 'cba')).toBeNull();
  });

  it('turns each step into a link, done or not', () => {
    render(<ExportRequirementsChecklist data={data} calculationId="c1" />);
    for (const k of KEYS) expect(screen.getByTestId(`export-requirement-link-${k}`).getAttribute('href')).toContain('/calculations/c1?surface=');
  });

  it('hands the address to onNavigate instead of reloading the page', () => {
    const go = vi.fn();
    render(<ExportRequirementsChecklist data={data} calculationId="c1" onNavigate={go} />);
    fireEvent.click(screen.getByTestId('export-requirement-link-metadata'));
    expect(go).toHaveBeenCalledWith('/calculations/c1?surface=field%2Fforestmetadata');
  });

  it('without a calculation id it is the plain list as before', () => {
    render(<ExportRequirementsChecklist data={data} />);
    expect(screen.queryByTestId('export-requirement-link-cba')).toBeNull();
    expect(screen.getByText('L-cba')).toBeTruthy();
  });
});
