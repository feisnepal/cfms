import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const get = vi.fn();
const post = vi.fn();
const put = vi.fn();
vi.mock('../../services/api', async (orig) => ({
  ...(await orig<typeof import('../../services/api')>()),
  default: { get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...a), put: (...a: unknown[]) => put(...a) },
}));

import { ForestSummaryPanel } from '../ForestSummaryPanel';
import { ForestSummaryButton } from '../ForestSummaryButton';
import { useWorkspaceStore } from '../../store/workspaceStore';
import type { DecisionsResponse, ForestSummary } from '../../lib/forestSummary';

const tile = (key: string, value: number | null, unit: string, extra: Record<string, unknown> = {}) => ({
  key, value, unit, state: value == null ? 'not_computed' : 'ready', source_map: null, source_step: value == null ? 5 : null, ...extra,
});

const SUMMARY: ForestSummary = {
  state: 'ready', area: 'forest', verdict: '60% of the area is in good condition, 0% moderate and 40% weak. Weak units: B2.',
  tiles: [
    tile('area', 100, 'ha', { unit_count: 2 }),
    tile('growing_stock', 168.4, 'm3/ha', { source_map: 'fi_growing_stock' }),
    tile('carbon', null, 'tC/ha', { source_map: 'fi_carbon' }),
    tile('landslide_high', 25, '%', { source_map: 'hazard_prone', source_step: 11, relative: true }),
  ] as never,
  themes: [
    { key: 'stock', headline: 'growing_stock', rows: [tile('growing_stock', 168.4, 'm3/ha', { source_map: 'fi_growing_stock' })] as never },
    { key: 'hazard', headline: 'landslide_high', rows: [tile('landslide_high', 25, '%', { source_map: 'hazard_prone' }), tile('soil_loss', 8.2, 't/ha/yr')] as never },
  ],
  basis: { collected_at: '2026-10-09T07:00:00Z', hazard_method: 'quantile' },
};

const DECISIONS: DecisionsResponse = {
  locked: false, locked_reason: null, open_count: 2,
  items: [
    { key: 'landslide_method', scope: null, who: 'committee_dfo', step: 11, choices: ['relative', 'needs_calibration'], state: 'open', choice: null, note: null, decided_at: null, decided_by: null },
    {
      key: 'orientation', scope: 'b7', who: 'committee', step: 12, choices: ['accept_suggested', 'custom'], state: 'open', choice: null, note: null,
      decided_at: null, decided_by: null, block_name: 'B7', current: 'Production', suggested: 'Protection',
    },
    {
      key: 'household_placement', scope: null, who: 'facilitator', step: 11, choices: ['building_footprints'], state: 'answered',
      choice: 'building_footprints', note: null, decided_at: '2026-10-08T05:00:00Z', decided_by: { id: 'u2', name: 'Ram Thapa', kind: 'dfo' },
    },
  ],
};

const routes = (over: Partial<Record<string, unknown>> = {}) =>
  get.mockImplementation(async (url: string) => {
    if (url.includes('workspace/layout')) return { data: { layout_json: over.layout ?? null } };
    if (url.endsWith('/forest-summary')) {
      if (over.summaryError) throw over.summaryError;
      return { data: over.summary ?? SUMMARY };
    }
    if (url.endsWith('/decisions')) {
      if (over.decisionsError) throw over.decisionsError;
      return { data: over.decisions ?? DECISIONS };
    }
    throw new Error(`unexpected GET ${url}`);
  });

const mount = () => render(<MemoryRouter><ForestSummaryPanel calculationId="c1" /></MemoryRouter>);

