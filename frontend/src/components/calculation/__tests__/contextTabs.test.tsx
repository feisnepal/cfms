/**
 * P5a — the inner-tab mechanism. WORKSPACE_FLOW_NAV_PLAN §8.4.
 *
 * `useT` is mocked to return the key, following `WorkflowStepper.test.tsx`. That
 * is deliberate rather than lazy: it makes "the label came from `labelKey`" a
 * literal assertion, because the only way a key can appear in the DOM is if the
 * component asked for it. The separate bundle test below then proves each key
 * actually resolves, so the two together cover what a real provider would.
 *
 * What is asserted and why:
 * - **Only the active pane is mounted.** The pane bodies fetch on mount, so a
 *   three-tab page mounting all three would triple every request.
 * - **The registry and the resolver must agree.** A `tabs` entry with no body
 *   renders nothing; a body with no `tabs` entry is unreachable. Both are silent
 *   failures otherwise, which is the class of bug P2a/P2b kept hitting.
 * - **Un-tabbed contexts keep the P2a path**, so the mechanism must not leak into
 *   the 11 contexts that are not tabbed.
 */
import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react';
import { vi } from 'vitest';
import React, { lazy } from 'react';
import ContextTabHost, { type ContextTabDefinition } from '../ContextTabHost';
import {
  CONTEXT_COMPONENTS,
  CONTEXT_TABS,
  renderContext,
  RESOLVED_CONTEXT_IDS,
} from '../contextComponents';
import { GROUP_CONTEXTS, findContext } from '../calcContexts';
import { TABS } from '../../../pages/calculationTabConfig';
import en from '../../../i18n/locales/en.json';
import ne from '../../../i18n/locales/ne.json';

vi.mock('../../../i18n/hooks', () => ({
  useT: () => (k: string) => k,
}));

afterEach(cleanup);

const PANEL_PROPS = {
  calculationId: 'calc-1',
  calculation: null,
  permissions: {},
  structureLocked: false,
  mapLifecycleStatus: 'idle',
} as any;

const pane = (id: string, locked = false): ContextTabDefinition => ({
  id,
  labelKey: `probe.${id}`,
  render: () => <div data-testid={`pane-${id}`}>{id}</div>,
  locked,
});

const TWO_TABS = [
  { id: 'upload', labelKey: 'workflow.tab.uploadData' },
  { id: 'results', labelKey: 'workflow.tab.results' },
];

const flat = (bundle: any, key: string) =>
  key.split('.').reduce<any>((acc, part) => acc?.[part], bundle);

