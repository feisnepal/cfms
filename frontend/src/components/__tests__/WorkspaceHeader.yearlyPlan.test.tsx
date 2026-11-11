/**
 * The workspace header's "Yearly plan" button (YEARLY_ACTIVITIES plan P4, YA-4.6): the way into the yearly plan
 * table that does not depend on the Activity Features layer being active.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
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
import { useWorkspaceStore } from '../../store/workspaceStore';

const base = { forestName: 'Forest', dimensionMode: 'block' as const, onDimensionToggle: () => undefined };

describe('WorkspaceHeader — Yearly plan button', () => {
  it('opens the yearly plan table when pressed', () => {
    const open = vi.fn();
    render(<WorkspaceHeader {...base} onOpenYearlyPlan={open} />);
    const button = screen.getByTestId('open-yearly-plan');
    expect(button.textContent).toBe('Yearly plan');
    expect(button).toHaveAttribute('title', 'Show the yearly plan table');
    fireEvent.click(button);
    expect(open).toHaveBeenCalledTimes(1);
  });

  it('is not shown when the host does not offer it (the guidance flag is off)', () => {
    render(<WorkspaceHeader {...base} />);
    expect(screen.queryByTestId('open-yearly-plan')).toBeNull();
  });
});

// Owner request, 2026-09-24: "Submit to Analysis" (and its siblings Withdraw
// / Review / Unlock) were plain unstyled <button>s whose text looked larger
// than the rest of the header. Converted to icon + tooltip — these tests
// pin the accessible name (aria-label) and tooltip (title) so that
// conversion can't silently lose either.
describe('WorkspaceHeader — lifecycle actions are icon + tooltip, not bare text', () => {
  afterEach(() => {
    useWorkspaceStore.setState({ mapLifecycleStatus: 'draft' } as never);
  });

  it('draft: Submit to Analysis is an icon button with the right tooltip, and opens the confirm dialog', () => {
    useWorkspaceStore.setState({ mapLifecycleStatus: 'draft' } as never);
    render(<WorkspaceHeader {...base} />);
    const button = screen.getByRole('button', { name: 'Submit to Analysis' });
    expect(button).toHaveAttribute('title', 'Submit to Analysis — this freezes the map for editing');
    expect(button.textContent).not.toBe('Submit to Analysis'); // it's a symbol now, not the label
    fireEvent.click(button);
    expect(screen.getByText('Submit this map for analysis?')).toBeInTheDocument();
  });

  it('submitted: Withdraw and Review are icon buttons with the right tooltips', () => {
    useWorkspaceStore.setState({ mapLifecycleStatus: 'submitted' } as never);
    render(<WorkspaceHeader {...base} />);
    const withdraw = screen.getByRole('button', { name: 'Withdraw' });
    expect(withdraw).toHaveAttribute('title', 'Take the map back — only while analysis has not started');
    const review = screen.getByRole('button', { name: 'Review' });
    expect(review).toHaveAttribute('title', 'Open DFO review panel');
  });

  it('locked: Unlock is an icon button with the right tooltip', () => {
    useWorkspaceStore.setState({ mapLifecycleStatus: 'locked' } as never);
    render(<WorkspaceHeader {...base} />);
    const unlock = screen.getByRole('button', { name: 'Unlock' });
    expect(unlock).toHaveAttribute('title', 'Super admin unlock');
    expect(unlock).toHaveClass('unlock-btn');
  });
});
