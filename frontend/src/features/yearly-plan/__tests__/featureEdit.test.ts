/**
 * Editing a drawn place from the table (P2): one saved edit = one undo entry; a refused edit leaves none; an
 * unplanned year is only planned when the person says yes.
 */
import { describe, expect, it, vi, type Mock } from 'vitest';
import { ActivityFeatureApiError } from '../../../lib/activityFeaturePayload';
import { parseYears, saveActivityFeatureEdit, type FeatureEditDeps } from '../featureEdit';

const feature = (props: Record<string, unknown> = {}): GeoJSON.Feature => ({
  type: 'Feature',
  geometry: { type: 'Point', coordinates: [85, 27] },
  properties: { id: 'f1', name: 'Nursery A', years: [1, 2], kind: 'nursery', activity_name: 'नर्सरी निर्माण', ...props },
});

type MockedDeps = FeatureEditDeps & { update: Mock; confirmPlanYears: Mock; pushOp: Mock; refresh: Mock; report: Mock };

function deps(over: Partial<Record<keyof FeatureEditDeps, unknown>> = {}): MockedDeps {
  return {
    calcId: 'c1',
    update: vi.fn().mockResolvedValue({}),
    confirmPlanYears: vi.fn().mockResolvedValue(true),
    pushOp: vi.fn(),
    refresh: vi.fn(),
    report: vi.fn(),
    ...over,
  } as MockedDeps;
}

const notPlanned = (years: number[]) =>
  new ActivityFeatureApiError({ detail: { code: 'YEAR_NOT_PLANNED', years } }, 422);

describe('parseYears', () => {
  it('sorts, drops duplicates and anything that is not a plan year', () => {
    expect(parseYears('3, 1,2,2')).toEqual([1, 2, 3]);
    expect(parseYears('0,11,x,,4')).toEqual([4]);
    expect(parseYears('')).toEqual([]);
  });
});

describe('name', () => {
  it('saves the trimmed name and remembers the old one for undo', async () => {
    const d = deps();
    expect(await saveActivityFeatureEdit(feature(), 'name', '  Nursery B ', d)).toBe('saved');
    expect(d.update).toHaveBeenCalledWith('f1', { properties: { name: 'Nursery B' } });
    const op = d.pushOp.mock.calls[0][0];
    expect(op).toMatchObject({
      kind: 'attribute_edit',
      layerId: 'activity_features',
      featureId: 'f1',
      previousPayload: { properties: { name: 'Nursery A' } },
      newPayload: { properties: { name: 'Nursery B' } },
    });
    expect(d.refresh).toHaveBeenCalled();
  });

  it('a blank name is sent as blank (the server falls back to the activity name)', async () => {
    const d = deps();
    await saveActivityFeatureEdit(feature(), 'name', '   ', d);
    expect(d.update).toHaveBeenCalledWith('f1', { properties: { name: '' } });
  });

  it('the same name is not saved again and leaves no undo entry', async () => {
    const d = deps();
    expect(await saveActivityFeatureEdit(feature(), 'name', 'Nursery A', d)).toBe('ignored');
    expect(d.update).not.toHaveBeenCalled();
    expect(d.pushOp).not.toHaveBeenCalled();
  });
});

describe('symbol', () => {
  it('saves a new symbol; choosing "-" clears the override', async () => {
    const d = deps();
    await saveActivityFeatureEdit(feature(), 'kind', 'road', d);
    expect(d.update).toHaveBeenCalledWith('f1', { properties: { kind: 'road' } });
    await saveActivityFeatureEdit(feature(), 'kind', '', d);
    expect(d.update).toHaveBeenLastCalledWith('f1', { properties: { kind: '' } });
  });
});

describe('years', () => {
  it('saves the chosen years, sorted, and remembers the old ones', async () => {
    const d = deps();
    expect(await saveActivityFeatureEdit(feature(), 'years', '3,1', d)).toBe('saved');
    expect(d.update).toHaveBeenCalledWith('f1', { properties: { years: [1, 3] } });
    expect(d.pushOp.mock.calls[0][0]).toMatchObject({
      previousPayload: { properties: { years: [1, 2] } },
      newPayload: { properties: { years: [1, 3] } },
    });
  });

  it('a place must keep at least one year: an empty choice is ignored', async () => {
    const d = deps();
    expect(await saveActivityFeatureEdit(feature(), 'years', '', d)).toBe('ignored');
    expect(d.update).not.toHaveBeenCalled();
  });

  it('an unplanned year: asks, and on "yes" retries with plan_years and remembers the retry', async () => {
    const d = deps({ update: vi.fn().mockRejectedValueOnce(notPlanned([4])).mockResolvedValueOnce({}) });
    expect(await saveActivityFeatureEdit(feature(), 'years', '1,2,4', d)).toBe('saved');
    expect(d.confirmPlanYears).toHaveBeenCalledWith('नर्सरी निर्माण', [4]);
    expect(d.update).toHaveBeenCalledTimes(2);
    expect(d.update).toHaveBeenLastCalledWith('f1', { properties: { years: [1, 2, 4], plan_years: true } });
    expect(d.pushOp).toHaveBeenCalledTimes(1);
    expect(d.pushOp.mock.calls[0][0].newPayload).toEqual({ properties: { years: [1, 2, 4], plan_years: true } });
  });

  it('an unplanned year: on "no" nothing is planned, nothing is remembered, the table re-reads', async () => {
    const d = deps({
      update: vi.fn().mockRejectedValue(notPlanned([4])),
      confirmPlanYears: vi.fn().mockResolvedValue(false),
    });
    expect(await saveActivityFeatureEdit(feature(), 'years', '1,2,4', d)).toBe('declined');
    expect(d.update).toHaveBeenCalledTimes(1);
    expect(d.pushOp).not.toHaveBeenCalled();
    expect(d.report).not.toHaveBeenCalled();
    expect(d.refresh).toHaveBeenCalled();
  });

  it('a failed retry is reported and leaves no undo entry', async () => {
    const boom = new ActivityFeatureApiError({ detail: 'x' }, 500);
    const d = deps({ update: vi.fn().mockRejectedValueOnce(notPlanned([4])).mockRejectedValueOnce(boom) });
    expect(await saveActivityFeatureEdit(feature(), 'years', '1,4', d)).toBe('failed');
    expect(d.report).toHaveBeenCalledWith(boom);
    expect(d.pushOp).not.toHaveBeenCalled();
  });
});

describe('failures and guards', () => {
  it('any other error is reported, the table re-reads, and no undo entry is left', async () => {
    const boom = new ActivityFeatureApiError({ detail: 'x' }, 500);
    const d = deps({ update: vi.fn().mockRejectedValue(boom) });
    expect(await saveActivityFeatureEdit(feature(), 'name', 'B', d)).toBe('failed');
    expect(d.report).toHaveBeenCalledWith(boom);
    expect(d.refresh).toHaveBeenCalled();
    expect(d.pushOp).not.toHaveBeenCalled();
  });

  it('a column that is not editable here, or a row without an id, is ignored', async () => {
    const d = deps();
    expect(await saveActivityFeatureEdit(feature(), 'length', '5', d)).toBe('ignored');
    expect(await saveActivityFeatureEdit(feature({ id: undefined }), 'name', 'B', d)).toBe('ignored');
    expect(d.update).not.toHaveBeenCalled();
  });
});
