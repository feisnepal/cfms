import { describe, it, expect } from 'vitest';
import { COLOR_RAMPS, sampleRamp, equalBreaks, quantileBreaks } from '../colorRamps';

describe('sampleRamp (WORKSPACE_LAYER_STYLING_PLAN.md P4.2)', () => {
  it('returns n hex colours, endpoints matching the ramp stops', () => {
    const out = sampleRamp('blues', 5);
    expect(out).toHaveLength(5);
    expect(out.every((c) => /^#[0-9a-f]{6}$/i.test(c))).toBe(true);
    expect(out[0].toLowerCase()).toBe(COLOR_RAMPS.blues[0].toLowerCase());
    expect(out[4].toLowerCase()).toBe(COLOR_RAMPS.blues[4].toLowerCase());
  });

  it('interpolates between stops for a count off the ramp length', () => {
    const out = sampleRamp('greys', 3);
    expect(out).toHaveLength(3);
    // middle sample sits between the lightest and darkest grey
    expect(out[1]).not.toBe(out[0]);
    expect(out[1]).not.toBe(out[2]);
  });

  it('unknown ramp falls back to blues; n<=0 → []', () => {
    expect(sampleRamp('nope', 2)[0].toLowerCase()).toBe(COLOR_RAMPS.blues[0].toLowerCase());
    expect(sampleRamp('blues', 0)).toEqual([]);
  });
});

describe('break computation', () => {
  const vals = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];

  it('equalBreaks splits [min,max] into classes-1 cut points', () => {
    expect(equalBreaks(vals, 4)).toEqual([3.25, 5.5, 7.75]);
  });

  it('quantileBreaks puts ~equal counts per class', () => {
    const b = quantileBreaks(vals, 4);
    expect(b).toHaveLength(3);
    // ascending
    expect(b[0]).toBeLessThan(b[1]);
    expect(b[1]).toBeLessThan(b[2]);
    // for 10 evenly-spaced values the quartile cuts land near 3.25 / 5.5 / 7.75
    expect(b[1]).toBeCloseTo(5.5, 1);
  });

  it('degenerate inputs yield []', () => {
    expect(equalBreaks([], 4)).toEqual([]);
    expect(quantileBreaks([5], 1)).toEqual([]);
  });
});
