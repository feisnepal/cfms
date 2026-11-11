/**
 * Geometry validation and repair utilities using Turf.js.
 *
 * Provides functions for validating, repairing, and analysing GeoJSON
 * polygon geometries used in forest boundary and block operations.
 * Includes self-intersection repair, inward buffering, and coordinate
 * rounding.
 */
import * as turf from '@turf/turf';
import type { Feature, Polygon } from 'geojson';
import {
  ensurePolygon,
  getSafeGeometry,
  safeIntersect,
  applyInwardBuffer,
  validateAndFixGeometry,
  roundCoordinates,
  GEOMETRY_CONFIG,
} from './geometryHelpers';

export interface ValidationResult {
  valid: boolean;
  error?: string;
  warnings?: string[];
}

/**
 * Calculate area of a polygon in hectares
 */
export const calculateAreaHectares = (geometry: any): number => {
  try {
    const feature = turf.feature(geometry);
    const areaSquareMeters = turf.area(feature);
    return areaSquareMeters / 10000; // Convert to hectares
  } catch (error) {
    throw new Error(`Failed to calculate area: ${error}`);
  }
};

/**
 * Check if two polygons overlap
 */
export const checkPolygonOverlap = (
  polygon1: any,
  polygon2: any
): { overlaps: boolean; overlapArea?: number } => {
  try {
    // Validate geometries exist and have coordinates
    if (!polygon1 || !polygon2 || 
        !polygon1.coordinates || !polygon2.coordinates ||
        polygon1.coordinates.length === 0 || polygon2.coordinates.length === 0) {
      return { overlaps: false };
    }

    // Only handle Polygon and MultiPolygon types
    const type1 = polygon1.type || (polygon1.geometry ? polygon1.geometry.type : null);
    const type2 = polygon2.type || (polygon2.geometry ? polygon2.geometry.type : null);
    
    if (!type1 || !type2 || 
        !['Polygon', 'MultiPolygon'].includes(type1) ||
        !['Polygon', 'MultiPolygon'].includes(type2)) {
      return { overlaps: false };
    }

    const feature1 = turf.feature(polygon1);
    const feature2 = turf.feature(polygon2);

    const intersection = turf.intersect(turf.featureCollection([feature1, feature2] as any));

    if (intersection) {
      const overlapArea = turf.area(intersection) / 10000; // hectares
      return { overlaps: true, overlapArea };
    }

    return { overlaps: false };
  } catch (error) {
    // Silently handle validation errors - not all geometries will overlap
    return { overlaps: false };
  }
};

/**
 * Check if a point is inside a polygon
 */
export const isPointInPolygon = (
  point: [number, number], // [lon, lat]
  polygon: any
): boolean => {
  try {
    const pt = turf.point(point);
    const poly = turf.feature(polygon);
    return turf.booleanPointInPolygon(pt, poly);
  } catch (error) {
    console.error('Error checking point in polygon:', error);
    return false;
  }
};

/**
 * Validate that blocks don't overlap
 */
export const validateBlocksNoOverlap = (
  blocks: Array<{ name: string; geometry: any }>
): ValidationResult => {
  const warnings: string[] = [];

  for (let i = 0; i < blocks.length; i++) {
    for (let j = i + 1; j < blocks.length; j++) {
      const block1 = blocks[i];
      const block2 = blocks[j];

      const { overlaps, overlapArea } = checkPolygonOverlap(
        block1.geometry,
        block2.geometry
      );

      if (overlaps && overlapArea && overlapArea > 0.01) {
        // Tolerance: 0.01 hectares (100 sq meters)
        return {
          valid: false,
          error: `Blocks "${block1.name}" and "${block2.name}" overlap by ${overlapArea.toFixed(2)} hectares`,
        };
      }
    }
  }

  return { valid: true, warnings };
};

/**
 * Validate that sum of block areas approximately equals outer boundary area
 */
