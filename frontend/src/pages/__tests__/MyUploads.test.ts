import { describe, it, expect } from 'vitest';
import { draftHasIslands, getNextAction, getNextHint } from '../MyUploads';
import type { Calculation } from '../../types/index';

const base = {
  id: 'd1',
  user_id: 'u1',
  status: 'pending',
  created_at: '',
} as Calculation;

describe('MyUploads draft next-action reroute (Phase 7 — Finding B)', () => {
  it('routes a boundary-less (name-only) draft to the workspace Add Geometry path', () => {
    const calc: Calculation = { ...base, is_draft: true, draft_data: { islands_count: 0 } };
    expect(draftHasIslands(calc)).toBe(false);
    expect(getNextAction(calc)).toEqual({
      label: 'uploads.addGeometry',
      to: `/calculations/${calc.id}`,
      color: 'text-purple-700',
    });
    expect(getNextHint(calc)).toContain('uploads.hintAddGeometry');
  });

  it('keeps the legacy island-bearing draft on Resume Drawing', () => {
    const calc: Calculation = {
      ...base,
      is_draft: true,
      draft_data: { islands_count: 2, islands: [{ geometry: {} }, { geometry: {} }] },
    };
    expect(draftHasIslands(calc)).toBe(true);
    expect(getNextAction(calc)).toEqual({
      label: 'uploads.resumeDrawing',
      to: `/drafts/${calc.id}/resume`,
      color: 'text-purple-700',
    });
    expect(getNextHint(calc)).toBe('uploads.hintFinishDrawing');
  });

  it('defaults to a boundary-less draft when draft_data is missing', () => {
    const calc: Calculation = { ...base, is_draft: true };
    expect(draftHasIslands(calc)).toBe(false);
    expect(getNextAction(calc)?.to).toBe(`/calculations/${calc.id}`);
  });

  it('non-draft statuses are unchanged', () => {
    const pending: Calculation = { ...base, status: 'pending' };
    expect(getNextAction(pending)).toEqual({
      label: 'uploads.nameBlocks',
      to: `/calculations/${pending.id}/block-naming`,
      color: 'text-blue-700',
    });
    const completed: Calculation = { ...base, status: 'completed' };
    expect(getNextAction(completed)?.to).toBe(`/calculations/${completed.id}`);
  });
});