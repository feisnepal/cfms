import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { MoreLayersBand } from '../MoreLayersBand';
import { useWorkspaceStore } from '../../store/workspaceStore';

const mount = (ntfpInside = false) =>
  render(<MoreLayersBand calculationId="c1" ntfpInside={ntfpInside}><div data-testid="inside">inside</div></MoreLayersBand>);

describe('MoreLayersBand', () => {
  beforeEach(() => {
    localStorage.clear();
    useWorkspaceStore.setState({ activeAnalysisMap: null });
  });

  it('starts closed but keeps its children mounted', () => {
    mount();
    expect(screen.getByRole('button', { name: /More layers/ }).getAttribute('aria-expanded')).toBe('false');
    expect(screen.getByTestId('more-layers-body').hasAttribute('hidden')).toBe(true);
    expect(screen.getByTestId('inside')).toBeTruthy();
  });

  it('opens on click and remembers the choice', () => {
    const first = mount();
    fireEvent.click(screen.getByRole('button', { name: /More layers/ }));
    expect(screen.getByTestId('more-layers-body').hasAttribute('hidden')).toBe(false);
    first.unmount();
    mount();
    expect(screen.getByRole('button', { name: /More layers/ }).getAttribute('aria-expanded')).toBe('true');
  });

  it('opens by itself when a reference layer was left on', () => {
    localStorage.setItem('cf_reference_layers_c1', JSON.stringify({ visible: ['river'], bufferM: 1000 }));
    mount();
    expect(screen.getByTestId('more-layers-body').hasAttribute('hidden')).toBe(false);
  });

  it('opens by itself when an analysis map is switched on elsewhere', () => {
    mount();
    act(() => { useWorkspaceStore.setState({ activeAnalysisMap: 'fi_growing_stock' as never }); });
    expect(screen.getByTestId('more-layers-body').hasAttribute('hidden')).toBe(false);
  });
});