export const validateBlockAreaSum = (
  outerBoundary: any,
  blocks: Array<{ name: string; geometry: any }>,
  tolerancePercent: number = 1 // 1% tolerance
): ValidationResult => {
  const outerArea = calculateAreaHectares(outerBoundary);
  const blocksArea = blocks.reduce((sum, block) => {
    return sum + calculateAreaHectares(block.geometry);
  }, 0);

  const difference = Math.abs(outerArea - blocksArea);
  const percentDiff = (difference / outerArea) * 100;

  if (percentDiff > tolerancePercent) {
    return {
      valid: false,
      error: `Sum of block areas (${blocksArea.toFixed(2)} ha) differs from outer boundary area (${outerArea.toFixed(2)} ha) by ${percentDiff.toFixed(1)}%`,
    };
  }

  const warnings: string[] = [];
  if (percentDiff > 0.1) {
    warnings.push(
      `Small area difference detected: ${difference.toFixed(2)} ha (${percentDiff.toFixed(2)}%)`
    );
  }

  return { valid: true, warnings };
};

/**
 * Validate that sub-areas don't overlap within the same block
 */
export const validateSubAreasNoOverlap = (
  subAreas: Array<{ name: string; category: string; geometry: any }>
): ValidationResult => {
  for (let i = 0; i < subAreas.length; i++) {
    for (let j = i + 1; j < subAreas.length; j++) {
      const area1 = subAreas[i];
      const area2 = subAreas[j];

      const { overlaps, overlapArea } = checkPolygonOverlap(
        area1.geometry,
        area2.geometry
      );

      if (overlaps && overlapArea && overlapArea > 0.01) {
        return {
          valid: false,
          error: `Sub-areas "${area1.name}" (${area1.category}) and "${area2.name}" (${area2.category}) overlap by ${overlapArea.toFixed(2)} hectares`,
        };
      }
    }
  }

  return { valid: true };
};

/**
 * Validate that sum of sub-area areas doesn't exceed block area
 */
export const validateSubAreaSum = (
  blockGeometry: any,
  subAreas: Array<{ name: string; geometry: any }>,
  tolerancePercent: number = 1
): ValidationResult => {
  const blockArea = calculateAreaHectares(blockGeometry);
  const subAreasTotal = subAreas.reduce((sum, subArea) => {
    return sum + calculateAreaHectares(subArea.geometry);
  }, 0);

  if (subAreasTotal > blockArea * (1 + tolerancePercent / 100)) {
    return {
      valid: false,
      error: `Sum of sub-areas (${subAreasTotal.toFixed(2)} ha) exceeds block area (${blockArea.toFixed(2)} ha)`,
    };
  }

  return { valid: true };
};

/**
 * Detect which block a sub-area belongs to
 */
export const detectBlockForSubArea = (
  subAreaGeometry: any,
  blocks: Array<{ id: string; name: string; geometry: any }>
): { blockId?: string; blockName?: string; confidence: number } => {
  try {
    const subAreaFeature = turf.feature(subAreaGeometry);
    const subAreaCentroid = turf.centroid(subAreaFeature);

    // Check which block contains the centroid
    for (const block of blocks) {
      if (isPointInPolygon(subAreaCentroid.geometry.coordinates as [number, number], block.geometry)) {
        return {
          blockId: block.id,
          blockName: block.name,
          confidence: 1.0,
        };
      }
    }

    // If centroid method fails, check for intersection
    for (const block of blocks) {
      const blockFeature = turf.feature(block.geometry);
      const intersection = turf.intersect(turf.featureCollection([subAreaFeature, blockFeature] as any));

      if (intersection) {
        const intersectionArea = turf.area(intersection);
        const subAreaArea = turf.area(subAreaFeature);
        const confidence = intersectionArea / subAreaArea;

        if (confidence > 0.5) {
          // More than 50% of sub-area is in this block
          return {
            blockId: block.id,
            blockName: block.name,
            confidence,
          };
        }
      }
    }

    return { confidence: 0 };
  } catch (error) {
    console.error('Error detecting block for sub-area:', error);
    return { confidence: 0 };
  }
};

/**
 * Validate polygon geometry
 */
