/**
 * contextResolver — the context -> component contract. WORKSPACE_FLOW_NAV_PLAN P2a.
 *
 * P2a's gate is "behaviour identical". That is only checkable if the mapping is
 * pinned, because the four per-group container components it replaces were
 * `===` switch statements whose behaviour lived in their own files and had no
 * test of their own beyond one container's test.
 *
 * What is asserted here:
 *  1. Every context in the registry resolves to a renderer. A missing entry is a
 *     blank panel, which is the failure the containers could not produce.
 *  2. Context ids are globally unique across groups, because the resolver is
 *     keyed by id alone.
 *  3. All 21 legacy `?surface=` ids and all 21 legacy `?tab=&context=` pairs
 *     still resolve — the deep-link contract.
 *  4. Unmapped ids render nothing, matching what the containers did.
 *  5. The `treemodel` composition still renders the generator and the all-tree
 *     export accordion together, and still derives `hasCompartments` from
 *     `result_data`. This is the port of the old `SamplingModelTab` test.
 */
import { describe, it, expect, vi } from 'vitest';
import React, { Suspense } from 'react';
import { render, screen } from '@testing-library/react';
import { TABS } from '../../../pages/calculationTabConfig';
import { GROUP_CONTEXTS } from '../calcContexts';
import { toSurfaceId, parseSurfaceId } from '../../../lib/calcSurface';
import { CONTEXT_COMPONENTS, CONTEXT_TABS, RESOLVED_CONTEXT_IDS, renderContext } from '../contextComponents';
import TreeModelPanel from '../contexts/TreeModelPanel';

vi.mock('../../../i18n/hooks', () => ({ useT: () => (k: string) => k }));
vi.mock('../../../components/TreeModelGenerator', () => ({
  __esModule: true,
  default: (p: { forestName?: string; hasCompartments?: boolean }) => (
    <div
      data-testid="tree-model"
      data-forest={p.forestName}
      data-compartments={String(!!p.hasCompartments)}
    />
  ),
  TotalTreeExportAccordion: () => <div data-testid="all-tree-exports" />,
}));

const base = {
  calculationId: 'c1',
  permissions: {},
  structureLocked: false,
  mapLifecycleStatus: 'completed',
};

const allRegistryContexts = TABS.flatMap((t) => GROUP_CONTEXTS[t].map((c) => c.id));

describe('CONTEXT_COMPONENTS', () => {
  it('every context in the registry resolves, flat or tabbed', () => {
    // Since P5a a context is rendered either by a single node in
    // CONTEXT_COMPONENTS or by a set of panes in CONTEXT_TABS, so a registry
    // entry missing from BOTH would render nothing. Mutual exclusion (never both)
    // is asserted in `contextTabs.test.tsx`.
    const missing = allRegistryContexts.filter(
      (id) => !CONTEXT_COMPONENTS[id] && !CONTEXT_TABS[id],
    );
    expect(missing).toEqual([]);
  });

  it('context ids are unique across all groups', () => {
    // The resolver is keyed by id alone, so a reused id would silently shadow.
    expect(new Set(allRegistryContexts).size).toBe(allRegistryContexts.length);
  });

  it('covers 19 registry contexts plus the 4 legacy workspace ids', () => {
    // boundary / blocks / subcompartments / block_naming are not in
    // GROUP_CONTEXTS but survive as pass-through deep links, so they must keep
    // resolving. block_naming additionally used to render a blank panel.
    expect(allRegistryContexts).toHaveLength(19);
    expect(RESOLVED_CONTEXT_IDS).toHaveLength(23);
    for (const legacy of ['boundary', 'blocks', 'subcompartments', 'block_naming']) {
      expect(CONTEXT_COMPONENTS[legacy], legacy).toBeTypeOf('function');
    }
  });

  it('has no entries beyond the registry and the legacy workspace ids', () => {
    // Catches a stale entry left behind after a context is removed.
    const allowed = new Set([
      ...allRegistryContexts,
      'boundary',
      'blocks',
      'subcompartments',
      'block_naming',
    ]);
    expect(RESOLVED_CONTEXT_IDS.filter((id) => !allowed.has(id))).toEqual([]);
  });

  it('the six retired contexts are unreachable, not merely hidden', () => {
    // D3 subareas/compartments/maps, D4 totalinventory, D6 reports,
    // D9 yearlyactivities. A stale bookmark must not be able to render them.
    for (const gone of [
      'subareas',
      'compartments',
      'maps',
      'totalinventory',
      'reports',
      'yearlyactivities',
    ]) {
      expect(CONTEXT_COMPONENTS[gone], gone).toBeUndefined();
      expect(renderContext(gone, base as never), gone).toBeNull();
    }
  });

  it('a context is tabbed or flat, never both', () => {
    // The resolver checks CONTEXT_TABS first, so a context in both maps would
    // silently stop being flat. That is exactly how the flat map's count
    // shrank once before, and the count test above would not catch it.
    for (const id of Object.keys(CONTEXT_TABS)) {
      expect(CONTEXT_COMPONENTS[id], id).toBeUndefined();
    }
  });

  it('every tabbed pane has a body and a matching registry tab', () => {
    // Two halves of one contract: the registry (calcContexts) decides the tab
    // order, labels and locks; the resolver (CONTEXT_TABS) supplies the bodies.
    // If they drift, the host renders a tab with no pane or a pane with no tab,
    // and the mismatch is invisible until someone clicks it.
    for (const [id, group] of Object.entries(CONTEXT_TABS)) {
      const spec = TABS.flatMap((t) => GROUP_CONTEXTS[t]).find((c) => c.id === id);
      expect(spec, `${id} is in CONTEXT_TABS but not in the registry`).toBeDefined();
      expect(spec!.tabs?.map((t) => t.id).sort(), `${id} tab order`).toEqual(
        Object.keys(group.panes).sort(),
      );
      for (const [paneId, pane] of Object.entries(group.panes)) {
        expect(pane.id, `${id}/${paneId} id matches its key`).toBe(paneId);
        expect(pane.render, `${id}/${paneId} has a body`).toBeTypeOf('function');
      }
    }
  });

  it('locks only Results, and only where there is nothing behind it', () => {
    // A locked *entering* pane would make the step unusable, and a locked
    // Results pane is only honest when it is derived from this step's own data.
    for (const [id, group] of Object.entries(CONTEXT_TABS)) {
      for (const [paneId, pane] of Object.entries(group.panes)) {
        const locked = pane.locked === true;
        const needsData = pane.needsStepData === true;
        if (locked || needsData) {
          expect(paneId, `${id}/${paneId}`).toMatch(/^results$|^yearly$|^plan$/);
        }
      }
    }
  });
});

