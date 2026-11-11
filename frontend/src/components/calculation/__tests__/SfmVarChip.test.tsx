import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { AuthContext } from '../../../contexts/AuthContext';
import { SfmVarChip, SfmVarCopyMenu } from '../SfmVarChip';

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

describe('SfmVarChip', () => {
  it('renders nothing for a non-designer', () => {
    const { container } = render(
      withRole('user', <SfmVarChip tokenKey="sfm_total_annual_harvest_m3" />),
    );
    expect(container.querySelector('button')).toBeNull();
  });

  it('renders nothing with no auth context', () => {
    const { container } = render(<SfmVarChip tokenKey="sfm_x" />);
    expect(container.querySelector('button')).toBeNull();
  });

  it('copies {{key}} for a template designer', () => {
    render(withRole('template_designer', <SfmVarChip tokenKey="sfm_yield_table" />));
    fireEvent.click(screen.getByRole('button'));
    expect(writeText).toHaveBeenCalledWith('{{sfm_yield_table}}');
  });

  it('super admin sees it too', () => {
    render(withRole('super_admin', <SfmVarChip tokenKey="sfm_x" />));
    expect(screen.getByRole('button')).toBeTruthy();
  });
});

describe('SfmVarCopyMenu', () => {
  const groups = [
    { labelKey: 'sfm.varChip.grpNumbers', keys: ['sfm_dominant_type_ne', 'sfm_production_area_ha'] },
    { labelKey: 'sfm.varChip.grpMaps', keys: ['thememap:sfm__forest_type'] },
  ];

  it('hidden for a non-designer', () => {
    const { container } = render(withRole('user', <SfmVarCopyMenu groups={groups} />));
    expect(container.querySelector('button')).toBeNull();
  });

  it('copies all tokens as one block for a designer', async () => {
    render(withRole('super_admin', <SfmVarCopyMenu groups={groups} />));
    fireEvent.click(screen.getByRole('button'));
    const allItem = await screen.findByText(/Copy all/i);
    fireEvent.click(allItem);
    expect(writeText).toHaveBeenCalledWith(
      '{{sfm_dominant_type_ne}}\n{{sfm_production_area_ha}}\n{{thememap:sfm__forest_type}}',
    );
  });
});
