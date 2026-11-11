import { describe, expect, it } from 'vitest';
import {
  EMPTY_PARTS, composeNationalCode, divisionLabel, divisionsOf, isCompleteNationalCode, localsOf, parseNationalCode,
  type NationalCodeProvince,
} from '../cfNationalCode';

const REF: NationalCodeProvince[] = [
  {
    name: 'Koshi', code: 'KOS',
    divisions: [{ name: 'Taplejung', code: 'TAP', districts: ['Taplejung'], locals: [{ name: 'Phaktanglung', no: '01', district: 'Taplejung' }] }],
  },
  {
    name: 'Sudurpashchim', code: 'SUD',
    divisions: [
      { name: 'Kailai Dhangadhi', code: 'KAI', districts: ['Kailai'], locals: [{ name: 'Chure', no: '09', district: 'Kailai' }] },
      { name: 'Kailai Pahalmanpur', code: 'KLP', districts: ['Kailai'], locals: [{ name: 'Mohanyal', no: '01', district: 'Kailai' }] },
    ],
  },
];

describe('Schedule 11 national database code', () => {
  it('composes the code and shows what is still missing', () => {
    expect(composeNationalCode({ province: 'KOS', division: 'TAP', subDivision: 'ab', localNo: '1', serial: '7' })).toBe('KOS/TAP/AB/01/7');
    expect(composeNationalCode({ ...EMPTY_PARTS, province: 'KOS', division: 'TAP' })).toBe('KOS/TAP/__/__/___');
    expect(composeNationalCode(EMPTY_PARTS)).toBe('___/___/__/__/___');
  });

  it('is complete only when every part is chosen and well formed', () => {
    expect(isCompleteNationalCode({ province: 'KOS', division: 'TAP', subDivision: 'AB', localNo: '01', serial: '007' })).toBe(true);
    expect(isCompleteNationalCode({ province: 'KOS', division: 'TAP', subDivision: '', localNo: '01', serial: '007' })).toBe(false);
    expect(isCompleteNationalCode({ province: 'KOS', division: 'TAP', subDivision: 'AB', localNo: '01', serial: '' })).toBe(false);
  });

  it('splits an existing code, and refuses one that does not follow the format', () => {
    expect(parseNationalCode('KOS/TAP/AB/01/007')).toEqual({ province: 'KOS', division: 'TAP', subDivision: 'AB', localNo: '01', serial: '007' });
    expect(parseNationalCode('MAK/PH/42/33')).toBeNull();
    expect(parseNationalCode('')).toBeNull();
    expect(parseNationalCode(null)).toBeNull();
  });

  it('lists divisions of a province and local levels of a division (a district can have two divisions)', () => {
    expect(divisionsOf(REF, 'SUD').map((d) => d.code)).toEqual(['KAI', 'KLP']);
    expect(localsOf(REF, 'SUD', 'KLP').map((l) => l.name)).toEqual(['Mohanyal']);
    expect(localsOf(REF, 'SUD', 'NOPE')).toEqual([]);
    expect(divisionsOf(REF, 'XXX')).toEqual([]);
  });

  it('names the district next to a division whose name differs from it', () => {
    expect(divisionLabel(REF[0].divisions[0])).toBe('Taplejung (TAP)');
    expect(divisionLabel(REF[1].divisions[0])).toBe('Kailai Dhangadhi (KAI) - Kailai');
  });
});
