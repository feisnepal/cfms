import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

// antd Tabs pulls in a ResizeObserver — jsdom has none.
class RO { observe() {} unobserve() {} disconnect() {} }
(globalThis as unknown as { ResizeObserver: typeof RO }).ResizeObserver = RO;

vi.mock('../../i18n/hooks', () => ({ useT: () => (k: string) => k }));

// The tab pulls in a Leaflet map + many analysis panels — stub them all.
vi.mock('../UserGroup/UserGroupMapVisualization', () => ({ UserGroupMapVisualization: () => <div /> }));
vi.mock('../UserGroup/SettlementStatistics', () => ({ SettlementStatistics: () => <div /> }));
vi.mock('../UserGroup/LandCoverAnalysis', () => ({ LandCoverAnalysis: () => <div /> }));
vi.mock('../UserGroup/MapExportPanel', () => ({ MapExportPanel: () => <div /> }));
vi.mock('../HouseholdInfo/HouseholdInfoTab', () => ({ default: () => <div /> }));

const get = vi.fn();
const post = vi.fn();
const del = vi.fn();
vi.mock('../../services/api', () => ({
  default: { get: (...a: unknown[]) => get(...a), post: (...a: unknown[]) => post(...a), delete: (...a: unknown[]) => del(...a) },
}));

import { UserGroupMapTab } from '../UserGroupMapTab';

const results = {
  extent_id: 7,
  forest_boundary: {},
  extent_geometry: {},
  settlements: [],
  buildings: [],
};

const withExtent = () => {
  get.mockReset();
  get.mockImplementation((url: string) => {
    if (String(url).includes('/user-group/results')) return Promise.resolve({ data: results });
    if (String(url).includes('/user-group/poi')) return Promise.resolve({ data: { poi: [], education: [], health: [], rivers: [] } });
    return Promise.resolve({ data: { forest_name: 'CF' } });
  });
};

// A boundary drawn in the workspace but never analysed: results 404 until the analysis has run.
const withBoundaryNoAnalysis = () => {
  get.mockReset();
  get.mockImplementation((url: string) => {
    const u = String(url);
    if (u.includes('/user-group/results')) {
      return post.mock.calls.length > 0 ? Promise.resolve({ data: results }) : Promise.reject({ response: { status: 404 } });
    }
    if (u.includes('/user-group/extents')) return Promise.resolve({ data: { features: [{ id: 7 }], count: 1 } });
    if (u.includes('/user-group/poi')) return Promise.resolve({ data: { poi: [], education: [], health: [], rivers: [] } });
    return Promise.resolve({ data: { forest_name: 'CF' } });
  });
};

describe('UserGroupMapTab — results-only (USER_GROUP_BOUNDARY_PLAN.md P4)', () => {
  beforeEach(() => {
    get.mockReset();
    get.mockRejectedValue({ response: { status: 404 } }); // no existing extent
    post.mockReset().mockResolvedValue({});
    del.mockReset().mockResolvedValue({});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('shows the "author from the workspace" hint and no boundary-creation widgets', async () => {
    render(<UserGroupMapTab calculationId="c1" forestBoundary={null} forestName="CF" />);
    await screen.findByText('userGroup.tab.workspaceHint');
    // the old method selector is gone
    expect(screen.queryByText('userGroup.tab.uploadBoundary')).toBeNull();
    expect(document.querySelector('.method-selector')).toBeNull();
  });

  it('analyses by itself when a boundary exists but has no analysis, and notifies onChanged("analyzed")', async () => {
    withBoundaryNoAnalysis();
    const onChanged = vi.fn();
    render(<UserGroupMapTab calculationId="c1" forestName="CF" onChanged={onChanged} />);

    await waitFor(() => expect(onChanged).toHaveBeenCalledWith('analyzed'));
    expect(post).toHaveBeenCalledWith('/api/calculations/c1/user-group/analyze', null, { params: { extent_id: 7 } });
    // no button press, and the "draw a boundary" hint is not shown
    expect(screen.queryByText('userGroup.tab.workspaceHint')).toBeNull();
  });

  it('shows a failed analysis inline (no alert, no notification) and lets the user retry', async () => {
    withBoundaryNoAnalysis();
    post.mockRejectedValueOnce({ response: { data: { detail: 'boom' } } });
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
    const onChanged = vi.fn();
    render(<UserGroupMapTab calculationId="c1" forestName="CF" onChanged={onChanged} />);

    expect(await screen.findByRole('alert')).toHaveTextContent('boom');
    expect(alertSpy).not.toHaveBeenCalled();
    expect(onChanged).not.toHaveBeenCalled();
    // the manual button is still there to retry
    expect(screen.getByText('userGroup.tab.analyze')).toBeTruthy();
  });

  it('notifies onChanged("deleted") after a confirmed delete success', async () => {
    withExtent();
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
    const onChanged = vi.fn();
    render(<UserGroupMapTab calculationId="c1" forestName="CF" onChanged={onChanged} />);

    const delBtn = await screen.findByText('common.delete');
    fireEvent.click(delBtn);

    await waitFor(() => expect(onChanged).toHaveBeenCalledWith('deleted'));
    expect(del).toHaveBeenCalledWith('/api/calculations/c1/user-group');
    alertSpy.mockRestore();
  });

  it('does not notify when analysis is cancelled (no extent)', async () => {
    const onChanged = vi.fn();
    render(<UserGroupMapTab calculationId="c1" forestName="CF" onChanged={onChanged} />);

    await screen.findByText('userGroup.tab.workspaceHint');
    expect(screen.queryByText('userGroup.tab.analyze')).toBeNull();
    expect(onChanged).not.toHaveBeenCalled();
  });
});