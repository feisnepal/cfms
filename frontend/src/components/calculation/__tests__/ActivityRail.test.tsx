/**
 * ActivityRail — the merged group/context navigator.
 *
 * WORKSPACE_FLOW_NAV_PLAN P2b/P4. The four groups are the phases of the work
 * (`base`, `field`, `analysis`, `plan`), their items are numbered steps, and
 * each carries a type badge plus a done/stale marker. The i18n mock returns the
 * key, so assertions are against keys, which is what makes them stable when a
 * translation changes.
 *
 * The accessible name of a step is composed (`"<n>. <label>"` plus any state),
 * so selectors here match on a trailing-key regex rather than the bare key.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ActivityRail } from '../ActivityRail';
import { useCalcRailStore, RAIL_WIDTH } from '../../../store/calcRailStore';
import { TABS } from '../../../pages/calculationTabConfig';
import { GROUP_CONTEXTS } from '../calcContexts';

vi.mock('../../../i18n/hooks', () => ({
  // Interpolates, so a key carrying values renders as "key:v1,v2" and a test can
  // assert the numbers reached the strip.
  useT: () => (k: string, o?: Record<string, unknown>) =>
    o ? `${k}:${Object.values(o).join(',')}` : k,
}));

/** The group labels the rail renders, in order — derived, never re-typed. */
const GROUP_LABEL_KEYS = TABS.map((t) => `workspace.phase.${t}`);

const render1 = (over: Partial<Parameters<typeof ActivityRail>[0]> = {}) =>
  render(
    <ActivityRail
      activeTab="analysis"
      activeContext="sustainablefm"
      onSelectGroup={vi.fn()}
      onNavigate={vi.fn()}
      {...over}
    />,
  );

