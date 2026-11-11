/**
 * usePermissionGate — derives action permissions for the calculation page.
 *
 * Reality-aligned implementation (Phase 3, Tabbed Calculation Detail plan).
 * The AI_READY spec assumed a fictional `owner/admin/editor/viewer` role enum
 * and action-string permission array. The real model is:
 *   - backend `User.role`: 'guest' | 'user' | 'org_admin' | 'super_admin'
 *   - U07 frontend roles: FrontendRole[] ('editor' | 'reviewer' | 'dfo' | 'super_admin')
 *     stored in `workspaceStore.userRoles` (set from `AuthContext`/`roleMapping`).
 *   - map lifecycle status incl. 'submitted' and 'retrying'.
 *
 * We accept the real inputs and expose the plan's `can.*` / `showEditTools` /
 * `showDeleteButton` / `isTabDisabled` UI booleans so callers never hide via
 * CSS — they conditionally render.
 */
import { useMemo } from 'react';
import type { BackendRole, FrontendRole } from '../lib/roleMapping';
import { mapBackendRoleToFrontend } from '../lib/roleMapping';

export const LOCKED_STATUSES = ['locked', 'calculating', 'failed'];

export interface PermissionGateInput {
  /** Backend user role — drives owner/admin bypass + delete. */
  backendRole?: BackendRole;
  /** U07 frontend permission roles (from workspaceStore.userRoles). */
  frontendRoles?: FrontendRole[];
  /** U01 map lifecycle status. */
  mapLifecycleStatus?: string;
  /** Explicit structural lock flag. */
  structureLocked?: boolean;
}

export interface PermissionGateCan {
  view: boolean;
  edit: boolean;
  delete: boolean;
  createSampling: boolean;
  createOp: boolean;
  exportReports: boolean;
  /** UI-specific — render only, never CSS-hide. */
  showEditTools: boolean;
  showDeleteButton: boolean;
  isTabDisabled: (tabRequiresEdit: boolean) => boolean;
}

export interface PermissionGateResult {
  can: PermissionGateCan;
  isLocked: boolean;
}

const isOwnerOrAdmin = (backendRole?: BackendRole): boolean =>
  backendRole === 'super_admin' || backendRole === 'org_admin';

/**
 * Pure permission computation — separated from the hook so it is testable
 * without mounting (repo logic-only test pattern).
 */
export const computePermissionGate = ({
  backendRole = 'user',
  frontendRoles = [],
  mapLifecycleStatus = 'draft',
  structureLocked = false,
}: PermissionGateInput = {}): PermissionGateResult => {
  const isLocked =
    structureLocked || LOCKED_STATUSES.includes(mapLifecycleStatus);

  // Fall back to backend-role mapping when no explicit frontend roles are
  // provided (reality: store `userRoles` are set via mapBackendRoleToFrontend).
  const effectiveRoles: FrontendRole[] =
    frontendRoles.length > 0 ? frontendRoles : mapBackendRoleToFrontend(backendRole);

  const bypass = isOwnerOrAdmin(backendRole) && !isLocked;
  const hasEditCapability =
    isOwnerOrAdmin(backendRole) ||
    effectiveRoles.includes('editor') ||
    effectiveRoles.includes('dfo') ||
    effectiveRoles.includes('super_admin');
  const hasReviewCapability =
    effectiveRoles.includes('reviewer') || hasEditCapability;

  const can: PermissionGateCan = {
    view: true, // any authenticated user can view their own calculation
    edit: (hasEditCapability || bypass) && !isLocked,
    delete: isOwnerOrAdmin(backendRole) && !isLocked,
    createSampling: (hasReviewCapability || bypass) && !isLocked,
    createOp:
      (isOwnerOrAdmin(backendRole) || effectiveRoles.includes('dfo')) && !isLocked,
    exportReports: hasEditCapability || bypass,
    showEditTools: (hasEditCapability || bypass) && !isLocked,
    showDeleteButton: isOwnerOrAdmin(backendRole),
    isTabDisabled: (tabRequiresEdit: boolean) =>
      tabRequiresEdit && isLocked && !hasEditCapability,
  };

  return { can, isLocked };
};

/** Hook wrapper around `computePermissionGate` for component usage. */
export const usePermissionGate = (
  input: PermissionGateInput = {},
): PermissionGateResult =>
  useMemo(() => computePermissionGate(input), [
    input.backendRole,
    input.frontendRoles,
    input.mapLifecycleStatus,
    input.structureLocked,
  ]);
