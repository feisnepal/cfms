import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import NtfpCardReview from '../NtfpCardReview';
import * as api from '../../../services/api';

vi.mock('../../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../../services/api')>();
  return { ...actual, ntfpApi: { ...actual.ntfpApi, reviewQueue: vi.fn(), review: vi.fn() } };
});

const m = api.ntfpApi as unknown as { reviewQueue: ReturnType<typeof vi.fn>; review: ReturnType<typeof vi.fn> };

const card = (over: Record<string, unknown>) => ({
  species_key: 'a', nepali_name: 'क', scientific_name: 'Aa a', part_ne: 'जरा', part_groups: ['क'], growth_class: 'herb', growth_how: '', growth_guessed: false,
  sampling_method: 'destructive', plot_min_sqm: 4, plot_max_sqm: 25, n_individuals_min: 10, n_individuals_max: 20, maturity: null, conversion_factor: null,
  sample_fraction_pct: null, aah_pct_min: null, aah_pct_max: null, aah_source_key: null, ...over,
});

beforeEach(() => {
  m.reviewQueue.mockReset();
  m.review.mockReset();
  m.reviewQueue.mockResolvedValue({ cards: [card({ species_key: 'a', nepali_name: 'अ' }), card({ species_key: 'b', nepali_name: 'ब', growth_guessed: true })] });
  m.review.mockResolvedValue({ cards_confirmed: 1, values_written: 3, skipped: [], remaining: 1 });
});

describe('NtfpCardReview', () => {
  it('lists the waiting cards and marks a guessed growth form', async () => {
    render(<NtfpCardReview />);
    expect(await screen.findByText('अ')).toBeInTheDocument();
    expect(screen.getByText('ब')).toBeInTheDocument();
    expect(screen.getByText('2 cards waiting')).toBeInTheDocument();
    expect(screen.getAllByText('Guessed')).toHaveLength(1);
  });

  it('confirms an untouched card as it stands and takes it off the list', async () => {
    render(<NtfpCardReview />);
    await screen.findByText('अ');
    fireEvent.click(screen.getAllByRole('button', { name: 'Confirm as it stands' })[0]);
    await waitFor(() => expect(m.review).toHaveBeenCalledWith([{ species_key: 'a', confirmed: true }]));
    await waitFor(() => expect(screen.queryByText('अ')).not.toBeInTheDocument());
    expect(screen.getByText('1 cards reviewed.')).toBeInTheDocument();
  });

  it('sends only what was changed, as a correction', async () => {
    render(<NtfpCardReview />);
    await screen.findByText('अ');
    const box = screen.getByLabelText('Smallest plot a');
    fireEvent.change(box, { target: { value: '9' } });
    const save = await screen.findByRole('button', { name: 'Save correction' });
    fireEvent.click(save);
    await waitFor(() => expect(m.review).toHaveBeenCalledWith([{ species_key: 'a', confirmed: false, plot_min_sqm: 9 }]));
  });

  it('confirms together only the untouched cards whose growth form is not a guess', async () => {
    render(<NtfpCardReview />);
    await screen.findByText('अ');
    fireEvent.click(screen.getByRole('button', { name: 'Confirm the 1 untouched cards with a known growth form' }));
    const ok = await screen.findAllByRole('button', { name: 'Confirm as it stands' });
    fireEvent.click(ok[ok.length - 1]);                                   // the popover's button comes last
    await waitFor(() => expect(m.review).toHaveBeenCalledWith([{ species_key: 'a', confirmed: true }]));
  });

  it('shows a refusal plainly', async () => {
    m.reviewQueue.mockRejectedValue({ response: { status: 403, data: { detail: { code: 'super_admin_only', message: 'Only a super admin reviews the method cards.' } } } });
    render(<NtfpCardReview />);
    expect(await screen.findByText('Only a super admin reviews the method cards.')).toBeInTheDocument();
  });
});
