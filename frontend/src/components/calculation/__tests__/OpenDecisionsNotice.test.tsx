import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

const get = vi.fn();
vi.mock('../../../services/api', async (orig) => ({
  ...(await orig<typeof import('../../../services/api')>()),
  default: { get: (...a: unknown[]) => get(...a) },
}));

import OpenDecisionsNotice from '../OpenDecisionsNotice';
import { useWorkspaceStore } from '../../../store/workspaceStore';

const Where = () => <div data-testid="where">{useLocation().pathname + useLocation().search}</div>;
const mount = () =>
  render(
    <MemoryRouter initialEntries={['/calculations/c1?surface=analysis/sustainablefm']}>
      <Routes>
        <Route path="*" element={<><OpenDecisionsNotice calculationId="c1" /><Where /></>} />
      </Routes>
    </MemoryRouter>,
  );

describe('OpenDecisionsNotice (step 13)', () => {
  beforeEach(() => {
    get.mockReset();
    useWorkspaceStore.setState({ forestSummaryOpen: false });
  });

  it('says how many decisions are open and does not block anything', async () => {
    get.mockResolvedValue({ data: { locked: false, locked_reason: null, open_count: 2, items: [] } });
    mount();
    expect((await screen.findByTestId('open-decisions-notice')).textContent).toMatch(/2 plan decisions are still open\. Step 13 is not blocked/);
  });

  it('uses the singular for one', async () => {
    get.mockResolvedValue({ data: { locked: false, locked_reason: null, open_count: 1, items: [] } });
    mount();
    expect((await screen.findByTestId('open-decisions-notice')).textContent).toMatch(/1 plan decision is still open/);
  });

  it('shows nothing when none are open, when the load fails, or when the forest may not be opened', async () => {
    get.mockResolvedValue({ data: { locked: false, locked_reason: null, open_count: 0, items: [] } });
    const { unmount } = mount();
    await waitFor(() => expect(get).toHaveBeenCalled());
    expect(screen.queryByTestId('open-decisions-notice')).toBeNull();
    unmount();
    get.mockRejectedValue({ response: { status: 403 } });
    mount();
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
    expect(screen.queryByTestId('open-decisions-notice')).toBeNull();
  });

  it('its button opens the Forest summary on the map', async () => {
    get.mockResolvedValue({ data: { locked: false, locked_reason: null, open_count: 3, items: [] } });
    mount();
    fireEvent.click(await screen.findByRole('button', { name: 'Open the Forest summary' }));
    expect(useWorkspaceStore.getState().forestSummaryOpen).toBe(true);
    expect(screen.getByTestId('where').textContent).toMatch(/^\/calculations\/c1\?surface=/);
    expect(screen.getByTestId('where').textContent).not.toContain('sustainablefm');
  });
});
