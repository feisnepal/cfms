/** Customize mode of the attribute toolbar: reorder, hide into "More", reset, and keep the layout per user. */
import React, { useState } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, renderHook, screen, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

vi.mock('../../i18n/hooks', () => ({
  useT: () => (key: string, values?: Record<string, unknown>) => (values?.count != null ? `${key}:${values.count}` : values?.name ? `${key}:${values.name}` : key),
}));

import { AttributeToolbar, type AttributeToolbarProps } from '../AttributeToolbar';
import { useToolbarLayout } from '../../hooks/useToolbarLayout';
import { DEFAULT_LAYOUT, type ToolbarLayout } from '../../lib/toolbarLayout';

const props = (over: Partial<AttributeToolbarProps> = {}): Omit<AttributeToolbarProps, 'layoutStore'> => ({
  toolsOpen: true,
  onToggleTools: () => undefined,
  searchQuery: '',
  onSearchChange: () => undefined,
  selectionCount: 0,
  showOnlySelected: false,
  onToggleShowOnlySelected: () => undefined,
  filter: {
    field: '', op: 'eq', value: '', active: false, onField: () => undefined, onOp: () => undefined, onValue: () => undefined,
    onClear: () => undefined, onMap: false, onOnMap: () => undefined, columns: [{ key: 'name', label: 'Name' }], suggestions: [],
  },
  columnsChooser: { rows: [{ key: 'name', label: 'Name', shown: true }], onToggle: () => undefined },
  downloads: { onCsv: () => undefined, onGeoJson: () => undefined, onCopy: () => undefined },
  onUpdateAttribute: () => undefined,
  ...over,
});

function Harness({ initial = DEFAULT_LAYOUT, extra = {} as Partial<AttributeToolbarProps>, seen }: { initial?: ToolbarLayout; extra?: Partial<AttributeToolbarProps>; seen?: (l: ToolbarLayout) => void }) {
  const [layout, setLayout] = useState(initial);
  seen?.(layout);
  return <AttributeToolbar {...props(extra)} layoutStore={{ layout, setLayout }} />;
}

const barOrder = () =>
  Array.from(document.querySelectorAll('[data-testid="attribute-toolbar"] [data-testid]'))
    .map((n) => n.getAttribute('data-testid'))
    .filter((id) => ['tb-download', 'tb-update-attribute', 'tb-filter'].includes(id ?? ''));

beforeEach(() => localStorage.clear());

describe('customize toolbar', () => {
  it('reorders with the arrows, within a side', async () => {
    render(<Harness />);
    expect(barOrder()).toEqual(['tb-filter', 'tb-update-attribute', 'tb-download']);
    await userEvent.click(screen.getByTestId('tb-customize'));
    await userEvent.click(screen.getByTestId('tb-cust-up-download'));
    expect(barOrder()).toEqual(['tb-filter', 'tb-download', 'tb-update-attribute']);
    // the first item of a side cannot move up
    expect((screen.getByTestId('tb-cust-up-filter') as HTMLButtonElement).disabled).toBe(true);
  });

  it('reorders by drag and drop', async () => {
    render(<Harness />);
    await userEvent.click(screen.getByTestId('tb-customize'));
    fireEvent.dragStart(screen.getByTestId('tb-cust-update'));
    fireEvent.dragOver(screen.getByTestId('tb-cust-columns'));
    fireEvent.drop(screen.getByTestId('tb-cust-columns'));
    const rows = Array.from(document.querySelectorAll('.tb-cust-row')).map((r) => r.getAttribute('data-testid'));
    expect(rows.indexOf('tb-cust-update')).toBeLessThan(rows.indexOf('tb-cust-columns'));
  });

  it('unticking moves an item into the More menu, where it still works; ticking brings it back', async () => {
    const onUpdate = vi.fn();
    render(<Harness extra={{ onUpdateAttribute: onUpdate }} />);
    expect(screen.queryByTestId('tb-more')).toBeNull();
    await userEvent.click(screen.getByTestId('tb-customize'));
    await userEvent.click(screen.getByTestId('tb-cust-show-update'));
    await userEvent.click(screen.getByTestId('tb-cust-done'));
    expect(screen.queryByTestId('tb-update-attribute')).toBeNull();
    await userEvent.click(screen.getByTestId('tb-more'));
    await userEvent.click(screen.getByTestId('tb-more-update'));
    expect(onUpdate).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByTestId('tb-customize'));
    await userEvent.click(screen.getByTestId('tb-cust-show-update'));
    expect(screen.getByTestId('tb-update-attribute')).toBeTruthy();
    expect(screen.queryByTestId('tb-more')).toBeNull();
  });

  it('a pop-up item taken off the bar opens under More', async () => {
    render(<Harness initial={{ ...DEFAULT_LAYOUT, hidden: ['download'] }} />);
    await userEvent.click(screen.getByTestId('tb-more'));
    await userEvent.click(screen.getByTestId('tb-more-download'));
    expect(screen.getByRole('menu', { name: 'attributeTable.downloadMenu' })).toBeTruthy();
  });

  it('the fixed parts survive hiding everything: an active filter chip and the selection count stay', () => {
    const all = ['filter', 'view', 'selection', 'columns', 'colour', 'update', 'download', 'history'] as const;
    render(
      <Harness
        initial={{ ...DEFAULT_LAYOUT, hidden: [...all] }}
        extra={{ selectionCount: 3, filter: { ...props().filter, field: 'name', value: 'A', active: true } }}
      />,
    );
    expect(screen.getByTestId('tb-filter-chip')).toBeTruthy();
    expect(screen.getByText('attributeTable.selected:3')).toBeTruthy();
    expect(screen.getByLabelText('attributeTable.moreTools')).toBeTruthy();
    expect(screen.getByTestId('tb-customize')).toBeTruthy();
  });

  it('Reset restores the default layout and is disabled when it already is the default', async () => {
    render(<Harness initial={{ ...DEFAULT_LAYOUT, hidden: ['download'] }} />);
    await userEvent.click(screen.getByTestId('tb-customize'));
    expect((screen.getByTestId('tb-cust-reset') as HTMLButtonElement).disabled).toBe(false);
    await userEvent.click(screen.getByTestId('tb-cust-reset'));
    expect(screen.getByTestId('tb-download')).toBeTruthy();
    expect((screen.getByTestId('tb-cust-reset') as HTMLButtonElement).disabled).toBe(true);
  });

  it('only lists items this layer has (no colour or view item without them)', async () => {
    render(<Harness />);
    await userEvent.click(screen.getByTestId('tb-customize'));
    expect(screen.queryByTestId('tb-cust-colour')).toBeNull();
    expect(screen.queryByTestId('tb-cust-view')).toBeNull();
    expect(screen.getByTestId('tb-cust-update')).toBeTruthy();
  });
});

describe('useToolbarLayout', () => {
  it('keeps the layout in the browser and restores it, tolerating junk', () => {
    const first = renderHook(() => useToolbarLayout());
    act(() => first.result.current.setLayout({ ...DEFAULT_LAYOUT, hidden: ['download'] }));
    first.unmount();
    const again = renderHook(() => useToolbarLayout());
    expect(again.result.current.layout.hidden).toEqual(['download']);
    again.unmount();
    localStorage.setItem('cfms.attributeToolbar.layout', '{not json');
    expect(renderHook(() => useToolbarLayout()).result.current.layout).toEqual(DEFAULT_LAYOUT);
  });
});
