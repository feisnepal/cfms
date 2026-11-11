import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import i18n from '../../i18n';

const get = vi.fn();
vi.mock('../../services/api', async (orig) => ({
  ...(await orig<typeof import('../../services/api')>()),
  default: { get: (...a: unknown[]) => get(...a), post: vi.fn(), put: vi.fn() },
}));

import { ForestSummaryPanel } from '../ForestSummaryPanel';
import OpenDecisionsNotice from '../calculation/OpenDecisionsNotice';
import { formatValue, localDigits } from '../../lib/forestSummary';
import { useWorkspaceStore } from '../../store/workspaceStore';

const tile = (key: string, value: number | null, unit: string, extra: Record<string, unknown> = {}) => ({
  key, value, unit, state: value == null ? 'not_computed' : 'ready', source_map: null, source_step: value == null ? 5 : null, ...extra,
});
const SUMMARY = {
  state: 'ready', area: 'forest', verdict: 'verdict', basis: { collected_at: '2026-10-09T07:00:00Z', hazard_method: 'quantile' },
  tiles: [tile('area', 412.4, 'ha', { unit_count: 8 }), tile('growing_stock', 168.4, 'm3/ha'), tile('carbon', null, 'tC/ha'),
    tile('landslide_high', 25, '%', { relative: true })],
  themes: [{ key: 'hazard', headline: 'landslide_high', rows: [tile('landslide_high', 25, '%'), tile('priority_households', 14, 'households', { of: 214 })] }],
};
const DECISIONS = {
  locked: false, locked_reason: null, open_count: 2,
  items: [{
    key: 'household_placement', scope: null, who: 'facilitator', step: 11, choices: ['building_footprints'], state: 'answered',
    choice: 'building_footprints', note: null, decided_at: '2026-10-08T05:00:00Z', decided_by: { id: 'u2', name: 'Ram Thapa', kind: 'dfo' },
  }],
};

const routes = () =>
  get.mockImplementation(async (url: string) => {
    if (url.includes('workspace/layout')) return { data: { layout_json: null } };
    if (url.endsWith('/forest-summary')) return { data: SUMMARY };
    if (url.endsWith('/decisions')) return { data: DECISIONS };
    throw new Error(`unexpected GET ${url}`);
  });

describe('Forest summary numerals follow the language', () => {
  const previous = i18n.language;
  beforeEach(() => {
    get.mockReset();
    routes();
    useWorkspaceStore.setState({ forestSummaryOpen: true, analysisArea: 'forest', geometryVersion: 0 });
  });
  afterEach(async () => {
    await i18n.changeLanguage(previous);
  });

  it('formatValue and localDigits write Devanagari in Nepali and Latin in English', () => {
    expect(formatValue(168.4, 'ne')).toBe('१६८');
    expect(formatValue(8.24, 'ne')).toBe('८.२');
    expect(formatValue(1234, 'ne')).toBe('१,२३४');
    expect(formatValue(168.4, 'en')).toBe('168');
    expect(localDigits('2026-10-09', 'ne')).toBe('२०२६-१०-०९');
    expect(localDigits(5, 'en')).toBe('5');
  });

  it('the panel shows tiles, step numbers, counts and the basis date in Devanagari digits in Nepali', async () => {
    await i18n.changeLanguage('ne');
    render(<MemoryRouter><ForestSummaryPanel calculationId="c1" /></MemoryRouter>);
    const area = await screen.findByTestId('tile-area');
    expect(area.textContent).toContain('४१२');
    expect(area.textContent).toContain('· ८');
    expect(screen.getByTestId('tile-growing_stock').textContent).toContain('१६८');
    expect(screen.getByTestId('tile-carbon').textContent).toMatch(/\(.*५\)/);
    expect(screen.getByTestId('tile-landslide_high').textContent).toContain('२५');
    // the unit words are Nepali too
    expect(area.textContent).toContain('हे.');
    expect(area.textContent).not.toMatch(/ha/);
    expect(screen.getByTestId('tile-growing_stock').textContent).toContain('घन मि./हे.');
    expect(screen.getByTestId('forest-summary-basis').textContent).toContain('२०२६-१०-०९');
    expect(screen.getByTestId('decisions-badge').textContent).toBe('२');
    const panel = screen.getByTestId('forest-summary-panel');
    expect(panel.textContent?.replace(/[^0-9]/g, '')).toBe(''); // no Latin digit anywhere in the panel
  });

  it('the panel keeps Latin digits in English', async () => {
    await i18n.changeLanguage('en');
    render(<MemoryRouter><ForestSummaryPanel calculationId="c1" /></MemoryRouter>);
    expect((await screen.findByTestId('tile-area')).textContent).toContain('412');
    expect(screen.getByTestId('tile-area').textContent).toContain('ha');
    expect(screen.getByTestId('tile-growing_stock').textContent).toContain('m³/ha');
    expect(screen.getByTestId('decisions-badge').textContent).toBe('2');
    expect(screen.getByTestId('forest-summary-panel').textContent).not.toMatch(/[०-९]/);
  });

  it('the Decisions tab writes the open count and the decision date in Devanagari in Nepali', async () => {
    await i18n.changeLanguage('ne');
    render(<MemoryRouter><ForestSummaryPanel calculationId="c1" /></MemoryRouter>);
    await screen.findByTestId('forest-summary');
    fireEvent.click(screen.getByRole('tab', { name: /निर्णय आवश्यक/ }));
    expect((await screen.findByTestId('decisions-footer')).textContent).toContain('२');
    expect(screen.getByTestId('decision-household_placement:').textContent).toContain('२०२६-१०-०८');
    expect(screen.getByTestId('decisions-tab').textContent?.replace(/[^0-9]/g, '')).toBe('');
  });

  it('the step 12 notice writes its count in Devanagari in Nepali and Latin in English', async () => {
    await i18n.changeLanguage('ne');
    const { unmount } = render(<MemoryRouter><OpenDecisionsNotice calculationId="c1" /></MemoryRouter>);
    expect((await screen.findByTestId('open-decisions-notice')).textContent).toContain('२');
    expect(screen.getByTestId('open-decisions-notice').textContent?.replace(/[^0-9]/g, '')).toBe('');
    unmount();
    await i18n.changeLanguage('en');
    render(<MemoryRouter><OpenDecisionsNotice calculationId="c1" /></MemoryRouter>);
    expect((await screen.findByTestId('open-decisions-notice')).textContent).toContain('2 plan decisions');
  });
});
