import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const get = vi.fn();
vi.mock('../../services/api', async (orig) => ({
  ...(await orig<typeof import('../../services/api')>()),
  default: { get: (...a: unknown[]) => get(...a), post: vi.fn(), put: vi.fn() },
}));
const downloadFromApi = vi.fn();
vi.mock('../../utils/download', () => ({ downloadFromApi: (...a: unknown[]) => downloadFromApi(...a) }));

import { ForestSummaryPanel } from '../ForestSummaryPanel';
import { useWorkspaceStore } from '../../store/workspaceStore';

const SUMMARY = {
  state: 'ready', area: 'forest', verdict: 'A verdict.', basis: { collected_at: '2026-10-09T07:00:00Z' },
  tiles: [{ key: 'area', value: 100, unit: 'ha', state: 'ready', source_map: null, source_step: null, unit_count: 2 }],
  themes: [],
};

const routes = (summary: unknown = SUMMARY) =>
  get.mockImplementation(async (url: string) => {
    if (url.includes('workspace/layout')) return { data: { layout_json: null } };
    if (url.endsWith('/forest-summary')) return { data: summary };
    if (url.endsWith('/forest-summary/export')) return { data: '﻿FOREST SUMMARY - X\n' };
    if (url.endsWith('/decisions')) return { data: { locked: false, locked_reason: null, open_count: 0, items: [] } };
    throw new Error(`unexpected GET ${url}`);
  });

const mount = () => render(<MemoryRouter><ForestSummaryPanel calculationId="c1" /></MemoryRouter>);

describe('Forest summary export (plain text)', () => {
  const writeText = vi.fn();
  beforeEach(() => {
    get.mockReset();
    downloadFromApi.mockReset().mockResolvedValue(undefined);
    writeText.mockReset().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    useWorkspaceStore.setState({ forestSummaryOpen: true, analysisArea: 'forest', geometryVersion: 0 });
  });

  it('offers the export only once the summary is ready', async () => {
    routes({ state: 'not_collected', area: 'forest', tiles: [], themes: [], verdict: null, basis: null });
    mount();
    await waitFor(() => expect(get).toHaveBeenCalled());
    expect(screen.queryByRole('button', { name: 'Copy text' })).toBeNull();
  });

  it('copies the server text without its byte-order mark', async () => {
    routes();
    mount();
    fireEvent.click(await screen.findByRole('button', { name: 'Copy text' }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('FOREST SUMMARY - X\n'));
    expect(get).toHaveBeenCalledWith('/api/calculations/c1/forest-summary/export', { params: { area: 'forest', lang: 'en' }, responseType: 'text' });
    expect((await screen.findByTestId('export-note')).textContent).toBe('Copied.');
  });

  it('says so when the clipboard refuses, and points to Download', async () => {
    routes();
    writeText.mockRejectedValue(new Error('denied'));
    mount();
    fireEvent.click(await screen.findByRole('button', { name: 'Copy text' }));
    expect((await screen.findByTestId('export-note')).textContent).toMatch(/Use Download instead/);
  });

  it('downloads the file for the chosen area and language', async () => {
    routes();
    mount();
    fireEvent.click(await screen.findByRole('button', { name: 'User group' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Download .txt' }));
    await waitFor(() => expect(downloadFromApi).toHaveBeenCalledWith(
      '/api/calculations/c1/forest-summary/export', 'ForestSummary_Report.txt', { area: 'user_group', lang: 'en' },
    ));
  });

  it('reports a failed download', async () => {
    routes();
    downloadFromApi.mockRejectedValue(new Error('500'));
    mount();
    fireEvent.click(await screen.findByRole('button', { name: 'Download .txt' }));
    expect((await screen.findByTestId('export-note')).textContent).toMatch(/Could not download/);
  });
});
