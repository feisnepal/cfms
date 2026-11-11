import { describe, it, expect, beforeEach } from 'vitest';
import { ATTRIBUTION, BUFFER_CHOICES_M, DEFAULT_BUFFER_M, layerLabel, licenceState, pathStyle, pointRadius, popupContent, readSaved, writeSaved } from '../referenceLayers';

const info = (over: Record<string, unknown> = {}) => ({ geometry: 'line', style: { color: '#1e88e5', weight: 1.6, opacity: 0.9 }, ...over }) as any;

describe('how a layer is drawn', () => {
  it('draws a line with no fill, and keeps its dash', () => {
    expect(pathStyle(info({ style: { color: '#8d6e63', weight: 1.4, dashArray: '6 3' } }))).toMatchObject({ color: '#8d6e63', weight: 1.4, fill: false, dashArray: '6 3' });
  });
  it('fills a polygon only when its style asks for a fill', () => {
    expect(pathStyle(info({ geometry: 'polygon', style: { color: '#7b1fa2', fillOpacity: 0 } })).fill).toBe(false);
    expect(pathStyle(info({ geometry: 'polygon', style: { color: '#2e7d32', fillColor: '#66bb6a', fillOpacity: 0.12 } }))).toMatchObject({ fill: true, fillColor: '#66bb6a', fillOpacity: 0.12 });
  });
  it('falls back to a plain style for a layer that gave none', () => {
    expect(pathStyle(info({ geometry: 'polygon', style: {} }))).toMatchObject({ color: '#607d8b', weight: 1.5, fill: true });
    expect(pointRadius({ style: { radius: 6 } } as any)).toBe(6);
    expect(pointRadius({ style: {} } as any)).toBe(4);
  });
});

describe('names and licences', () => {
  it('uses the Nepali name in Nepali and the English one otherwise', () => {
    const l = { label_en: 'Rivers', label_ne: 'नदी' };
    expect(layerLabel(l, 'ne')).toBe('नदी');
    expect(layerLabel(l, 'ne-NP')).toBe('नदी');
    expect(layerLabel(l, 'en')).toBe('Rivers');
    expect(layerLabel(l, undefined)).toBe('Rivers');
  });
  it('says confirmed only when the server gave a licence', () => {
    expect(licenceState({ licence: 'ODbL 1.0' })).toEqual({ confirmed: true, name: 'ODbL 1.0' });
    expect(licenceState({ licence: null })).toEqual({ confirmed: false, name: null });
  });
  it('asks for the OpenStreetMap credit for the roads, and for nothing it does not know', () => {
    expect(ATTRIBUTION.roads).toContain('OpenStreetMap contributors');
    expect(ATTRIBUTION.rivers).toBeUndefined();
  });
});

describe('what is remembered for a forest', () => {
  beforeEach(() => localStorage.clear());
  it('starts with everything off and the default distance', () => {
    expect(readSaved('c1')).toEqual({ visible: [], bufferM: DEFAULT_BUFFER_M });
    expect(readSaved(undefined)).toEqual({ visible: [], bufferM: DEFAULT_BUFFER_M });
  });
  it('remembers the layers and the distance per forest', () => {
    writeSaved('c1', { visible: ['rivers', 'roads'], bufferM: 5000 });
    expect(readSaved('c1')).toEqual({ visible: ['rivers', 'roads'], bufferM: 5000 });
    expect(readSaved('c2')).toEqual({ visible: [], bufferM: DEFAULT_BUFFER_M });
  });
  it('ignores what it cannot trust: a distance that is not a choice, junk, a broken value', () => {
    writeSaved('c1', { visible: ['rivers'], bufferM: 123456 });
    expect(readSaved('c1')).toEqual({ visible: ['rivers'], bufferM: DEFAULT_BUFFER_M });
    localStorage.setItem('cf_reference_layers_c1', '{not json');
    expect(readSaved('c1')).toEqual({ visible: [], bufferM: DEFAULT_BUFFER_M });
    localStorage.setItem('cf_reference_layers_c1', JSON.stringify({ visible: ['x', 5, null], bufferM: 1000 }));
    expect(readSaved('c1').visible).toEqual(['x']);
    expect(BUFFER_CHOICES_M).toContain(DEFAULT_BUFFER_M);
  });
});

describe('the popup of a feature', () => {
  it('shows its values as text, leaving out the internal ones and the empty ones', () => {
    const el = popupContent('Test Khola', { name: 'Test Khola', length_m: 900, surface: null, width: '  ', _ref: 'rivers-0', _label: 'x' });
    expect(el.querySelector('strong')!.textContent).toBe('Test Khola');
    const rows = Array.from(el.querySelectorAll('tr')).map((tr) => [tr.querySelector('th')!.textContent, tr.querySelector('td')!.textContent]);
    expect(rows).toEqual([['Name', 'Test Khola'], ['Length m', '900']]);
  });
  it('never turns a value into markup', () => {
    const el = popupContent('<img src=x onerror=alert(1)>', { name: '<script>alert(1)</script>' });
    expect(el.querySelector('img')).toBeNull();
    expect(el.querySelector('script')).toBeNull();
    expect(el.textContent).toContain('<script>alert(1)</script>');     // shown as the characters it is made of
  });
  it('is just the title when there is nothing else to show', () => {
    expect(popupContent('Buildings', { _ref: 'b-0', area_sqm: null }).querySelector('table')).toBeNull();
  });
});