export const validatePolygonGeometry = (geometry: any): ValidationResult => {
  try {
    const feature = turf.feature(geometry);

    // Check if it's a valid polygon
    if (feature.geometry.type !== 'Polygon' && feature.geometry.type !== 'MultiPolygon') {
      return {
        valid: false,
        error: 'Geometry must be a Polygon or MultiPolygon',
      };
    }

    // Check for self-intersections using kinks
    const kinks = turf.kinks(feature);
    if (kinks.features.length > 0) {
      return {
        valid: false,
        error: `Polygon has ${kinks.features.length} self-intersection(s)`,
      };
    }

    // Calculate area
    const area = turf.area(feature);
    if (area === 0) {
      return {
        valid: false,
        error: 'Polygon has zero area',
      };
    }

    // Check minimum area (0.1 hectares = 1000 sq meters)
    if (area < 1000) {
      return {
        valid: false,
        error: `Polygon area too small: ${(area / 10000).toFixed(4)} hectares (minimum: 0.1 ha)`,
      };
    }

    const warnings: string[] = [];

    // Check if polygon is very small (warning)
    if (area < 5000) {
      // Less than 0.5 hectares
      warnings.push(`Small polygon area: ${(area / 10000).toFixed(2)} hectares`);
    }

    return { valid: true, warnings };
  } catch (error) {
    return {
      valid: false,
      error: `Invalid polygon geometry: ${error}`,
    };
  }
};

/**
 * Simplify polygon to reduce vertices (useful for large GPS tracks)
 */
export const simplifyPolygon = (
  geometry: any,
  tolerance: number = 0.0001 // degrees (~11 meters)
): any => {
  try {
    const feature = turf.feature(geometry);
    const simplified = turf.simplify(feature, { tolerance, highQuality: true });
    return simplified.geometry;
  } catch (error) {
    console.error('Error simplifying polygon:', error);
    return geometry;
  }
};

/**
 * Get polygon centroid
 */
export const getPolygonCentroid = (geometry: any): [number, number] => {
  try {
    const feature = turf.feature(geometry);
    const centroid = turf.centroid(feature);
    return centroid.geometry.coordinates as [number, number];
  } catch (error) {
    throw new Error(`Failed to calculate centroid: ${error}`);
  }
};

/**
 * Get polygon bounding box
 */
export const getPolygonBounds = (
  geometry: any
): { north: number; south: number; east: number; west: number } => {
  try {
    const feature = turf.feature(geometry);
    const bbox = turf.bbox(feature);
    return {
      west: bbox[0],
      south: bbox[1],
      east: bbox[2],
      north: bbox[3],
    };
  } catch (error) {
    throw new Error(`Failed to calculate bounds: ${error}`);
  }
};

/**
 * Check if a polygon is completely within another polygon
 */
export const isPolygonWithin = (innerPolygon: any, outerPolygon: any): boolean => {
  try {
    const inner = turf.feature(innerPolygon);
    const outer = turf.feature(outerPolygon);
    return turf.booleanWithin(inner, outer);
  } catch (error) {
    console.error('Error checking polygon containment:', error);
    return false;
  }
};

/**
 * Validate that all blocks are within the outer boundary
 */
export const validateBlocksWithinBoundary = (
  outerBoundary: any,
  blocks: Array<{ name: string; geometry: any }>
): ValidationResult => {
  for (const block of blocks) {
    if (!isPolygonWithin(block.geometry, outerBoundary)) {
      return {
        valid: false,
        error: `Block "${block.name}" extends outside the outer boundary`,
      };
    }
  }

  return { valid: true };
};

/**
 * Format area for display
 */
export const formatArea = (hectares: number | undefined | null): string => {
  if (hectares === undefined || hectares === null || isNaN(hectares)) {
    return '0 ha';
  }
  if (hectares < 0.01) {
    return `${(hectares * 10000).toFixed(0)} m²`;
  } else if (hectares < 1) {
    return `${hectares.toFixed(3)} ha`;
  } else if (hectares < 100) {
    return `${hectares.toFixed(2)} ha`;
  } else {
    return `${hectares.toFixed(1)} ha`;
  }
};

/**
 * Split a polygon using a line
 * Returns array of resulting polygons after the split
 */