describe('ActivityRail', () => {
  beforeEach(() => {
    localStorage.clear();
    useCalcRailStore.setState({ mode: 'expanded', width: RAIL_WIDTH.DEFAULT });
  });

  it('renders the four phase groups as a vertical tablist, in workflow order', () => {
    render1();
    const tabs = screen.getAllByRole('tab');
    expect(tabs.map((b) => b.textContent)).toEqual(GROUP_LABEL_KEYS);
    expect(GROUP_LABEL_KEYS).toEqual([
      'workspace.phase.base',
      'workspace.phase.field',
      'workspace.phase.analysis',
      'workspace.phase.plan',
    ]);
  });

  it('the active group is selected', () => {
    render1();
    expect(screen.getByRole('tab', { name: 'workspace.phase.analysis' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
  });

  it('the active group shows its steps; the active one is aria-current', () => {
    render1();
    expect(screen.getByRole('button', { name: /sustainableFm$/ })).toHaveAttribute(
      'aria-current',
      'page',
    );
    expect(screen.getByRole('button', { name: /cba$/ })).toBeInTheDocument();
  });

  it('clicking a group tab selects that group (does not navigate a step)', () => {
    const onSelectGroup = vi.fn();
    const onNavigate = vi.fn();
    render1({ onSelectGroup, onNavigate });
    fireEvent.click(screen.getByRole('tab', { name: 'workspace.phase.field' }));
    expect(onSelectGroup).toHaveBeenCalledWith('field');
    expect(onNavigate).not.toHaveBeenCalled();
  });

  it('a step click navigates with (group, ctx)', () => {
    const onNavigate = vi.fn();
    render1({ onNavigate });
    fireEvent.click(screen.getByRole('button', { name: /sustainableFm$/ }));
    expect(onNavigate).toHaveBeenCalledWith('analysis', 'sustainablefm');
  });

  it('a non-active group is collapsed; its peek chevron previews without navigating', () => {
    const onSelectGroup = vi.fn();
    render1({ onSelectGroup });
    expect(screen.queryByRole('button', { name: /inventory.title$/ })).not.toBeInTheDocument();
    const peeks = screen.getAllByRole('button', { name: /calc.rail.peek/ });
    expect(peeks).toHaveLength(3);
    fireEvent.click(peeks[0]);
    expect(screen.getByRole('button', { name: /map$/ })).toBeInTheDocument();
    expect(onSelectGroup).not.toHaveBeenCalled();
  });

  it('a disabled group disables its tab (role gate only)', () => {
    render1({ disabledTabs: ['field'] });
    expect(screen.getByRole('tab', { name: 'workspace.phase.field' })).toBeDisabled();
  });

  it('the header button toggles icon-only (compact) and back', () => {
    render1();
    expect(screen.getAllByRole('tab').every((t) => t.textContent!.trim().length > 0)).toBe(true);

    fireEvent.click(screen.getByRole('button', { name: 'calc.subnav.collapse' }));
    expect(useCalcRailStore.getState().mode).toBe('compact');
    const compactTabs = screen.getAllByRole('tab');
    expect(compactTabs).toHaveLength(4);
    expect(compactTabs.every((t) => t.textContent!.trim() === '')).toBe(true);
    // The accessible name is the i18n KEY, which proves the label goes through
    // t() now rather than being hardcoded English.
    expect(compactTabs[0]).toHaveAttribute('aria-label', 'workspace.phase.base');

    fireEvent.click(screen.getByRole('button', { name: 'calc.subnav.show' }));
    expect(screen.getAllByRole('tab').map((t) => t.textContent)).toEqual(GROUP_LABEL_KEYS);
  });

  it('lists every step of a group, and only those', () => {
    render1({ activeTab: 'field', activeContext: 'sampling' });
    for (const c of GROUP_CONTEXTS.field.filter((x) => !x.optional)) {
      expect(
        screen.getByRole('button', { name: new RegExp(`${c.labelKey}( workflow\.stepper\.incomplete)?$`) }),
        c.labelKey,
      ).toBeInTheDocument();
    }
    expect(screen.queryByRole('button', { name: /cba$/ })).not.toBeInTheDocument();
  });

  // ── the governing rule ──────────────────────────────────────────────────
  it('every step is reachable even when its prerequisites are unmet', () => {
    // "Sequence, never enforce": nothing is complete, and every step must still
    // be enabled and clickable.
    const onNavigate = vi.fn();
    render1({
      activeTab: 'field',
      activeContext: 'fieldbook',
      isDone: () => false,
      doneCount: 0,
      totalCount: 15,
      onNavigate,
    });
    for (const c of GROUP_CONTEXTS.field.filter((x) => !x.optional)) {
      const btn = screen.getByRole('button', { name: new RegExp(`${c.labelKey}( workflow\.stepper\.incomplete)?$`) });
      expect(btn, c.labelKey).toBeEnabled();
      fireEvent.click(btn);
    }
    expect(onNavigate).toHaveBeenCalledTimes(GROUP_CONTEXTS.field.filter((x) => !x.optional).length);
    // And the strip reports zero progress rather than hiding anything.
    expect(screen.getByText(/0,15/)).toBeInTheDocument();
  });

  it('reports progress in the readiness strip', () => {
    render1({ doneCount: 4, totalCount: 15 });
    expect(screen.getByText(/4,15/)).toBeInTheDocument();
  });

  it('the Optional band is collapsed by default and reveals the Trial page', () => {
    const onNavigate = vi.fn();
    render1({ activeTab: 'field', activeContext: 'sampling', onNavigate });
    expect(screen.queryByRole('button', { name: /treeModel/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /optional/i }));
    fireEvent.click(screen.getByRole('button', { name: /treeModel/ }));
    expect(onNavigate).toHaveBeenCalledWith('field', 'treemodel');
  });

  it('the Advanced pages (Analysis, Hazard & Erosion) are in the same collapsed band, not among the numbered steps', () => {
    const onNavigate = vi.fn();
    render1({ onNavigate });
    expect(screen.queryByRole('button', { name: /hazardErosion$/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /sidebar\.analysis$/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /optional/i }));
    fireEvent.click(screen.getByRole('button', { name: /hazardErosion/ }));
    expect(onNavigate).toHaveBeenCalledWith('analysis', 'hazarderosion');
    fireEvent.click(screen.getByRole('button', { name: /sidebar\.analysis/ }));
    expect(onNavigate).toHaveBeenCalledWith('analysis', 'analysis');
  });

  it('marks a done step and a stale step in the accessible name', () => {
    render1({
      activeTab: 'analysis',
      activeContext: 'cba',
      isDone: (id: string) => id === 'cba',
      stale: [{ step: 'cba', seen: 2 }],
    });
    const label = screen.getByRole('button', { name: /cba/ })
      .getAttribute('aria-label');
    expect(label).toContain('workflow.rail.done');
    expect(label).toContain('workflow.rail.stale');
  });

  it('the number and badge glyph are decoration, not read aloud separately', () => {
    render1({ activeTab: 'analysis', activeContext: 'cba' });
    // The composed name carries step and state once; the inner glyphs are hidden
    // so a screen reader does not announce "13" and a symbol separately.
    const label = screen.getByRole('button', { name: /cba/ }).getAttribute('aria-label')!;
    expect(label.startsWith('13. ')).toBe(true);
  });
});

describe('ActivityRail - Template store entry', () => {
  beforeEach(() => useCalcRailStore.setState({ mode: 'expanded', width: RAIL_WIDTH.DEFAULT }));

  it('offers the store plainly while steps are open, and as a call to action once the export gate says the forest is ready', () => {
    const open = vi.fn();
    const { rerender } = render1({ onOpenStore: open });
    expect(screen.getByTestId('rail-template-store').textContent).toContain('workflow.store.rail');
    expect(screen.getByTestId('rail-template-store').textContent).not.toContain('railReady');
    rerender(
      <ActivityRail activeTab="analysis" activeContext="sustainablefm" onSelectGroup={vi.fn()} onNavigate={vi.fn()}
        onOpenStore={open} storeReady />,
    );
    expect(screen.getByTestId('rail-template-store').textContent).toContain('workflow.store.railReady');
    fireEvent.click(screen.getByTestId('rail-template-store'));
    expect(open).toHaveBeenCalledTimes(1);
  });

  it('shows no store button where no handler is given', () => {
    render1();
    expect(screen.queryByTestId('rail-template-store')).toBeNull();
  });
});

