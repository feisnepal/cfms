import { describe, expect, it } from 'vitest';
import {
  DEFAULT_LAYOUT, DEFAULT_ORDER, ITEM_SIDE, barItems, isDefaultLayout, menuItems, moveItem, normalizeLayout, reorderItem, setHidden,
  type ToolbarItemId,
} from '../toolbarLayout';

const ALL = new Set<ToolbarItemId>(DEFAULT_ORDER);

describe('toolbar layout', () => {
  it('starts as the default and recognises it', () => {
    expect(isDefaultLayout(DEFAULT_LAYOUT)).toBe(true);
    expect(barItems(DEFAULT_LAYOUT, 'left', ALL)).toEqual(['filter', 'view', 'selection']);
    expect(barItems(DEFAULT_LAYOUT, 'right', ALL)).toEqual(['columns', 'colour', 'update', 'download', 'history']);
    expect(menuItems(DEFAULT_LAYOUT, ALL)).toEqual([]);
  });

  it('cleans up anything that was saved: unknown items dropped, duplicates removed, missing ones put back where they default to', () => {
    const l = normalizeLayout({ order: ['update', 'nonsense', 'update', 'filter'], hidden: ['download', 'download', 'who'] });
    expect(l.order.filter((x) => x === 'update')).toHaveLength(1);
    expect([...l.order].sort()).toEqual([...DEFAULT_ORDER].sort());
    expect(l.order.indexOf('update')).toBeLessThan(l.order.indexOf('filter')); // the saved order of what it knew is kept
    expect(l.hidden).toEqual(['download']);
    expect(normalizeLayout(null)).toEqual(DEFAULT_LAYOUT);
    expect(normalizeLayout('x')).toEqual(DEFAULT_LAYOUT);
    expect(normalizeLayout({ order: 5, hidden: {} })).toEqual(DEFAULT_LAYOUT);
  });

  it('a newly added item lands after the one before it by default', () => {
    // a layout saved before "history" existed
    const l = normalizeLayout({ order: ['filter', 'view', 'selection', 'columns', 'colour', 'update', 'download'], hidden: [] });
    expect(l.order[l.order.length - 1]).toBe('history');
  });

  it('moves an item one place within its side, and stops at the end of the side', () => {
    const l1 = moveItem(DEFAULT_LAYOUT, 'view', -1);
    expect(barItems(l1, 'left', ALL)).toEqual(['view', 'filter', 'selection']);
    expect(moveItem(l1, 'view', -1)).toBe(l1); // already first on its side
    const l2 = moveItem(DEFAULT_LAYOUT, 'selection', 1);
    expect(l2).toBe(DEFAULT_LAYOUT); // last on the left; it does not slip across to the right side
    expect(barItems(moveItem(DEFAULT_LAYOUT, 'columns', 1), 'right', ALL)).toEqual(['colour', 'columns', 'update', 'download', 'history']);
  });

  it('drag and drop reorders within a side only', () => {
    const l = reorderItem(DEFAULT_LAYOUT, 'selection', 'filter', 'before');
    expect(barItems(l, 'left', ALL)).toEqual(['selection', 'filter', 'view']);
    expect(reorderItem(DEFAULT_LAYOUT, 'filter', 'download')).toBe(DEFAULT_LAYOUT); // different sides: refused
    expect(reorderItem(DEFAULT_LAYOUT, 'filter', 'filter')).toBe(DEFAULT_LAYOUT);
    expect(barItems(reorderItem(DEFAULT_LAYOUT, 'history', 'columns', 'before'), 'right', ALL)[0]).toBe('history');
  });

  it('hiding takes an item off the bar and offers it in the More menu; showing puts it back in its place', () => {
    const hidden = setHidden(setHidden(DEFAULT_LAYOUT, 'download', true), 'update', true);
    expect(barItems(hidden, 'right', ALL)).toEqual(['columns', 'colour', 'history']);
    expect(menuItems(hidden, ALL)).toEqual(['update', 'download']);
    expect(isDefaultLayout(hidden)).toBe(false);
    const back = setHidden(hidden, 'update', false);
    expect(barItems(back, 'right', ALL)).toEqual(['columns', 'colour', 'update', 'history']);
  });

  it('only available items are drawn or offered (an item the layer has no use for never shows)', () => {
    const some = new Set<ToolbarItemId>(['filter', 'columns', 'download']);
    expect(barItems(DEFAULT_LAYOUT, 'left', some)).toEqual(['filter']);
    expect(barItems(DEFAULT_LAYOUT, 'right', some)).toEqual(['columns', 'download']);
    expect(menuItems(setHidden(DEFAULT_LAYOUT, 'view', true), some)).toEqual([]);
  });

  it('every item has a side, and the defaults cover them all exactly once', () => {
    expect(new Set(DEFAULT_ORDER).size).toBe(DEFAULT_ORDER.length);
    for (const id of DEFAULT_ORDER) expect(['left', 'right']).toContain(ITEM_SIDE[id]);
  });

  it('reordering never loses or duplicates an item', () => {
    let l = DEFAULT_LAYOUT;
    for (const [id, d] of [['view', -1], ['columns', 1], ['history', -1], ['filter', 1], ['download', -1]] as const) l = moveItem(l, id, d);
    l = reorderItem(l, 'update', 'columns', 'before');
    expect([...l.order].sort()).toEqual([...DEFAULT_ORDER].sort());
  });
});
