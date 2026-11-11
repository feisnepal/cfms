import { describe, it, expect } from 'vitest';
import { subUnitNamingPattern, subUnitSerial } from '../namingStrategies';

describe('sub-unit naming pattern (FS-4a.2)', () => {
  it('the compartment pattern matches the live backend default', () => {
    expect(subUnitNamingPattern(true)).toBe('{parent_name}-SC{index}');
  });

  it('the block pattern is the new sub-block form', () => {
    expect(subUnitNamingPattern(false)).toBe('{parent_name}-SB{index}');
  });

  it('renders a serial without the caller knowing the template syntax', () => {
    expect(subUnitSerial(false, 'B1', 1)).toBe('B1-SB1');
    expect(subUnitSerial(true, 'C1', 2)).toBe('C1-SC2');
  });
});