describe('ContextTabHost', () => {
  const panes = { upload: pane('upload'), results: pane('results') };

  it('renders one tab per registry entry, labelled from the i18n key', () => {
    render(<ContextTabHost {...PANEL_PROPS} tabs={TWO_TABS} panes={panes} label="Field Inventory" />);

    expect(screen.getByRole('tab', { name: 'workflow.tab.uploadData' })).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'workflow.tab.results' })).toBeTruthy();
    // The bar carries the step's own label, so it is distinguishable in a11y trees.
    expect(screen.getByRole('tablist', { name: 'Field Inventory' })).toBeTruthy();
  });

  it('mounts only the active pane, so a tabbed page fetches once', () => {
    render(<ContextTabHost {...PANEL_PROPS} tabs={TWO_TABS} panes={panes} />);

    expect(screen.getByTestId('pane-upload')).toBeTruthy();
    expect(screen.queryByTestId('pane-results')).toBeNull();

    fireEvent.click(screen.getByRole('tab', { name: 'workflow.tab.results' }));
    expect(screen.getByTestId('pane-results')).toBeTruthy();
    expect(screen.queryByTestId('pane-upload')).toBeNull();
  });

  it('opens on the first pane that is not locked', () => {
    // `results` is declared first but locked, so the page must not open on it.
    const tabs = [
      { id: 'results', labelKey: 'workflow.tab.results' },
      { id: 'upload', labelKey: 'workflow.tab.uploadData' },
    ];
    render(
      <ContextTabHost
        {...PANEL_PROPS}
        tabs={tabs}
        panes={{ upload: pane('upload'), results: pane('results', true) }}
      />,
    );
    expect(screen.getByTestId('pane-upload')).toBeTruthy();
  });

  it('disables a locked pane and gives it a reason, without blocking the step', () => {
    render(
      <ContextTabHost
        {...PANEL_PROPS}
        tabs={TWO_TABS}
        panes={{ upload: pane('upload'), results: pane('results', true) }}
      />,
    );

    const results = screen.getByRole('tab', { name: 'workflow.tab.results' }) as HTMLButtonElement;
    expect(results.disabled).toBe(true);
    expect(results.getAttribute('title')).toBe('workflow.tabs.resultsLocked');
    // Sequence, never enforce: the pane that does the entering is still usable.
    expect(screen.getByTestId('pane-upload')).toBeTruthy();
  });

  it('locks a needsStepData pane until the step reports it has data', () => {
    // The lock is the step's own server-side readiness, so a Results tab cannot
    // disagree with the tick mark beside the step in the rail.
    const tabs = [
      { id: 'data', labelKey: 'workflow.tab.data' },
      { id: 'results', labelKey: 'workflow.tab.results', needsStepData: true },
    ];
    const panes = { data: pane('data'), results: pane('results') };

    const { rerender } = render(
      <ContextTabHost {...PANEL_PROPS} tabs={tabs} panes={panes} stepDone={false} />,
    );
    const results = () => screen.getByRole('tab', { name: 'workflow.tab.results' }) as HTMLButtonElement;
    expect(results().disabled).toBe(true);
    // Opens on the pane that has something behind it.
    expect(screen.getByTestId('pane-data')).toBeTruthy();

    rerender(<ContextTabHost {...PANEL_PROPS} tabs={tabs} panes={panes} stepDone />);
    expect(results().disabled).toBe(false);
  });

  it('leaves a pane open when readiness is unknown, rather than guessing it is empty', () => {
    // `stepDone` is omitted while readiness is still loading. Locking then would
    // flash a disabled tab on every page load, which reads as "your data is
    // gone" — so unknown means unlocked.
    const tabs = [
      { id: 'data', labelKey: 'workflow.tab.data' },
      { id: 'results', labelKey: 'workflow.tab.results', needsStepData: true },
    ];
    render(<ContextTabHost {...PANEL_PROPS} tabs={tabs} panes={{ data: pane('data'), results: pane('results') }} />);
    const results = screen.getByRole('tab', { name: 'workflow.tab.results' }) as HTMLButtonElement;
    expect(results.disabled).toBe(false);
  });

  it('shows the reason instead of a pane body if the open pane becomes locked', () => {
    const tabs = [
      { id: 'data', labelKey: 'workflow.tab.data' },
      { id: 'results', labelKey: 'workflow.tab.results', needsStepData: true },
    ];
    const panes = { data: pane('data'), results: pane('results') };
    const { rerender } = render(
      <ContextTabHost {...PANEL_PROPS} tabs={tabs} panes={panes} stepDone />,
    );
    fireEvent.click(screen.getByRole('tab', { name: 'workflow.tab.results' }));
    expect(screen.getByTestId('pane-results')).toBeTruthy();

    // The data was removed while the user was on Results.
    rerender(<ContextTabHost {...PANEL_PROPS} tabs={tabs} panes={panes} stepDone={false} />);
    expect(screen.queryByTestId('pane-results')).toBeNull();
    expect(screen.getByTestId('context-tabpanel-locked')).toBeTruthy();
  });

  it('says so plainly when the registry and the resolver disagree', () => {
    // A body for a tab id the registry never declared.
    render(
      <ContextTabHost
        {...PANEL_PROPS}
        tabs={[{ id: 'upload', labelKey: 'workflow.tab.uploadData' }]}
        panes={{ ghost: pane('ghost') }}
      />,
    );
    expect(screen.getByText('workflow.tabs.missingPane')).toBeTruthy();
  });

  it('keeps the selection when a pane suspends, because every real body is lazy', async () => {
    // Regression test for a bug the live probe found and the other tests could not:
    // pane bodies are `React.lazy`, and the shell's only Suspense boundary wraps
    // the entire panel. So a suspending pane used to bubble up, unmount the tab bar
    // with it, and remount the host on its default tab — the click looked inert and
    // the selection snapped back. Rendered here with a real lazy component.
    let resolveLazy: (() => void) | undefined;
    const LazyPane = lazy(
      () =>
        new Promise<{ default: React.FC }>((resolve) => {
          resolveLazy = () => resolve({ default: () => <div data-testid="pane-lazy">LAZY</div> });
        }),
    );
    const lazyPanes: Record<string, ContextTabDefinition> = {
      upload: pane('upload'),
      results: { id: 'results', labelKey: 'probe.results', render: () => <LazyPane /> },
    };

    render(<ContextTabHost {...PANEL_PROPS} tabs={TWO_TABS} panes={lazyPanes} />);

    fireEvent.click(screen.getByRole('tab', { name: 'workflow.tab.results' }));

    // Still suspended: the bar must still be there, on the tab the user chose.
    expect(screen.getByRole('tab', { name: 'workflow.tab.results' }).getAttribute('aria-selected')).toBe('true');
    expect(screen.getByRole('tab', { name: 'workflow.tab.uploadData' })).toBeTruthy();

    // And when it resolves, the selection is unchanged.
    await act(async () => {
      resolveLazy?.();
    });
    expect(screen.getByTestId('pane-lazy')).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'workflow.tab.results' }).getAttribute('aria-selected')).toBe('true');
  });
});

