import { describe, it, expect } from 'vitest';
import { pointsAreNonCollinear } from '../geometryValidation';

describe('pointsAreNonCollinear (U-4 / Task 4.1, case E)', () => {
  it('returns false for fewer than 3 points', () => {
    expect(pointsAreNonCollinear([])).toBe(false);
    expect(pointsAreNonCollinear([[0, 0]])).toBe(false);
    expect(pointsAreNonCollinear([[0, 0], [1, 0]])).toBe(false);
  });

  it('returns true for a non-collinear triangle', () => {
    expect(pointsAreNonCollinear([[0, 0], [1, 0], [0.5, 0.5]])).toBe(true);
  });

  it('returns true for a square', () => {
    expect(pointsAreNonCollinear([[0, 0], [1, 0], [1, 1], [0, 1]])).toBe(true);
  });

  it('returns false for collinear points along a line', () => {
    expect(pointsAreNonCollinear([[0, 0], [1, 0], [2, 0], [3, 0]])).toBe(false);
  });

  it('returns false for coincident/duplicate points (zero area)', () => {
    expect(pointsAreNonCollinear([[0, 0], [0, 0], [0, 0]])).toBe(false);
    expect(pointsAreNonCollinear([[1, 1], [1, 1], [2, 2]])).toBe(false);
  });
});
