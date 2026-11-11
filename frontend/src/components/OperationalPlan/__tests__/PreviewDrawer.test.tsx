import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import { AuthContext } from '../../../contexts/AuthContext';
import PreviewDrawer from '../PreviewDrawer';

const previewOperationalPlan = vi.fn().mockResolvedValue('<html><body>ok</body></html>');

vi.mock('../../../services/api', () => ({
  operationalPlanApi: {
    previewOperationalPlan: (...a: unknown[]) => previewOperationalPlan(...a),
  },
}));

const withRole = (role: string | undefined, ui: React.ReactNode) => (
  <AuthContext.Provider value={{ user: role ? { role } : null } as never}>
    {ui}
  </AuthContext.Provider>
);

beforeEach(() => previewOperationalPlan.mockClear());

describe('PreviewDrawer render-mode toggle', () => {
  it('a plain user gets no Values/Tokens toggle and a values-only preview', async () => {
    render(withRole('user', <PreviewDrawer planId="p1" />));
    fireEvent.click(screen.getByRole('button', { name: /preview/i }));
    await waitFor(() => expect(previewOperationalPlan).toHaveBeenCalledWith('p1', 'values'));
    expect(screen.queryByText('Tokens')).toBeNull();
  });

  it('a designer can switch the preview to Tokens', async () => {
    render(withRole('template_designer', <PreviewDrawer planId="p1" />));
    fireEvent.click(screen.getByRole('button', { name: /preview/i }));
    await waitFor(() => expect(previewOperationalPlan).toHaveBeenCalledWith('p1', 'values'));
    fireEvent.click(screen.getByText('Tokens'));
    await waitFor(() => expect(previewOperationalPlan).toHaveBeenCalledWith('p1', 'tokens'));
  });
});
