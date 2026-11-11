/**
 * Phase 3 — usePermissionGate logic tests (repo logic-only pattern).
 * Tests the pure `computePermissionGate` factory, not the React hook.
 */
import { describe, it, expect } from 'vitest';
import { computePermissionGate, LOCKED_STATUSES } from '../usePermissionGate';

const lockStatuses = ['locked', 'calculating', 'failed'];

describe('computePermissionGate', () => {
  describe('isLocked', () => {
    it('is false for draft/submitted/completed/retrying and unset structureLocked', () => {
      for (const status of ['draft', 'submitted', 'completed', 'retrying']) {
        const { isLocked } = computePermissionGate({ mapLifecycleStatus: status });
        expect(isLocked).toBe(false);
      }
    });

    it('is true for locked statuses', () => {
      for (const status of lockStatuses) {
        const { isLocked } = computePermissionGate({ mapLifecycleStatus: status });
        expect(isLocked).toBe(true);
      }
    });

    it('is true when structureLocked is set even with draft lifecycle', () => {
      const { isLocked } = computePermissionGate({ structureLocked: true, mapLifecycleStatus: 'draft' });
      expect(isLocked).toBe(true);
    });

    it('exported LOCKED_STATUSES matches the runtime lock set', () => {
      expect(LOCKED_STATUSES).toEqual(lockStatuses);
    });
  });

  describe('can — locked state', () => {
    it('blocks edit/create/delete when locked, regardless of role', () => {
      const { can } = computePermissionGate({
        backendRole: 'org_admin',
        mapLifecycleStatus: 'locked',
      });
      expect(can.edit).toBe(false);
      expect(can.createSampling).toBe(false);
      expect(can.createOp).toBe(false);
      expect(can.delete).toBe(false);
      expect(can.showEditTools).toBe(false);
    });

    it('still allows view + export + delete button when locked for super_admin', () => {
      const { can } = computePermissionGate({
        backendRole: 'super_admin',
        mapLifecycleStatus: 'locked',
      });
      expect(can.view).toBe(true);
      expect(can.exportReports).toBe(true);
      expect(can.showDeleteButton).toBe(true);
    });
  });

  describe('can — unlocked state', () => {
    it('editor (user) can edit and create sampling, but not create op', () => {
      const { can } = computePermissionGate({ backendRole: 'user' });
      expect(can.edit).toBe(true);
      expect(can.createSampling).toBe(true);
      expect(can.createOp).toBe(false); // dfo/org_admin only
      expect(can.exportReports).toBe(true);
      expect(can.showEditTools).toBe(true);
    });

    it('guest/reviewer cannot edit but can create sampling', () => {
      const { can } = computePermissionGate({ backendRole: 'guest' });
      expect(can.edit).toBe(false);
      expect(can.createSampling).toBe(true); // reviewer can sample
      expect(can.showEditTools).toBe(false);
    });

    it('org_admin bypasses op-creation restriction and can delete', () => {
      const { can } = computePermissionGate({ backendRole: 'org_admin' });
      expect(can.createOp).toBe(true);
      expect(can.delete).toBe(true);
      expect(can.showDeleteButton).toBe(true);
    });

    it('dfo frontend role can create op', () => {
      const { can } = computePermissionGate({ backendRole: 'user', frontendRoles: ['dfo'] });
      expect(can.createOp).toBe(true);
    });
  });

  describe('can.isTabDisabled', () => {
    it('disables edit-required tabs only when locked and no edit capability', () => {
      const lockedGuest = computePermissionGate({ backendRole: 'guest', mapLifecycleStatus: 'locked' });
      expect(lockedGuest.can.isTabDisabled(true)).toBe(true);

      const lockedEditor = computePermissionGate({ backendRole: 'user', mapLifecycleStatus: 'locked' });
      expect(lockedEditor.can.isTabDisabled(true)).toBe(false);

      const unlockedGuest = computePermissionGate({ backendRole: 'guest' });
      expect(unlockedGuest.can.isTabDisabled(true)).toBe(false);
    });

    it('never disables view-only tabs', () => {
      const { can } = computePermissionGate({ backendRole: 'guest', mapLifecycleStatus: 'locked' });
      expect(can.isTabDisabled(false)).toBe(false);
    });
  });
});