export const splitPolygonWithLine = (
  polygon: any,
  line: any
): any[] => {
  const coords = line.coordinates || line.geometry?.coordinates;
  if (!coords || coords.length < 2) {
    return splitPolygonWithBuffer(polygon, line);
  }

  const startPoint = coords[0];
  const endPoint = coords[coords.length - 1];
  const geom = polygon.geometry || polygon;
  const polyCoords = geom.coordinates[0];
  const n = polyCoords ? polyCoords.length - 1 : 0;

  if (n < 3) {
    return splitPolygonWithBuffer(polygon, line);
  }

  const distSq = (a: number[], b: number[]) =>
    Math.pow(a[0] - b[0], 2) + Math.pow(a[1] - b[1], 2);

  let startIdx = 0, endIdx = 1;
  let minStartDist = Infinity, minEndDist = Infinity;

  for (let i = 0; i < n; i++) {
    const dStart = distSq(startPoint, polyCoords[i]);
    const dEnd = distSq(endPoint, polyCoords[i]);
    if (dStart < minStartDist) { minStartDist = dStart; startIdx = i; }
    if (dEnd < minEndDist) { minEndDist = dEnd; endIdx = i; }
  }

  if (startIdx === endIdx) {
    endIdx = (startIdx + 1) % n;
  }

  const walk = (from: number, to: number): number[][] => {
    const result: number[][] = [];
    for (let i = from; ; i = (i + 1) % n) {
      result.push(polyCoords[i]);
      if (i === to) break;
    }
    return result;
  };

  const part1 = walk(startIdx, endIdx);
  const part2 = walk(endIdx, startIdx);
  const lineReversed = [...coords].reverse();

  const makeRing = (bc: number[][]): any => ({
    type: 'Polygon',
    coordinates: [[...bc, bc[0]]],
  });

  try {
    const p1 = makeRing([...part1, ...lineReversed]);
    const p2 = makeRing([...part2, ...coords]);
    const a1 = turf.area(turf.feature(p1));
    const a2 = turf.area(turf.feature(p2));
    if (a1 > 100 && a2 > 100) {
      return [cleanPolygonGeometry(p1), cleanPolygonGeometry(p2)];
    }
  } catch {}

  return splitPolygonWithBuffer(polygon, line);
};

/**
 * Clean and fix polygon geometry
 * Removes duplicate coordinates, fixes self-intersections, and ensures validity
 */
export function cleanPolygonGeometry(polygon: any): any {
  try {
    let feature = turf.feature(polygon);

    // Remove duplicate/redundant coordinates
    feature = turf.cleanCoords(feature);

    // Use a tiny buffer(0) trick to fix self-intersections and topology issues
    // Buffer by 0.00001 meters then back - this cleans up invalid geometries
    let buffered = turf.buffer(feature, 0.00001, { units: 'meters' });
    if (buffered) {
      buffered = turf.buffer(buffered, -0.00001, { units: 'meters' });
      if (buffered && (buffered.geometry.type === 'Polygon' || buffered.geometry.type === 'MultiPolygon')) {
        // If it's a MultiPolygon, take the largest part
        if (buffered.geometry.type === 'MultiPolygon') {
          const polygons = buffered.geometry.coordinates.map((coords: any) => ({
            type: 'Polygon',
            coordinates: coords,
          }));
          // Return the polygon with the largest area
          const largest = polygons.reduce((max: any, current: any) => {
            const maxArea = turf.area(turf.feature(max));
            const currentArea = turf.area(turf.feature(current));
            return currentArea > maxArea ? current : max;
          });
          return largest;
        }
        return buffered.geometry;
      }
    }

    // If buffer didn't work, return cleaned original
    return feature.geometry;
  } catch (error) {
    console.error('Error cleaning polygon geometry:', error);
    // Return original if cleaning fails
    return polygon;
  }
}

/**
 * Alternative splitting method using buffer
 */
function splitPolygonWithBuffer(polygon: any, line: any): any[] {
  const rawLine = line.coordinates ? line : (line.geometry || line);
  const rawPoly = polygon.geometry || polygon;
  const lineCoords = rawLine.coordinates || rawLine;
  if (!lineCoords || lineCoords.length < 2) throw new Error('Invalid line');
  const extended = extendLine(
    turf.lineString(lineCoords),
    10
  );
  const band = turf.buffer(extended, 0.02, { units: 'kilometers' });
  if (!band) throw new Error('Failed to create buffer');
  const diff = turf.difference(turf.featureCollection([turf.feature(rawPoly), band] as any));
  if (!diff) throw new Error('Line does not intersect polygon');
  if (diff.geometry.type === 'MultiPolygon') {
    return diff.geometry.coordinates.map((c: any) => {
      const p = { type: 'Polygon', coordinates: c };
      try { return cleanPolygonGeometry(p); } catch { return p; }
    });
  }
  throw new Error('Split did not divide polygon');
}


/**
 * Extend a line on both ends
 */
