import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import NtfpPlotEntry from '../NtfpPlotEntry';
import * as api from '../../../services/api';

vi.mock('../../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../../services/api')>();
  return { ...actual, ntfpApi: { ...actual.ntfpApi, savePlot: vi.fn(), plotExtras: vi.fn() } };
});
const m = api.ntfpApi as unknown as { savePlot: ReturnType<typeof vi.fn>; plotExtras: ReturnType<typeof vi.fn> };

const base = { open: true, calculationId: 'c1', plotNumber: 4, stratum: 'forest', speciesKeys: ['x', 'y'], names: { x: 'टिमुर', y: 'नीम' }, stored: [] as any[] };
const setup = (over: Record<string, unknown> = {}) => {
  const onSaved = vi.fn();
  const onClose = vi.fn();
  render(<NtfpPlotEntry {...base} {...over} onSaved={onSaved} onClose={onClose} />);
  return { onSaved, onClose };
};
const TITLE = 'Plot 4: what was found';

beforeEach(() => {
  m.savePlot.mockReset();
  m.plotExtras.mockReset();
  m.plotExtras.mockResolvedValue({ plot_number: 4, presence: null, photos: [] });
  m.savePlot.mockResolvedValue({ ok: true, findings: [], observations_written: 1, weights_written: 0, cleared: 0 });
});

describe('NtfpPlotEntry', () => {
  it('has one card per species of the plot, with the plot number in the title', async () => {
    setup();
    expect(await screen.findByText(TITLE)).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'टिमुर' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'नीम' })).toBeInTheDocument();
  });

  it('loads the position check and photos of the plot and offers both', async () => {
    setup();
    await screen.findByText(TITLE);
    await waitFor(() => expect(m.plotExtras).toHaveBeenCalledWith('c1', 4));
    expect(screen.getByRole('button', { name: /I am here/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Take a photo/ })).toBeInTheDocument();
  });

  it('saves the whole plot: the filled species with its count, the empty one as just its key', async () => {
    const { onSaved, onClose } = setup();
    await screen.findByText(TITLE);
    fireEvent.change(screen.getByLabelText('Total counted टिमुर'), { target: { value: '7' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save plot' }));
    await waitFor(() => expect(m.savePlot).toHaveBeenCalled());
    const [id, plot, entries] = m.savePlot.mock.calls[0];
    expect([id, plot]).toEqual(['c1', 4]);
    expect(entries[0]).toMatchObject({ species_key: 'x', count_total: 7 });
    expect(entries[0].visit_date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(entries[1]).toEqual({ species_key: 'y', weights: [] });
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(onClose).toHaveBeenCalled();
  });

  it('offers weights only once something was counted, and adds them', async () => {
    setup();
    await screen.findByText(TITLE);
    expect(screen.queryByRole('button', { name: /Add a weighed plant/ })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Total counted टिमुर'), { target: { value: '3' } });
    fireEvent.click(await screen.findByRole('button', { name: /Add a weighed plant/ }));
    fireEvent.change(await screen.findByLabelText('Fresh weight 1 टिमुर'), { target: { value: '800' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save plot' }));
    await waitFor(() => expect(m.savePlot.mock.calls[0][2][0].weights).toEqual([{ sample_no: 1, fresh_weight_g: 800, dry_weight_g: null }]));
  });

  it('stops an obvious mistake before the server and names the species', async () => {
    setup({ stored: [{ plot_number: 4, species_key: 'x', visit_date: null, count_total: 2, count_mature: 5, count_small: null, clumps: null, tillers: null, notes: null, source: 'manual', weights: [] }] });
    await screen.findByText(TITLE);
    fireEvent.click(screen.getByRole('button', { name: 'Save plot' }));
    expect(await screen.findByText(/टिमुर: mature plus small is more than the total/)).toBeInTheDocument();
    expect(m.savePlot).not.toHaveBeenCalled();
  });

  it('lists the findings of a refusal by species and stays open', async () => {
    m.savePlot.mockRejectedValue({ response: { data: { detail: { code: 'plot.invalid', findings: [{ severity: 'error', code: 'x', message: 'The fresh weight must be above 0.', species_key: 'y' }] } } } });
    const { onClose } = setup();
    await screen.findByText(TITLE);
    fireEvent.change(screen.getByLabelText('Total counted नीम'), { target: { value: '1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save plot' }));
    expect(await screen.findByText(/नीम: The fresh weight must be above 0\./)).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });

  it('says plainly that the other way of recording is in use', async () => {
    m.savePlot.mockRejectedValue({ response: { data: { detail: { code: 'mode_conflict', message: 'x' } } } });
    setup();
    await screen.findByText(TITLE);
    fireEvent.change(screen.getByLabelText('Total counted टिमुर'), { target: { value: '1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save plot' }));
    expect(await screen.findByText(/were uploaded from the form/)).toBeInTheDocument();
  });
});
