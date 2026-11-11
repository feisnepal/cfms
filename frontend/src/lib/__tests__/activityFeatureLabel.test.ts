import { describe, it, expect } from 'vitest';
import {
  activityFeatureBase,
  activityFeatureLabel,
  disambiguateLabels,
  featureYears,
  formatYears,
  type Translate,
} from '../activityFeatureLabel';
import { activityFeaturesFromApi } from '../layerRegistry';

// English wording, keyed the way the app's i18n is, so a test reads the label a user would.
const t: Translate = (key, o) => {
  const opts = (o ?? {}) as Record<string, unknown>;
  if (key === 'yearlyActivities.page.yearN') return `Year ${opts.year}`;
  if (key === 'yearlyActivities.page.yearsN') return `Years ${opts.years}`;
  if (key === 'layer.activityFeatureFallback') return 'Activity feature';
  return key;
};
const format = (n: number) => String(n);
const opts = { t, format };

describe('formatYears', () => {
  it('lists separate years and folds three or more in a row into a range', () => {
    expect(formatYears([1, 2, 4], format)).toBe('1, 2, 4');
    expect(formatYears([1, 2, 3, 4], format)).toBe('1–4');
    expect(formatYears([1, 2, 3, 5, 6, 9], format)).toBe('1–3, 5, 6, 9');
  });

  it('sorts, drops duplicates and ignores junk', () => {
    expect(formatYears([4, 1, 1, 2, NaN], format)).toBe('1, 2, 4');
    expect(formatYears([], format)).toBe('');
  });
});

describe('featureYears', () => {
  it('reads `years`, falling back to the older single `year`', () => {
    expect(featureYears({ years: [1, 2] })).toEqual([1, 2]);
    expect(featureYears({ year: 3 })).toEqual([3]);
    expect(featureYears({})).toEqual([]);
    expect(featureYears(null)).toEqual([]);
  });
});

describe('activityFeatureBase — what the feature is called', () => {
  it('uses the activity when the name is the old "Feature N" counter', () => {
    expect(activityFeatureBase({ name: 'Feature 1', activity_name: 'Nursery' }, t)).toBe('Nursery');
    expect(activityFeatureBase({ name: ' feature 12 ', activity_name: 'Nursery' }, t)).toBe('Nursery');
  });

  it('uses the activity when the name is just the activity saved as the default', () => {
    expect(activityFeatureBase({ name: 'Nursery', activity_name: 'Nursery' }, t)).toBe('Nursery');
  });

  it('keeps a name the user typed', () => {
    expect(activityFeatureBase({ name: 'Baseshi plot', activity_name: 'Plantation' }, t)).toBe('Baseshi plot');
  });

  it('falls back to a generic label when the feature knows nothing', () => {
    expect(activityFeatureBase({}, t)).toBe('Activity feature');
    expect(activityFeatureBase({ name: 'Feature 3' }, t)).toBe('Activity feature');
  });
});

describe('activityFeatureLabel — "<activity> · year(s)"', () => {
  it('names the activity and the year', () => {
    expect(activityFeatureLabel({ name: 'Feature 1', activity_name: 'Nursery', years: [1] }, opts)).toBe('Nursery · Year 1');
  });

  it('several years read as "Years …", with runs compressed', () => {
    expect(activityFeatureLabel({ activity_name: 'Nursery', years: [1, 2, 4] }, opts)).toBe('Nursery · Years 1, 2, 4');
    expect(activityFeatureLabel({ activity_name: 'Nursery', years: [1, 2, 3, 4] }, opts)).toBe('Nursery · Years 1–4');
  });

  it('a typed name stays and gains the year', () => {
    expect(activityFeatureLabel({ name: 'Baseshi plot', activity_name: 'Plantation', years: [2] }, opts)).toBe('Baseshi plot · Year 2');
  });

  it('no year, no suffix', () => {
    expect(activityFeatureLabel({ activity_name: 'Nursery' }, opts)).toBe('Nursery');
  });

  it('uses the digits the caller formats with (Devanagari, say)', () => {
    const dev = (n: number) => String(n).replace(/\d/g, (d) => '०१२३४५६७८९'[Number(d)]);
    expect(activityFeatureLabel({ activity_name: 'नर्सरी निर्माण', years: [1] }, { t, format: dev })).toBe('नर्सरी निर्माण · Year १');
  });
});

describe('disambiguateLabels', () => {
  it('leaves unique labels alone', () => {
    expect(disambiguateLabels([{ label: 'A · Year 1' }, { label: 'B · Year 1' }], format)).toEqual(['A · Year 1', 'B · Year 1']);
  });

  it('numbers identical labels, oldest first, whatever order they arrive in', () => {
    const items = [
      { label: 'Nursery · Year 1', createdAt: '2026-09-02' },
      { label: 'Seed orchard · Year 1', createdAt: '2026-09-01' },
      { label: 'Nursery · Year 1', createdAt: '2026-09-01' },
    ];
    expect(disambiguateLabels(items, format)).toEqual([
      'Nursery · Year 1 (2)',
      'Seed orchard · Year 1',
      'Nursery · Year 1 (1)',
    ]);
  });
});

describe('the Activity Features layer, end to end', () => {
  const row = (id: string, name: string, years: number[], activity: string, created: string) => ({
    id,
    proposed_activity_id: 'a',
    feature_type: 'point',
    geometry: JSON.stringify({ type: 'Point', coordinates: [85, 27] }),
    properties: { name, years },
    activity_name: activity,
    program_name: 'Forest development',
    block_name: null,
    created_at: created,
  });

  it('labels the features from the real data shape — no more Feature 1 / Feature 2', () => {
    const feats = activityFeaturesFromApi(
      [
        row('1', 'Feature 1', [1], 'Nursery', '2026-09-01'),
        row('2', 'Feature 2', [1], 'Nursery', '2026-09-02'),
        row('3', 'Feature 1', [1, 2, 4], 'Nursery', '2026-09-03'),
        row('4', 'Feature 2', [1], 'Seed orchard', '2026-09-04'),
        row('5', 'Baseshi plantation ', [1], 'Plantation', '2026-09-05'),
      ],
      opts,
    );

    expect(feats.map((f) => f.properties?.display_label)).toEqual([
      'Nursery · Year 1 (1)',
      'Nursery · Year 1 (2)',
      'Nursery · Years 1, 2, 4',
      'Seed orchard · Year 1',
      'Baseshi plantation · Year 1',
    ]);
    expect(feats[0].properties).toMatchObject({ activity_name: 'Nursery', program_name: 'Forest development' });
  });
});
