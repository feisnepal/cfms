import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import * as L from 'leaflet';
import { ReferenceLayersGroup } from '../ReferenceLayersGroup';
import * as api from '../../services/api';

vi.mock('../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../services/api')>();
  return { ...actual, referenceLayersApi: { catalog: vi.fn(), features: vi.fn() } };
});
const m = api.referenceLayersApi as unknown as { catalog: ReturnType<typeof vi.fn>; features: ReturnType<typeof vi.fn> };

const CATALOG = [
  { key: 'rivers', label_en: 'Rivers and streams', label_ne: 'नदी तथा खोला', geometry: 'line', style: { color: '#1e88e5', weight: 1.6 }, group: 'context', source: 'River network (river84)', licence: null, licence_note: 'not recorded', max_features: 6000, default_buffer_m: 2000, max_buffer_m: 10000 },
  { key: 'roads', label_en: 'Roads and tracks', label_ne: 'सडक तथा बाटो', geometry: 'line', style: { color: '#8d6e63', dashArray: '6 3' }, group: 'context', source: 'OpenStreetMap contributors', licence: 'ODbL 1.0', licence_note: null, max_features: 6000, default_buffer_m: 2000, max_buffer_m: 10000 },
  { key: 'settlements', label_en: 'Settlements', label_ne: 'बस्ती', geometry: 'point', style: { color: '#e65100', fillColor: '#ff9800', fillOpacity: 0.9, radius: 4 }, group: 'context', source: 'Settlement points', licence: null, licence_note: 'not recorded', max_features: 6000, default_buffer_m: 2000, max_buffer_m: 10000 },
];
const fc = (key: string, n = 2, over: Record<string, unknown> = {}) => ({
  type: 'FeatureCollection', key, count: n, truncated: false, buffer_m: 2000, max_features: 6000,
  features: Array.from({ length: n }, (_, i) => ({ type: 'Feature', id: `${key}-${i}`, geometry: key === 'settlements' ? { type: 'Point', coordinates: [83.4 + i * 0.001, 27.4] } : { type: 'LineString', coordinates: [[83.4, 27.4 + i * 0.001], [83.41, 27.41 + i * 0.001]] }, properties: { name: `N${i}`, _label: `N${i}`, _ref: `${key}-${i}` } })),
  ...over,
});

let map: L.Map;
const countLayers = () => { let n = 0; map.eachLayer((l) => { if ((l as any).feature || (l as L.FeatureGroup).getLayers) { if ((l as any).getLayers && !(l as any).feature) n += (l as L.FeatureGroup).getLayers().length; } }); return n; };
const geoJsonGroups = () => { const out: L.GeoJSON[] = []; map.eachLayer((l) => { if (l instanceof L.GeoJSON) out.push(l); }); return out; };

beforeEach(() => {
  localStorage.clear();
  m.catalog.mockReset();
  m.features.mockReset();
  m.catalog.mockResolvedValue({ layers: CATALOG });
  m.features.mockImplementation(async (_c: string, key: string) => fc(key));
  const div = document.createElement('div');
  document.body.appendChild(div);
  map = L.map(div).setView([27.4, 83.4], 12);
});

const open = async () => {
  fireEvent.click(screen.getByRole('button', { name: /Reference data/ }));
  await screen.findByText('Rivers and streams');
};

