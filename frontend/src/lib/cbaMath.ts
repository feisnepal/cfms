/**
 * cbaMath — a tiny client-side NPV / IRR / B-C for the sensitivity preview
 * (CBA_MODULE_PLAN.md P6). The authoritative computation is the backend engine;
 * this only drives the live slider preview and mirrors its conventions:
 * rates are percentages, cash-flow lists are 1-indexed by position, and IRR is
 * `null` when the series has no sign change.
 */

export const npv = (net: number[], ratePct: number): number => {
  const r = ratePct / 100;
  return net.reduce((s, cf, i) => s + cf / (1 + r) ** (i + 1), 0);
};

export const bcRatio = (
  costs: number[],
  benefits: number[],
  ratePct: number,
): number | null => {
  const r = ratePct / 100;
  const pv = (a: number[]) => a.reduce((s, v, i) => s + v / (1 + r) ** (i + 1), 0);
  const c = pv(costs);
  return c === 0 ? null : pv(benefits) / c;
};

/** IRR as a fraction via bisection; `null` when undefined (no sign change or no
 * bracket). Matches the backend engine's "return None" behaviour. */
export const irr = (net: number[]): number | null => {
  if (net.every((v) => v >= 0) || net.every((v) => v <= 0)) return null;
  const f = (rate: number) => net.reduce((s, cf, i) => s + cf / (1 + rate) ** (i + 1), 0);
  let lo = -0.9;
  let hi = 10;
  let flo = f(lo);
  const fhi = f(hi);
  if (flo * fhi > 0) return null;
  for (let k = 0; k < 200; k += 1) {
    const mid = (lo + hi) / 2;
    const fm = f(mid);
    if (Math.abs(fm) < 1e-6 || hi - lo < 1e-8) return mid;
    if (flo * fm < 0) {
      hi = mid;
    } else {
      lo = mid;
      flo = fm;
    }
  }
  return (lo + hi) / 2;
};
