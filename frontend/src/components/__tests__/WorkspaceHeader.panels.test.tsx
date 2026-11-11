/** The header's panel buttons sit behind the single "Layers" button (owner rule 2026-10-10): they took too much room. */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import en from '../../i18n/locales/en.json';

vi.mock('react-i18next', () => {
  const lookup = (key: string): unknown =>
    key.split('.').reduce<unknown>((node, part) => (node as Record<string, unknown> | undefined)?.[part], en);
  const t = (key: string, values: Record<string, unknown> = {}): string => {
    const node = lookup(key);
    if (typeof node !== 'string') return key;
    return node.replace(/\{\{\s*(\w+)\s*\}\}/g, (_m, name) => String(values[name] ?? ''));
  };
  return { useTranslation: () => ({ t, i18n: { language: 'en' } }) };
});
vi.mock('../DfoReviewPanel', () => ({ DfoReviewPanel: () => null }));
vi.mock('../ExportButton', () => ({ ExportButton: () => null }));
vi.mock('../UnsavedEditBar', () => ({ UnsavedEditBar: () => null }));
vi.mock('../AddDataButton', () => ({ default: () => null }));
vi.mock('../BulkImportRunner', () => ({ default: () => null }));

import { WorkspaceHeader } from '../WorkspaceHeader';

const PANELS = [
  { id: 'layers', label: 'Layers', icon: '▤', visible: true },
  { id: 'basemap', label: 'Basemap', icon: '▧', visible: true },
  { id: 'imported', label: 'Imported Layers', icon: '⬈', visible: true },
  { id: 'raster', label: 'Raster Layers', icon: '▨', visible: true },
  { id: 'attributeTable', label: 'Attribute Table...', icon: '☷', visible: true },
  { id: 'legend', label: 'Legend', icon: '◈', visible: true },
];
const base = { forestName: 'Forest', dimensionMode: 'block' as const, onDimensionToggle: () => undefined };

beforeEach(() => {
  localStorage.clear();
});

describe('WorkspaceHeader - panel buttons behind "Layers"', () => {
  it('shows only the Layers button until it is clicked', () => {
    render(<WorkspaceHeader {...base} panels={PANELS} onOpenYearlyPlan={() => undefined} onTogglePanel={() => undefined} />);
    const disclosure = screen.getByTestId('panel-toggles-disclosure');
    expect(disclosure.textContent).toContain('Layers');
    expect(disclosure.getAttribute('aria-expanded')).toBe('false');
    for (const name of ['Basemap', 'Imported Layers', 'Raster Layers', 'Attribute Table...', 'Legend']) {
      expect(screen.queryByText(name)).toBeNull();
    }
    expect(screen.queryByTestId('open-yearly-plan')).toBeNull();
  });

  it('reveals the other buttons, and the Yearly plan one, on click; a second click hides them again', () => {
    const open = vi.fn();
    const toggle = vi.fn();
    render(<WorkspaceHeader {...base} panels={PANELS} onOpenYearlyPlan={open} onTogglePanel={toggle} />);
    const disclosure = screen.getByTestId('panel-toggles-disclosure');
    fireEvent.click(disclosure);
    expect(disclosure.getAttribute('aria-expanded')).toBe('true');
    for (const name of ['Basemap', 'Imported Layers', 'Raster Layers', 'Attribute Table...', 'Legend']) {
      expect(screen.getByText(name)).toBeTruthy();
    }
    fireEvent.click(screen.getByTestId('open-yearly-plan'));
    expect(open).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByText('Legend'));
    expect(toggle).toHaveBeenCalledWith('legend');
    expect(toggle).not.toHaveBeenCalledWith('layers'); // opening the group does not hide or show the Layers panel
    fireEvent.click(disclosure);
    expect(screen.queryByText('Basemap')).toBeNull();
  });

  it('brings the Layers panel back if it was hidden', () => {
    const toggle = vi.fn();
    render(
      <WorkspaceHeader {...base} panels={PANELS.map((p) => (p.id === 'layers' ? { ...p, visible: false } : p))} onTogglePanel={toggle} />,
    );
    fireEvent.click(screen.getByTestId('panel-toggles-disclosure'));
    expect(toggle).toHaveBeenCalledWith('layers');
  });

  it('remembers the choice in this browser', () => {
    const { unmount } = render(<WorkspaceHeader {...base} panels={PANELS} onTogglePanel={() => undefined} />);
    fireEvent.click(screen.getByTestId('panel-toggles-disclosure'));
    unmount();
    render(<WorkspaceHeader {...base} panels={PANELS} onTogglePanel={() => undefined} />);
    expect(screen.getByTestId('panel-toggles-disclosure').getAttribute('aria-expanded')).toBe('true');
    expect(screen.getByText('Basemap')).toBeTruthy();
  });
});