describe('ForestSummaryPanel', () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    put.mockReset().mockResolvedValue({ data: DECISIONS });
    useWorkspaceStore.setState({ forestSummaryOpen: true, analysisArea: 'forest', activeAnalysisMap: null, geometryVersion: 0 });
  });

  it('shows the verdict, the tiles and the themes from the server', async () => {
    routes();
    mount();
    expect(await screen.findByTestId('forest-summary-verdict')).toBeTruthy();
    expect(screen.getByTestId('forest-summary-verdict').textContent).toContain('Weak units: B2');
    expect(within(screen.getByTestId('tile-growing_stock')).getByText('168')).toBeTruthy();
    expect(screen.getByTestId('tile-growing_stock').textContent).toContain('m³/ha');
    expect(screen.getByTestId('tile-area').textContent).toContain('100');
    expect(screen.getByTestId('tile-carbon').textContent).toMatch(/not computed \(step 5\)/i);
    expect(screen.getByTestId('theme-stock')).toBeTruthy();
    expect(screen.getByTestId('forest-summary-basis').textContent).toContain('2026-10-09');
    expect(screen.getByTestId('forest-summary-basis').textContent).toMatch(/relative/i);
  });

  it('asks for the summary in the chosen area and re-asks when it changes', async () => {
    routes();
    mount();
    await screen.findByTestId('forest-summary');
    expect(get).toHaveBeenCalledWith('/api/calculations/c1/forest-summary', { params: { area: 'forest', lang: 'en' } });
    fireEvent.click(screen.getByRole('button', { name: 'User group' }));
    expect(useWorkspaceStore.getState().analysisArea).toBe('user_group');
    await waitFor(() => expect(get).toHaveBeenCalledWith('/api/calculations/c1/forest-summary', { params: { area: 'user_group', lang: 'en' } }));
  });

  it('prepares the summary once when the server has none, then shows it', async () => {
    routes({ summary: { state: 'not_collected', area: 'forest', tiles: [], themes: [], verdict: null, basis: null } });
    post.mockResolvedValue({ data: SUMMARY });
    mount();
    expect(await screen.findByTestId('forest-summary')).toBeTruthy();
    expect(post).toHaveBeenCalledTimes(1);
    expect(post).toHaveBeenCalledWith('/api/calculations/c1/forest-summary/refresh', null, { params: { area: 'forest', lang: 'en' } });
  });

  it('does not loop when the server still has nothing after preparing', async () => {
    const empty = { state: 'not_collected', area: 'forest', tiles: [], themes: [], verdict: null, basis: null };
    routes({ summary: empty });
    post.mockResolvedValue({ data: empty });
    mount();
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    await new Promise((r) => setTimeout(r, 50));
    expect(post).toHaveBeenCalledTimes(1);
  });

  it('says so when the forest may not be opened', async () => {
    routes({ summaryError: { response: { status: 403 } } });
    mount();
    expect((await screen.findByRole('alert')).textContent).toMatch(/cannot open this forest/i);
  });

  it('a tile opens its Analysis map; a tile with no map does nothing', async () => {
    routes();
    mount();
    await screen.findByTestId('forest-summary');
    expect((screen.getByTestId('tile-area') as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByTestId('tile-growing_stock'));
    expect(useWorkspaceStore.getState().activeAnalysisMap).toBe('fi_growing_stock');
    fireEvent.click(screen.getByTestId('tile-landslide_high'));
    expect(useWorkspaceStore.getState().activeAnalysisMap).toBe('hazard_prone');
  });

  it('themes expand and collapse; the hazard theme starts open', async () => {
    routes();
    mount();
    await screen.findByTestId('forest-summary');
    const hazard = screen.getByTestId('theme-hazard');
    expect(within(hazard).getByText('Mean soil loss')).toBeTruthy();
    fireEvent.click(within(hazard).getByRole('button', { name: /Hazard/ }));
    expect(within(hazard).queryByText('Mean soil loss')).toBeNull();
    const stock = screen.getByTestId('theme-stock');
    fireEvent.click(within(stock).getByRole('button', { name: /Stock/ }));
    fireEvent.click(within(stock).getByRole('button', { name: 'Show on map' }));
    expect(useWorkspaceStore.getState().activeAnalysisMap).toBe('fi_growing_stock');
  });

  it('closing hides the panel and saves that; the layer-panel button brings it back', async () => {
    routes();
    render(<MemoryRouter><ForestSummaryPanel calculationId="c1" /><ForestSummaryButton /></MemoryRouter>);
    await screen.findByTestId('forest-summary');
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(screen.queryByTestId('forest-summary-panel')).toBeNull();
    expect(useWorkspaceStore.getState().forestSummaryOpen).toBe(false);
    fireEvent.click(screen.getByTestId('open-forest-summary'));
    expect(await screen.findByTestId('forest-summary-panel')).toBeTruthy();
  });

  it('stays closed when the saved layout says it was closed', async () => {
    routes({ layout: { position: { x: 5, y: 5 }, collapsed: false, open: false } });
    mount();
    await waitFor(() => expect(useWorkspaceStore.getState().forestSummaryOpen).toBe(false));
    expect(screen.queryByTestId('forest-summary-panel')).toBeNull();
  });

  describe('Decisions needed', () => {
    const openTab = async () => {
      mount();
      await screen.findByTestId('forest-summary');
      fireEvent.click(screen.getByRole('tab', { name: /Decisions needed/ }));
    };

    it('shows the open count on the tab and every card with who decided', async () => {
      routes();
      await openTab();
      expect(screen.getByTestId('decisions-badge').textContent).toBe('2');
      expect(screen.getByText('Landslide classes: relative or calibrated?')).toBeTruthy();
      expect(screen.getByText('Management orientation of B7')).toBeTruthy();
      expect(screen.getByTestId('decision-household_placement:').textContent).toContain('Decided by Ram Thapa (DFO) · 2026-10-08');
      expect(screen.getByTestId('decision-landslide_method:').textContent).toContain('Open');
      expect(screen.getByTestId('decisions-footer').textContent).toMatch(/2 decisions still open/);
    });

    it('answering sends the choice and shows the server\'s new state', async () => {
      routes();
      put.mockResolvedValue({ data: { ...DECISIONS, open_count: 1, items: DECISIONS.items.map((i) => (i.key === 'landslide_method' ? { ...i, state: 'answered', choice: 'relative', decided_at: '2026-10-09T08:00:00Z', decided_by: { id: 'u1', name: 'Sita Rai', kind: 'owner' } } : i)) } });
      await openTab();
      fireEvent.click(screen.getByRole('button', { name: 'Stay relative' }));
      await waitFor(() => expect(put).toHaveBeenCalledWith('/api/calculations/c1/decisions/landslide_method', { choice: 'relative', scope: null }));
      await waitFor(() => expect(screen.getByTestId('decision-landslide_method:').textContent).toContain('Decided by Sita Rai (owner) · 2026-10-09'));
      expect(screen.getByTestId('decisions-badge').textContent).toBe('1');
    });

    it('accepting the suggested orientation names the block; choosing another asks for the value first', async () => {
      routes();
      await openTab();
      fireEvent.click(screen.getByRole('button', { name: 'Accept Protection' }));
      await waitFor(() => expect(put).toHaveBeenCalledWith('/api/calculations/c1/decisions/orientation', { choice: 'accept_suggested', scope: 'b7' }));
      put.mockClear();
      fireEvent.click(screen.getByRole('button', { name: 'Choose another' }));
      expect(put).not.toHaveBeenCalled();
      fireEvent.change(screen.getByRole('combobox'), { target: { value: 'Conservation' } });
      fireEvent.click(screen.getByRole('button', { name: 'Save' }));
      await waitFor(() => expect(put).toHaveBeenCalledWith('/api/calculations/c1/decisions/orientation', { choice: 'custom', scope: 'b7', value: 'Conservation' }));
    });

    it('a locked map shows why and disables every choice', async () => {
      routes({ decisions: { ...DECISIONS, locked: true, locked_reason: 'locked' } });
      await openTab();
      expect(screen.getByText(/DFO has approved this map/)).toBeTruthy();
      for (const b of screen.getAllByRole('button', { name: /Stay relative|Ask for calibration|Accept Protection|Choose another|Building footprints/ })) {
        expect((b as HTMLButtonElement).disabled).toBe(true);
      }
    });

    it('a map being calculated says so', async () => {
      routes({ decisions: { ...DECISIONS, locked: true, locked_reason: 'calculating' } });
      await openTab();
      expect(screen.getByText(/analysis is running/i)).toBeTruthy();
    });

    it('a refused save (423) is explained and the list is re-read', async () => {
      routes();
      put.mockRejectedValue({ response: { status: 423 } });
      await openTab();
      const before = get.mock.calls.filter((c) => String(c[0]).endsWith('/decisions')).length;
      fireEvent.click(screen.getByRole('button', { name: 'Stay relative' }));
      expect((await screen.findByRole('alert')).textContent).toMatch(/read-only/);
      await waitFor(() => expect(get.mock.calls.filter((c) => String(c[0]).endsWith('/decisions')).length).toBeGreaterThan(before));
    });

    it('says so when the forest may not be opened', async () => {
      routes({ decisionsError: { response: { status: 403 } } });
      await openTab();
      expect((await screen.findByRole('alert')).textContent).toMatch(/cannot open this forest/i);
    });
  });
});
