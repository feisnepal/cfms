import { describe, expect, it } from 'vitest';
import {
  activityFeatureCreateBody,
  activityFeatureUpdateBody,
  apiErrorMessage,
} from '../activityFeaturePayload';

const point = { type: 'Point', coordinates: [85.05, 27.44] };

describe('activityFeatureCreateBody', () => {
  it('maps a drawn GeoJSON feature to the facade body, geometry as a string', () => {
    const body = activityFeatureCreateBody({
      geometry: point,
      properties: {
        potential_activity_id: 4,
        years: [1, 2],
        name: 'Ward 3 nursery',
        kind: 'nursery',
        quantity: 2,
        budget: 60000,
      },
    });
    expect(body).toEqual({
      potential_activity_id: 4,
      feature_type: 'point',
      geometry: JSON.stringify(point),
      years: [1, 2],
      name: 'Ward 3 nursery',
      kind: 'nursery',
      quantity: 2,
      budget: 60000,
    });
  });

  it('maps the three geometry types', () => {
    const type = (g: string) =>
      activityFeatureCreateBody({
        geometry: { type: g, coordinates: [] },
        properties: { potential_activity_id: 1 },
      }).feature_type;
    expect(type('Point')).toBe('point');
    expect(type('LineString')).toBe('line');
    expect(type('Polygon')).toBe('polygon');
  });

  it('keeps a budget of 0 (a real value) and leaves out what was not given', () => {
    const body = activityFeatureCreateBody({
      geometry: point,
      properties: { potential_activity_id: 4, budget: 0 },
    });
    expect(body.budget).toBe(0);
    expect(body).not.toHaveProperty('quantity');
    expect(body).not.toHaveProperty('years');
    expect(body).not.toHaveProperty('name');
  });

  it('refuses to draw without an activity, and refuses an unsupported geometry', () => {
    expect(() => activityFeatureCreateBody({ geometry: point, properties: {} })).toThrow(/activity/i);
    expect(() =>
      activityFeatureCreateBody({
        geometry: { type: 'MultiPolygon', coordinates: [] },
        properties: { potential_activity_id: 1 },
      }),
    ).toThrow(/Unsupported/);
  });

  it('passes plan_years only when it is true', () => {
    const withIt = activityFeatureCreateBody({
      geometry: point,
      properties: { potential_activity_id: 1, plan_years: true },
    });
    const without = activityFeatureCreateBody({
      geometry: point,
      properties: { potential_activity_id: 1, plan_years: false },
    });
    expect(withIt.plan_years).toBe(true);
    expect(without).not.toHaveProperty('plan_years');
  });
});

describe('activityFeatureUpdateBody', () => {
  it('sends only the fields that were given', () => {
    expect(activityFeatureUpdateBody({ properties: { name: 'New name' } })).toEqual({ name: 'New name' });
    expect(activityFeatureUpdateBody({ properties: { years: [2, 3] } })).toEqual({ years: [2, 3] });
    expect(activityFeatureUpdateBody({ properties: {} })).toEqual({});
  });

  it('a cleared name or symbol is sent as empty so the server falls back to the default', () => {
    expect(activityFeatureUpdateBody({ properties: { name: '', kind: '' } })).toEqual({ name: '', kind: '' });
  });

  it('can move a feature to another activity', () => {
    expect(activityFeatureUpdateBody({ properties: { potential_activity_id: '9' } })).toEqual({
      potential_activity_id: 9,
    });
  });
});

describe('apiErrorMessage', () => {
  it('reads a string, a {code} object, and falls back to the status', () => {
    expect(apiErrorMessage({ detail: 'Plan line not found' }, 404)).toBe('Plan line not found');
    expect(apiErrorMessage({ detail: { code: 'YEAR_NOT_PLANNED', years: [4] } }, 422)).toBe('YEAR_NOT_PLANNED');
    expect(apiErrorMessage({ detail: [{ msg: 'x' }] }, 422)).toBe('Request failed (422)');
    expect(apiErrorMessage(null, 500)).toBe('Request failed (500)');
  });
});
