import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom';
import { TemplateStoreBanner } from '../TemplateStoreBanner';
import * as api from '../../../services/api';

vi.mock('../../../i18n/hooks', () => ({ useT: () => (k: string) => k }));
vi.mock('../../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../../services/api')>();
  return { ...actual, operationalPlanApi: { ...actual.operationalPlanApi, getByCalculation: vi.fn() } };
});

const getPlan = (api.operationalPlanApi as unknown as { getByCalculation: ReturnType<typeof vi.fn> }).getByCalculation;
const Where = () => <div data-testid="where">{useLocation().pathname + useLocation().search}</div>;

const mount = (props: { ready: boolean; loading?: boolean }) =>
  render(
    <MemoryRouter initialEntries={['/calculations/c1']}>
      <Routes>
        <Route path="/calculations/:id" element={<TemplateStoreBanner calculationId="c1" {...props} />} />
        <Route path="/templates" element={<Where />} />
      </Routes>
    </MemoryRouter>,
  );

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  getPlan.mockRejectedValue({ response: { status: 404 } });
});

describe('TemplateStoreBanner', () => {
  it('is silent while a required step is still open', async () => {
    mount({ ready: false });
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByTestId('template-store-banner')).toBeNull();
    expect(getPlan).not.toHaveBeenCalled();
  });

  it('appears when every required step is done and there is no plan, and its button opens the store for this forest', async () => {
    mount({ ready: true });
    await screen.findByTestId('template-store-banner');
    fireEvent.click(screen.getByTestId('template-store-banner-go'));
    await waitFor(() => expect(screen.getByTestId('where').textContent).toBe('/templates?calculation_id=c1'));
  });

  it('stays away once a plan exists (the user has already chosen)', async () => {
    getPlan.mockResolvedValue({ id: 'p1' });
    mount({ ready: true });
    await waitFor(() => expect(getPlan).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByTestId('template-store-banner')).toBeNull();
  });

  it('is remembered as closed for this forest', async () => {
    const first = mount({ ready: true });
    await screen.findByTestId('template-store-banner');
    fireEvent.click(screen.getByLabelText('workflow.store.dismiss'));
    expect(screen.queryByTestId('template-store-banner')).toBeNull();
    first.unmount();
    mount({ ready: true });
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByTestId('template-store-banner')).toBeNull();
  });
});
