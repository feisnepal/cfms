/**
 * CalcCommandPalette — Ctrl/Cmd+K quick-switch.
 *
 * WORKSPACE_FLOW_NAV_PLAN P2b. The option count is now **derived from the
 * registry** rather than hardcoded. The previous assertion was a literal `21`
 * with the per-group breakdown in a comment, which is exactly the kind of
 * assertion that breaks silently on a regroup and gets "fixed" by editing the
 * number instead of asking why the number moved.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { CalcCommandPalette } from '../CalcCommandPalette';
import { TABS } from '../../../pages/calculationTabConfig';
import { GROUP_CONTEXTS } from '../calcContexts';

vi.mock('../../../i18n/hooks', () => ({
  useT: () => (key: string) => key,
}));

const REGISTRY_TOTAL = TABS.reduce((n, t) => n + GROUP_CONTEXTS[t].length, 0);

const openPalette = () =>
  fireEvent.keyDown(window, { key: 'k', ctrlKey: true });

describe('CalcCommandPalette', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('Ctrl+K opens it; every registry context is listed', () => {
    render(<CalcCommandPalette onNavigate={vi.fn()} />);
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    openPalette();
    expect(screen.getAllByRole('option')).toHaveLength(REGISTRY_TOTAL);
    expect(REGISTRY_TOTAL).toBe(19);
  });

  it('lists no context that has been retired', () => {
    // D3/D4/D6/D9 removed six contexts. The palette is built from the registry,
    // so they cannot appear — this asserts the *user-visible* consequence.
    render(<CalcCommandPalette onNavigate={vi.fn()} />);
    openPalette();
    const text = screen.getAllByRole('option').map((o) => o.textContent).join(' ');
    for (const gone of [
      'workspace.sidebar.subAreas',
      'workspace.sidebar.maps',
      'workspace.sidebar.totalInventory',
    ]) {
      expect(text, gone).not.toContain(gone);
    }
  });

  it('filters by label and Enter navigates to the highlighted entry', () => {
    const onNavigate = vi.fn();
    render(<CalcCommandPalette onNavigate={onNavigate} />);
    openPalette();
    const input = screen.getByPlaceholderText('calc.palette.placeholder');
    fireEvent.change(input, { target: { value: 'biodiversity' } });
    expect(screen.getAllByRole('option')).toHaveLength(1);
    fireEvent.keyDown(input, { key: 'Enter' });
    // biodiversity moved from data-maps to the `field` phase.
    expect(onNavigate).toHaveBeenCalledWith('field', 'biodiversity');
  });

  it('shows the empty state when nothing matches', () => {
    render(<CalcCommandPalette onNavigate={vi.fn()} />);
    openPalette();
    fireEvent.change(screen.getByPlaceholderText('calc.palette.placeholder'), {
      target: { value: 'zzzznope' },
    });
    expect(screen.getByText('calc.palette.empty')).toBeInTheDocument();
  });
});