describe('ReferenceLayersGroup', () => {
  it('is closed at first, reads nothing, and lists the layers when opened', async () => {
    render(<ReferenceLayersGroup calculationId="c1" map={map} />);
    expect(screen.queryByText('Rivers and streams')).not.toBeInTheDocument();
    expect(m.features).not.toHaveBeenCalled();
    await open();
    expect(screen.getByText('Roads and tracks')).toBeInTheDocument();
    expect(m.catalog).toHaveBeenCalledWith('c1');
    expect(m.features).not.toHaveBeenCalled();           // listing a layer does not read it
  });

  it('reads a layer when it is switched on, draws it under the forest\'s layers, and shows the count and the source', async () => {
    render(<ReferenceLayersGroup calculationId="c1" map={map} />);
    await open();
    fireEvent.click(screen.getByRole('checkbox', { name: /Rivers and streams/ }));
    await waitFor(() => expect(m.features).toHaveBeenCalledWith('c1', 'rivers', 2000));
    await waitFor(() => expect(geoJsonGroups()).toHaveLength(1));
    expect(geoJsonGroups()[0].getLayers()).toHaveLength(2);
    expect(map.getPane('cfReference')!.style.zIndex).toBe('380');                  // below the overlay pane (400) the forest's own layers are drawn in
    expect(await screen.findByText(/· 2/)).toBeInTheDocument();
    expect(screen.getByText('River network (river84)')).toBeInTheDocument();
    expect(screen.getByText('licence not confirmed')).toBeInTheDocument();
  });

  it('asks for the credit the roads\' licence requires, only while the roads are on', async () => {
    render(<ReferenceLayersGroup calculationId="c1" map={map} />);
    await open();
    const credit = () => (map.attributionControl as any)._container.textContent as string;
    expect(credit()).not.toContain('OpenStreetMap contributors');
    fireEvent.click(screen.getByRole('checkbox', { name: /Roads and tracks/ }));
    await waitFor(() => expect(credit()).toContain('OpenStreetMap contributors'));
    expect(screen.getByText('ODbL 1.0')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('checkbox', { name: /Roads and tracks/ }));
    await waitFor(() => expect(credit()).not.toContain('OpenStreetMap contributors'));
    expect(geoJsonGroups()).toHaveLength(0);
  });

  it('shows a name on hover and the attributes as text in a popup', async () => {
    render(<ReferenceLayersGroup calculationId="c1" map={map} />);
    await open();
    fireEvent.click(screen.getByRole('checkbox', { name: /Rivers and streams/ }));
    await waitFor(() => expect(geoJsonGroups()).toHaveLength(1));
    const first = geoJsonGroups()[0].getLayers()[0] as L.Layer;
    expect((first as any).getTooltip().getContent()).toBe('N0');
    const content = (first as any).getPopup()._content();
    expect(content.querySelector('strong').textContent).toBe('N0');
  });

  it('remembers what was on and brings it back on the next visit without opening the group', async () => {
    const first = render(<ReferenceLayersGroup calculationId="c1" map={map} />);
    await open();
    fireEvent.click(screen.getByRole('checkbox', { name: /Settlements/ }));
    await waitFor(() => expect(geoJsonGroups()).toHaveLength(1));
    first.unmount();
    await waitFor(() => expect(geoJsonGroups()).toHaveLength(0));            // leaving the page takes the layers off the map
    render(<ReferenceLayersGroup calculationId="c1" map={map} />);
    await waitFor(() => expect(geoJsonGroups()).toHaveLength(1));            // ... and the next visit puts them back
    expect(screen.getByText(/· 1 on/)).toBeInTheDocument();
  });

  it('reads again, wider, when the distance changes, and remembers it', async () => {
    render(<ReferenceLayersGroup calculationId="c1" map={map} />);
    await open();
    fireEvent.click(screen.getByRole('checkbox', { name: /Rivers and streams/ }));
    await waitFor(() => expect(m.features).toHaveBeenCalledTimes(1));
    fireEvent.change(screen.getByRole('combobox', { name: /Distance round the forest/ }), { target: { value: '5000' } });
    await waitFor(() => expect(m.features).toHaveBeenLastCalledWith('c1', 'rivers', 5000));
    expect(JSON.parse(localStorage.getItem('cf_reference_layers_c1')!)).toMatchObject({ visible: ['rivers'], bufferM: 5000 });
  });

  it('says when a layer was cut short, when it is empty and when it failed', async () => {
    m.features.mockImplementation(async (_c: string, key: string) => {
      if (key === 'rivers') return fc('rivers', 3, { truncated: true, max_features: 3 });
      if (key === 'roads') return fc('roads', 0);
      throw { response: { data: { detail: { code: 'x', message: 'The forest has no boundary yet.' } } } };
    });
    render(<ReferenceLayersGroup calculationId="c1" map={map} />);
    await open();
    fireEvent.click(screen.getByRole('checkbox', { name: /Rivers and streams/ }));
    expect(await screen.findByText(/Only the first 3 are shown/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('checkbox', { name: /Roads and tracks/ }));
    expect(await screen.findByText('Nothing of this layer lies in this neighbourhood.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('checkbox', { name: /Settlements/ }));
    expect(await screen.findByText('The forest has no boundary yet.')).toBeInTheDocument();
  });

  it('draws nothing from a layer that was switched off while it was loading', async () => {
    let release: (v: unknown) => void = () => {};
    m.features.mockImplementation(() => new Promise((res) => { release = res; }));
    render(<ReferenceLayersGroup calculationId="c1" map={map} />);
    await open();
    fireEvent.click(screen.getByRole('checkbox', { name: /Rivers and streams/ }));
    await waitFor(() => expect(m.features).toHaveBeenCalled());
    fireEvent.click(screen.getByRole('checkbox', { name: /Rivers and streams/ }));
    release(fc('rivers'));
    await new Promise((r) => setTimeout(r, 50));
    expect(geoJsonGroups()).toHaveLength(0);
  });

  it('shows nothing when there is no forest', () => {
    const { container } = render(<ReferenceLayersGroup map={map} />);
    expect(container).toBeEmptyDOMElement();
  });
});
