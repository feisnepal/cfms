import { describe, it, expect } from 'vitest';
import { distanceBetween, bearingBetween, destinationPoint } from '../coordinateMath';

describe('coordinateMath (Gap 5.1)', () => {
  const kathmandu = { lat: 27.7172, lng: 85.3240 };

  it('calculates distance between points correctly', () => {
    const pt2 = { lat: 27.7272, lng: 85.3240 }; // ~1.11 km north
    const dist = distanceBetween(kathmandu, pt2);
    expect(dist).toBeGreaterThan(1100);
    expect(dist).toBeLessThan(1120);
  });

  it('calculates bearing between points correctly', () => {
    const ptNorth = { lat: 28.0, lng: 85.3240 };
    const bearing = bearingBetween(kathmandu, ptNorth);
    expect(bearing).toBeCloseTo(0, 1);
  });

  it('destinationPoint great-circle round-trip works', () => {
    const dest = destinationPoint(kathmandu, 90, 1000); // 1 km east
    const distBack = distanceBetween(kathmandu, dest);
    expect(distBack).toBeCloseTo(1000, 0);
  });
});
