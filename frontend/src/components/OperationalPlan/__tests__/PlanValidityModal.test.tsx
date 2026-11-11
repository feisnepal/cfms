import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import PlanValidityModal from '../PlanValidityModal';

const issue = (code: string, severity: 'error' | 'warning', extra = {}) => ({
  severity, code, message: `server says ${code}`, node_id: 'n1', title: 'Intro', token: '{{x}}', ...extra,
});

describe('PlanValidityModal', () => {
  it('says nothing is wrong when both lists are empty', () => {
    render(<PlanValidityModal open data={{ ok: true, errors: [], warnings: [] }} onClose={() => {}} onJump={() => {}} />);
    expect(screen.getByText(/Nothing to fix/i)).toBeInTheDocument();
  });

  it('shows errors and warnings, uses plain wording for known codes and the server text for others', () => {
    render(
      <PlanValidityModal
        open
        data={{ ok: false, errors: [issue('unknown_token', 'error')], warnings: [issue('some_new_code', 'warning')] }}
        onClose={() => {}}
        onJump={() => {}}
      />,
    );
    expect(screen.getByTestId('validity-unknown_token').textContent).toMatch(/not a variable the system knows/);
    expect(screen.getByTestId('validity-some_new_code').textContent).toMatch(/server says some_new_code/);
  });

  it('clicking an issue closes the dialog and jumps to its section', () => {
    const onJump = vi.fn();
    const onClose = vi.fn();
    render(<PlanValidityModal open data={{ ok: false, errors: [issue('broken_token', 'error')], warnings: [] }} onClose={onClose} onJump={onJump} />);
    fireEvent.click(screen.getByTestId('validity-broken_token'));
    expect(onClose).toHaveBeenCalled();
    expect(onJump).toHaveBeenCalledWith('n1');
  });

  it('folds many warnings of one kind into one row with a count, and keeps the few others in view', () => {
    const many = Array.from({ length: 12 }, (_, k) => issue('empty_section', 'warning', { node_id: `e${k}`, title: `Section ${k}` }));
    render(<PlanValidityModal open data={{ ok: true, errors: [], warnings: [...many, issue('some_new_code', 'warning')] }} onClose={() => {}} onJump={() => {}} />);
    expect(screen.getByTestId('validity-group-empty_section').textContent).toMatch(/12/);
    expect(screen.getByTestId('validity-some_new_code')).toBeInTheDocument();
  });
});
