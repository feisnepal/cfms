/**
 * The attribute table toolbar's customisable layout: which items sit on the bar, in what order, and which are tucked into the "More"
 * menu. A pure model, so it is tested without a browser; the screen only draws it and `useToolbarLayout` keeps it.
 *
 * Items keep their SIDE (left / right of the spacer) so a layout can never turn the bar into loose icons: they are reordered within
 * their side. Search, the selection count, the tools toggle and the customise button are fixed and not part of the layout, so the table
 * can never be left without a way to find rows or see what is selected.
 */
export type ToolbarItemId = 'filter' | 'view' | 'selection' | 'columns' | 'colour' | 'update' | 'download' | 'history';
export type ToolbarSide = 'left' | 'right';

export const ITEM_SIDE: Record<ToolbarItemId, ToolbarSide> = {
  filter: 'left', view: 'left', selection: 'left',
  columns: 'right', colour: 'right', update: 'right', download: 'right', history: 'right',
};

export const DEFAULT_ORDER: ToolbarItemId[] = ['filter', 'view', 'selection', 'columns', 'colour', 'update', 'download', 'history'];

export interface ToolbarLayout {
  /** every item, in the user's order (the order only matters within a side) */
  order: ToolbarItemId[];
  /** items taken off the bar; they are offered in the "More" menu instead */
  hidden: ToolbarItemId[];
}

export const DEFAULT_LAYOUT: ToolbarLayout = { order: [...DEFAULT_ORDER], hidden: [] };

const isItem = (v: unknown): v is ToolbarItemId => typeof v === 'string' && (DEFAULT_ORDER as string[]).includes(v);
const uniq = <T,>(xs: T[]): T[] => xs.filter((x, i) => xs.indexOf(x) === i);

/** Whatever was saved (any shape, any age) -> a valid layout: unknown items dropped, missing ones added back where they default to. */
export function normalizeLayout(raw: unknown): ToolbarLayout {
  const r = (raw && typeof raw === 'object' ? raw : {}) as { order?: unknown; hidden?: unknown };
  const saved = uniq((Array.isArray(r.order) ? r.order : []).filter(isItem));
  const order = [...saved];
  DEFAULT_ORDER.forEach((id, i) => {
    if (order.includes(id)) return;
    // a new item goes just after the item that precedes it by default (or first), so it lands where it would have by default
    const before = DEFAULT_ORDER.slice(0, i).reverse().find((x) => order.includes(x));
    order.splice(before ? order.indexOf(before) + 1 : 0, 0, id);
  });
  const hidden = uniq((Array.isArray(r.hidden) ? r.hidden : []).filter(isItem));
  return { order, hidden };
}

export const isDefaultLayout = (l: ToolbarLayout): boolean =>
  l.hidden.length === 0 && l.order.length === DEFAULT_ORDER.length && l.order.every((id, i) => id === DEFAULT_ORDER[i]);

/** Move an item one place up or down WITHIN its side (a no-op at the end of its side). */
export function moveItem(layout: ToolbarLayout, id: ToolbarItemId, delta: -1 | 1): ToolbarLayout {
  const side = ITEM_SIDE[id];
  const sameSide = layout.order.filter((x) => ITEM_SIDE[x] === side);
  const i = sameSide.indexOf(id);
  const j = i + delta;
  if (i < 0 || j < 0 || j >= sameSide.length) return layout;
  return reorderItem(layout, id, sameSide[j], delta > 0 ? 'after' : 'before');
}

/** Drop `id` next to `target` (drag and drop). Only within one side; an item cannot cross to the other side. */
export function reorderItem(layout: ToolbarLayout, id: ToolbarItemId, target: ToolbarItemId, where: 'before' | 'after' = 'before'): ToolbarLayout {
  if (id === target || ITEM_SIDE[id] !== ITEM_SIDE[target]) return layout;
  const without = layout.order.filter((x) => x !== id);
  const at = without.indexOf(target) + (where === 'after' ? 1 : 0);
  without.splice(at, 0, id);
  return { ...layout, order: without };
}

export function setHidden(layout: ToolbarLayout, id: ToolbarItemId, hidden: boolean): ToolbarLayout {
  const rest = layout.hidden.filter((x) => x !== id);
  return { ...layout, hidden: hidden ? [...rest, id] : rest };
}

/** The items to draw on one side of the bar: in the user's order, not hidden, and available for this layer. */
export function barItems(layout: ToolbarLayout, side: ToolbarSide, available: ReadonlySet<ToolbarItemId>): ToolbarItemId[] {
  return layout.order.filter((id) => ITEM_SIDE[id] === side && available.has(id) && !layout.hidden.includes(id));
}

/** The available items that are off the bar, for the "More" menu, in the user's order. */
export function menuItems(layout: ToolbarLayout, available: ReadonlySet<ToolbarItemId>): ToolbarItemId[] {
  return layout.order.filter((id) => available.has(id) && layout.hidden.includes(id));
}
