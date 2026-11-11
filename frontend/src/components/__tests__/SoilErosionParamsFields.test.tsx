import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import SoilErosionParamsFields, { type ParamPatch } from '../SoilErosionParamsFields';

function setup(value: ParamPatch = {}) {
  const onChange = vi.fn();
  const utils = render(
    <SoilErosionParamsFields value={value} onChange={onChange} />,
  );
  return { onChange, ...utils };
}

describe('SoilErosionParamsFields', () => {
  it('shows a clear (×) button only for fields that are set', () => {
    setup({ ls_cap: 50, sdr_enabled: true });
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

  it('reflects the SDR switch state from the value', () => {
    const { rerender } = setup({ sdr_enabled: true });
    expect(document.querySelector('.ant-switch-checked')).toBeTruthy();
    rerender(<SoilErosionParamsFields value={{}} onChange={vi.fn()} />);
    expect(document.querySelector('.ant-switch-checked')).toBeFalsy();
  });

  it('shows the severity breaks as a comma list and parses edits to numbers', () => {
    const { onChange } = setup({ severity_breaks: [5, 10, 20] });
    const input = screen.getByDisplayValue('5, 10, 20') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '4, 9, 18, 40' } });
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ severity_breaks: [4, 9, 18, 40] }),
    );
  });

  it('clears severity_breaks when the input is emptied', () => {
    const { onChange } = setup({ severity_breaks: [5, 10] });
    const input = screen.getByDisplayValue('5, 10') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '' } });
    expect(onChange).toHaveBeenCalledWith(
      expect.not.objectContaining({ severity_breaks: expect.anything() }),
    );
  });

  it('toggling SDR emits sdr_enabled', () => {
    const { onChange } = setup({});
    fireEvent.click(document.querySelector('.ant-switch') as HTMLElement);
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ sdr_enabled: true }),
    );
  });
});
