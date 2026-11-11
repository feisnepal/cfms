/**
 * Role mapping utilities — U07.
 * Maps backend UserRole to frontend U07 permission roles.
 */

/** Backend user roles from database/JWT */
export type BackendRole = 'guest' | 'user' | 'org_admin' | 'super_admin' | 'template_designer';

/** Frontend U07 permission roles */
export type FrontendRole = 'editor' | 'reviewer' | 'dfo' | 'super_admin';

/**
 * Map backend role to frontend U07 permission roles.
 * A user can have multiple permission roles.
 */
export function mapBackendRoleToFrontend(backendRole: BackendRole): FrontendRole[] {
  switch (backendRole) {
    case 'super_admin':
      return ['super_admin'];
    case 'org_admin':
      return ['dfo', 'editor'];
    case 'template_designer':
      return ['editor'];
    case 'user':
      return ['editor'];
    case 'guest':
      return ['reviewer'];
    default:
      return ['reviewer'];
  }
}

/**
 * Check if a backend role has a specific frontend permission.
 */
export function hasFrontendRole(backendRole: BackendRole, frontendRole: FrontendRole): boolean {
  return mapBackendRoleToFrontend(backendRole).includes(frontendRole);
}

/**
 * i18n key for a backend role's display label.
 *
 * `/auth/roles` returns `role.value.replace('_', ' ').title()`, which produces
 * English from the enum name and cannot be localized server-side. Nothing
 * consumes that endpoint today; when something does, it should render the
 * `value` through this map rather than the label the API supplies.
 */
export const ROLE_LABEL_KEY: Record<BackendRole, string> = {
  guest: 'role.guest',
  user: 'role.user',
  org_admin: 'role.orgAdmin',
  super_admin: 'role.superAdmin',
  template_designer: 'role.templateDesigner',
};

export function roleLabelKey(role: string): string {
  return ROLE_LABEL_KEY[role as BackendRole] ?? '';
}