describe('the registry and the resolver agree about tabbed contexts', () => {
  const tabbed = TABS.flatMap((t) => GROUP_CONTEXTS[t].filter((c) => c.tabs?.length));

  it('at least one context is tabbed, so the assertions below are not vacuous', () => {
    expect(tabbed.length).toBeGreaterThan(0);
  });

  it('every declared tab has a body', () => {
    for (const item of tabbed) {
      const group = CONTEXT_TABS[item.id];
      expect(group, `${item.id} declares tabs but has no CONTEXT_TABS entry`).toBeTruthy();
      for (const tab of item.tabs!) {
        expect(group.panes[tab.id], `${item.id} declares tab "${tab.id}" with no body`).toBeTruthy();
      }
    }
  });

  it('no context is in both CONTEXT_COMPONENTS and CONTEXT_TABS', () => {
    const both = RESOLVED_CONTEXT_IDS.filter((id) => CONTEXT_COMPONENTS[id] && CONTEXT_TABS[id]);
    expect(both).toEqual([]);
  });

  it('every tab label key resolves in BOTH bundles', () => {
    for (const t of TABS) {
      for (const item of GROUP_CONTEXTS[t]) {
        for (const tab of item.tabs ?? []) {
          expect(flat(en, tab.labelKey), `en: ${item.id}/${tab.id} ${tab.labelKey}`).toBeTruthy();
          expect(flat(ne, tab.labelKey), `ne: ${item.id}/${tab.id} ${tab.labelKey}`).toBeTruthy();
        }
      }
    }
  });

  it('the labels a real provider would show are actually translated, not English leftovers', () => {
    for (const t of TABS) {
      for (const item of GROUP_CONTEXTS[t]) {
        for (const tab of item.tabs ?? []) {
          const enText = flat(en, tab.labelKey);
          const neText = flat(ne, tab.labelKey);
          expect(neText, `${tab.labelKey} is identical in both bundles`).not.toBe(enText);
        }
      }
    }
  });

  it('tab ids are unique within a context', () => {
    for (const t of TABS) {
      for (const item of GROUP_CONTEXTS[t]) {
        const ids = (item.tabs ?? []).map((x) => x.id);
        expect(new Set(ids).size, `${item.id} has duplicate tab ids`).toBe(ids.length);
      }
    }
  });

  it('Biodiversity and Tree Mapping are tabbed Data / Results, per plan 8.4', () => {
    // P5c. Both are split by the same rule — the pane that records data, and the
    // pane derived from it — so they are asserted together rather than twice.
    for (const id of ['biodiversity', 'treemapping']) {
      const item = findContext(id)?.item;
      expect(item?.tabs?.map((t) => t.id), id).toEqual(['data', 'results']);
      // Results is derived, so it locks off the step's own readiness.
      expect(item!.tabs![1].needsStepData, `${id} results`).toBe(true);
      // Data is where the entering happens; locking it would enforce sequence.
      expect(item!.tabs![0].needsStepData, `${id} data`).toBeUndefined();
    }
  });

  it('the entering pane is never locked, in any tabbed context', () => {
    // "Sequence, never enforce": if the first pane can be locked, the step can
    // become unopenable, and no amount of reachable-elsewhere navigation saves
    // a user who is already sitting on that step.
    for (const t of TABS) {
      for (const item of GROUP_CONTEXTS[t]) {
        if (!item.tabs?.length) continue;
        const first = item.tabs[0];
        expect(
          CONTEXT_TABS[item.id]?.panes?.[first.id]?.locked,
          `${item.id}/${first.id} is the entering pane and must not be locked`,
        ).not.toBe(true);
      }
    }
  });
});

