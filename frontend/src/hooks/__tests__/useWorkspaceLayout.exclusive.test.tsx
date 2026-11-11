/** One panel per dock position: opening a panel gives it the whole position and closes the others there. */
import { describe, expect, it, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';

vi.mock('../../lib/workspaceLayout', async (orig) => ({
  ...(await orig<typeof import('../../lib/workspaceLayout')>()),
  fetchLayout: vi.fn().mockResolvedValue(null),
  saveLayout: vi.fn().mockResolvedValue(undefined),
}));

import { useWorkspaceLayout } from '../useWorkspaceLayout';

function fakePanel(collapsed: boolean) {
  const p = { collapsed, collapse: vi.fn(() => { p.collapsed = true; }), expand: vi.fn(() => { p.collapsed = false; }), isCollapsed: () => p.collapsed };
  return p;
}

function setup(initial: Record<string, boolean>) {
  const hook = renderHook(() => useWorkspaceLayout());
  const panels: Record<string, ReturnType<typeof fakePanel>> = {};
  for (const id of Object.keys(initial)) {
    panels[id] = fakePanel(initial[id]);
    hook.result.current.registerPanel(id as never)(panels[id]);
  }
  const left = { setLayout: vi.fn(), getLayout: vi.fn() };
  const right = { setLayout: vi.fn(), getLayout: vi.fn() };
  hook.result.current.registerGroup('workspace-left')(left as never);
  hook.result.current.registerGroup('workspace-right')(right as never);
  return { hook, panels, left, right };
}

describe('exclusive dock positions', () => {
  it('opening a panel closes the others in its column and gives it the whole column', () => {
    const { hook, panels, left } = setup({ layers: false, basemap: false, imported: true, raster: true, attributeTable: false, legend: false });
    act(() => hook.result.current.togglePanel('raster'));
    expect(panels.raster.collapsed).toBe(false);
    expect(panels.layers.collapsed).toBe(true);
    expect(panels.basemap.collapsed).toBe(true);
    expect(left.setLayout).toHaveBeenLastCalledWith({ layers: 0, basemap: 0, imported: 0, raster: 100 });
    expect(hook.result.current.collapsed).toMatchObject({ raster: false, layers: true, basemap: true, imported: true });
  });

  it('opening another replaces the first', () => {
    const { hook, panels } = setup({ layers: false, basemap: true, imported: true, raster: true, attributeTable: false, legend: false });
    act(() => hook.result.current.togglePanel('basemap'));
    expect(panels.basemap.collapsed).toBe(false);
    expect(panels.layers.collapsed).toBe(true);
  });

  it('the other column is left alone', () => {
    const { hook, panels, right } = setup({ layers: false, basemap: true, imported: true, raster: true, attributeTable: false, legend: true });
    act(() => hook.result.current.togglePanel('imported'));
    expect(panels.attributeTable.collapsed).toBe(false);
    expect(right.setLayout).not.toHaveBeenCalled();
  });

  it('the right column works the same way', () => {
    const { hook, panels, right } = setup({ layers: false, basemap: true, imported: true, raster: true, attributeTable: false, legend: true });
    act(() => hook.result.current.togglePanel('legend'));
    expect(panels.legend.collapsed).toBe(false);
    expect(panels.attributeTable.collapsed).toBe(true);
    expect(right.setLayout).toHaveBeenLastCalledWith({ attributeTable: 0, legend: 100 });
  });

  it('closing an open panel just closes it', () => {
    const { hook, panels, left } = setup({ layers: false, basemap: true, imported: true, raster: true, attributeTable: false, legend: true });
    act(() => hook.result.current.togglePanel('layers'));
    expect(panels.layers.collapsed).toBe(true);
    expect(left.setLayout).not.toHaveBeenCalled();
  });

  it('closing a secondary panel returns the position to its home panel, so it is never empty', () => {
    const { hook, panels, left, right } = setup({ layers: true, basemap: false, imported: true, raster: true, attributeTable: true, legend: false });
    act(() => hook.result.current.togglePanel('basemap'));
    expect(panels.basemap.collapsed).toBe(true);
    expect(panels.layers.collapsed).toBe(false);
    expect(left.setLayout).toHaveBeenLastCalledWith({ layers: 100, basemap: 0, imported: 0, raster: 0 });
    act(() => hook.result.current.togglePanel('legend')); // legend was open, attribute table closed
    expect(panels.attributeTable.collapsed).toBe(false);
    expect(right.setLayout).toHaveBeenLastCalledWith({ attributeTable: 100, legend: 0 });
  });

  it('closing the home panel itself just closes it (the user asked for that)', () => {
    const { hook, panels } = setup({ layers: false, basemap: true, imported: true, raster: true, attributeTable: false, legend: true });
    act(() => hook.result.current.togglePanel('layers'));
    expect(panels.layers.collapsed).toBe(true);
    expect(panels.basemap.collapsed).toBe(true);
  });
});

describe('saved layouts from before one-panel positions', () => {
  it('keep the home panel when several were open, and never leave a position empty', async () => {
    const { mergeDefaultLayout } = await import('../../lib/workspaceLayout');
    const many = mergeDefaultLayout({ version: 1, groups: {}, collapsed: { layers: false, basemap: false, imported: false, raster: false, attributeTable: false, legend: false } });
    expect(many.collapsed).toMatchObject({ layers: false, basemap: true, imported: true, raster: true, attributeTable: false, legend: true });
    const noHome = mergeDefaultLayout({ version: 1, groups: {}, collapsed: { layers: true, basemap: true, imported: false, raster: false, attributeTable: true, legend: true } });
    expect(noHome.collapsed).toMatchObject({ layers: true, basemap: true, imported: false, raster: true });
    expect(noHome.collapsed.attributeTable).toBe(false); // none open in the right position -> its home panel opens
    expect(noHome.groups['workspace-left']).toMatchObject({ imported: 100, layers: 0 });
  });
});
