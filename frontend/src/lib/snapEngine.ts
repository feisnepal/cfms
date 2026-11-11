/**
 * snapEngine.ts — Generalized high-performance snap engine (Gap 4.1–4.3, 7.1).
 */
import * as turf from '@turf/turf';
import RBush from 'rbush';
import type { Feature, LineString, Polygon, Point, Geometry } from 'geojson';

export type SnapTargetType = 'vertex' | 'endpoint' | 'intersection' | 'edge';

export interface SnapResult {
  point: [number, number];
  targetType: SnapTargetType;
  distancePx: number;
  featureId?: string;
}

interface RBushItem {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
  feature: Feature;
}

export class SnapEngine {
  private rbush = new RBush<RBushItem>();
  private indexedCount = 0;

  constructor(features: Feature[] = []) {
    this.load(features);
  }

  public load(features: Feature[]): void {
    this.rbush.clear();
    const items: RBushItem[] = [];
    for (const f of features) {
      if (!f || !f.geometry) continue;
      const box = turf.bbox(f);
      items.push({
        minX: box[0],
        minY: box[1],
        maxX: box[2],
        maxY: box[3],
        feature: f,
      });
    }
    this.rbush.load(items);
    this.indexedCount = items.length;
  }

  public snapToNearest(
    cursor: { lat: number; lng: number },
    tolerancePx: number = 10,
    mapScaleMetersPerPx: number = 1.0,
  ): SnapResult | null {
    const t0 = performance.now();
    const maxDistMeters = tolerancePx * mapScaleMetersPerPx;
    const cursorPt = turf.point([cursor.lng, cursor.lat]);

    const deltaDeg = (maxDistMeters / 111320) * 2;
    const searchBox = {
      minX: cursor.lng - deltaDeg,
      minY: cursor.lat - deltaDeg,
      maxX: cursor.lng + deltaDeg,
      maxY: cursor.lat + deltaDeg,
    };

    const candidates = this.rbush.search(searchBox);
    if (candidates.length === 0) {
      this.checkBudget(t0, 0);
      return null;
    }

    let bestSnap: SnapResult | null = null;
    let bestPriority = 99;
    let bestDist = Infinity;

    for (const item of candidates) {
      const geom = item.feature.geometry;
      if (!geom) continue;

      const coords = this.extractCoords(geom);
      const fid = (item.feature.properties as any)?.featureId ?? item.feature.id;

      for (let i = 0; i < coords.length; i++) {
        const c = coords[i];
        const isEndpoint = i === 0 || i === coords.length - 1;
        const targetType: SnapTargetType = isEndpoint ? 'endpoint' : 'vertex';
        const priority = isEndpoint ? 2 : 1;
        const distM = turf.distance(cursorPt, turf.point(c), { units: 'meters' });

        if (distM <= maxDistMeters) {
          if (priority < bestPriority || (priority === bestPriority && distM < bestDist)) {
            bestPriority = priority;
            bestDist = distM;
            bestSnap = { point: [c[0], c[1]], targetType, distancePx: distM / Math.max(mapScaleMetersPerPx, 0.001), featureId: String(fid ?? '') };
          }
        }
      }

      if (geom.type === 'LineString' || geom.type === 'Polygon') {
        const line = geom.type === 'Polygon' 
          ? turf.lineString((geom as Polygon).coordinates[0]) 
          : turf.lineString((geom as LineString).coordinates);
        const nearest = turf.nearestPointOnLine(line, cursorPt, { units: 'meters' });
        const distM = nearest.properties.dist ?? Infinity;

        if (distM <= maxDistMeters) {
          const priority = 4;
          const [lng, lat] = nearest.geometry.coordinates;
          if (priority < bestPriority || (priority === bestPriority && distM < bestDist)) {
            bestPriority = priority;
            bestDist = distM;
            bestSnap = { point: [lng, lat], targetType: 'edge', distancePx: distM / Math.max(mapScaleMetersPerPx, 0.001), featureId: String(fid ?? '') };
          }
        }
      }
    }

    this.checkBudget(t0, this.indexedCount);
    return bestSnap;
  }

  private extractCoords(geom: Geometry): number[][] {
    if (geom.type === 'Point') return [(geom as Point).coordinates];
    if (geom.type === 'LineString') return (geom as LineString).coordinates;
    if (geom.type === 'Polygon') return (geom as Polygon).coordinates.flat();
    return [];
  }

  private checkBudget(t0: number, count: number): void {
    const elapsed = performance.now() - t0;
    if (elapsed > 8.0) {
      console.warn(`[snapEngine] Over budget: ${elapsed.toFixed(2)}ms for ${count} indexed features`);
    }
  }
}
