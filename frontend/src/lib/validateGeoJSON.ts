import type { GeoJSON } from 'geojson'

export interface ValidationError {
  path: string
  message: string
  code: 'missing_type' | 'invalid_type' | 'missing_geometry' | 'invalid_geometry' | 'missing_coordinates' | 'invalid_coordinates' | 'invalid_feature_collection' | 'no_features' | 'invalid_feature'
}

const VALID_GEOMETRY_TYPES = [
  'Point', 'MultiPoint',
  'LineString', 'MultiLineString',
  'Polygon', 'MultiPolygon',
  'GeometryCollection',
]

export function validateGeoJSON(data: unknown): { valid: boolean; errors: ValidationError[] } {
  const errors: ValidationError[] = []

  if (!data || typeof data !== 'object') {
    errors.push({ path: '', message: 'Input must be a non-null object', code: 'missing_type' })
    return { valid: false, errors }
  }

  const root = data as Record<string, unknown>

  if (!root.type || typeof root.type !== 'string') {
    errors.push({ path: 'type', message: 'Missing or invalid "type" property', code: 'missing_type' })
    return { valid: false, errors }
  }

  if (root.type === 'FeatureCollection') {
    return validateFC(root, errors)
  }

  if (root.type === 'Feature') {
    return validateFeature(root, errors)
  }

  if (VALID_GEOMETRY_TYPES.includes(root.type as string)) {
    return validateGeometryObject(root, errors)
  }

  errors.push({ path: 'type', message: `Unknown GeoJSON type: "${root.type}"`, code: 'invalid_type' })
  return { valid: false, errors }
}

function validateFC(obj: Record<string, unknown>, errors: ValidationError[]): { valid: boolean; errors: ValidationError[] } {
  if (!Array.isArray(obj.features)) {
    errors.push({ path: 'features', message: 'FeatureCollection must have a "features" array', code: 'invalid_feature_collection' })
    return { valid: false, errors }
  }

  if (obj.features.length === 0) {
    errors.push({ path: 'features', message: 'FeatureCollection contains no features', code: 'no_features' })
    return { valid: false, errors }
  }

  for (let i = 0; i < obj.features.length; i++) {
    const feat = obj.features[i]
    if (!feat || typeof feat !== 'object') {
      errors.push({ path: `features[${i}]`, message: `Feature at index ${i} is not an object`, code: 'invalid_feature' })
      continue
    }
    validateFeature(feat as Record<string, unknown>, errors, `features[${i}]`)
  }

  return { valid: errors.length === 0, errors }
}

function validateFeature(obj: Record<string, unknown>, errors: ValidationError[], prefix = ''): { valid: boolean; errors: ValidationError[] } {
  if (obj.type !== 'Feature') {
    errors.push({ path: prefix ? `${prefix}.type` : 'type', message: `Expected "Feature", got "${obj.type}"`, code: 'invalid_type' })
  }

  if (obj.geometry === null) {
    return { valid: true, errors }
  }

  if (!obj.geometry) {
    errors.push({ path: prefix ? `${prefix}.geometry` : 'geometry', message: 'Feature missing "geometry"', code: 'missing_geometry' })
    return { valid: false, errors }
  }

  return validateGeometryObject(obj.geometry as Record<string, unknown>, errors, prefix ? `${prefix}.geometry` : 'geometry')
}

function validateGeometryObject(obj: Record<string, unknown>, errors: ValidationError[], path = ''): { valid: boolean; errors: ValidationError[] } {
  if (!obj.type || typeof obj.type !== 'string' || !VALID_GEOMETRY_TYPES.includes(obj.type as string)) {
    errors.push({ path: path ? `${path}.type` : 'type', message: `Invalid geometry type: "${obj.type}"`, code: 'invalid_geometry' })
    return { valid: false, errors }
  }

  if (!('coordinates' in obj) && obj.type !== 'GeometryCollection') {
    errors.push({ path: path ? `${path}.coordinates` : 'coordinates', message: `Geometry type "${obj.type}" missing coordinates`, code: 'missing_coordinates' })
    return { valid: false, errors }
  }

  if (obj.type !== 'GeometryCollection' && !Array.isArray(obj.coordinates)) {
    errors.push({ path: path ? `${path}.coordinates` : 'coordinates', message: 'Coordinates must be an array', code: 'invalid_coordinates' })
    return { valid: false, errors }
  }

  if (obj.type === 'GeometryCollection') {
    const geoms = obj.geometries
    if (!Array.isArray(geoms)) {
      errors.push({ path: path ? `${path}.geometries` : 'geometries', message: 'GeometryCollection missing geometries array', code: 'missing_geometry' })
    }
  }

  return { valid: errors.length === 0, errors }
}

export function validateFeatureCollection(data: unknown): GeoJSON.FeatureCollection | null {
  const result = validateGeoJSON(data)
  if (!result.valid) return null
  const fc = data as GeoJSON.FeatureCollection
  if (fc.type !== 'FeatureCollection') return null
  return fc
}
