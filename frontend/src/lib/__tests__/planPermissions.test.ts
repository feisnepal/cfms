import { describe, it, expect } from 'vitest';
import { planTools } from '../planPermissions';

describe('planTools', () => {
  it('lets an ordinary signed-in user edit and update the values but not reconfigure the plan record', () => {
    expect(planTools('user', true)).toEqual({ canEditDocument: true, canAutoPopulate: true, canEditPlanMetadata: false });
  });
  it('gives the super admin everything', () => {
    expect(planTools('super_admin', true)).toEqual({ canEditDocument: true, canAutoPopulate: true, canEditPlanMetadata: true });
  });
  it('gives a template designer the same document tools as any owner', () => {
    expect(planTools('template_designer', true).canEditPlanMetadata).toBe(false);
  });
  it('gives nobody anything when signed out', () => {
    expect(planTools(undefined, false)).toEqual({ canEditDocument: false, canAutoPopulate: false, canEditPlanMetadata: false });
  });
});
