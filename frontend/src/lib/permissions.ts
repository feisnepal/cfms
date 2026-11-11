/**
 * Tool permission gates — U07.
 *
 * Centralized authorization logic for map editor tools.
 * Mirrors backend `require_draw_role` for parity.
 * MUST stay in sync with backend deps.py.
 */

export type Role = 'editor' | 'reviewer' | 'dfo' | 'super_admin';
export type UiMode = 'simple' | 'advanced';

/** Toolbar modes from layerRegistry */
export type ToolbarMode =
  | 'view'
  | 'split'
  | 'merge'
  | 'move'
  | 'draw_polygon'
  | 'draw_point'
  | 'draw_line'
  | 'draw_polygon_af'
  | 'vertex_edit'
  | 'subarea_category'
  | 'import'
  | 'op_export'
  | 'approve'
  | null;

/** Gate definition per tool */
interface ToolGate {
  needsUi?: UiMode;
  allowedRoles?: Role[];
}

/** Tool permission matrix — EXACT match with backend deps.py `require_draw_role` */
const TOOL_GATES: Partial<Record<Exclude<ToolbarMode, null>, ToolGate>> = {
  // View/measure/pan/zoom: no gate (always allowed)
  view: undefined,

  // Advanced geometry editing — requires Editor+ and advanced UI
  split: { needsUi: 'advanced', allowedRoles: ['editor', 'super_admin'] },
  merge: { needsUi: 'advanced', allowedRoles: ['editor', 'super_admin'] },
  move: { needsUi: 'advanced', allowedRoles: ['editor', 'super_admin'] },
  draw_polygon: { needsUi: 'advanced', allowedRoles: ['editor', 'super_admin'] },
  draw_point: { needsUi: 'advanced', allowedRoles: ['editor', 'super_admin'] },
  draw_line: { needsUi: 'advanced', allowedRoles: ['editor', 'super_admin'] },
  draw_polygon_af: { needsUi: 'advanced', allowedRoles: ['editor', 'super_admin'] },
  vertex_edit: { needsUi: 'advanced', allowedRoles: ['editor', 'super_admin'] },
  subarea_category: { needsUi: 'advanced', allowedRoles: ['editor', 'super_admin'] },

  // Import — Editor+ in advanced mode
  import: { needsUi: 'advanced', allowedRoles: ['editor', 'super_admin'] },

  // OP export — all authenticated roles
  op_export: { allowedRoles: ['editor', 'reviewer', 'dfo', 'super_admin'] },

  // Approve/lock/unlock — DFO and Super Admin only
  approve: { allowedRoles: ['dfo', 'super_admin'] },
};

/**
 * Check if a tool is enabled for the current user context.
 *
 * @param tool - Toolbar mode to check
 * @param uiMode - Current workspace UI mode ('simple' | 'advanced')
 * @param roles - User's roles from JWT (decoded at login, stored in workspaceStore)
 * @returns true if the user may use this tool
 */
export function toolEnabled(tool: ToolbarMode, uiMode: UiMode, roles: Role[]): boolean {
  const gate = tool ? TOOL_GATES[tool] : undefined;
  if (!gate) return true; // no gate = always allowed (view, pan, measure, etc.)

  // Super admin bypasses ALL gates
  if (roles.includes('super_admin')) return true;

  // UI mode check
  if (gate.needsUi && uiMode !== gate.needsUi) return false;

  // Role check
  if (gate.allowedRoles && gate.allowedRoles.length > 0) {
    return roles.some((r) => gate.allowedRoles!.includes(r));
  }

  return true;
}

/**
 * Get all tools the current user can access.
 * Useful for rendering toolbars conditionally.
 */
export function getEnabledTools(uiMode: UiMode, roles: Role[]): ToolbarMode[] {
  const allTools: ToolbarMode[] = [
    'split',
    'merge',
    'draw_polygon',
    'draw_point',
    'draw_line',
    'draw_polygon_af',
    'vertex_edit',
    'subarea_category',
    'import',
    'op_export',
    'approve',
  ];
  return allTools.filter((t) => toolEnabled(t, uiMode, roles));
}

/**
 * Check if a role has any draw permissions.
 */
export function hasDrawPermission(roles: Role[]): boolean {
  return roles.some((r) => ['editor', 'super_admin'].includes(r));
}

/**
 * Check if a role is DFO or above (for approve/unlock).
 */
export function isDfoOrAbove(roles: Role[]): boolean {
  return roles.some((r) => ['dfo', 'super_admin'].includes(r));
}