function extendLine(line: any, distanceKm: number): any {
  const coords = line.geometry.coordinates;

  if (!coords || coords.length < 2) {
    throw new Error('Line must have at least 2 coordinates');
  }

  // Extend start
  const bearing1 = turf.bearing(turf.point(coords[1]), turf.point(coords[0]));
  const extendedStart = turf.destination(turf.point(coords[0]), distanceKm, bearing1);

  // Extend end
  const bearing2 = turf.bearing(
    turf.point(coords[coords.length - 2]),
    turf.point(coords[coords.length - 1])
  );
  const extendedEnd = turf.destination(
    turf.point(coords[coords.length - 1]),
    distanceKm,
    bearing2
  );

  return turf.lineString([
    extendedStart.geometry.coordinates,
    ...coords,
    extendedEnd.geometry.coordinates,
  ]);
}

/**
 * Calculate sub-area breakdown by blocks for cross-block sub-areas
 * Returns an array of block associations with their respective areas
 */
export const calculateSubAreaByBlock = (
  subAreaGeometry: any,
  blocks: Array<{ id: string; name: string; geometry: any }>
): Array<{ blockId: string; blockName: string; area: number; percentage: number }> => {
  try {
    console.log('[calculateSubAreaByBlock] Starting grid-based calculation');
    console.log('[calculateSubAreaByBlock] Sub-area geometry:', subAreaGeometry);
    console.log('[calculateSubAreaByBlock] Number of blocks:', blocks.length);

    // Validate sub-area geometry
    if (!subAreaGeometry || !subAreaGeometry.type || !subAreaGeometry.coordinates) {
      console.error('[calculateSubAreaByBlock] Invalid sub-area geometry:', subAreaGeometry);
      return [];
    }

    const subAreaFeature = turf.feature(subAreaGeometry);
    const subAreaTotalArea = calculateAreaHectares(subAreaGeometry);
    console.log('[calculateSubAreaByBlock] Sub-area total area:', subAreaTotalArea, 'ha');

    // Use grid-based sampling approach for reliable intersection calculation
    // This avoids turf.intersect() issues by testing points instead of polygon intersection

    // Step 1: Get bounding box of sub-area
    const bbox = turf.bbox(subAreaFeature);
    console.log('[calculateSubAreaByBlock] Sub-area bbox:', bbox);

    // Step 2: Create grid of points with fine resolution for accurate results
    // Use 50 points per side for better accuracy, or 20m minimum grid
    const cellSize = Math.sqrt(subAreaTotalArea) / 50; // ~50 points per side
    const gridSize = Math.max(cellSize, 0.02); // Minimum 20m grid (0.02 km)
    console.log('[calculateSubAreaByBlock] Grid size:', gridSize, 'km');

    const pointGrid = turf.pointGrid(bbox, gridSize, { units: 'kilometers' });
    console.log('[calculateSubAreaByBlock] Created grid with', pointGrid.features.length, 'points');

    // Step 3: Filter points that are inside the sub-area
    const pointsInSubArea = pointGrid.features.filter(point =>
      turf.booleanPointInPolygon(point, subAreaFeature)
    );
    console.log('[calculateSubAreaByBlock] Points inside sub-area:', pointsInSubArea.length);

    if (pointsInSubArea.length === 0) {
      console.warn('[calculateSubAreaByBlock] No points found in sub-area - grid might be too coarse');
      return [];
    }

    // Step 4: Count how many points fall in each block
    const blockPointCounts = new Map<string, number>();

    for (const block of blocks) {
      if (!block.geometry || !block.geometry.type || !block.geometry.coordinates) {
        continue;
      }

      const blockFeature = turf.feature(block.geometry);
      let pointsInBlock = 0;

      for (const point of pointsInSubArea) {
        if (turf.booleanPointInPolygon(point, blockFeature)) {
          pointsInBlock++;
        }
      }

      if (pointsInBlock > 0) {
        blockPointCounts.set(block.id, pointsInBlock);
        console.log(`[calculateSubAreaByBlock] Block ${block.name}: ${pointsInBlock} points`);
      }
    }

    // Step 5: Calculate proportional areas based on point distribution
    const breakdown: Array<{ blockId: string; blockName: string; area: number; percentage: number }> = [];
    const totalPointsDistributed = Array.from(blockPointCounts.values()).reduce((sum, count) => sum + count, 0);

    if (totalPointsDistributed === 0) {
      console.warn('[calculateSubAreaByBlock] No points matched any blocks');
      return [];
    }

    for (const block of blocks) {
      const pointCount = blockPointCounts.get(block.id) || 0;
      if (pointCount > 0) {
        const percentage = (pointCount / totalPointsDistributed) * 100;
        const area = (percentage / 100) * subAreaTotalArea;

        breakdown.push({
          blockId: block.id,
          blockName: block.name,
          area: parseFloat(area.toFixed(4)),
          percentage: parseFloat(percentage.toFixed(2))
        });

        console.log(`[calculateSubAreaByBlock] ✓ Block ${block.name}: ${area.toFixed(4)} ha (${percentage.toFixed(2)}%)`);
      }
    }

    return breakdown;
  } catch (error) {
    console.error('[calculateSubAreaByBlock] Error calculating sub-area by block:', error);
    return [];
  }
};

