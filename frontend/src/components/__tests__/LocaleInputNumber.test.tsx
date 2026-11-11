/** Guards that antd numeric fields accept Devanagari input (D6, revised). */
import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { InputNumber } from 'antd';
import { useState } from 'react';
import { LocaleInputNumber } from '../LocaleInputNumber';

function Probe({ Comp }: { Comp: typeof InputNumber | typeof LocaleInputNumber }) {
  const [v, setV] = useState<number | null>(null);
  return (
    <>
      <Comp value={v as never} onChange={setV as never} />
      <span data-testid="out">{v === null || v === undefined ? 'EMPTY' : String(v)}</span>
    </>
  );
}

const type = (value: string) => {
  const input = screen.getByRole('spinbutton');
  fireEvent.change(input, { target: { value } });
  fireEvent.blur(input);
  return screen.getByTestId('out').textContent;
};

describe('LocaleInputNumber', () => {
  it('documents why the wrapper exists: plain antd InputNumber drops Devanagari', () => {
    render(<Probe Comp={InputNumber} />);
    expect(type('७०')).toBe('EMPTY');
  });

  it('accepts Devanagari digits', () => {
    render(<Probe Comp={LocaleInputNumber} />);
    expect(type('७०')).toBe('70');
  });

  it('still accepts ASCII, so English entry is unaffected', () => {
    render(<Probe Comp={LocaleInputNumber} />);
    expect(type('70')).toBe('70');
  });

  it('accepts a value typed in both scripts', () => {
    render(<Probe Comp={LocaleInputNumber} />);
    expect(type('७0')).toBe('70');
  });
});
