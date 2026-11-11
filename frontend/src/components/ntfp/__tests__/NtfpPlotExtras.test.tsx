import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import NtfpPlotHere from '../NtfpPlotHere';
import NtfpPlotPhotos from '../NtfpPlotPhotos';
import { readPosition } from '../../../lib/ntfp';
import { shrinkImage } from '../../../lib/imageShrink';
import * as api from '../../../services/api';

vi.mock('../../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../../services/api')>();
  return { ...actual, ntfpApi: { ...actual.ntfpApi, checkPresence: vi.fn(), uploadPhoto: vi.fn(), photoBlob: vi.fn(), deletePhoto: vi.fn() } };
});
const m = api.ntfpApi as unknown as Record<string, ReturnType<typeof vi.fn>>;

const geo = (impl: (ok: (p: any) => void, fail: (e: any) => void) => void) => {
  Object.defineProperty(navigator, 'geolocation', { configurable: true, value: { getCurrentPosition: impl } });
};
const fix = { coords: { latitude: 28.1, longitude: 84.2, accuracy: 8.26 } };
const presence = (verdict: string, distance = 12) => ({ latitude: 28.1, longitude: 84.2, accuracy_m: 8.3, distance_m: distance, verdict, checked_at: '2026-10-22T10:00:00Z', near_m: 40 });

beforeEach(() => {
  ['checkPresence', 'uploadPhoto', 'photoBlob', 'deletePhoto'].forEach((k) => m[k].mockReset());
  m.photoBlob.mockResolvedValue(new Blob(['x'], { type: 'image/jpeg' }));
  (globalThis.URL as any).createObjectURL = vi.fn(() => 'blob:thumb');
  (globalThis.URL as any).revokeObjectURL = vi.fn();
});
afterEach(() => { Object.defineProperty(navigator, 'geolocation', { configurable: true, value: undefined }); });

describe('readPosition', () => {
  it('gives the position with its accuracy rounded to a tenth of a metre', async () => {
    geo((ok) => ok(fix));
    expect(await readPosition()).toEqual({ latitude: 28.1, longitude: 84.2, accuracy_m: 8.3 });
  });
  it('names why it failed', async () => {
    geo((_ok, fail) => fail({ code: 1 }));
    await expect(readPosition()).rejects.toBe('denied');
    geo((_ok, fail) => fail({ code: 3 }));
    await expect(readPosition()).rejects.toBe('timeout');
    geo((_ok, fail) => fail({ code: 2 }));
    await expect(readPosition()).rejects.toBe('unavailable');
    Object.defineProperty(navigator, 'geolocation', { configurable: true, value: undefined });
    await expect(readPosition()).rejects.toBe('unsupported');
  });
});

describe('NtfpPlotHere', () => {
  const setup = (p: any = null) => {
    const onChecked = vi.fn();
    render(<NtfpPlotHere calculationId="c1" plotNumber={4} presence={p} onChecked={onChecked} />);
    return onChecked;
  };

  it('sends the position and tells the person they are at the plot', async () => {
    geo((ok) => ok(fix));
    m.checkPresence.mockResolvedValue(presence('at'));
    const onChecked = setup();
    fireEvent.click(screen.getByRole('button', { name: /I am here/ }));
    await waitFor(() => expect(m.checkPresence).toHaveBeenCalledWith('c1', 4, { latitude: 28.1, longitude: 84.2, accuracy_m: 8.3 }));
    await waitFor(() => expect(onChecked).toHaveBeenCalled());
  });

  it.each([
    ['at', /You are at this plot/], ['far', /You are far from this plot/], ['uncertain', /too uncertain to tell/],
  ])('shows the %s verdict with the distance and the accuracy', (verdict, text) => {
    setup(presence(verdict, 1112));
    expect(screen.getByText(text)).toBeInTheDocument();
    expect(screen.getByText(/Distance to the plot marker: 1\.1 km\. Phone accuracy: 8 m\./)).toBeInTheDocument();
  });

  it('explains a blocked location in plain words and does not call the server', async () => {
    geo((_ok, fail) => fail({ code: 1 }));
    setup();
    fireEvent.click(screen.getByRole('button', { name: /I am here/ }));
    expect(await screen.findByText(/Location is blocked/)).toBeInTheDocument();
    expect(m.checkPresence).not.toHaveBeenCalled();
  });
});

describe('shrinkImage', () => {
  it('sends the original when the browser cannot shrink it', async () => {
    const f = new File(['abc'], 'p.jpg', { type: 'image/jpeg' });
    expect(await shrinkImage(f)).toBe(f);      // jsdom has no createImageBitmap
  });
});

describe('NtfpPlotPhotos', () => {
  const photo = (id: string) => ({ id, file_name: `${id}.jpg`, content_type: 'image/jpeg', size_bytes: 10, caption: null, latitude: null, longitude: null, created_at: null });
  const setup = (photos: any[] = [], position: any = null) => {
    const onChanged = vi.fn();
    render(<NtfpPlotPhotos calculationId="c1" plotNumber={4} photos={photos} position={position} onChanged={onChanged} />);
    return onChanged;
  };

  it('sends a chosen photo with the position of the last check, then reloads', async () => {
    m.uploadPhoto.mockResolvedValue(photo('new'));
    const onChanged = setup([], { latitude: 28.1, longitude: 84.2, accuracy_m: 5 });
    const file = new File(['abc'], 'IMG_1.jpg', { type: 'image/jpeg' });
    fireEvent.change(screen.getByTestId('photo-input'), { target: { files: [file] } });
    await waitFor(() => expect(m.uploadPhoto).toHaveBeenCalled());
    const [id, plot, blob, name, pos] = m.uploadPhoto.mock.calls[0];
    expect([id, plot, name]).toEqual(['c1', 4, 'IMG_1.jpg']);
    expect(blob).toBe(file);
    expect(pos).toEqual({ latitude: 28.1, longitude: 84.2, accuracy_m: 5 });
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it('opens the phone camera: the input asks for the back camera', () => {
    setup();
    const input = screen.getByTestId('photo-input');
    expect(input).toHaveAttribute('accept', 'image/*');
    expect(input).toHaveAttribute('capture', 'environment');
  });

  it('shows each photo as a thumbnail fetched with the sign-in, and deletes one', async () => {
    m.deletePhoto.mockResolvedValue({ deleted: true });
    const onChanged = setup([photo('a'), photo('b')]);
    await waitFor(() => expect(m.photoBlob).toHaveBeenCalledTimes(2));
    expect(await screen.findAllByAltText(/\.jpg$/)).toHaveLength(2);
    fireEvent.click(screen.getAllByRole('button', { name: /Delete photo/ })[0]);
    fireEvent.click(await screen.findByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(m.deletePhoto).toHaveBeenCalledWith('c1', 'a'));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it('stops at ten photos', () => {
    setup(Array.from({ length: 10 }, (_, i) => photo(`p${i}`)));
    expect(screen.getByRole('button', { name: /Take a photo/ })).toBeDisabled();
    expect(screen.getByText(/most photos allowed/)).toBeInTheDocument();
  });

  it('says why the server refused a photo', async () => {
    m.uploadPhoto.mockRejectedValue({ response: { data: { detail: { code: 'photo.wrong_type', message: 'x' } } } });
    setup();
    fireEvent.change(screen.getByTestId('photo-input'), { target: { files: [new File(['<html>'], 'a.jpg', { type: 'image/jpeg' })] } });
    expect(await screen.findByText('Only JPEG, PNG or WebP photos are taken.')).toBeInTheDocument();
  });
});
