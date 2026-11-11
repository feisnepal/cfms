import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const list = vi.fn();
const preview = vi.fn();
const role = { current: 'user' };
vi.mock('../../services/api', async (orig) => ({
  ...(await orig<typeof import('../../services/api')>()),
  operationalPlanApi: { listMapVariables: (...a: unknown[]) => list(...a), mapVariablePreviewObjectUrl: (...a: unknown[]) => preview(...a) },
}));
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ user: { role: role.current } }) }));

import { PlaceholderIcon, canOpenMapVariablesPage } from '../PlaceholderIcon';
import { useWorkspaceStore } from '../../store/workspaceStore';

const mount = (id: Parameters<typeof PlaceholderIcon>[0]['id'] = 'sfm_type') =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <PlaceholderIcon id={id} calculationId="c1" />
    </QueryClientProvider>,
  );

describe('PlaceholderIcon — the map variable a workspace map stands for', () => {
  beforeEach(() => {
    URL.revokeObjectURL = vi.fn(); // jsdom has none; the thumbnail releases its object URL on close
    list.mockReset().mockResolvedValue({
      variables: [{
        key: 'thememap:sfm__forest_type', label_en: 'Forest-type Map', label_ne: 'वन किसिम',
        description_en: 'Each unit coloured by its forest type.', description_ne: 'क', section_en: 'Sustainable FM', section_ne: 'ख',
        palette_swatch: ['#111111', '#222222'],
      }],
    });
    preview.mockReset().mockResolvedValue('blob:thumb');
    role.current = 'user';
    useWorkspaceStore.setState({ layerRenderers: {} });
  });

  it('costs nothing while closed: no request is made until it is opened', () => {
    mount();
    expect(list).not.toHaveBeenCalled();
    expect(screen.getByTestId('placeholder-icon-sfm_type')).toBeTruthy();
  });

  it('opens a card with the token, the page description and the DEFAULT thumbnail (never the forest recoloured one)', async () => {
    mount();
    fireEvent.click(screen.getByTestId('placeholder-icon-sfm_type'));
    await waitFor(() => expect(screen.getByTestId('placeholder-token').textContent).toBe('thememap:sfm__forest_type'));
    await waitFor(() => expect(screen.getByText('Each unit coloured by its forest type.')).toBeTruthy());
    expect(preview).toHaveBeenCalledWith('thememap:sfm__forest_type'); // no calc id: the page's default look
  });

  it('the link to the Map-variables page is for designers and super-admins only', async () => {
    mount();
    fireEvent.click(screen.getByTestId('placeholder-icon-sfm_type'));
    await waitFor(() => screen.getByTestId('placeholder-token'));
    expect(screen.queryByTestId('placeholder-open-page')).toBeNull();
    expect(canOpenMapVariablesPage('user')).toBe(false);
    expect(canOpenMapVariablesPage('super_admin') && canOpenMapVariablesPage('template_designer')).toBe(true);
  });

  it('a designer gets the link, opening the page on this very card', async () => {
    role.current = 'template_designer';
    mount();
    fireEvent.click(screen.getByTestId('placeholder-icon-sfm_type'));
    const link = (await screen.findByTestId('placeholder-open-page')) as HTMLAnchorElement;
    expect(link.getAttribute('href')).toBe('/templates/map-variables?calc_id=c1&q=thememap%3Asfm__forest_type');
  });

  it('marks the icon when the colours differ from the default, and "Reset to placeholder look" removes them', async () => {
    useWorkspaceStore.setState({ layerRenderers: { 'analysis:sfm_type': { mode: 'categorized', field: 'sfm_type', classes: [] } as never } });
    mount();
    expect(screen.getByTestId('placeholder-icon-sfm_type').className).toContain('placeholder-icon-custom');
    fireEvent.click(screen.getByTestId('placeholder-icon-sfm_type'));
    fireEvent.click(await screen.findByTestId('placeholder-reset'));
    expect(useWorkspaceStore.getState().layerRenderers['analysis:sfm_type']).toBeUndefined();
  });

  it('a map with no placeholder renders nothing', () => {
    const { container } = mount('hazard_unknown' as never);
    expect(container.querySelector('.placeholder-icon')).toBeNull();
  });
});
