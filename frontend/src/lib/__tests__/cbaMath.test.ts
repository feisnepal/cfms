import { describe, it, expect } from 'vitest';
import { npv, irr, bcRatio } from '../cbaMath';

describe('cbaMath', () => {
  it('npv discounts each year by (1+r)^t', () => {
    // one year, net 110 at 10% -> 100
    expect(npv([110], 10)).toBeCloseTo(100, 6);
    expect(npv([0, 0, 0], 10)).toBe(0);
  });

  it('irr brackets zero NPV for a series with a sign change', () => {
    const net = [-100000, 30000, 75000, 110000, 145000];
    const r = irr(net);
    expect(r).not.toBeNull();
    expect(npv(net, (r as number) * 100)).toBeCloseTo(0, 0);
  });

  it('irr is null when every year has the same sign', () => {
    expect(irr([300, 300, 300])).toBeNull(); // all-positive plan
    expect(irr([-5, -5, -5])).toBeNull();
  });

  it('bcRatio is PV(benefits) / PV(costs), null when PV(costs) is 0', () => {
    expect(bcRatio([100, 100], [200, 200], 10)).toBeCloseTo(2, 6);
    expect(bcRatio([0, 0], [10, 10], 10)).toBeNull();
  });
});
