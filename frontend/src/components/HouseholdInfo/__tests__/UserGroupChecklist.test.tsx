/** The user group step reminds the user what it still needs (owner, 2026-10-11): household data and the committee. */
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

vi.mock('../../../i18n/hooks', () => ({ useT: () => (k: string) => k }));

import { UserGroupChecklist, type UserGroupChecklistProps } from '../UserGroupChecklist';

const base = (over: Partial<UserGroupChecklistProps> = {}): UserGroupChecklistProps => ({
  hasHouseholds: false, mainCommitteeCount: 0, otherCommitteeCount: 0, committeesLoaded: true,
  onGoHouseholds: () => undefined, onGoCommittee: () => undefined, ...over,
});

describe('UserGroupChecklist', () => {
  it('stays quiet until the committees have loaded, so it never flashes a wrong reminder', () => {
    const { container } = render(<UserGroupChecklist {...base({ committeesLoaded: false })} />);
    expect(container.firstChild).toBeNull();
  });

  it('asks for the household data and the committee when both are missing, and takes the user to each', async () => {
    const goH = vi.fn();
    const goC = vi.fn();
    render(<UserGroupChecklist {...base({ onGoHouseholds: goH, onGoCommittee: goC })} />);
    expect(screen.getByTestId('checklist-households')).toBeTruthy();
    expect(screen.getByTestId('checklist-committee')).toBeTruthy();
    await userEvent.click(screen.getByTestId('checklist-households').querySelector('button')!);
    await userEvent.click(screen.getByTestId('checklist-committee').querySelector('button')!);
    expect(goH).toHaveBeenCalledTimes(1);
    expect(goC).toHaveBeenCalledTimes(1);
  });

  it('asks only for what is missing', () => {
    render(<UserGroupChecklist {...base({ hasHouseholds: true })} />);
    expect(screen.queryByTestId('checklist-households')).toBeNull();
    expect(screen.getByTestId('checklist-committee')).toBeTruthy();
  });

  it('once the committee is in, the advisory and financial committees are only a gentle prompt', () => {
    render(<UserGroupChecklist {...base({ hasHouseholds: true, mainCommitteeCount: 7 })} />);
    expect(screen.getByTestId('checklist-other')).toBeTruthy();
    expect(screen.queryByTestId('checklist-committee')).toBeNull();
  });

  it('shrinks to one line when everything is entered', () => {
    render(<UserGroupChecklist {...base({ hasHouseholds: true, mainCommitteeCount: 7, otherCommitteeCount: 3 })} />);
    expect(screen.getByTestId('user-group-checklist-done')).toBeTruthy();
    expect(screen.queryByTestId('user-group-checklist')).toBeNull();
  });
});
