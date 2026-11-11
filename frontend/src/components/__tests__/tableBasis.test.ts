/**
 * The basis convention, enforced.
 *
 * A reader cannot tell a rate from a quantity if the header does not say so. The
 * old convention was the *presence or absence* of "/ha", and absence is not a
 * label: a bare `Count` gives nothing to separate "this is a total" from "the
 * suffix was forgotten". The codebase was inconsistent too - `Trees/hectare` in
 * one table, `Count/ha` in another, `Trees/ha` in a third - so the reader had to
 * learn three spellings of one idea.
 *
 * The rule is now positive on BOTH sides: a rate says per hectare, a quantity
 * says Total. This test is the enforcement. It reads the source rather than the
 * DOM because a rendered header cannot be told apart from a group label.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import en from '../../i18n/locales/en.json';
import ne from '../../i18n/locales/ne.json';

const SRC = resolve(
  process.cwd(),
  'src/components/fieldInventory/FieldInventoryResultsTables.tsx',
);
const source = readFileSync(SRC, 'utf8');

const ti = en.totalInventory as Record<string, string>;
const tiNe = ne.totalInventory as Record<string, string>;

/** Column keys that are names, categories or money, not per-hectare quantities. */
const NOT_A_QUANTITY = new Set([
  'areaHa', 'dbhClass', 'species', 'localName', 'scientificName',
  'ratePerM3', 'ratePerTco2', 'value', 'co2Unit', 'carbon',
]);

/**
 * Columns whose basis is stated by a SPANNING BAND above them rather than in the
 * column itself. Exempt individually, with the band asserted below, because a
 * blanket "skip anything under a band" rule cannot be checked from source and
 * would silently re-admit the bare columns this test exists to catch.
 *
 * Adding "Total" to these as well would read as "Total Pole" under a band that
 * already says "Total Trees" - redundant, and the band is the better label.
 */
const BANDED = new Set([
  // Compartment table: sub-columns of `Total Trees` / `Total Volume (m³)` /
  // `Total Carbon` (three colSpan bands in the header).
  'pole', 'tree', 'stock', 'maiPerYear', 'aahPerYear', 'biomassT',
  // Economics table: `Timber` / `Firewood` are themselves colSpan band labels
  // over a table that is entirely absolute and badged as such.
  'timber', 'firewood',
]);

/** Money, summed, not spread over an area. */
const MONEY = new Set(['sumRst', 'sumRs']);

/** Says a rate. */
const saysRate = (s: string) => /\/ha\b|per hectare|प्रति हेक्टर/i.test(s);
/** Says a quantity. */
const saysQuantity = (s: string) => /\btotal\b|जम्मा|कुल/i.test(s);

const headerKeys = (): string[] =>
  [...source.matchAll(/<th[^>]*>\s*\{t\('totalInventory\.([a-zA-Z0-9]+)'\)/g)].map(
    (m) => m[1],
  );

describe('every numeric column header states its basis', () => {
  const keys = [...new Set(headerKeys())];
  it('finds the headers to check', () => {
    expect(keys.length).toBeGreaterThan(20);
  });

  it('no numeric header is silent about rate vs quantity', () => {
    const offenders: string[] = [];
    for (const k of keys) {
      if (NOT_A_QUANTITY.has(k) || BANDED.has(k) || MONEY.has(k)) continue;
      const enText = ti[k] ?? '';
      if (saysRate(enText) || saysQuantity(enText)) continue;
      offenders.push(`${k} = "${enText}"`);
    }
    // A bare `Count` / `Timber (m³)` used to pass here, and it is exactly the
    // column a reader cannot classify.
    expect(offenders).toEqual([]);
  });

  it('every exemption rests on a band that still exists', () => {
    // Otherwise BANDED grows into a silent hole: a band could be deleted, the
    // sub-columns left saying nothing, and the rule above would still pass.
    for (const band of ['totalTrees', 'totalVolumeM3', 'totalCarbon']) {
      expect(source).toContain(`<th colSpan={`)
      expect(source).toMatch(new RegExp(`<th colSpan=\\{\\d+\\}[^>]*>\\s*\\{t\\('totalInventory\\.${band}'`));
    }
    // The economics bands.
    for (const band of ['timber', 'firewood']) {
      expect(source).toMatch(
        new RegExp(`<th colSpan=\\{\\d+\\}[^>]*>\\s*\\{t\\('totalInventory\\.${band}'`),
      );
    }
  });

  it('every header key resolves in BOTH bundles', () => {
    const missing = keys.filter((k) => !ti[k] || !tiNe[k]);
    expect(missing).toEqual([]);
  });

  it('the Nepali of a rate header says per hectare, not just "/ha"', () => {
    // The rate words must survive translation, or a Nepali reader gets the same
    // ambiguity the English one had.
    for (const k of keys) {
      if (NOT_A_QUANTITY.has(k)) continue;
      if (!saysRate(ti[k])) continue;
      expect(`${k}=${tiNe[k]}`).toMatch(/हे\.|हेक्टर/);
    }
  });

  it('the Nepali of a quantity header says जम्मा or कुल', () => {
    for (const k of keys) {
      if (NOT_A_QUANTITY.has(k)) continue;
      if (!saysQuantity(ti[k])) continue;
      expect(`${k}=${tiNe[k]}`).toMatch(/जम्मा|कुल/);
    }
  });
});

describe('every table carries a basis badge', () => {
  const TITLES = [
    'unitWiseStock', 'bySpeciesTitle', 'speciesDbhTitle', 'wholeForestSpeciesDbh',
    'byDbhTitle', 'byDbhPerHaTitle', 'maiBySpecies', 'maiByDbh',
    'aahBySpecies', 'aahByDbh', 'economicValuation', 'sustainabilityIndex',
  ];

  it.each(TITLES)('%s is badged', (titleKey) => {
    const idx = source.indexOf(`t('totalInventory.${titleKey}'`);
    expect(idx).toBeGreaterThan(-1);
    const window = source.slice(idx, idx + 900);
    expect(window).toMatch(/<BasisBadge basis="(perha|absolute|mixed)"/);
  });

  it('the badge vocabulary is translated in both bundles', () => {
    for (const k of ['basisPerHectare', 'basisAbsolute', 'basisMixed', 'basisRuleNote']) {
      expect(ti[k]).toBeTruthy();
      expect(tiNe[k]).toBeTruthy();
      expect(tiNe[k]).not.toBe(ti[k]);
    }
  });

  it('the legend states the rule once, above the numbers', () => {
    expect(source).toContain('<BasisLegend />');
    const legendAt = source.indexOf('<BasisLegend />');
    const firstBadge = source.indexOf('<BasisBadge basis=', legendAt + 1);
    expect(legendAt).toBeGreaterThan(-1);
    expect(firstBadge).toBeGreaterThan(legendAt);
  });
});
