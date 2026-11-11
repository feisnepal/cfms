/**
 * U07 — toolEnabled permission matrix tests.
 */
import { describe, it, expect } from 'vitest';
import { toolEnabled, getEnabledTools, hasDrawPermission, isDfoOrAbove, type Role } from '../permissions';

describe('toolEnabled', () => {
  const roles = {
    editor: ['editor'] as Role[],
    reviewer: ['reviewer'] as Role[],
    dfo: ['dfo'] as Role[],
    superAdmin: ['super_admin'] as Role[],
    editorReviewer: ['editor', 'reviewer'] as Role[],
    none: [] as Role[],
  };

  it('view/measure/pan always allowed (no gate)', () => {
    expect(toolEnabled(null, 'simple', roles.none)).toBe(true);
    expect(toolEnabled('view', 'simple', roles.none)).toBe(true);
  });

  it('super_admin bypasses all gates regardless of uiMode', () => {
    const tools = [
      'split', 'merge', 'draw_polygon', 'draw_point', 'draw_line',
      'draw_polygon_af', 'vertex_edit', 'subarea_category',
      'import', 'op_export', 'approve',
    ];
    for (const tool of tools) {
      expect(toolEnabled(tool as any, 'simple', roles.superAdmin)).toBe(true);
      expect(toolEnabled(tool as any, 'advanced', roles.superAdmin)).toBe(true);
    }
  });

  it('draw tools require advanced UI and editor role', () => {
    const drawTools = [
      'split', 'merge', 'draw_polygon', 'draw_point', 'draw_line',
      'draw_polygon_af', 'vertex_edit', 'subarea_category',
    ];
    for (const tool of drawTools) {
      // Editor in advanced = OK
      expect(toolEnabled(tool as any, 'advanced', roles.editor)).toBe(true);
      // Editor in simple = NO
      expect(toolEnabled(tool as any, 'simple', roles.editor)).toBe(false);
      // Reviewer in advanced = NO (not in allowedRoles)
      expect(toolEnabled(tool as any, 'advanced', roles.reviewer)).toBe(false);
      // DFO in advanced = NO
      expect(toolEnabled(tool as any, 'advanced', roles.dfo)).toBe(false);
      // No role = NO
      expect(toolEnabled(tool as any, 'advanced', roles.none)).toBe(false);
    }
  });

  it('import requires advanced UI and editor role', () => {
    expect(toolEnabled('import', 'advanced', roles.editor)).toBe(true);
    expect(toolEnabled('import', 'simple', roles.editor)).toBe(false);
    expect(toolEnabled('import', 'advanced', roles.reviewer)).toBe(false);
    expect(toolEnabled('import', 'advanced', roles.dfo)).toBe(false);
  });

  it('op_export allowed for all authenticated roles', () => {
    expect(toolEnabled('op_export', 'simple', roles.editor)).toBe(true);
    expect(toolEnabled('op_export', 'advanced', roles.reviewer)).toBe(true);
    expect(toolEnabled('op_export', 'advanced', roles.dfo)).toBe(true);
    expect(toolEnabled('op_export', 'advanced', roles.editorReviewer)).toBe(true);
    expect(toolEnabled('op_export', 'simple', roles.none)).toBe(false);
  });

  it('approve only for DFO and super_admin', () => {
    expect(toolEnabled('approve', 'simple', roles.dfo)).toBe(true);
    expect(toolEnabled('approve', 'advanced', roles.superAdmin)).toBe(true);
    expect(toolEnabled('approve', 'advanced', roles.editor)).toBe(false);
    expect(toolEnabled('approve', 'simple', roles.reviewer)).toBe(false);
  });
});

describe('getEnabledTools', () => {
  it('returns only permitted tools for editor in advanced', () => {
    const tools = getEnabledTools('advanced', ['editor']);
    expect(tools).toContain('split');
    expect(tools).toContain('draw_polygon');
    expect(tools).toContain('import');
    expect(tools).toContain('op_export');
    expect(tools).not.toContain('approve');
  });

  it('returns minimal set for reviewer', () => {
    const tools = getEnabledTools('advanced', ['reviewer']);
    expect(tools).toEqual(['op_export']);
  });

  it('returns DFO tools', () => {
    const tools = getEnabledTools('advanced', ['dfo']);
    expect(tools).toEqual(['op_export', 'approve']);
  });

  it('returns all for super_admin', () => {
    const tools = getEnabledTools('advanced', ['super_admin']);
    expect(tools.length).toBe(11); // all tools
  });
});

describe('hasDrawPermission', () => {
  it('true for editor', () => expect(hasDrawPermission(['editor'])).toBe(true));
  it('true for super_admin', () => expect(hasDrawPermission(['super_admin'])).toBe(true));
  it('false for reviewer', () => expect(hasDrawPermission(['reviewer'])).toBe(false));
  it('false for dfo', () => expect(hasDrawPermission(['dfo'])).toBe(false));
  it('false for none', () => expect(hasDrawPermission([])).toBe(false));
});

describe('isDfoOrAbove', () => {
  it('true for dfo', () => expect(isDfoOrAbove(['dfo'])).toBe(true));
  it('true for super_admin', () => expect(isDfoOrAbove(['super_admin'])).toBe(true));
  it('false for editor', () => expect(isDfoOrAbove(['editor'])).toBe(false));
  it('false for reviewer', () => expect(isDfoOrAbove(['reviewer'])).toBe(false));
  it('false for none', () => expect(isDfoOrAbove([])).toBe(false));
});