describe('a provider outlives the pane switch', () => {
  // The host mounts one pane at a time, so state inside a pane is destroyed by
  // switching away. Anything that must survive — a half-filled form, a fetched
  // record — belongs in the group provider, which sits above the host. If this
  // ever regresses, the symptom is silent: the user's typing just disappears.
  const Counter: React.FC<{ children?: React.ReactNode }> = ({ children }) => {
    const [n, setN] = React.useState(0);
    return (
      <div>
        <button type="button" onClick={() => setN((v) => v + 1)}>
          bump
        </button>
        <span data-testid="count">{n}</span>
        {children}
      </div>
    );
  };

  const spec = [
    { id: 'data', labelKey: 'workflow.tab.data' },
    { id: 'results', labelKey: 'workflow.tab.results' },
  ];

  it('keeps provider state when the user looks at another tab and comes back', () => {
    // Proving the real ordering matters: a provider rendered *inside* the host
    // would be unmounted along with the pane it was meant to outlive.
    const Group: React.FC<{ children?: React.ReactNode }> = ({ children }) => <Counter>{children}</Counter>;
    const panes = {
      data: pane('data'),
      results: pane('results'),
    };
    render(
      <Group>
        <ContextTabHost {...PANEL_PROPS} tabs={spec} panes={panes} />
      </Group>,
    );

    fireEvent.click(screen.getByText('bump'));
    fireEvent.click(screen.getByText('bump'));
    expect(screen.getByTestId('count').textContent).toBe('2');

    fireEvent.click(screen.getByRole('tab', { name: 'workflow.tab.results' }));
    expect(screen.getByTestId('count').textContent).toBe('2');
    fireEvent.click(screen.getByRole('tab', { name: 'workflow.tab.data' }));
    expect(screen.getByTestId('count').textContent, 'state was lost on the switch').toBe('2');
  });

  it('renderContext puts the provider ABOVE the host, not inside it', () => {
    // The test above proves React's semantics; this proves our wiring. If the
    // provider were rendered inside the host it would be unmounted with the pane
    // it exists to outlive, and the symptom would be a form that quietly forgets
    // what the user typed. So this asserts the ordering through the real
    // resolver, with a provider supplied by a real tabbed group.
    const bumps: string[] = [];
    const Provider: React.FC<{ children?: React.ReactNode }> = ({ children }) => {
      const [n, setN] = React.useState(0);
      return (
        <div>
          <button type="button" onClick={() => { bumps.push(`bump:${n}`); setN((v) => v + 1); }}>
            provider-bump
          </button>
          <span data-testid="wired-count">{n}</span>
          {children}
        </div>
      );
    };

    const id = 'biodiversity';
    const real = CONTEXT_TABS[id];
    CONTEXT_TABS[id] = {
      provider: Provider,
      panes: {
        data: { id: 'data', labelKey: 'workflow.tab.data', render: () => <div>pane-data</div> },
        results: { id: 'results', labelKey: 'workflow.tab.results', render: () => <div>pane-results</div> },
      },
    };
    try {
      const { unmount } = render(renderContext(id, PANEL_PROPS, true));
      fireEvent.click(screen.getByText('provider-bump'));
      expect(screen.getByTestId('wired-count').textContent).toBe('1');

      fireEvent.click(screen.getByRole('tab', { name: 'workflow.tab.results' }));
      expect(screen.getByText('pane-results')).toBeTruthy();
      expect(
        screen.getByTestId('wired-count').textContent,
        'provider state died with the pane',
      ).toBe('1');

      fireEvent.click(screen.getByRole('tab', { name: 'workflow.tab.data' }));
      expect(screen.getByTestId('wired-count').textContent).toBe('1');
      expect(bumps, 'the provider re-rendered, so the bump re-ran').toEqual(['bump:0']);
      unmount();
    } finally {
      CONTEXT_TABS[id] = real;
    }
  });

  it('a group without a provider still renders', () => {
    // The slot is optional: biodiversity and treemapping have no
    // shared state to keep, and adding the feature must not change them.
    for (const id of ['biodiversity', 'treemapping']) {
      expect(CONTEXT_TABS[id].provider, `${id} should not need a provider`).toBeUndefined();
      const el = renderContext(id, PANEL_PROPS, true);
      expect(el, `${id} did not render`).not.toBeNull();
    }
  });
});

describe('renderContext routing', () => {
  it('leaves an un-tabbed context on the flat map', () => {
    // `unified` is the Map and is not tabbed in any phase.
    expect(findContext('unified')?.item.tabs).toBeUndefined();
    expect(CONTEXT_COMPONENTS.unified).toBeTruthy();
  });

  it('returns an element for every registered context', () => {
    for (const id of RESOLVED_CONTEXT_IDS) {
      expect(renderContext(id, PANEL_PROPS), `renderContext(${id}) returned null`).not.toBeNull();
    }
  });
});
