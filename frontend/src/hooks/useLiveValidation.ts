/**
 * useLiveValidation.ts — On-the-fly client-side validation rules (Task 3.4.1).
 *
 * Mirrors backend rules: allowed geometry per purpose, feature count (≤50),
 * vertex count (≤5000), area limit (≤1000 ha), and turf geometric validity (booleanValid, kinks).
 */
import * as turf from '@turf/turf';
import type { GeoJSON, Feature } from 'geojson';
import { allowedGeometryTypes } from '../lib/purposeGeometryRules';

export interface ValidationResult {
  valid: boolean;
  errors: string[];
}

export function validateFeatureLive(feature: Feature, purpose: string, currentFeatureCount: number): ValidationResult {
  const errors: string[] = [];
  const geom = feature.geometry;

  if (!geom) {
    return { valid: false, errors: ['Feature has no geometry'] };
  }

  // 1. Feature count limit (≤ 50 per batch/layer draft)
  if (currentFeatureCount >= 50) {
    errors.push('Maximum feature count limit reached (50 features max per layer)');
  }

  // 2. Allowed geometry type per purpose
  const allowed = allowedGeometryTypes(purpose);
  const gtype = geom.type.replace('Multi', '');
  if (!allowed.includes(gtype as any) && !allowed.includes(geom.type as any)) {
    errors.push(`Geometry type '${geom.type}' not allowed for purpose '${purpose}'`);
  }

  // 3. Vertex count check (≤ 5000)
  let vertexCount = 0;
  if (geom.type === 'Point') vertexCount = 1;
  else if (geom.type === 'LineString') vertexCount = geom.coordinates.length;
  else if (geom.type === 'Polygon') vertexCount = geom.coordinates.flat().length;

  if (vertexCount > 5000) {
    errors.push(`Vertex count exceeds limit (5000 max, found ${vertexCount})`);
  }

  // 4. Area limit for polygons (≤ 1000 ha)
  if (geom.type === 'Polygon' || geom.type === 'MultiPolygon') {
    try {
      const areaSqM = turf.area(feature);
      const areaHa = areaSqM / 10000;
      if (areaHa > 1000) {
        errors.push(`Area exceeds limit (1000 ha max, found ${areaHa.toFixed(2)} ha)`);
      }
    } catch {
      /* ignore invalid polygon area calculation */
    }
  }

  // 5. Geometric validity (turf booleanValid & kinks)
  if (geom.type === 'Polygon') {
    try {
      const isValid = turf.booleanValid(feature as any);
      if (!isValid) {
        errors.push('Geometric validity check failed (polygon self-intersection / bow-tie detected)');
      }
      const kinkList = turf.kinks(feature as any);
      if (kinkList.features.length > 0) {
        errors.push('Self-intersecting polygon (kinks/bow-tie) detected');
      }
    } catch {
      /* ignore */
    }
  }

  return {
    valid: errors.length === 0,
    errors,
  };
}
