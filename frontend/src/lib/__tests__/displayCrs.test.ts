import { describe, it, expect } from 'vitest';
import { DISPLAY_CRS, formatCoords, parseCoords } from '../displayCrs';

describe('displayCrs (Gap 2)', () => {
  it('has default EPSG:4326', () => {
    expect(DISPLAY_CRS.epsg).toBe(4326);
    expect(DISPLAY_CRS.unit).toBe('degrees');
  });

  it('formatCoords formats to 6 decimal places', () => {
    expect(formatCoords({ lat: 27.5123456, lng: 83.5678912 })).toBe('27.512346, 83.567891');
    expect(formatCoords({ lat: NaN, lng: 0 })).toBe('—, —');
  });

  it('parseCoords parses comma or space-separated lat/lng correctly', () => {
    expect(parseCoords('27.5, 83.5')).toEqual({ lat: 27.5, lng: 83.5 });
    expect(parseCoords(' 27.5   83.5 ')).toEqual({ lat: 27.5, lng: 83.5 });
    expect(parseCoords('invalid')).toBeNull();
    expect(parseCoords('91, 0')).toBeNull(); // out of range lat
    expect(parseCoords('0, 181')).toBeNull(); // out of range lng
  });
});
