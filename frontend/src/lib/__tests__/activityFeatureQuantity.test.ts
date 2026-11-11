/**
 * The Quantity column of the Activity Features table (YEARLY_ACTIVITIES plan §5.2, YA-4.3): the quantity is the
 * plan LINE's, so places of one activity share it — and the cell must say so.
 */
import { describe, expect, it, vi } from 'vitest';

vi.mock('i18next', () => ({
  default: {
    language: 'en',
    t: (key: string, values: Record<string, unknown> = {}) =>
      ({
        'yearlyPlan.planTable.sharedTag': `shared ×${values.n}`,
        'yearlyPlan.planTable.sharedTitle': `all ${values.n} places share it`,
      })[key] ?? key,
  },
}));
vi.mock('../../i18n/numberFormat', () => ({ formatNumber: (n: number) => String(n), formatDecimal: (n: number) => String(n) }));

import { featureQuantityText, featureSharedCount, featureSharedTag, featureSharedTitle } from '../activityFeatureQuantity';
import { activityFeaturesFromApi, LAYER_REGISTRY } from '../layerRegistry';

describe('featureQuantityText', () => {
  it('shows the quantity with its unit and never rounds it', () => {
    expect(featureQuantityText({ plan_quantity: 4, plan_unit: 'ha' })).toBe('4 ha');
    expect(featureQuantityText({ plan_quantity: 0.5, plan_unit: 'ha' })).toBe('0.5 ha');
    expect(featureQuantityText({ plan_quantity: 2 })).toBe('2');
  });
  it('shows a real 0 as 0, and a quantity the server did not send as a dash', () => {
    expect(featureQuantityText({ plan_quantity: 0, plan_unit: 'km' })).toBe('0 km');
    expect(featureQuantityText({ plan_quantity: null })).toBe('-');
    expect(featureQuantityText({})).toBe('-');
    expect(featureQuantityText(null)).toBe('-');
  });
});

describe('the shared tag', () => {
  it('appears only when more than one place shares the quantity', () => {
    expect(featureSharedTag({ shared_count: 3 })).toBe('shared ×3');
    expect(featureSharedTitle({ shared_count: 3 })).toBe('all 3 places share it');
    for (const one of [{ shared_count: 1 }, { shared_count: 0 }, { shared_count: 'x' }, {}, null]) {
      expect(featureSharedTag(one as never)).toBe('');
      expect(featureSharedTitle(one as never)).toBe('');
      expect(featureSharedCount(one as never)).toBe(1);
    }
  });
});

describe('the Activity Features layer carries the quantity', () => {
  const api = [
    {
      id: 'f1',
      proposed_activity_id: 'L1',
      geometry: JSON.stringify({ type: 'Point', coordinates: [85, 27] }),
      properties: { name: 'A', years: [1] },
      activity_name: 'Nursery',
      plan_quantity: 4,
      plan_unit: 'ha',
      shared_count: 2,
    },
  ];

  it('passes the plan line, quantity, unit and shared count through to the feature', () => {
    const [f] = activityFeaturesFromApi(api);
    expect(f.properties).toMatchObject({ proposed_activity_id: 'L1', plan_quantity: 4, plan_unit: 'ha', shared_count: 2 });
  });

  it('the table has a Quantity column that shows the number, sorts by it, and tags a shared one', () => {
    const [f] = activityFeaturesFromApi(api);
    const col = LAYER_REGISTRY.activity_features.columns.find((c) => c.key === 'plan_quantity')!;
    expect(col).toBeTruthy();
    expect(col.labelKey).toBe('attributeTable.col.planQuantity');
    expect(col.getValue!(f, 0)).toBe('4 ha');
    expect(col.sortValue!(f)).toBe(4);
    const cell = col.render!(null, f) as { props: { children: unknown[] } };
    expect(JSON.stringify(cell)).toContain('shared ×2');
  });

  it('an unshared quantity has no tag', () => {
    const [f] = activityFeaturesFromApi([{ ...api[0], shared_count: 1 }]);
    const col = LAYER_REGISTRY.activity_features.columns.find((c) => c.key === 'plan_quantity')!;
    expect(JSON.stringify(col.render!(null, f))).not.toContain('shared');
  });
});
