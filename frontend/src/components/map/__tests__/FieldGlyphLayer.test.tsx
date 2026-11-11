import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { createElement } from 'react';
import { GlyphHover, glyphHeight, glyphIconHtml, glyphLabel, safeColour } from '../FieldGlyphLayer';
import type { GlyphUnit } from '../../../hooks/useFieldGlyphs';

const seg = (index: number, key: string, value: number, color: string) => ({
  index, key, label_ne: key, label_en: `Class ${key}`, value, color,
});
const unit = (over: Partial<GlyphUnit> = {}): GlyphUnit => ({
  name: 'blocks-3', anchor: [84.1, 27.9], total_m3_per_ha: 80.1, ge40_pct: 56, plots: 4,
  segments: [seg(3, '20_30', 13.9, '#aaaaaa'), seg(4, '30_40', 21.3, '#bbbbbb'), seg(5, '40_50', 38.2, '#cccccc'), seg(6, '50_60', 6.7, '#dddddd')],
  ...over,
});

describe('field glyph — the timber-by-size bar', () => {
  it('height follows the stock against the forest richest unit, with a floor', () => {
    expect(glyphHeight(80, 80)).toBe(46);
    expect(glyphHeight(40, 80)).toBe(23);
    expect(glyphHeight(0.5, 80)).toBe(6); // a poor unit is short, never invisible
    expect(glyphHeight(0, 80)).toBe(6);
    expect(glyphHeight(10, 0)).toBe(6);
  });

  it('the label is compact and grows with the zoom: none, the stock, then stock and the share at 40 cm and above', () => {
    expect(glyphLabel(unit(), 12)).toBe('');
    expect(glyphLabel(unit(), 14)).toBe('80');
    expect(glyphLabel(unit(), 16)).toBe('80 m³/ha · 56% ≥40');
    expect(glyphLabel(unit({ ge40_pct: null, total_m3_per_ha: 0 }), 17)).toBe('0 m³/ha');
  });

  it('draws one rect per class present, in the server colours, the small classes at the bottom', () => {
    const { html, h } = glyphIconHtml(unit(), 80.1, 15);
    expect(h).toBe(46);
    for (const c of ['#aaaaaa', '#bbbbbb', '#cccccc', '#dddddd']) expect(html).toContain(`fill="${c}"`);
    expect((html.match(/<rect /g) ?? []).length).toBe(4);
    const y = (c: string) => Number(new RegExp('y="([0-9.]+)"[^>]*fill="' + c + '"').exec(html)![1]);
    expect(y('#aaaaaa')).toBeGreaterThan(y('#bbbbbb')); // SVG y grows downward: a larger y is LOWER on screen
    expect(y('#bbbbbb')).toBeGreaterThan(y('#cccccc'));
    expect(y('#cccccc')).toBeGreaterThan(y('#dddddd')); // so the first (smallest) class is at the bottom
  });

  it('a unit with a summary but no timber is an empty outline, not a gap', () => {
    const { html } = glyphIconHtml(unit({ total_m3_per_ha: 0, ge40_pct: null, segments: [] }), 80, 15);
    expect(html).toContain('stroke-dasharray');
    expect(html).not.toContain('fill="#');
  });

  it('a class a forest does not have is simply absent (any class may be empty)', () => {
    const only = unit({ segments: [seg(0, '0_4', 5, '#111111')], total_m3_per_ha: 5 });
    expect((glyphIconHtml(only, 80, 15).html.match(/<rect /g) ?? []).length).toBe(1);
  });

  it('a unit name is user text: it is rendered as text, never as markup', () => {
    render(createElement(GlyphHover, { u: unit({ name: '<script>alert(1)</script>' }), lang: 'en' }));
    const card = screen.getByTestId('glyph-hover');
    expect(card.querySelector('script')).toBeNull();
    expect(card.textContent).toContain('<script>alert(1)</script>');
    expect(card.textContent).toContain('Class 50_60');
  });

  it('the hover card follows the language', () => {
    render(createElement(GlyphHover, { u: unit(), lang: 'ne' }));
    expect(screen.getByTestId('glyph-hover').textContent).toContain('50_60');
    expect(screen.getByTestId('glyph-hover').textContent).not.toContain('Class');
  });

  it('only a plain #rrggbb ever reaches the SVG', () => {
    expect(safeColour('#74c476')).toBe('#74c476');
    expect(safeColour('red" onload="x')).toBe('#bdbdbd');
    const { html } = glyphIconHtml(unit({ segments: [seg(0, '0_4', 5, 'red" onload="x')], total_m3_per_ha: 5 }), 80, 15);
    expect(html).not.toContain('onload');
  });
});

