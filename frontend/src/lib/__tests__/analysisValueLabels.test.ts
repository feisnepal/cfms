import { describe, expect, it } from 'vitest';
import { analysisDisplayValue } from '../analysisValueLabels';
import { SLOPE_BAND_LABEL } from '../layerRegistry';

describe('analysis values in plain language', () => {
  it('shows a slope class code as its name and the अनुसूची-१ degrees, never a bare number', () => {
    expect(analysisDisplayValue('slope_min_code', 1)).toBe('Gentle (<19°)');
    expect(analysisDisplayValue('slope_max_code', '3')).toBe('Steep (31–45°)');
    expect(analysisDisplayValue('slope_max_code', 4)).toBe('Very steep (>45°)');
    expect(analysisDisplayValue('slope_dominant_class', 'very_steep')).toBe('Very steep (>45°)');
  });

  it('rewrites the slope breakdown text class by class', () => {
    expect(analysisDisplayValue('slope_percentages', 'gentle 48.67%; moderate 38.94%; steep 12.39%')).toBe(
      'Gentle (<19°) 48.67%; Moderate (19–31°) 38.94%; Steep (31–45°) 12.39%',
    );
  });

  it('uses the same degrees as the table\'s Slope Class column', () => {
    const bands = ['gentle', 'moderate', 'steep', 'very_steep'].map((k) => analysisDisplayValue('slope_dominant_class', k)!.match(/\((.*)\)/)![1]);
    expect(bands.map((b) => b.replace(/\s/g, ''))).toEqual([1, 2, 3, 4].map((c) => SLOPE_BAND_LABEL[c].replace(/\s/g, '')));
  });

  it('shows canopy, aspect and fertility classes with their heights, directions and score bands', () => {
    expect(analysisDisplayValue('canopy_dominant_class', 'pole_trees')).toBe('Pole trees (6–15 m)');
    expect(analysisDisplayValue('canopy_percentages', 'pole_trees 61.63%; tree 23.84%; regeneration 11.26%; non_forest 3.27%')).toBe(
      'Pole trees (6–15 m) 61.63%; Trees (>15 m) 23.84%; Regeneration (2–5 m) 11.26%; Non-forest (≤1 m) 3.27%',
    );
    expect(analysisDisplayValue('aspect_dominant', 'SE')).toBe('South-east');
    expect(analysisDisplayValue('aspect_percentages', 'S 45.86%; SE 33.08%')).toBe('South 45.86%; South-east 33.08%');
    expect(analysisDisplayValue('fertility_class', 'very_low')).toBe('Very low (<20)');
    expect(analysisDisplayValue('fertility_class', 'High')).toBe('High (score 80+)');
  });

  it('says "Not mapped" where the forest-type layer has no data, instead of "Data Not Available"', () => {
    expect(analysisDisplayValue('forest_type_dominant', 'Data Not Available')).toBe('Not mapped');
    expect(analysisDisplayValue('forest_type_percentages', 'Data Not Available 51.33%; Tropical Mixed Broadleaved Forest 35.4%')).toBe(
      'Not mapped 51.33%; Tropical Mixed Broadleaved Forest 35.4%',
    );
  });

  it('leaves other values, blanks and unknown codes as stored', () => {
    expect(analysisDisplayValue('elevation_mean_m', 684.1)).toBe('684.1');
    expect(analysisDisplayValue('slope_min_code', null)).toBeNull();
    expect(analysisDisplayValue('slope_min_code', 9)).toBe('9');
  });
});
