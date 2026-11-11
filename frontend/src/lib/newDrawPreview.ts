import {
  area as turfArea,
  intersect as turfIntersect,
  polygon as turfPolygon,
} from '@turf/turf';
import type { Feature, FeatureCollection, Polygon, MultiPolygon } from 'geojson';
import { SQM_PER_HA } from './splitPreview';

export interface NewDrawPreviewResult {
  /** The polygon exactly as drawn (ha). */
  drawnHa: number;
  /** Area of the drawn polygon that survives following the boundary clip (ha). */
  clippedHa: number;
  /** Area of the drawn polygon outside the boundary, removed by the clip (ha). */
  outsideHa: number;
  /** true when the drawn polygon shares no area with the boundary. */
  outsideBoundary: boolean;
  /** true when the drawn polygon overlaps an existing feature at this level. */
  overlapsExisting: boolean;
  /** Human warnings — warn-only; the server remains authoritative on reject. */
  warnings: string[];
}

function closedRing(coords: Array<[number, number]>): Array<[number, number]> {
  const ring = coords.map((c) => [c[0], c[1]] as [number, number]);
  if (ring.length >= 3) ring.push(ring[0]);
  return ring;
}

function polygonFromCoords(coords: Array<[number, number]>): Feature<Polygon> | null {
  if (coords.length < 3) return null;
  return turfPolygon([closedRing(coords)]);
}

const EPSILON_M2 = 1e-9;

/**
 * turf 7.3.4 `intersect` only accepts a FeatureCollection and returns null for
 * disjoint inputs (passing raw features throws "Must specify at least 2
 * geometries"). Normalise to a safe feature-pair intersection that returns
 * null when the polygons share no area.
 */
function safeIntersect(a: Feature, b: Feature): Feature | null {
  try {
    const fc: FeatureCollection<Polygon | MultiPolygon> = {
      type: 'FeatureCollection',
      features: [a as Feature<Polygon | MultiPolygon>, b as Feature<Polygon | MultiPolygon>],
    };
    const res = turfIntersect(fc) as Feature | null;
    return res && turfArea(res) > EPSILON_M2 ? res : null;
  } catch {
    return null;
  }
}

/**
 * Live preview for the builtin "＋ New Block / New Compartment" draw tool.
 * Mirrors what the E.7 backend will do: clip the drawn polygon to the forest
 * boundary and reject draws that overlap an existing feature — but purely
 * client-side so the user sees the resulting area *while* drawing (scissor-like).
 */
export function computeNewDrawPreview(
  coords: Array<[number, number]>,
  boundaryFeatures: unknown[] | undefined,
  existingFeatures: unknown[] | undefined,
): NewDrawPreviewResult {
  const warnings: string[] = [];
  const drawn = polygonFromCoords(coords);
  if (!drawn) {
    return {
      drawnHa: 0, clippedHa: 0, outsideHa: 0,
      outsideBoundary: true, overlapsExisting: false,
      warnings: ['Draw at least 3 points on the block boundary.'],
    };
  }
  const drawnHa = turfArea(drawn) / SQM_PER_HA;

  const boundary = (boundaryFeatures ?? []).find(
    (f) => {
      const t = (f as any)?.geometry?.type;
      return t === 'Polygon' || t === 'MultiPolygon';
    },
  ) as Feature | undefined;

  let clippedHa = drawnHa;
  let outsideHa = 0;
  let outsideBoundary = false;
  if (!boundary) {
    warnings.push('Boundary geometry unavailable — showing drawn area only.');
    } else {
      const clipped = safeIntersect(drawn, boundary);
      if (!clipped || turfArea(clipped) < EPSILON_M2) {
      clippedHa = 0;
      outsideHa = drawnHa;
      outsideBoundary = true;
      warnings.push('Drawn polygon lies entirely outside the forest boundary.');
    } else {
      clippedHa = turfArea(clipped) / SQM_PER_HA;
      outsideHa = Math.max(0, drawnHa - clippedHa);
      if (outsideHa > 0) warnings.push(`Clipped to boundary (${outsideHa.toFixed(2)} ha removed).`);
    }
  }

  let overlapsExisting = false;
  for (const f of existingFeatures ?? []) {
    const t = (f as any)?.geometry?.type;
    if (t !== 'Polygon' && t !== 'MultiPolygon') continue;
    const inter = safeIntersect(drawn, f as Feature);
    if (inter && turfArea(inter) > EPSILON_M2) {
      overlapsExisting = true;
      break;
    }
  }
  if (overlapsExisting) {
    warnings.push('Drawn polygon overlaps an existing block — draw in an uncovered area.');
  }

  return { drawnHa, clippedHa, outsideHa, outsideBoundary, overlapsExisting, warnings };
}