/**
 * Clean and validate blocks before sending to backend
 * Fixes geometry issues, clips to outer boundary, and removes overlaps
 * UPDATED: Now uses geometryHelpers for safer geometry operations
 */
export const cleanAndValidateBlocks = (
  blocks: Array<{ id: string; name: string; geometry: any; area: number }>,
  outerBoundary: any
): Array<{ id: string; name: string; geometry: any; area: number }> => {
  console.log('[cleanAndValidateBlocks] Starting validation with', blocks.length, 'blocks');

  try {
    // Validate outer boundary
    if (!outerBoundary) {
      console.warn('[cleanAndValidateBlocks] No outer boundary provided, skipping cleaning');
      return blocks;
    }

    // Safely extract and convert outer boundary to polygon
    const outerPoly = ensurePolygon(outerBoundary);
    if (!outerPoly) {
      console.error('[cleanAndValidateBlocks] Failed to convert outer boundary to polygon');
      return blocks;
    }

    console.log('[cleanAndValidateBlocks] Outer boundary validated successfully');

    const cleanedBlocks: Array<{ id: string; name: string; geometry: any; area: number }> = [];

    for (const block of blocks) {
      try {
        console.log(`[cleanAndValidateBlocks] Processing block: ${block.name}`);

        // Step 1: Validate and fix geometry
        const validation = validateAndFixGeometry(block.geometry);
        if (!validation.valid) {
          console.warn(`[cleanAndValidateBlocks] Block ${block.name} has invalid geometry:`, validation.errors);
          // Try to use original if fix failed
          cleanedBlocks.push(block);
          continue;
        }

        let cleanedGeometry = validation.geometry;
        console.log(`[cleanAndValidateBlocks] Block ${block.name} geometry validated`);

        // Step 2: Round coordinates to avoid floating-point drift
        cleanedGeometry = roundCoordinates(cleanedGeometry);

        // Step 3: Clip to outer boundary using safe intersection
        const clipped = safeIntersect(cleanedGeometry, outerPoly);

        if (clipped && clipped.geometry) {
          cleanedGeometry = clipped.geometry;
          console.log(`[cleanAndValidateBlocks] Block ${block.name} clipped to boundary successfully`);
        } else {
          console.warn(`[cleanAndValidateBlocks] Block ${block.name} intersection returned null, keeping original`);
          // Block might be completely inside - check if it needs inward buffer
        }

        // Step 4: Apply micro-inward buffer to ensure it's strictly inside boundary
        const safeGeometry = applyInwardBuffer(cleanedGeometry, GEOMETRY_CONFIG.BUFFER_INWARD);
        if (safeGeometry) {
          cleanedGeometry = safeGeometry;
          console.log(`[cleanAndValidateBlocks] Block ${block.name} inward buffer applied`);
        }

        // Step 5: Recalculate area after cleaning
        const newArea = calculateAreaHectares(cleanedGeometry);
        console.log(`[cleanAndValidateBlocks] Block ${block.name} area: ${newArea.toFixed(4)} ha`);

        // Only add if significant area remains (> 0.01 ha)
        if (newArea > 0.01) {
          cleanedBlocks.push({
            id: block.id,
            name: block.name,
            geometry: cleanedGeometry,
            area: newArea,
          });
        } else {
          console.warn(`[cleanAndValidateBlocks] Block ${block.name} has negligible area (${newArea.toFixed(4)} ha), skipping`);
        }
      } catch (error) {
        console.error(`[cleanAndValidateBlocks] Error processing block ${block.name}:`, error);
        // Keep original block if cleaning fails
        cleanedBlocks.push(block);
      }
    }

    console.log(`[cleanAndValidateBlocks] Cleaned ${cleanedBlocks.length} blocks, now fixing overlaps`);

    // Step 6: Fix overlaps between blocks
    const nonOverlappingBlocks = fixBlockOverlaps(cleanedBlocks);

    console.log(`[cleanAndValidateBlocks] Final result: ${nonOverlappingBlocks.length} blocks`);
    return nonOverlappingBlocks;
  } catch (error) {
    console.error('[cleanAndValidateBlocks] Critical error in validation:', error);
    // Return original blocks if processing fails
    return blocks;
  }
};

