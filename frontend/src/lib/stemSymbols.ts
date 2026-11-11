/**
 * Stem Mapping symbol rules: SIZE from the DBH class, SHAPE from the tree group.
 *
 * Colour (species) is decided by the renderer; this file owns the two things a
 * renderer cannot express. Sizes grow with the map zoom because a Leaflet marker's
 * radius is in screen pixels: a radius that reads at z18 is a speck at z21.
 */
import { dbhBandIndex } from './dbhClassSymbols';

export type TreeGroup = 'felling' | 'mother' | 'seedling' | 'other';
export type StemShape = 'circle' | 'star';

const BASE_RADIUS = 1.6; // px at z18, smallest DBH band
const BAND_STEP = 0.5;   // 8 bands -> 1.6 .. 5.1 px at z18
const MOTHER_SCALE = 1.5;
const MOTHER_MIN = 3.5;  // a star smaller than this stops reading as a star
const SEEDLING_RADIUS = 1.6;
const MAX_RADIUS = 12;

export function treeGroupOf(value: unknown): TreeGroup {
  return value === 'mother' || value === 'felling' || value === 'seedling' ? value : 'other';
}

export function stemShape(group: TreeGroup): StemShape {
  return group === 'mother' ? 'star' : 'circle';
}

/** 1.0 at z18, doubling every two zooms, never smaller than 0.9 or bigger than 2.6. */
export function stemZoomFactor(zoom: number): number {
  const f = Math.pow(2, (zoom - 18) / 2);
  return Math.min(2.6, Math.max(0.9, f));
}

/** Marker radius in px: DBH class x zoom, with the group's own floor. */
export function stemRadius(dbhCm: number | null | undefined, group: TreeGroup, zoom: number): number {
  const zf = stemZoomFactor(zoom);
  if (group === 'seedling') return Math.min(MAX_RADIUS, SEEDLING_RADIUS * zf);
  const band = dbhBandIndex(dbhCm);
  const base = BASE_RADIUS + (band >= 0 ? band : 2) * BAND_STEP; // unrecognized reads mid-size
  const r = group === 'mother' ? Math.max(base * MOTHER_SCALE, MOTHER_MIN) : base;
  return Math.min(MAX_RADIUS, r * zf);
}
