/**
 * Prime species for Stem Mapping -- the 21 species with a permanent colour.
 *
 * Mirror of `backend/app/core/prime_species.py` (the SSOT); the parity test in
 * `__tests__/primeSpecies.test.ts` reads the Python file and fails if the two drift.
 * `code` is `tree_species_coefficients.species_code`. The server resolves which
 * prime species a tree is (exact name, aliases, or the genus rule for the four
 * "spp" groups) and sends `prime_species_code`, so the matching rules live in one
 * place; this file only maps a code to its colour and name.
 *
 * Colours are fixed per species (never by frequency) so a species reads the same in
 * every forest. Every other species gets the single OTHER_COLOR.
 */
import type { CategorizedRenderer } from './layerRenderers';

export const OTHER_COLOR = '#9E9E9E';

/** Legend / isolate key for "every species that is not one of the 21". */
export const OTHER_KEY = 'other';

export interface PrimeSpecies {
  code: number;
  name: string;
  color: string;
}

export const PRIME_SPECIES: PrimeSpecies[] = [
  { code: 1, name: 'Abies spp', color: '#1BE0B5' },
  { code: 2, name: 'Acacia catechu', color: '#D492EE' },
  { code: 3, name: 'Adina cardifolia', color: '#0CE46A' },
  { code: 4, name: 'Albizia spp', color: '#E86489' },
  { code: 5, name: 'Alnus nepalensis', color: '#FBBA62' },
  { code: 6, name: 'Anogeissus latifolia', color: '#924C02' },
  { code: 7, name: 'Bombax ceiba', color: '#1B5CB6' },
  { code: 8, name: 'Cedrela toona', color: '#7D7B07' },
  { code: 9, name: 'Dalbergia sissoo', color: '#755FF2' },
  { code: 10, name: 'Syzygium cumini', color: '#99D777' },
  { code: 11, name: 'Hymenodictyon excelsum', color: '#FF8B6B' },
  { code: 12, name: 'Lagerstroemia parviflora', color: '#9D357F' },
  { code: 13, name: 'Michelia champaca', color: '#BD0A34' },
  { code: 14, name: 'Pinus roxburghii', color: '#A6D71B' },
  { code: 15, name: 'Pinus wallichiana', color: '#FD3EC1' },
  { code: 16, name: 'Quercus spp', color: '#D7C939' },
  { code: 17, name: 'Schima wallichii', color: '#DC3C07' },
  { code: 18, name: 'Shorea robusta', color: '#A608AB' },
  { code: 19, name: 'Terminalia alata', color: '#0D6E20' },
  { code: 20, name: 'Trewia nudiflora', color: '#21A707' },
  { code: 21, name: 'Tsuga spp', color: '#D07D07' },
];

/** Field the server sends on every individual tree (null = not a prime species). */
export const PRIME_SPECIES_FIELD = 'prime_species_code';

const BY_CODE = new Map(PRIME_SPECIES.map((s) => [s.code, s]));

export function primeSpeciesByCode(code: unknown): PrimeSpecies | undefined {
  const n = typeof code === 'number' ? code : Number(code);
  return Number.isFinite(n) ? BY_CODE.get(n) : undefined;
}

/**
 * Stem Mapping's default renderer: colour by prime species, everything else grey.
 * An ordinary categorized renderer, so the Style Layer dialog, the legend panel and
 * exports all handle it without special cases.
 */
export const PRIME_SPECIES_RENDERER: CategorizedRenderer = {
  mode: 'categorized',
  field: PRIME_SPECIES_FIELD,
  classes: PRIME_SPECIES.map((s) => ({ value: String(s.code), color: s.color, label: s.name })),
  otherColor: OTHER_COLOR,
};