const withSegs = (segs: Array<[string, number]>, over: Partial<GlyphUnit> = {}): GlyphUnit =>
  unit({ segments: segs.map(([k, v], i) => seg(i, k, v, ['#111111', '#222222', '#333333', '#444444'][i % 4])), ...over });

describe('field glyph — the other shapes', () => {
  it('a pie has one wedge per class present; a single class is a full disc; no data is a dashed outline', () => {
    expect((glyphIconHtml(withSegs([['a', 30], ['b', 70]]), 100, 15, 'pie').html.match(/<path /g) ?? []).length).toBe(2);
    const one = glyphIconHtml(withSegs([['a', 30]]), 100, 15, 'pie').html;
    expect(one).toContain('<circle');
    expect(one).not.toContain('<path');
    expect(glyphIconHtml(withSegs([]), 100, 15, 'pie').html).toContain('stroke-dasharray');
  });
  it('a waffle always has 25 cells: the classes by share, the rest pale', () => {
    const { html } = glyphIconHtml(withSegs([['a', 60], ['b', 40]]), 100, 15, 'waffle');
    expect((html.match(/<rect /g) ?? []).length).toBe(25);
    expect((html.match(/fill="#111111"/g) ?? []).length).toBe(15);
    expect((html.match(/fill="#222222"/g) ?? []).length).toBe(10);
    expect(glyphIconHtml(withSegs([]), 100, 15, 'waffle').html).toContain('#eeeeee');
  });
  it('a sparkline is a polyline through every class, high values high; flat zero is a dashed baseline', () => {
    const { html } = glyphIconHtml(withSegs([['a', 100], ['b', 10], ['c', 1]]), 100, 15, 'sparkline');
    const pts = /points="([^"]+)"/.exec(html)![1].split(' ').map((p) => Number(p.split(',')[1]));
    expect(pts).toHaveLength(3);
    expect(pts[0]).toBeLessThan(pts[1]); // SVG y grows downward: the largest class is drawn highest
    expect(pts[1]).toBeLessThan(pts[2] + 0.001);
    expect(glyphIconHtml(withSegs([['a', 0], ['b', 0]]), 100, 15, 'sparkline').html).toContain('stroke-dasharray');
  });
  it('a ternary dot sits nearest the corner of the stage that dominates', () => {
    const cx = (v: Array<[string, number]>) => Number(/<circle cx="([0-9.]+)"/.exec(glyphIconHtml(withSegs(v), 100, 15, 'ternary').html)![1]);
    const left = cx([['regeneration', 0], ['pole', 100], ['tree', 0]]);
    const right = cx([['regeneration', 0], ['pole', 0], ['tree', 100]]);
    const top = cx([['regeneration', 100], ['pole', 0], ['tree', 0]]);
    expect(left).toBeLessThan(top);
    expect(top).toBeLessThan(right);
  });
  it('a radar draws one vertex per axis, scaled by the server fraction', () => {
    const { html } = glyphIconHtml(unit({ segments: [], radar: [1, 0.5, 0, 0.25, 1] }), 0, 15, 'radar');
    expect(/points="([^"]+)"/.exec(html)![1].split(' ')).toHaveLength(5);
    expect(html).toContain('<polygon');
  });
  it('the label comes from the server: short from zoom 14, long from 16, nothing below 14', () => {
    const u = unit({ text_short: '4,530', text_long: '4,530 stems/ha' });
    expect([glyphLabel(u, 13), glyphLabel(u, 14), glyphLabel(u, 15), glyphLabel(u, 16)]).toEqual(['', '4,530', '4,530', '4,530 stems/ha']);
    expect(glyphLabel(unit({ text_short: '', text_long: '12 · 3 · 85 %' }), 14)).toBe('');
  });
  it('the radar hover names every axis', () => {
    render(createElement(GlyphHover, { u: unit({ segments: [], radar: [1, 0.5] }), lang: 'en', axes: [{ label_ne: 'क', label_en: 'Condition' }, { label_ne: 'ख', label_en: 'Carbon' }] }));
    const t = screen.getByTestId('glyph-hover').textContent!;
    expect(t).toContain('Condition: 100%');
    expect(t).toContain('Carbon: 50%');
  });
});