describe('legacy deep links', () => {
  it('all 19 registry surfaces resolve to a renderer', () => {
    for (const tab of TABS) {
      for (const ctx of GROUP_CONTEXTS[tab]) {
        const parsed = parseSurfaceId(toSurfaceId(tab, ctx.id));
        expect(parsed).not.toBeNull();
        // Flat or tabbed — a tabbed context resolves through CONTEXT_TABS.
        const resolved = CONTEXT_COMPONENTS[parsed!.ctx] ?? CONTEXT_TABS[parsed!.ctx];
        expect(resolved, `${tab}/${ctx.id}`).toBeDefined();
      }
    }
  });

  it('the legacy ?tab=&context= pair lands on the same context', () => {
    // The shell composes the pair into `group/context`, so both shapes run
    // through one resolver (plan 6.1).
    for (const tab of TABS) {
      for (const ctx of GROUP_CONTEXTS[tab]) {
        expect(parseSurfaceId(toSurfaceId(tab, ctx.id))).toEqual({ tab, ctx: ctx.id });
      }
    }
  });
});

describe('renderContext', () => {
  it('renders nothing for an unmapped id', () => {
    expect(renderContext('does_not_exist', base as never)).toBeNull();
  });

  it('builds an element for EVERY resolved id, not just a sample', () => {
    // Building the element (rather than mounting it) is the part that depends on
    // the mapping; mounting would additionally depend on every leaf's providers.
    const broken = RESOLVED_CONTEXT_IDS.filter((id) => !React.isValidElement(renderContext(id, base as never)));
    expect(broken).toEqual([]);
  });
});

// Port of the old `SamplingModelTab` test.
//
// `treemodel` is the one context that is a composition rather than a single leaf,
// and the only one whose props are derived from `calculation` instead of passed
// through. It is tested against `TreeModelPanel` directly rather than through
// `renderContext`, because every leaf sits behind `React.lazy` and a dynamic
// import does not reliably pick up a `vi.mock` factory — mounting it here would
// assert on the mock's behaviour, not on the composition. The mapping itself is
// covered by the "builds an element for EVERY resolved id" case above.
describe('TreeModelPanel (the treemodel composition)', () => {
  it('renders BOTH the model generator and the All-Tree Exports accordion', () => {
    render(<TreeModelPanel calculationId="c1" />);
    expect(screen.getByTestId('tree-model')).toBeInTheDocument();
    expect(screen.getByTestId('all-tree-exports')).toBeInTheDocument();
  });

  it('passes forestName + hasCompartments through from the calculation', () => {
    render(
      <TreeModelPanel
        calculationId="c1"
        calculation={{ forest_name: 'Alpha CF', result_data: { compartments: [{}] } }}
      />,
    );
    const el = screen.getByTestId('tree-model');
    expect(el).toHaveAttribute('data-forest', 'Alpha CF');
    expect(el).toHaveAttribute('data-compartments', 'true');
  });

  it('reports no compartments when result_data has none', () => {
    render(<TreeModelPanel calculationId="c1" calculation={{ forest_name: 'Beta CF' }} />);
    expect(screen.getByTestId('tree-model')).toHaveAttribute('data-compartments', 'false');
  });

  it('tolerates a missing calculation', () => {
    render(<TreeModelPanel calculationId="c1" />);
    expect(screen.getByTestId('tree-model')).toHaveAttribute('data-compartments', 'false');
  });
});
