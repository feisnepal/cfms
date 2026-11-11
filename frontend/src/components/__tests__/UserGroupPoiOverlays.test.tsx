import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/react';
import { UserGroupPoiOverlays } from '../UserGroupPoiOverlays';
import { useWorkspaceStore } from '../../store/workspaceStore';

const { markers, geoRivers } = vi.hoisted(() => ({ markers: [] as unknown[], geoRivers: [] as unknown[] }));

vi.mock('react-leaflet', () => ({
  Marker: (props: { position: [number, number]; icon: { options: { className: string } } }) => {
    markers.push(props);
    return <div data-testid="marker" />;
  },
  GeoJSON: (props: { data: { type?: string } }) => {
    geoRivers.push(props);
    return <div data-testid="river" />;
  },
  Popup: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
  Tooltip: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
}));

vi.mock('../../services/api', () => ({ default: { get: vi.fn() } }));
import api from '../../services/api';

const poiData = {
  poi: [{ name: 'Shop', type: 'store', lat: 27.1, lon: 84.1 }],
  education: [{ name: 'School', lat: 27.2, lon: 84.2 }],
  health: [{ name: 'Clinic', lat: 27.3, lon: 84.3 }],
  rivers: [{ name: 'Bagmati', geometry: { type: 'LineString', coordinates: [[84, 27], [85, 27]] } }],
};

function countByIcon(className: string) {
  return markers.filter((m: any) => m.icon.options.className === className).length;
}

describe('UserGroupPoiOverlays (BG-3 / D6)', () => {
  beforeEach(() => {
    markers.length = 0;
    geoRivers.length = 0;
    (api.get as unknown as ReturnType<typeof vi.fn>).mockReset();
    useWorkspaceStore.setState({ userGroupPoiVisible: {} });
  });

  it('does not fetch or render anything while no category is turned on', () => {
    render(<UserGroupPoiOverlays calculationId="calc-1" />);
    expect(api.get).not.toHaveBeenCalled();
    expect(document.querySelectorAll('[data-testid="marker"]').length).toBe(0);
  });

  it('fetches layer_type=all once a category is turned on', () => {
    useWorkspaceStore.setState({ userGroupPoiVisible: { education: true } });
    (api.get as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({ data: poiData });
    render(<UserGroupPoiOverlays calculationId="calc-1" />);
    expect(api.get).toHaveBeenCalledWith('/api/calculations/calc-1/user-group/poi', {
      params: { layer_type: 'all' },
    });
  });

  it('renders only the enabled categories (education only)', async () => {
    useWorkspaceStore.setState({ userGroupPoiVisible: { education: true } });
    (api.get as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({ data: poiData });
    render(<UserGroupPoiOverlays calculationId="calc-1" />);
    await vi.waitFor(() => expect(markers.length).toBe(1));
    expect(countByIcon('education-marker')).toBe(1);
    expect(countByIcon('health-marker')).toBe(0);
    expect(countByIcon('poi-marker')).toBe(0);
    expect(geoRivers.length).toBe(0);
  });

  it('renders every enabled category with the right icon/position', async () => {
    useWorkspaceStore.setState({
      userGroupPoiVisible: { education: true, health: true, poi: true, rivers: true },
    });
    (api.get as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({ data: poiData });
    render(<UserGroupPoiOverlays calculationId="calc-1" />);
    await vi.waitFor(() => expect(markers.length).toBe(3));
    expect(countByIcon('education-marker')).toBe(1);
    expect(countByIcon('health-marker')).toBe(1);
    expect(countByIcon('poi-marker')).toBe(1);
    expect(geoRivers.length).toBe(1);
    expect((geoRivers[0] as any).data.type).toBe('LineString');
    const edu = markers.find((m: any) => m.icon.options.className === 'education-marker') as any;
    expect(edu.position).toEqual([27.2, 84.2]);
  });

  it('stays quiet when the POI fetch fails (no analysis path)', async () => {
    useWorkspaceStore.setState({ userGroupPoiVisible: { rivers: true } });
    (api.get as unknown as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('boom'));
    render(<UserGroupPoiOverlays calculationId="calc-1" />);
    await vi.waitFor(() => expect(geoRivers.length).toBe(0));
    expect(document.querySelectorAll('[data-testid="marker"]').length).toBe(0);
  });
})