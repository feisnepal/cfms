import { describe, it, expect } from 'vitest';
import { dotColour, DOT_RAMP } from '../map/HouseholdDotsLayer';

describe('household dot colours', () => {
  const ramp = DOT_RAMP();
  it('runs from the palest to the darkest of the ramp across the score range', () => {
    expect(dotColour(0.2, 0.2, 0.4, ramp)).toBe(ramp[0]);
    expect(dotColour(0.4, 0.2, 0.4, ramp)).toBe(ramp[ramp.length - 1]);
    expect(dotColour(0.3, 0.2, 0.4, ramp)).toBe(ramp[Math.round((ramp.length - 1) / 2)]);
  });
  it('a single score (no range) is drawn in the darkest colour, never NaN', () => {
    expect(dotColour(0.3, 0.3, 0.3, ramp)).toBe(ramp[ramp.length - 1]);
  });
  it('a score outside the range is clamped', () => {
    expect(dotColour(9, 0.2, 0.4, ramp)).toBe(ramp[ramp.length - 1]);
    expect(dotColour(-1, 0.2, 0.4, ramp)).toBe(ramp[0]);
  });
});
