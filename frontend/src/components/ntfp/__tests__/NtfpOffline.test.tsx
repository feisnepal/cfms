import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import NtfpPlotEntry from '../NtfpPlotEntry';
import NtfpPlotHere from '../NtfpPlotHere';
import NtfpPlotPhotos from '../NtfpPlotPhotos';
import NtfpOutboxBar from '../NtfpOutboxBar';
import NtfpCollectPanel from '../NtfpCollectPanel';
import * as api from '../../../services/api';
import { _resetForTests, enqueue, listOutbox, type OutboxItem } from '../../../services/ntfpOutbox';

vi.mock('../NtfpPlotMap', async () => {
  const lib = await vi.importActual<typeof import('../../../lib/ntfp')>('../../../lib/ntfp');
  return {
    default: ({ plots, summaries, layer, pending }: any) => (
      <div data-testid="map-stub">
        {plots.map((p: any) => <span key={p.plot_number}>{`plot ${p.plot_number}: ${lib.layerLabel(layer, summaries?.[p.plot_number])}${pending?.has(p.plot_number) ? ' (waiting)' : ''}`}</span>)}
      </div>
    ),
  };
});
vi.mock('../../../utils/download', () => ({ downloadFromApi: vi.fn() }));
vi.mock('../../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../../services/api')>();
  return { ...actual, ntfpApi: { ...actual.ntfpApi, savePlot: vi.fn(), plotExtras: vi.fn(), checkPresence: vi.fn(), uploadPhoto: vi.fn(), photoBlob: vi.fn(), allExtras: vi.fn() } };
});
const m = api.ntfpApi as unknown as Record<'savePlot' | 'plotExtras' | 'checkPresence' | 'uploadPhoto' | 'photoBlob' | 'allExtras', ReturnType<typeof vi.fn>>;

const noSignal = () => ({ message: 'Network Error' });
const setOnline = (v: boolean) => Object.defineProperty(navigator, 'onLine', { configurable: true, value: v });

beforeEach(() => {
  _resetForTests();
  ['savePlot', 'plotExtras', 'checkPresence', 'uploadPhoto', 'photoBlob', 'allExtras'].forEach((k) => m[k as keyof typeof m].mockReset());
  m.plotExtras.mockResolvedValue({ plot_number: 4, presence: null, photos: [] });
  m.allExtras.mockResolvedValue({ plots: {} });
  setOnline(true);
  (globalThis.URL as any).createObjectURL = vi.fn(() => 'blob:x');
  (globalThis.URL as any).revokeObjectURL = vi.fn();
});
afterEach(() => { setOnline(true); Object.defineProperty(navigator, 'geolocation', { configurable: true, value: undefined }); });

const base = { open: true, calculationId: 'c1', plotNumber: 4, stratum: 'forest', speciesKeys: ['x'], names: { x: 'टिमुर' }, stored: [] as any[] };
const TITLE = 'Plot 4: what was found';

