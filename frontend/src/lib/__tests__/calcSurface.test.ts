/**
 * calcSurface — parsing, the legacy compatibility layer, and fail-closed
 * resolution. WORKSPACE_FLOW_NAV_PLAN §6.
 *
 * The compatibility contract is the point of this file: all 21 pre-P2b surface
 * ids still resolve, in both the `?surface=` and the legacy `?tab=&context=`
 * form, and anything unrecognised lands on the Map instead of a blank panel.
 */
import { describe, it, expect } from 'vitest';
import {
  ALL_LEGACY_SURFACE_IDS,
  FALLBACK_SURFACE,
  LEGACY_PASSTHROUGH_ALLOWLIST,
  LEGACY_SURFACE_ALIASES,
  allSurfaceIds,
  isKnownSurfaceId,
  parseSurfaceId,
  resolveSurface,
  surfaceFromLegacyParams,
  toSurfaceId,
} from '../calcSurface';
import { TABS } from '../../pages/calculationTabConfig';
import { GROUP_CONTEXTS } from '../../components/calculation/calcContexts';

const LEGACY_GROUPS = ['forest-data', 'sampling-model', 'data-maps', 'reports-outputs'];

describe('calcSurface — building and parsing', () => {
  it('joins group and context with a slash', () => {
    expect(toSurfaceId('analysis', 'hazarderosion')).toBe('analysis/hazarderosion');
  });

  it('round-trips every registry entry', () => {
    for (const tab of TABS) {
      for (const c of GROUP_CONTEXTS[tab]) {
        expect(parseSurfaceId(toSurfaceId(tab, c.id))).toEqual({ tab, ctx: c.id });
      }
    }
  });

  it('rejects malformed ids', () => {
    expect(parseSurfaceId('analysis')).toBeNull(); // no slash
    expect(parseSurfaceId('analysis/')).toBeNull(); // empty context
    expect(parseSurfaceId('analysis/a/extra')).toBeNull(); // two segments
    expect(parseSurfaceId(null)).toBeNull();
    expect(parseSurfaceId('')).toBeNull();
  });

  it('rejects an unknown group', () => {
    expect(parseSurfaceId('nope/analysis')).toBeNull();
  });

  it('does not validate the context — that is resolveSurface\'s job', () => {
    // Parseable and resolvable are different questions. parseSurfaceId answering
    // "is this real?" is what made blank panels possible.
    expect(parseSurfaceId('analysis/does_not_exist')).toEqual({
      tab: 'analysis',
      ctx: 'does_not_exist',
    });
    expect(isKnownSurfaceId('analysis/does_not_exist')).toBe(false);
  });
});

describe('calcSurface — the legacy compatibility contract', () => {
  it('covers all 21 pre-P2b surfaces', () => {
    expect(ALL_LEGACY_SURFACE_IDS).toHaveLength(21);
    for (const g of LEGACY_GROUPS) {
      expect(Object.keys(LEGACY_SURFACE_ALIASES).filter((k) => k.startsWith(`${g}/`)).length)
        .toBeGreaterThan(0);
    }
  });

  it('every legacy id resolves to a surface that exists today', () => {
    const nowGroups = TABS.flatMap((t) => GROUP_CONTEXTS[t].map((c) => `${t}/${c.id}`));
    for (const [legacy, target] of Object.entries(LEGACY_SURFACE_ALIASES)) {
      expect(nowGroups, `${legacy} -> ${target}`).toContain(target);
    }
  });

  it('every legacy id resolves to a real current surface', () => {
    // Not "resolves to something other than the Map" — `forest-data/unified`
    // legitimately resolves TO the Map, because the Map is its replacement.
    // What must hold is that the result is a surface that exists, and that
    // resolving it did not go through the fail-closed path.
    for (const legacy of ALL_LEGACY_SURFACE_IDS) {
      const seen: string[] = [];
      const r = resolveSurface(legacy, (bad) => seen.push(bad));
      expect(isKnownSurfaceId(toSurfaceId(r.tab, r.ctx)), `${legacy} -> ${r.tab}/${r.ctx}`).toBe(
        true,
      );
      expect(seen, `${legacy} fell through to the fallback`).toEqual([]);
    }
  });

  it('every legacy id resolves in the ?tab=&context= form too', () => {
    // §6.1 — one resolver, two URL shapes. Roughly half the e2e specs use the
    // legacy pair, so a surface that only works in one form is a broken bookmark.
    for (const legacy of ALL_LEGACY_SURFACE_IDS) {
      const slash = legacy.indexOf('/');
      const composed = surfaceFromLegacyParams(legacy.slice(0, slash), legacy.slice(slash + 1));
      expect(composed).toBe(legacy);
      const r = resolveSurface(composed);
      expect(r, `?tab=&context= ${legacy}`).toEqual(resolveSurface(legacy));
    }
  });

  it('the five removed surfaces point at whatever now does the work', () => {
    // (D3) Map owns all geometry work. (D4) total inventory IS the inventory
    // results. (D6) the reports metadata form is forest metadata. (D9) yearly
    // activities merged into the plan.
    expect(resolveSurface('forest-data/subareas')).toEqual({ tab: 'base', ctx: 'unified' });
    expect(resolveSurface('forest-data/compartments')).toEqual({ tab: 'base', ctx: 'unified' });
    expect(resolveSurface('data-maps/maps')).toEqual({ tab: 'base', ctx: 'unified' });
    expect(resolveSurface('data-maps/totalinventory')).toEqual({
      tab: 'field',
      ctx: 'fieldinventory',
    });
    expect(resolveSurface('reports-outputs/reports')).toEqual({
      tab: 'field',
      ctx: 'fieldinventory',
    });
    expect(resolveSurface('reports-outputs/yearlyactivities')).toEqual({
      tab: 'plan',
      ctx: 'yearly',
    });
  });

  it('an alias never points at itself', () => {
    for (const [legacy, target] of Object.entries(LEGACY_SURFACE_ALIASES)) {
      expect(target, legacy).not.toBe(legacy);
    }
  });
});

