import * as turf from '@turf/turf';

interface BufferOperationInput {
  feature: GeoJSON.Feature<GeoJSON.Polygon | GeoJSON.MultiPolygon>;
  distanceMeters: number;
  steps?: number;
  units?: turf.Units;
}

interface BufferOperationResult {
  resultFeature: GeoJSON.Feature | null;
  isValid: boolean;
  error?: string;
  areaDeltaSqm: number;
  areaDeltaPercent: number;
}

export function computeBufferPreview(input: BufferOperationInput): BufferOperationResult {
  const {
    feature, distanceMeters,
    steps = 8, units = 'meters',
  } = input;

  if (Math.abs(distanceMeters) < 0.1) {
    return {
      resultFeature: null, isValid: false,
      error: 'Distance too small (min 0.1m)',
      areaDeltaSqm: 0, areaDeltaPercent: 0,
    };
  }

  if (Math.abs(distanceMeters) > 500) {
    return {
      resultFeature: null, isValid: false,
      error: 'Distance too large (max 500m)',
      areaDeltaSqm: 0, areaDeltaPercent: 0,
    };
  }

  const startTime = performance.now();
  let buffered: GeoJSON.Feature | null | undefined;

  try {
    buffered = turf.buffer(feature, distanceMeters, { units, steps });
  } catch (err) {
    return {
      resultFeature: null, isValid: false,
      error: `Buffer computation error: ${err}`,
      areaDeltaSqm: 0, areaDeltaPercent: 0,
    };
  }

  if (!buffered) {
    return {
      resultFeature: null, isValid: false,
      error: 'Buffer returned null — geometry may be too complex or degenerate',
      areaDeltaSqm: 0, areaDeltaPercent: 0,
    };
  }

  const resultFeature = buffered as GeoJSON.Feature;

  if (!turf.booleanValid(resultFeature)) {
    const fixed = turf.buffer(resultFeature, 0, { units: 'meters' });
    if (!fixed || !turf.booleanValid(fixed)) {
      return {
        resultFeature: null, isValid: false,
        error: 'Buffer result has invalid geometry',
        areaDeltaSqm: 0, areaDeltaPercent: 0,
      };
    }
    return computeBufferPreview({
      ...input,
      feature: fixed as GeoJSON.Feature<GeoJSON.Polygon>,
    });
  }

  const originalArea = turf.area(feature);
  const resultArea = turf.area(resultFeature);
  const areaDeltaSqm = resultArea - originalArea;
  const areaDeltaPercent = originalArea > 0
    ? (areaDeltaSqm / originalArea) * 100
    : 0;

  const duration = performance.now() - startTime;
  performance.measure('buffer-preview', { start: startTime, end: performance.now() });

  return {
    resultFeature,
    isValid: true,
    areaDeltaSqm,
    areaDeltaPercent,
  };
}