describe('saving a plot with no signal', () => {
  it('keeps it on the phone, says so, and closes', async () => {
    m.savePlot.mockRejectedValue(noSignal());
    const onSaved = vi.fn(), onClose = vi.fn();
    render(<NtfpPlotEntry {...base} onSaved={onSaved} onClose={onClose} />);
    await screen.findByText(TITLE);
    fireEvent.change(screen.getByLabelText('Total counted टिमुर'), { target: { value: '7' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save plot' }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    const [item] = await listOutbox('c1');
    expect(item).toMatchObject({ kind: 'plot', plotNumber: 4, state: 'waiting' });
    expect(item.entries?.[0]).toMatchObject({ species_key: 'x', count_total: 7 });
    expect(onSaved).toHaveBeenCalled();
  });

  it('does not even call the server when the phone says it is offline', async () => {
    setOnline(false);
    const onClose = vi.fn();
    render(<NtfpPlotEntry {...base} onSaved={() => {}} onClose={onClose} />);
    await screen.findByText(TITLE);
    fireEvent.change(screen.getByLabelText('Total counted टिमुर'), { target: { value: '2' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save plot' }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(m.savePlot).not.toHaveBeenCalled();
    expect(await listOutbox('c1')).toHaveLength(1);
  });

  it('still shows the server\'s refusal as before, and keeps nothing', async () => {
    m.savePlot.mockRejectedValue({ response: { status: 422, data: { detail: { code: 'plot.invalid', findings: [{ severity: 'error', code: 'x', message: 'Mature is more than the total.', species_key: 'x' }] } } } });
    const onClose = vi.fn();
    render(<NtfpPlotEntry {...base} onSaved={() => {}} onClose={onClose} />);
    await screen.findByText(TITLE);
    fireEvent.change(screen.getByLabelText('Total counted टिमुर'), { target: { value: '2' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save plot' }));
    expect(await screen.findByText(/Mature is more than the total/)).toBeInTheDocument();
    expect(await listOutbox('c1')).toEqual([]);
    expect(onClose).not.toHaveBeenCalled();
  });
});

describe('the position check with no signal', () => {
  it('reads the position and queues it', async () => {
    Object.defineProperty(navigator, 'geolocation', { configurable: true, value: { getCurrentPosition: (ok: any) => ok({ coords: { latitude: 28.1, longitude: 84.2, accuracy: 6 } }) } });
    m.checkPresence.mockRejectedValue(noSignal());
    const onQueued = vi.fn();
    render(<NtfpPlotHere calculationId="c1" plotNumber={4} presence={null} onChecked={() => {}} onQueued={onQueued} />);
    fireEvent.click(screen.getByRole('button', { name: /I am here/ }));
    await waitFor(() => expect(onQueued).toHaveBeenCalledWith({ latitude: 28.1, longitude: 84.2, accuracy_m: 6 }));
    expect(await listOutbox('c1')).toMatchObject([{ kind: 'presence', plotNumber: 4, position: { latitude: 28.1, longitude: 84.2, accuracy_m: 6 } }]);
  });

  it('tells the person it is kept while it waits', () => {
    render(<NtfpPlotHere calculationId="c1" plotNumber={4} presence={null} onChecked={() => {}} queued />);
    expect(screen.getByText(/your position is saved on this phone/)).toBeInTheDocument();
  });
});

describe('a photo with no signal', () => {
  const file = () => new File(['abc'], 'IMG_9.jpg', { type: 'image/jpeg' });

  it('waits on the phone, with the position of the last check', async () => {
    m.uploadPhoto.mockRejectedValue(noSignal());
    const onQueued = vi.fn();
    render(<NtfpPlotPhotos calculationId="c1" plotNumber={4} photos={[]} position={{ latitude: 28, longitude: 84, accuracy_m: 5 }} onChanged={() => {}} onQueued={onQueued} />);
    fireEvent.change(screen.getByTestId('photo-input'), { target: { files: [file()] } });
    await waitFor(() => expect(onQueued).toHaveBeenCalled());
    const [item] = await listOutbox('c1');
    expect(item).toMatchObject({ kind: 'photo', plotNumber: 4, fileName: 'IMG_9.jpg', position: { latitude: 28, longitude: 84, accuracy_m: 5 } });
    expect(item.blob).toBeInstanceOf(Blob);
  });

  it('shows the waiting photos beside the sent ones, counts them toward the ten, and can discard one', async () => {
    const waiting = await enqueue({ calcId: 'c1', kind: 'photo', plotNumber: 4, blob: new Blob(['a']), fileName: 'w.jpg' });
    render(<NtfpPlotPhotos calculationId="c1" plotNumber={4} photos={[]} onChanged={() => {}} pending={[waiting]} />);
    expect(screen.getByTestId('pending-photo')).toBeInTheDocument();
    expect(screen.getByText('Waiting to send')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Delete photo/ }));
    await waitFor(async () => expect(await listOutbox('c1')).toEqual([]));
  });

  it('counts waiting photos toward the limit of ten', () => {
    const items = Array.from({ length: 10 }, (_, i) => ({ id: `w${i}`, calcId: 'c1', kind: 'photo', plotNumber: 4, createdAt: i, state: 'waiting', attempts: 0, blob: new Blob(['a']), fileName: `${i}.jpg` })) as OutboxItem[];
    render(<NtfpPlotPhotos calculationId="c1" plotNumber={4} photos={[]} onChanged={() => {}} pending={items} />);
    expect(screen.getByRole('button', { name: /Take a photo/ })).toBeDisabled();
  });
});

describe('NtfpOutboxBar', () => {
  const outbox = (over: Record<string, unknown> = {}): any => ({ items: [], waiting: [], rejected: [], online: true, sending: false, flush: vi.fn(), discard: vi.fn(), retry: vi.fn(), ...over });
  const item = (over: Record<string, unknown>): OutboxItem => ({ id: 'i', calcId: 'c1', kind: 'plot', plotNumber: 3, createdAt: 1, state: 'waiting', attempts: 0, ...over }) as OutboxItem;

  it('is not there when online with nothing waiting', () => {
    const { container } = render(<NtfpOutboxBar outbox={outbox()} names={{}} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('says it is offline, counts what waits, and sends on request', () => {
    const flush = vi.fn();
    const w = [item({ id: 'a' }), item({ id: 'b', kind: 'photo' }), item({ id: 'c', kind: 'photo' }), item({ id: 'd', kind: 'presence' })];
    render(<NtfpOutboxBar outbox={outbox({ online: false, waiting: w, items: w, flush })} names={{}} />);
    expect(screen.getByText(/No signal\. What you save is kept on this phone/)).toBeInTheDocument();
    expect(screen.getByText('Waiting to send: 1 plots, 2 photos, 1 position checks.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Send now' })).toBeDisabled();     // offline: nothing to send with
  });

  it('lets the person send now once online', () => {
    const flush = vi.fn();
    const w = [item({ id: 'a' })];
    render(<NtfpOutboxBar outbox={outbox({ waiting: w, items: w, flush })} names={{}} />);
    fireEvent.click(screen.getByRole('button', { name: 'Send now' }));
    expect(flush).toHaveBeenCalled();
  });

  it('lists a refused item with the reason by species, and offers try again and discard', () => {
    const retry = vi.fn(), discard = vi.fn();
    const r = item({ id: 'r', state: 'rejected', error: 'Nothing was saved: check the entries.', findings: [{ severity: 'error', sheet: 'Plots', row: null, column: null, code: 'c', message: 'Mature is more than the total.', species_key: 'x' }] });
    render(<NtfpOutboxBar outbox={outbox({ rejected: [r], items: [r], retry, discard })} names={{ x: 'टिमुर' }} />);
    expect(screen.getByText('The server refused the entries of plot 3.')).toBeInTheDocument();
    expect(screen.getByText(/टिमुर: Mature is more than the total\./)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(retry).toHaveBeenCalledWith(r);
    fireEvent.click(screen.getByRole('button', { name: 'Discard' }));
    expect(discard).toHaveBeenCalledWith('r');
  });
});

describe('the collect panel with something waiting', () => {
  const design: any = {
    plot_shape: 'square', seed: 1, min_plots: 3, species: [{ species_key: 'x', label: 'टिमुर', growth_class: 'shrub', plot_sqm: 25, intensity_pct: 1, plots: 2, intensity_achieved_pct: 1, plots_by_stratum: {} }],
    strata: [], plots: [
      { plot_number: 1, stratum: 'a', transect: 1, longitude: 84, latitude: 28, species_keys: ['x'] },
      { plot_number: 2, stratum: 'a', transect: 1, longitude: 84, latitude: 28, species_keys: ['x'] },
    ], warnings: [], transects: { type: 'FeatureCollection', features: [] }, layout: {},
  };

  it('shows a plot saved offline as recorded at once, marks it as waiting, and sends it when the signal is back', async () => {
    setOnline(false);
    await enqueue({ calcId: 'c1', kind: 'plot', plotNumber: 2, entries: [{ species_key: 'x', count_total: 5, weights: [] }] });
    const onChanged = vi.fn();
    const records: any = { pairs_assigned: 2, pairs_recorded: 0, weights: 0, mode: null, observations: [] };
    render(<NtfpCollectPanel calculationId="c1" hasDesign records={records} onChanged={onChanged} design={design} boundary={null} />);
    fireEvent.click(screen.getByText('Enter on the map'));
    expect(await screen.findByText('plot 2: 1/1 (waiting)')).toBeInTheDocument();     // typed offline, shown now
    expect(screen.getByText('plot 1: 0/1')).toBeInTheDocument();
    expect(screen.getByText(/No signal\. What you save is kept on this phone/)).toBeInTheDocument();
    expect(screen.getByText('Waiting to send: 1 plots, 0 photos, 0 position checks.')).toBeInTheDocument();

    m.savePlot.mockResolvedValue({ ok: true, findings: [], observations_written: 1, weights_written: 0, cleared: 0 });
    setOnline(true);
    window.dispatchEvent(new Event('online'));
    await waitFor(() => expect(m.savePlot).toHaveBeenCalledWith('c1', 2, [{ species_key: 'x', count_total: 5, weights: [] }], expect.objectContaining({ idempotencyKey: expect.any(String) })));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());          // the page reloads its records after the send
    await waitFor(async () => expect(await listOutbox('c1')).toEqual([]));
  });
});
