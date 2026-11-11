import { describe, it, expect } from 'vitest';
import { analysisUnitStyle, resolveRendererStyle, ANALYSIS_UNIT_OUTLINE } from '../layerStyles';

describe('a unit coloured by an analysis map keeps a visible boundary', () => {
  const base = { color: '#112233', weight: 1, opacity: 0.8, fillColor: '#aaaaaa', fillOpacity: 0.5 };

  it('fills with the class colour but outlines in a dark, fully opaque line', () => {
    const s = analysisUnitStyle(base, '#2e7d32');
    expect(s.fillColor).toBe('#2e7d32');
    expect(s.color).toBe(ANALYSIS_UNIT_OUTLINE);
    expect(s.color).not.toBe(s.fillColor); // the old stroke was the fill's own colour, so the edge vanished
    expect(s.opacity).toBe(1);
    expect(s.weight).toBeGreaterThanOrEqual(1.6);
  });

  it('two neighbours of the same class still have an outline each', () => {
    const a = analysisUnitStyle(base, '#ffd92f');
    const b = analysisUnitStyle(base, '#ffd92f');
    expect(a.fillColor).toBe(b.fillColor);
    expect(a.color).toBe(ANALYSIS_UNIT_OUTLINE);
    expect(b.color).toBe(ANALYSIS_UNIT_OUTLINE);
  });

  it('keeps a thicker line the layer already had, and leaves the style alone when there is no colour', () => {
    expect(analysisUnitStyle({ ...base, weight: 3 }, '#2e7d32').weight).toBe(3);
    expect(analysisUnitStyle(base, null)).toBe(base);
  });

  it('other thematic renderers are unchanged: their stroke is still the fill colour', () => {
    const s = resolveRendererStyle(base, '#2e7d32');
    expect(s.color).toBe('#2e7d32');
    expect(s.fillColor).toBe('#2e7d32');
  });
});
