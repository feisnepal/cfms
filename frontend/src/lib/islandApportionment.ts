/**
 * Apportion N equal-area compartments across the islands of a multi-part
 * (MultiPolygon) forest boundary — the client mirror of the backend
 * `app/services/island_apportionment.py::allocate_island_counts`.
 *
 * A compartment never spans two detached parcels, so each island gets a whole
 * number of pieces, at least one. `n_effective` is `max(n, islands)` — you
 * cannot have fewer compartments than parcels. Hamilton / largest-remainder
 * with a floor of one per island; see MULTI_ISLAND_DIVIDE_PLAN.md.
 *
 * Used by the multi-island mode of `EqualAreaDividePanel` to fill / refill the
 * per-island count table when the user changes N. The backend recomputes the
 * same allocation, so a submit without `island_counts` lands identically.
 */

/** An island whose average piece is below this fraction of the target is flagged. */
export const UNDERSIZED_REL = 0.5;

export interface IslandAllocation {
  /** pieces per island, same order as `areas`; sums to `nEffective` */
  counts: number[];
  /** `n`, raised to `areas.length` when `n` is smaller */
  nEffective: number;
  /** Σ area / nEffective — the ideal equal piece size */
  targetArea: number;
  /** indices of islands whose avg piece < UNDERSIZED_REL × targetArea */
  undersized: number[];
}

export function allocateIslandCounts(areas: number[], n: number): IslandAllocation {
  if (!areas.length) throw new Error('no islands to divide');
  if (areas.some((a) => !(a > 0))) throw new Error('island areas must be positive');
  n = Math.trunc(n);
  if (n < 1) throw new Error('n must be at least 1');

  const k = areas.length;
  const nEff = Math.max(n, k);
  const total = areas.reduce((s, a) => s + a, 0);
  const target = total / nEff;
  const quota = areas.map((a) => a / target); // Σ quota === nEff

  const counts = quota.map((q) => Math.max(1, Math.floor(q)));
  const diff = nEff - counts.reduce((s, c) => s + c, 0);

  if (diff > 0) {
    const order = [...counts.keys()].sort((i, j) => {
      const fi = quota[i] - Math.floor(quota[i]);
      const fj = quota[j] - Math.floor(quota[j]);
      if (fi !== fj) return fj - fi;
      if (areas[i] !== areas[j]) return areas[j] - areas[i];
      return i - j; // lower index first
    });
    for (let t = 0; t < diff; t++) counts[order[t]] += 1;
  } else if (diff < 0) {
    let take = -diff;
    while (take > 0) {
      const cands = [...counts.keys()].filter((i) => counts[i] > 1);
      if (!cands.length) break;
      cands.sort((i, j) => {
        const oi = counts[i] - quota[i];
        const oj = counts[j] - quota[j];
        if (oi !== oj) return oj - oi;
        if (counts[i] !== counts[j]) return counts[j] - counts[i];
        return i - j;
      });
      counts[cands[0]] -= 1;
      take -= 1;
    }
  }

  const undersized = [...counts.keys()].filter(
    (i) => areas[i] / counts[i] < UNDERSIZED_REL * target,
  );

  return { counts, nEffective: nEff, targetArea: target, undersized };
}
