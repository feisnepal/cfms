import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

vi.mock('../../../services/api', () => ({
  yearlyPlanApi: { getStatus: vi.fn(), setDone: vi.fn() },
}));
vi.mock('../../../i18n/hooks', () => ({ useT: () => (k: string) => k }));

import { YearlyDoneBar } from '../YearlyDoneBar';
import { yearlyPlanApi } from '../../../services/api';

const getStatus = yearlyPlanApi.getStatus as unknown as ReturnType<typeof vi.fn>;
const setDone = yearlyPlanApi.setDone as unknown as ReturnType<typeof vi.fn>;
const open = { done: false, done_at: null, done_by: null, reopened_reason: null };
const done = { done: true, done_at: '2026-10-15T00:00:00Z', done_by: 'u1', reopened_reason: null };

beforeEach(() => {
  getStatus.mockReset();
  setDone.mockReset();
});

describe('YearlyDoneBar', () => {
  it('asks the question until the owner says done, then shows a switch', async () => {
    getStatus.mockResolvedValue(open);
    setDone.mockResolvedValue(done);
    render(<YearlyDoneBar calculationId="c1" />);
    expect(await screen.findByText('yearlyStep.question')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('yearly-mark-done'));
    await waitFor(() => expect(setDone).toHaveBeenCalledWith('c1', true));
    expect(await screen.findByTestId('yearly-done-switch')).toBeInTheDocument();
    expect(screen.queryByText('yearlyStep.question')).not.toBeInTheDocument();
  });

  it('turning the switch off opens it again', async () => {
    getStatus.mockResolvedValue(done);
    setDone.mockResolvedValue(open);
    render(<YearlyDoneBar calculationId="c1" />);
    fireEvent.click(await screen.findByTestId('yearly-done-switch'));
    await waitFor(() => expect(setDone).toHaveBeenCalledWith('c1', false));
    expect(await screen.findByText('yearlyStep.question')).toBeInTheDocument();
  });

  it('says why it reopened when the system did it', async () => {
    getStatus.mockResolvedValue({ ...open, reopened_reason: 'plan_changed' });
    render(<YearlyDoneBar calculationId="c1" />);
    expect(await screen.findByText('yearlyStep.reopened')).toBeInTheDocument();
  });

  it('Add more is only a shortcut to the grid', async () => {
    getStatus.mockResolvedValue(open);
    const onAddMore = vi.fn();
    render(<YearlyDoneBar calculationId="c1" onAddMore={onAddMore} />);
    fireEvent.click(await screen.findByTestId('yearly-add-more'));
    expect(onAddMore).toHaveBeenCalled();
    expect(setDone).not.toHaveBeenCalled();
  });

  it('on other pages it says nothing once the owner has said done, but still asks while it is open', async () => {
    getStatus.mockResolvedValue(done);
    const { unmount } = render(<YearlyDoneBar calculationId="c1" quietWhenDone />);
    await waitFor(() => expect(getStatus).toHaveBeenCalled());
    expect(screen.queryByTestId('yearly-done-bar')).not.toBeInTheDocument();
    unmount();
    getStatus.mockResolvedValue(open);
    render(<YearlyDoneBar calculationId="c1" quietWhenDone />);
    expect(await screen.findByText('yearlyStep.question')).toBeInTheDocument();
  });
});
