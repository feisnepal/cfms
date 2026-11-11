/** The automatic user group analysis as a status on the layer: nothing to press, nothing silent. */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('../../i18n/hooks', () => ({ useT: () => (k: string) => k }));

import { UserGroupAnalysisChip } from '../UserGroupAnalysisChip';
import { useWorkspaceStore } from '../../store/workspaceStore';

const set = (v: any) => useWorkspaceStore.setState({ userGroupAnalysis: v } as never);

beforeEach(() => set(null));

describe('UserGroupAnalysisChip', () => {
  it('shows nothing before any status is known or when nothing ever ran', () => {
    const { container, rerender } = render(<UserGroupAnalysisChip />);
    expect(container.firstChild).toBeNull();
    set({ state: 'idle' });
    rerender(<UserGroupAnalysisChip />);
    expect(container.firstChild).toBeNull();
  });

  it.each(['running', 'done', 'failed', 'skipped'] as const)('says what is happening: %s', (state) => {
    set({ state });
    render(<UserGroupAnalysisChip />);
    const chip = screen.getByTestId('user-group-analysis-chip');
    expect(chip.getAttribute('data-state')).toBe(state);
    expect(chip.textContent).toContain(`workspace.userGroup.status.${state}`);
    expect(chip.getAttribute('role')).toBe('status'); // announced to a screen reader when it changes
  });

  it('puts the reason in the tooltip (why it failed or was skipped)', () => {
    set({ state: 'skipped', message: 'User group area 6,200 ha exceeds the 5,000 ha analysis limit.' });
    render(<UserGroupAnalysisChip />);
    expect(screen.getByTestId('user-group-analysis-chip').getAttribute('title')).toContain('6,200 ha');
  });
});
