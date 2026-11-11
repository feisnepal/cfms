import * as turf from '@turf/turf';

interface ReshapeEdgeInput {
  polygon: GeoJSON.Feature<GeoJSON.Polygon>;
  vertexIndex: number;
  newPosition: [number, number];
  propagationRadius?: number;
  isInteriorRing?: boolean;
  interiorRingIndex?: number;
}

interface ReshapeEdgeResult {
  updatedPolygon: GeoJSON.Feature<GeoJSON.Polygon> | null;
  isValid: boolean;
  error?: string;
  verticesMoved: number;
  maxDisplacementM: number;
}

const DEFAULT_PROPAGATION_RADIUS = 5;
const MIN_POLYGON_AREA_SQM = 10;

export function reshapeEdge(input: ReshapeEdgeInput): ReshapeEdgeResult {
  const {
    polygon, vertexIndex, newPosition,
    propagationRadius = DEFAULT_PROPAGATION_RADIUS,
    isInteriorRing = false, interiorRingIndex = 0,
  } = input;

  const coords = isInteriorRing
    ? polygon.geometry.coordinates[interiorRingIndex + 1]
    : polygon.geometry.coordinates[0];

  if (vertexIndex < 0 || vertexIndex >= coords.length) {
    return { updatedPolygon: null, isValid: false, error: 'Vertex index out of bounds', verticesMoved: 0, maxDisplacementM: 0 };
  }

  const originalVertex = coords[vertexIndex];
  const dx = newPosition[0] - originalVertex[0];
  const dy = newPosition[1] - originalVertex[1];
  const translationVec: [number, number] = [dx, dy];

  const displacementM = turf.distance(
    turf.point(originalVertex),
    turf.point(newPosition),
    { units: 'meters' }
  );

  const n = coords.length - 1;
  const newCoords: [number, number][] = [];

  let verticesMoved = 0;

  for (let i = 0; i < coords.length; i++) {
    let dist = Math.abs(i - vertexIndex);
    dist = Math.min(dist, n - dist);

    if (dist === 0) {
      newCoords.push(newPosition);
      verticesMoved++;
    } else if (dist <= propagationRadius) {
      const ratio = dist / propagationRadius;
      const weight = Math.cos(ratio * Math.PI / 2);
      const newX = coords[i][0] + dx * weight;
      const newY = coords[i][1] + dy * weight;
      newCoords.push([newX, newY]);
      if (weight > 0.01) verticesMoved++;
    } else {
      newCoords.push(coords[i] as [number, number]);
    }
  }

  const updatedCoords = isInteriorRing
    ? polygon.geometry.coordinates.map((ring, idx) =>
        idx === interiorRingIndex + 1 ? newCoords : ring
      )
    : [newCoords, ...polygon.geometry.coordinates.slice(1)];

  const updatedTurfPoly = turf.polygon(updatedCoords);

  if (!turf.booleanValid(updatedTurfPoly)) {
    const fixed = turf.buffer(updatedTurfPoly, 0, { units: 'meters' });
    if (!fixed || !turf.booleanValid(fixed)) {
      return {
        updatedPolygon: null,
        isValid: false,
        error: 'Reshape results in invalid geometry (self-intersection detected)',
        verticesMoved,
        maxDisplacementM: displacementM,
      };
    }
    return {
      updatedPolygon: fixed as GeoJSON.Feature<GeoJSON.Polygon>,
      isValid: true,
      verticesMoved,
      maxDisplacementM: displacementM,
    };
  }

  const area = turf.area(updatedTurfPoly);
  if (area < MIN_POLYGON_AREA_SQM) {
    return {
      updatedPolygon: null,
      isValid: false,
      error: `Resulting polygon too small (${area.toFixed(1)} sqm)`,
      verticesMoved,
      maxDisplacementM: displacementM,
    };
  }

  return {
    updatedPolygon: updatedTurfPoly as GeoJSON.Feature<GeoJSON.Polygon>,
    isValid: true,
    verticesMoved,
    maxDisplacementM: displacementM,
  };
}
