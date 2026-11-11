/**
 * Request bodies for the calculation-scoped activity-feature routes
 * (`/api/yearly-activities/calculations/{id}/activity-features`, YEARLY_ACTIVITIES plan §5.1).
 *
 * The workspace draws GeoJSON features; the server wants the activity, the geometry as a string and the
 * years. The plan line, its year rows and the feature are then created together, server side.
 */

export interface ActivityFeatureInput {
  geometry: { type: string; coordinates: unknown };
  properties?: Record<string, unknown> | null;
}

const FEATURE_TYPE: Record<string, 'point' | 'line' | 'polygon'> = {
  Point: 'point',
  LineString: 'line',
  Polygon: 'polygon',
};

const numberList = (value: unknown): number[] | undefined =>
  Array.isArray(value) ? value.map(Number).filter((n) => Number.isFinite(n)) : undefined;

const optionalNumber = (value: unknown): number | undefined => {
  if (value === null || value === undefined || value === '') return undefined;
  const n = Number(value);
  return Number.isFinite(n) ? n : undefined;
};

const optionalText = (value: unknown): string | undefined =>
  typeof value === 'string' && value.trim() ? value : undefined;

/** Body of `POST …/activity-features`. The activity must be known: it decides the plan line. */
export function activityFeatureCreateBody(feature: ActivityFeatureInput): Record<string, unknown> {
  const props = feature.properties ?? {};
  const featureType = FEATURE_TYPE[feature.geometry?.type];
  if (!featureType) throw new Error(`Unsupported geometry type: ${feature.geometry?.type}`);
  const activityId = optionalNumber(props.potential_activity_id);
  if (activityId === undefined) throw new Error('Choose the activity before drawing its place');
  const body: Record<string, unknown> = {
    potential_activity_id: activityId,
    feature_type: featureType,
    geometry: JSON.stringify(feature.geometry),
  };
  const years = numberList(props.years);
  if (years && years.length > 0) body.years = years;
  const name = optionalText(props.name);
  if (name) body.name = name;
  const kind = optionalText(props.kind);
  if (kind) body.kind = kind;
  const quantity = optionalNumber(props.quantity);
  if (quantity !== undefined) body.quantity = quantity;
  const budget = optionalNumber(props.budget);
  if (budget !== undefined) body.budget = budget;
  if (props.plan_years === true) body.plan_years = true;
  return body;
}

/** Body of `PATCH …/activity-features/{id}`: only what was actually given. */
export function activityFeatureUpdateBody(
  feature: Pick<ActivityFeatureInput, 'properties'>,
): Record<string, unknown> {
  const props = feature.properties ?? {};
  const body: Record<string, unknown> = {};
  if ('name' in props) body.name = typeof props.name === 'string' ? props.name : '';
  const years = numberList(props.years);
  if (years) body.years = years;
  if ('kind' in props) body.kind = typeof props.kind === 'string' ? props.kind : '';
  const activityId = optionalNumber(props.potential_activity_id);
  if (activityId !== undefined) body.potential_activity_id = activityId;
  if (props.plan_years === true) body.plan_years = true;
  return body;
}

/** A readable message from a FastAPI error body (`detail` is a string, a `{code}` object or a list). */
export function apiErrorMessage(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    const code = (detail as { code?: unknown }).code;
    if (typeof code === 'string') return code;
  }
  return `Request failed (${status})`;
}

/**
 * An error from the activity-feature routes that keeps what the server said in structured form, so a caller
 * can act on it (for example offer to plan a year the activity is not planned in) instead of showing a code.
 */
export class ActivityFeatureApiError extends Error {
  readonly code: string | undefined;

  readonly years: number[];

  readonly status: number;

  constructor(body: unknown, status: number) {
    super(apiErrorMessage(body, status));
    this.name = 'ActivityFeatureApiError';
    this.status = status;
    const detail = (body as { detail?: unknown } | null)?.detail;
    const obj = detail && typeof detail === 'object' && !Array.isArray(detail) ? (detail as Record<string, unknown>) : {};
    this.code = typeof obj.code === 'string' ? obj.code : undefined;
    this.years = Array.isArray(obj.years) ? obj.years.map(Number).filter((n) => Number.isFinite(n)) : [];
  }
}

/** The server refused because these years are not planned for the activity ("plan them too?"). */
export const YEAR_NOT_PLANNED = 'YEAR_NOT_PLANNED';
