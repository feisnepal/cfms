import { describe, it, expect } from 'vitest';
import {
  buildDesignRequest, designProblem, emptyPick, errorKey, needsGrowthClass, partKey, plotColour, plotsPerSpecies, progressPct, sortFindings, trustOf, warningKey, yieldOf,
} from '../ntfp';
import type { NtfpSpecies } from '../../services/api';

const sp = (key: string, growth: string | null): NtfpSpecies => ({ species_key: key, growth_class: growth } as NtfpSpecies);

describe('buildDesignRequest', () => {
  it('leaves blank numbers out so the server applies the guideline defaults', () => {
    const req = buildDesignRequest({ a: emptyPick(), b: { plot_sqm: 25, intensity_pct: 0.5, growth_class: 'shrub' } }, 'square', null, 3);
    expect(req.species).toEqual([{ species_key: 'a' }, { species_key: 'b', plot_sqm: 25, intensity_pct: 0.5, growth_class: 'shrub' }]);
    expect(req).toMatchObject({ plot_shape: 'square', min_plots: 3 });
    expect('seed' in req).toBe(false);
  });
  it('sends a seed only when it is a positive number', () => {
    expect(buildDesignRequest({ a: emptyPick() }, 'circular', 42, 5).seed).toBe(42);
    expect('seed' in buildDesignRequest({ a: emptyPick() }, 'circular', 0, 5)).toBe(false);
  });
  it('drops zero or negative overrides instead of sending them', () => {
    const req = buildDesignRequest({ a: { plot_sqm: 0, intensity_pct: -1, growth_class: null } }, 'square', null, 3);
    expect(req.species).toEqual([{ species_key: 'a' }]);
  });
});

describe('designProblem', () => {
  const species = [sp('card', 'herb'), sp('nocard', null)];
  it('asks for at least one species', () => expect(designProblem(species, {})).toBe('ntfp.design.problemNoSpecies'));
  it('asks for the growth class of a species with no method card', () => {
    expect(designProblem(species, { nocard: emptyPick() })).toBe('ntfp.design.problemGrowthClass');
    expect(designProblem(species, { nocard: { ...emptyPick(), growth_class: 'tree' } })).toBeNull();
  });
  it('refuses an intensity above 100 %', () => {
    expect(designProblem(species, { card: { ...emptyPick(), intensity_pct: 150 } })).toBe('ntfp.design.problemIntensity');
  });
  it('accepts a species with a card and no overrides', () => expect(designProblem(species, { card: emptyPick() })).toBeNull());
  it('needsGrowthClass looks at the species and the pick', () => {
    expect(needsGrowthClass(sp('x', null), undefined)).toBe(true);
    expect(needsGrowthClass(sp('x', 'herb'), undefined)).toBe(false);
  });
});

describe('findings, warnings and errors', () => {
  it('lists errors before warnings, each in row order', () => {
    const f = (severity: 'error' | 'warning', row: number) => ({ severity, sheet: 'Plots', row, column: null, code: 'x', message: 'm' });
    expect(sortFindings([f('warning', 2), f('error', 9), f('error', 3)]).map((x) => `${x.severity}${x.row}`)).toEqual(['error3', 'error9', 'warning2']);
  });
  it('maps every warning code to a key and never shows a raw code', () => {
    expect(warningKey('few_plots')).toBe('ntfp.warn.fewPlots');
    expect(warningKey('something_new')).toBe('ntfp.warn.other');
  });
  it('maps the server error codes the page can meet', () => {
    expect(errorKey('has_records')).toBe('ntfp.error.hasRecords');
    expect(errorKey('nope')).toBeNull();
    expect(errorKey(undefined)).toBeNull();
  });
});

describe('part keys', () => {
  it('maps every Schedule-7 group to a plain key segment and falls back to whole plant', () => {
    expect(['क', 'ख', 'ग', 'घ', 'ङ', 'च', 'छ'].map(partKey)).toEqual(['root', 'bark', 'leaf', 'flower', 'fruit', 'whole', 'resin']);
    expect(partKey(null)).toBe('whole');
  });
});

describe('results helpers', () => {
  it('rates trust from the precision', () => {
    expect([trustOf(10), trustOf(35), trustOf(80), trustOf(null)]).toEqual(['good', 'fair', 'poor', 'unknown']);
  });
  it('reports progress as a capped whole percentage', () => {
    expect(progressPct(3, 8)).toBe(38);
    expect(progressPct(9, 8)).toBe(100);
    expect(progressPct(0, 0)).toBe(0);
  });
  it('prefers the dry yield and says which it is', () => {
    expect(yieldOf({ yield_dry_kg_ha: 10, yield_fresh_kg_ha: 30 })).toEqual({ value: 10, basis: 'dry' });
    expect(yieldOf({ yield_dry_kg_ha: null, yield_fresh_kg_ha: 30 })).toEqual({ value: 30, basis: 'fresh' });
  });
  it('counts plot positions per species and shades by how many species they carry', () => {
    expect(plotsPerSpecies([{ species_keys: ['a', 'b'] }, { species_keys: ['a'] }])).toEqual({ a: 2, b: 1 });
    expect(new Set([plotColour(1), plotColour(2), plotColour(3)]).size).toBe(3);
  });
});
