import { describe, it, expect } from 'vitest';
import { analysisMapFor, clampPosition, formatValue, unitLabel } from '../forestSummary';

describe('clampPosition', () => {
  const container = { width: 800, height: 600 };
  const panel = { width: 372 };
  it('leaves a position inside the container alone', () => {
    expect(clampPosition({ x: 40, y: 30 }, container, panel, 40)).toEqual({ x: 40, y: 30 });
  });
  it('never lets the header go above the container', () => {
    expect(clampPosition({ x: 10, y: -50 }, container, panel, 40).y).toBe(0);
  });
  it('keeps the header reachable at the bottom', () => {
    expect(clampPosition({ x: 10, y: 5000 }, container, panel, 40).y).toBe(560);
  });
  it('keeps a grab handle inside on both sides', () => {
    expect(clampPosition({ x: 5000, y: 0 }, container, panel, 40).x).toBe(752);
    expect(clampPosition({ x: -5000, y: 0 }, container, panel, 40).x).toBe(48 - 372);
  });
  it('does nothing before the container is laid out', () => {
    expect(clampPosition({ x: -9, y: 9999 }, { width: 0, height: 0 }, panel, 40)).toEqual({ x: -9, y: 9999 });
  });
});

describe('helpers', () => {
  it('formats big numbers whole and small ones with one decimal', () => {
    expect(formatValue(168.4)).toBe('168');
    expect(formatValue(8.24)).toBe('8.2');
    expect(formatValue(1234)).toMatch(/1.?234/);
  });
  it('writes units for display', () => {
    expect(unitLabel('m3/ha')).toBe('m³/ha');
    expect(unitLabel('tCO2e/ha')).toBe('tCO₂e/ha');
    expect(unitLabel('ha')).toBe('ha');
  });
  it('maps a tile source to an Analysis map only when it is one', () => {
    expect(analysisMapFor('fi_growing_stock')).toBe('fi_growing_stock');
    expect(analysisMapFor('hazard_prone')).toBe('hazard_prone');
    expect(analysisMapFor('user_group')).toBeNull();
    expect(analysisMapFor(null)).toBeNull();
  });
});