/**
 * Fix overlaps between blocks by subtracting intersections
 * UPDATED: Now uses safeIntersect and proper error handling
 */
function fixBlockOverlaps(
  blocks: Array<{ id: string; name: string; geometry: any; area: number }>
): Array<{ id: string; name: string; geometry: any; area: number }> {
  console.log(`[fixBlockOverlaps] Processing ${blocks.length} blocks for overlaps`);
  const result: Array<{ id: string; name: string; geometry: any; area: number }> = [];

  for (let i = 0; i < blocks.length; i++) {
    let currentGeometry = blocks[i].geometry;

    // Convert to polygon feature safely
    let currentFeature = ensurePolygon(currentGeometry);
    if (!currentFeature) {
      console.warn(`[fixBlockOverlaps] Block ${blocks[i].name} has invalid geometry, skipping`);
      result.push(blocks[i]);
      continue;
    }

    // Subtract any overlaps with previously processed blocks
    for (let j = 0; j < i; j++) {
      try {
        const previousFeature = ensurePolygon(result[j].geometry);
        if (!previousFeature) continue;

        // Check if they intersect
        if (turf.booleanIntersects(currentFeature, previousFeature)) {
          // Use safe intersection
          const intersection = safeIntersect(currentFeature, previousFeature);

          // Only process significant overlaps (> configurable threshold)
          const minOverlapArea = GEOMETRY_CONFIG.MIN_OVERLAP_AREA * 1e10; // Convert to sq meters
          if (intersection && turf.area(intersection) > minOverlapArea) {
            console.log(
              `[fixBlockOverlaps] Found overlap between ${blocks[i].name} and ${result[j].name}: ` +
              `${turf.area(intersection).toFixed(2)} sqm`
            );

            // Subtract the overlap from current block
            const difference = turf.difference(
              turf.featureCollection([currentFeature, previousFeature])
            );

            if (difference) {
              if (difference.geometry.type === 'Polygon') {
                currentGeometry = difference.geometry;
                currentFeature = difference as Feature<Polygon>;
              } else if (difference.geometry.type === 'MultiPolygon') {
                // Take the largest part
                const polygons = difference.geometry.coordinates.map((coords: any) =>
                  turf.polygon(coords)
                );
                const largest = polygons.reduce((max: any, current: any) => {
                  const maxArea = turf.area(max);
                  const currentArea = turf.area(current);
                  return currentArea > maxArea ? current : max;
                });
                currentGeometry = largest.geometry;
                currentFeature = largest;
              }
              console.log(`[fixBlockOverlaps] Removed overlap from ${blocks[i].name}`);
            }
          }
        }
      } catch (error) {
        console.error(`[fixBlockOverlaps] Error fixing overlap between blocks ${i} and ${j}:`, error);
      }
    }

    // Recalculate area after fixing overlaps
    const finalArea = calculateAreaHectares(currentGeometry);

    // Only add if significant area remains
    if (finalArea > 0.01) {
      result.push({
        id: blocks[i].id,
        name: blocks[i].name,
        geometry: currentGeometry,
        area: finalArea,
      });
      console.log(`[fixBlockOverlaps] Added ${blocks[i].name} with final area: ${finalArea.toFixed(4)} ha`);
    } else {
      console.warn(`[fixBlockOverlaps] Block ${blocks[i].name} has negligible area after fixing overlaps (${finalArea.toFixed(4)} ha), skipping`);
    }
  }

  console.log(`[fixBlockOverlaps] Completed: ${result.length} blocks after overlap resolution`);
  return result;
}
