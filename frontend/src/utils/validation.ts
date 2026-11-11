// utils/validation.ts — Zod schemas for API contracts
import { z } from 'zod';
import { simplify as turfSimplify } from '@turf/turf';

/** Max vertices accepted for a boundary geometry before forcing simplification. */
export const VERTEX_LIMIT = 5000;

// GeoJSON coordinate validation
const LngLat = z.tuple([
  z.number().min(-180).max(180), // longitude
  z.number().min(-90).max(90),   // latitude
]);

const LinearRing = z.array(LngLat).refine(
  (ring) => ring.length >= 4,
  'Linear ring must have at least 4 positions'
).refine(
  (ring) => {
    const first = ring[0];
    const last = ring[ring.length - 1];
    return first[0] === last[0] && first[1] === last[1];
  },
  'Linear ring must be closed (first === last point)'
);

const Polygon = z.object({
  type: z.literal('Polygon'),
  coordinates: z.array(LinearRing).min(1),
});

const MultiPolygon = z.object({
  type: z.literal('MultiPolygon'),
  coordinates: z.array(z.array(LinearRing)),
});

/** A GeoJSON boundary geometry (Polygon or MultiPolygon) with vertex limit. */
export const BoundaryGeoJSON = z.union([Polygon, MultiPolygon]).refine(
  (geo) => getVertexCount(geo) < VERTEX_LIMIT,
  'Boundary is too complex or too large. Please simplify.'
);

/** Shared boundary fields for any create/update request. */
const boundaryFields = {
  forest_name: z.string()
    .trim()
    .min(1, 'Forest name is required')
    .max(255, 'Forest name must be under 255 characters'),
};

// Calculation creation schema (matches POST /api/forests/create-from-map)
export const CreateCalculationSchema = z.object({
  ...boundaryFields,
  outer_boundary: BoundaryGeoJSON,
  gps_points: z.array(z.any()).optional(),
  blocks: z.array(z.any()).optional().default([]),
  sub_areas: z.array(z.any()).optional().default([]),
  analysis_options: z.record(z.string(), z.boolean()).optional(),
  map_options: z.record(z.string(), z.boolean()).optional(),
  polygon_type: z.enum(['block', 'compartment']).optional(),
});

export type CreateCalculationInput = z.infer<typeof CreateCalculationSchema>;

/** Validates just the boundary geometry (used pre-submit in the wizard). */
export const validateBoundary = (geo: unknown) => BoundaryGeoJSON.safeParse(geo);

// Client-side validation helper with user-friendly messages
export const validateCalculationInput = (data: unknown) => {
  const result = CreateCalculationSchema.safeParse(data);
  if (!result.success) {
    const errors = result.error.issues.map((issue) => ({
      field: issue.path.join('.'),
      message: issue.message,
    }));
    return { valid: false as const, errors };
  }
  return { valid: true as const, data: result.data };
};

// GeoJSON simplification helper (before upload)
export const simplifyGeoJSON = (geojson: any, tolerance: number = 0.0001): any => {
  try {
    return turfSimplify(geojson, { tolerance, highQuality: true });
  } catch (err) {
    console.warn('Turf simplification failed', err);
    return geojson;
  }
};

// Check vertex count across Polygon/MultiPolygon
export const getVertexCount = (geojson: any): number => {
  if (!geojson || !geojson.type) return 0;
  if (geojson.type === 'Polygon') {
    return geojson.coordinates.reduce((sum: number, ring: number[][]) => sum + ring.length, 0);
  }
  if (geojson.type === 'MultiPolygon') {
    return geojson.coordinates.reduce((sum: number, polygon: number[][][]) =>
      sum + polygon.reduce((s: number, ring: number[][]) => s + ring.length, 0), 0
    );
  }
  return 0;
};
