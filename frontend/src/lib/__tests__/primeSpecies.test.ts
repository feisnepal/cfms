import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { OTHER_COLOR, PRIME_SPECIES, PRIME_SPECIES_RENDERER, primeSpeciesByCode } from '../primeSpecies';
import { rendererColorFor } from '../layerRenderers';

describe('PRIME_SPECIES (mirror of backend/app/core/prime_species.py)', () => {
  it('is identical to the backend list: same codes, names and colours', () => {
    const py = readFileSync(resolve(__dirname, '../../../../backend/app/core/prime_species.py'), 'utf-8');
    const backend = [...py.matchAll(/PrimeSpecies\((\d+), "([^"]+)", (?:True|False), "(#[0-9A-Fa-f]{6})"\)/g)].map(
      (m) => ({ code: Number(m[1]), name: m[2], color: m[3].toUpperCase() }),
    );
    expect(backend).toHaveLength(21);
    expect(PRIME_SPECIES.map((s) => ({ ...s, color: s.color.toUpperCase() }))).toEqual(backend);
    const otherPy = /OTHER_COLOR = "(#[0-9A-Fa-f]{6})"/.exec(py)![1];
    expect(OTHER_COLOR.toUpperCase()).toBe(otherPy.toUpperCase());
  });

  it('has 21 unique colours, none equal to the default colour', () => {
    const colours = PRIME_SPECIES.map((s) => s.color.toUpperCase());
    expect(new Set(colours).size).toBe(21);
    expect(colours).not.toContain(OTHER_COLOR.toUpperCase());
  });

  it('the renderer gives each prime code its own colour and everything else the default', () => {
    for (const s of PRIME_SPECIES) {
      expect(rendererColorFor(PRIME_SPECIES_RENDERER, s.code)).toBe(s.color);
    }
    expect(rendererColorFor(PRIME_SPECIES_RENDERER, null)).toBe(OTHER_COLOR);
    expect(rendererColorFor(PRIME_SPECIES_RENDERER, 99)).toBe(OTHER_COLOR);
  });

  it('looks a species up by code, tolerating the string form the legend uses', () => {
    expect(primeSpeciesByCode(18)?.name).toBe('Shorea robusta');
    expect(primeSpeciesByCode('18')?.name).toBe('Shorea robusta');
    expect(primeSpeciesByCode('other')).toBeUndefined();
    expect(primeSpeciesByCode(null)).toBeUndefined();
  });
});
