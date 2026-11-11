import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { AuthContext } from '../../../contexts/AuthContext';
import { HazardVarChip, HazardVarCopyMenu } from '../HazardVarChip';

const writeText = vi.fn().mockResolvedValue(undefined);
beforeEach(() => {
  writeText.mockClear();
  Object.assign(navigator, { clipboard: { writeText } });
});

const withRole = (role: string | undefined, ui: React.ReactNode) => (
  <AuthContext.Provider value={{ user: role ? { role } : null } as never}>
    {ui}
  </AuthContext.Provider>
);

describe('HazardVarChip', () => {
  it('renders nothing for a non-designer', () => {
    const { container } = render(withRole('user', <HazardVarChip tokenKey="hazard_landslide_prone_area_pct" />));
    expect(container.querySelector('button')).toBeNull();
  });

  it('renders nothing with no auth context at all', () => {
    const { container } = render(<HazardVarChip tokenKey="hazard_x" />);
    expect(container.querySelector('button')).toBeNull();
  });

  it('copies {{key}} for a template designer', () => {
    render(withRole('template_designer', <HazardVarChip tokenKey="hazard_landslide_prone_area_pct" />));
    fireEvent.click(screen.getByRole('button'));
    expect(writeText).toHaveBeenCalledWith('{{hazard_landslide_prone_area_pct}}');
  });

  it('super admin sees it too', () => {
    render(withRole('super_admin', <HazardVarChip tokenKey="hazard_x" />));
    expect(screen.getByRole('button')).toBeTruthy();
  });
});

describe('HazardVarCopyMenu', () => {
  const groups = [
    { labelKey: 'hazardErosion.varChip.grpTables', keys: ['hazard_erosion_by_unit_table', 'hazard_household_priority_table'] },
    { labelKey: 'hazardErosion.varChip.grpCharts', keys: ['chart:hazard_slope_class_split'] },
  ];

  it('hidden for a non-designer', () => {
    const { container } = render(withRole('user', <HazardVarCopyMenu groups={groups} />));
    expect(container.querySelector('button')).toBeNull();
  });

  it('copies all tokens as one block for a designer', async () => {
    render(withRole('super_admin', <HazardVarCopyMenu groups={groups} />));
    fireEvent.click(screen.getByRole('button'));
    const allItem = await screen.findByText(/Copy all/i);
    fireEvent.click(allItem);
    expect(writeText).toHaveBeenCalledWith(
      '{{hazard_erosion_by_unit_table}}\n{{hazard_household_priority_table}}\n{{chart:hazard_slope_class_split}}',
    );
  });
});
