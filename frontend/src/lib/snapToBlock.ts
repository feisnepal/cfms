import type { GeoJSON, Feature, FeatureCollection } from 'geojson';
import * as turf from '@turf/turf';

export interface SnapToBlockInput {
  geometry: GeoJSON.Geometry;
  blockFeatures: GeoJSON.Feature[] | null | undefined;
  tolerance?: number;
  enabled: boolean;
}

export interface SnapToBlockResult {
  geometry: GeoJSON.Geometry;
  snappedVertices: number;
  durationMs: number;
  didSnap: boolean;
}

export function snapToBlock(input: SnapToBlockInput): SnapToBlockResult {
  const start = performance.now();
  const { geometry, blockFeatures, tolerance = 5, enabled } = input;

  if (!enabled || !blockFeatures || blockFeatures.length === 0) {
    return { geometry, snappedVertices: 0, durationMs: 0, didSnap: false };
  }

  try {
    const validBlocks = blockFeatures.filter(
      f => f.geometry.type === 'Polygon' || f.geometry.type === 'MultiPolygon'
    );
    if (validBlocks.length === 0) {
      return { geometry, snappedVertices: 0, durationMs: 0, didSnap: false };
    }

    const feature = turf.feature(geometry);
    let blockUnion: GeoJSON.Feature | undefined;

    if (validBlocks.length === 1) {
      blockUnion = turf.buffer(validBlocks[0] as any, 0);
    } else {
      const safe = validBlocks.map(b => turf.buffer(b as any, 0)).filter(Boolean) as GeoJSON.Feature[];
      blockUnion = turf.union(turf.featureCollection(safe as any)) as GeoJSON.Feature;
    }

    if (!blockUnion) {
      return { geometry, snappedVertices: 0, durationMs: 0, didSnap: false };
    }

    const blockCoords = (blockUnion.geometry as any).coordinates;
    const snapped = feature;

    const originalCoords = flattenCoords(geometry);
    const snappedCoords = flattenCoords(snapped.geometry);

    let snappedVertices = 0;
    for (let i = 0; i < Math.min(originalCoords.length, snappedCoords.length); i++) {
      const orig = originalCoords[i];
      const snap = snappedCoords[i];
      const dx = orig[0] - snap[0];
      const dy = orig[1] - snap[1];
      const dist = Math.sqrt(dx * dx + dy * dy) * 111320;
      if (dist > 0.01) snappedVertices++;
    }

    const durationMs = performance.now() - start;
    if (durationMs > 10) {
      console.warn(`[snapToBlock] Performance warning: ${durationMs.toFixed(1)}ms`);
    }

    return {
      geometry: snapped.geometry,
      snappedVertices,
      durationMs: Math.round(durationMs),
      didSnap: snappedVertices > 0,
    };
  } catch (err) {
    console.warn('[snapToBlock] Error during snap, returning original geometry:', err);
    const durationMs = performance.now() - start;
    return { geometry, snappedVertices: 0, durationMs: Math.round(durationMs), didSnap: false };
  }
}

function flattenCoords(geometry: GeoJSON.Geometry): [number, number][] {
  const coords: [number, number][] = [];
  function walk(g: any): void {
    if (g.type === 'Point') {
      coords.push(g.coordinates);
    } else if (g.type === 'LineString' || g.type === 'MultiPoint') {
      g.coordinates.forEach((c: any) => coords.push(c));
    } else if (g.type === 'Polygon') {
      g.coordinates.forEach((ring: any) => ring.forEach((c: any) => coords.push(c)));
    } else if (g.type === 'MultiLineString') {
      g.coordinates.forEach((line: any) => line.forEach((c: any) => coords.push(c)));
    } else if (g.type === 'MultiPolygon') {
      g.coordinates.forEach((poly: any) => poly.forEach((ring: any) => ring.forEach((c: any) => coords.push(c))));
    } else if (g.type === 'GeometryCollection') {
      g.geometries.forEach(walk);
    }
  }
  walk(geometry);
  return coords;
}

export function isNearBlockEdge(
  latlng: { lat: number; lng: number },
  blockFeatures: GeoJSON.Feature[],
  tolerance: number = 5,
): boolean {
  const pt = turf.point([latlng.lng, latlng.lat]);
  for (const block of blockFeatures) {
    if (block.geometry.type !== 'Polygon' && block.geometry.type !== 'MultiPolygon') continue;
    try {
      const dist = turf.distance(pt, block as any, { units: 'meters' });
      if (dist <= tolerance) return true;
    } catch {
      continue;
    }
  }
  return false;
}

export default snapToBlock;
