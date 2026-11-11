/** The user group data dialog opens on the screen the menu command asked for. */
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('../../i18n/hooks', () => ({ useT: () => (k: string) => k }));
vi.mock('../HouseholdInfo/HouseholdInfoTab', () => ({ default: (p: any) => <div data-testid="hh-tab" data-initial={p.initialTab} data-calc={p.calculationId} /> }));

import { UserGroupDataModal } from '../UserGroupDataModal';

describe('UserGroupDataModal', () => {
  it('opens the household screens for the household command and the committee screen for the committee commands', () => {
    const { rerender } = render(<UserGroupDataModal open calculationId="c1" section="households" onClose={() => {}} />);
    expect(screen.getByTestId('hh-tab').getAttribute('data-initial')).toBe('2');
    rerender(<UserGroupDataModal open calculationId="c1" section="committee" onClose={() => {}} />);
    expect(screen.getByTestId('hh-tab').getAttribute('data-initial')).toBe('5');
    expect(screen.getByTestId('hh-tab').getAttribute('data-calc')).toBe('c1');
  });

  it('renders nothing while closed', () => {
    render(<UserGroupDataModal open={false} calculationId="c1" section="households" onClose={() => {}} />);
    expect(screen.queryByTestId('hh-tab')).toBeNull();
  });
});
