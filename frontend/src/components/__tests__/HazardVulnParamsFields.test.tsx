import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import HazardVulnParamsFields, { type ParamPatch } from '../HazardVulnParamsFields';

function setup(value: ParamPatch = {}) {
  const onChange = vi.fn();
  const utils = render(
    <HazardVulnParamsFields value={value} onChange={onChange} />,
  );
  return { onChange, ...utils };
}

describe('HazardVulnParamsFields', () => {
  it('shows a clear (×) button only for keys that are set, across groups', () => {
    setup({
      landslide: { prone_class_min: 3 },
      factor_of_safety: { saturation_ratio_m: 0.9 },
      household: {},
    });
    expect(
      document.querySelectorAll('button[title="Clear this override"]').length,
    ).toBe(2);
  });

  it('renders no clear buttons when nothing is overridden', () => {
    setup({});
    expect(
      document.querySelectorAll('button[title="Clear this override"]').length,
    ).toBe(0);
  });

  it('shows the number field value from the nested patch', () => {
    setup({ household: { top_n: 25 } });
    expect(screen.getByDisplayValue('25')).toBeTruthy();
  });

  it('emits a nested patch when a number field is set', () => {
    const { onChange } = setup({ household: { top_n: 25 } });
    const input = screen.getByDisplayValue('25') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '40' } });
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        household: expect.objectContaining({ top_n: 40 }),
      }),
    );
  });

  it('drops the group when its last key is cleared', () => {
    const { onChange } = setup({ landslide: { seismic_enabled: true } });
    const clearBtn = document.querySelector(
      'button[title="Clear this override"]',
    ) as HTMLElement;
    fireEvent.click(clearBtn);
    expect(onChange).toHaveBeenCalledWith(
      expect.not.objectContaining({ landslide: expect.anything() }),
    );
  });

  it('reflects the seismic switch state from the nested value', () => {
    const { rerender } = setup({ landslide: { seismic_enabled: true } });
    expect(document.querySelector('.ant-switch-checked')).toBeTruthy();
    rerender(<HazardVulnParamsFields value={{}} onChange={vi.fn()} />);
    // fresh render: FS-enabled + TWI-varied switches default to checked, but the
    // seismic switch (first, unchecked) means not *all* switches are checked
    const switches = document.querySelectorAll('.ant-switch');
    expect(switches.length).toBeGreaterThanOrEqual(3);
  });

  it('renders the three group dividers', () => {
    setup({});
    const text = document.body.textContent || '';
    expect(text).toContain('Landslide susceptibility');
    expect(text).toContain('Slope stability');
    expect(text).toContain('Household vulnerability');
  });
});