describe('calcSurface — legacy passthrough allowlist', () => {
  it('keeps the four legacy context ids addressable', () => {
    // boundary/blocks/subcompartments render the Map workspace on a different
    // view; block_naming is asserted as a preserved context by
    // tabbed-detail.spec.ts. All four resolve into `base`, under both a current
    // group and the legacy `forest-data` group.
    for (const [ctx, group] of Object.entries(LEGACY_PASSTHROUGH_ALLOWLIST)) {
      expect(resolveSurface(`base/${ctx}`), `base/${ctx}`).toEqual({ tab: group, ctx });
      expect(resolveSurface(`forest-data/${ctx}`), `forest-data/${ctx}`).toEqual({
        tab: group,
        ctx,
      });
    }
  });

  it('every allowlisted id is NOT in the registry, or the entry is pointless', () => {
    const registryIds = new Set(TABS.flatMap((t) => GROUP_CONTEXTS[t].map((c) => c.id)));
    for (const ctx of Object.keys(LEGACY_PASSTHROUGH_ALLOWLIST)) {
      expect(registryIds.has(ctx), `${ctx} is in the registry; drop the passthrough entry`).toBe(
        false,
      );
    }
  });
});

describe('calcSurface — fail-closed resolution', () => {
  it('falls back to the Map for an unknown context in a known group', () => {
    expect(resolveSurface('analysis/does_not_exist')).toEqual(FALLBACK_SURFACE);
  });

  it('falls back for an unknown group, a typo, and nothing at all', () => {
    expect(resolveSurface('nope/analysis')).toEqual(FALLBACK_SURFACE);
    expect(resolveSurface('analysi')).toEqual(FALLBACK_SURFACE);
    expect(resolveSurface(null)).toEqual(FALLBACK_SURFACE);
    expect(resolveSurface(undefined)).toEqual(FALLBACK_SURFACE);
    expect(resolveSurface('')).toEqual(FALLBACK_SURFACE);
  });

  it('reports what it absorbed, so a wrong link is visible not swallowed', () => {
    const seen: string[] = [];
    resolveSurface('analysis/does_not_exist', (bad) => seen.push(bad));
    expect(seen).toEqual(['analysis/does_not_exist']);
  });

  it('does not report a fallback for a surface that resolved', () => {
    const seen: string[] = [];
    resolveSurface('analysis/cba', (bad) => seen.push(bad));
    resolveSurface('forest-data/unified', (bad) => seen.push(bad));
    expect(seen).toEqual([]);
  });

  it('the fallback is itself a real surface', () => {
    // A fallback to a blank panel would reintroduce the original bug.
    expect(isKnownSurfaceId(toSurfaceId(FALLBACK_SURFACE.tab, FALLBACK_SURFACE.ctx))).toBe(true);
  });
});

describe('calcSurface — exhaustive listings', () => {
  it('allSurfaceIds lists one id per registry entry, all unique', () => {
    const ids = allSurfaceIds();
    const total = TABS.reduce((n, t) => n + GROUP_CONTEXTS[t].length, 0);
    expect(ids).toHaveLength(total);
    expect(new Set(ids).size).toBe(total);
    for (const id of ids) expect(parseSurfaceId(id)).not.toBeNull();
  });

  it('every current surface resolves to itself, with no fallback needed', () => {
    for (const id of allSurfaceIds()) {
      const seen: string[] = [];
      expect(resolveSurface(id, (b) => seen.push(b)), id).toEqual(parseSurfaceId(id));
      expect(seen, id).toEqual([]);
    }
  });
});
