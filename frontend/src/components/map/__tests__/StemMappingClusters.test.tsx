import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { StemMappingClusters } from '../StemMappingClusters';
import { useWorkspaceStore } from '../../../store/workspaceStore';

// z19 -- above MIN_VISIBLE_ZOOM (13), so the default mock exercises the
// normal "layer actually renders" path. The dedicated below-threshold tests
// override getZoom per-case.
const mockMap = {
  getBounds: () => ({ getWest: () => 10, getSouth: () => 20, getEast: () => 11, getNorth: () => 21 }),
  getZoom: () => 19,
  on: vi.fn(),
  off: vi.fn(),
  setView: vi.fn(),
};

vi.mock('react-leaflet', () => ({
  useMap: () => mockMap,
}));

const useVisibleTreeClusterTilesMock = vi.fn();
vi.mock('../../../hooks/useTreeClusters', () => ({
  useVisibleTreeClusterTiles: (...a: unknown[]) => useVisibleTreeClusterTilesMock(...a),
}));

let lastLayerProps: { onSelectTree?: (id: string) => void } = {};
vi.mock('../TreeClustersLayer', () => ({
  TreeClustersLayer: (props: {
    visible?: boolean; renderer?: { field: string };
    filter?: { layerId: string; field: string } | null;
    onSelectTree?: (id: string) => void;
  }) => {
    lastLayerProps = props;
    return (
      <div
        data-testid="tree-clusters-layer"
        data-visible={String(props.visible)}
        data-renderer-field={props.renderer?.field ?? ''}
        data-filter-field={props.filter?.field ?? ''}
        data-has-select={String(!!props.onSelectTree)}
      />
    );
  },
}));

describe('StemMappingClusters — viewport-tile rendering (fixes the "unresponsive" report)', () => {
  beforeEach(() => {
    useVisibleTreeClusterTilesMock.mockReset().mockReturnValue({ tiles: new Map() });
    mockMap.on.mockClear();
    mockMap.off.mockClear();
    useWorkspaceStore.setState({ calculationId: 'calc-1', geometryVersion: 0, layerRenderers: {} });
  });

  it('renders nothing and attaches no map listeners while not visible — panning with it hidden costs nothing', () => {
    render(<StemMappingClusters visible={false} />);
    expect(screen.queryByTestId('tree-clusters-layer')).not.toBeInTheDocument();
    expect(mockMap.on).not.toHaveBeenCalled();
  });

  it('tracks the viewport (moveend/zoomend) and renders the cluster layer once visible', () => {
    render(<StemMappingClusters visible />);
    expect(mockMap.on).toHaveBeenCalledWith('moveend', expect.any(Function));
    expect(mockMap.on).toHaveBeenCalledWith('zoomend', expect.any(Function));
    expect(screen.getByTestId('tree-clusters-layer')).toHaveAttribute('data-visible', 'true');
  });

  it('never asks for tiles outside the viewport it just measured — passes the real bounds/zoom through', () => {
    render(<StemMappingClusters visible />);
    expect(useVisibleTreeClusterTilesMock).toHaveBeenCalledWith(
      'calc-1', 0, [[10, 20], [11, 21]], 19, true,
    );
  });

  it('passes the Style Layer dialog\'s active renderer through, when one is configured', () => {
    useWorkspaceStore.setState({
      layerRenderers: { stem_mapping: { mode: 'categorized', field: 'species', classes: [] } },
    });
    render(<StemMappingClusters visible />);
    expect(screen.getByTestId('tree-clusters-layer')).toHaveAttribute('data-renderer-field', 'species');
  });

  it('wires a tree-click handler that selects that tree in the Stem Mapping table', () => {
    useWorkspaceStore.setState({ selection: { layerId: null, featureIds: [], mode: 'replace' } as never });
    render(<StemMappingClusters visible />);
    expect(screen.getByTestId('tree-clusters-layer')).toHaveAttribute('data-has-select', 'true');

    lastLayerProps.onSelectTree?.('tree-99');
    const sel = useWorkspaceStore.getState().selection;
    expect(sel.layerId).toBe('stem_mapping');
    expect(sel.featureIds).toEqual(['tree-99']);
  });
});

describe('StemMappingClusters — permanent scale-based visibility (MIN_VISIBLE_ZOOM = 13)', () => {
  beforeEach(() => {
    useVisibleTreeClusterTilesMock.mockReset().mockReturnValue({ tiles: new Map() });
    mockMap.on.mockClear();
    mockMap.off.mockClear();
    useWorkspaceStore.setState({ calculationId: 'calc-1', geometryVersion: 0, layerRenderers: {} });
  });

  it('below the floor (z12): shows a zoom-in hint instead of the cluster layer, and fetches no tiles', () => {
    mockMap.getZoom = () => 12;
    render(<StemMappingClusters visible />);
    expect(screen.queryByTestId('tree-clusters-layer')).not.toBeInTheDocument();
    expect(screen.getByText(/Zoom in to see Stem Mapping/)).toBeInTheDocument();
    // `enabled` (5th arg) is false — no tile fetch is issued while below the threshold.
    expect(useVisibleTreeClusterTilesMock).toHaveBeenCalledWith(
      'calc-1', 0, [[10, 20], [11, 21]], 12, false,
    );
    mockMap.getZoom = () => 19; // restore the module-level default for later tests
  });

  it('at exactly the floor (z13): renders the cluster layer, not the hint, and enables tile fetch', () => {
    mockMap.getZoom = () => 13;
    render(<StemMappingClusters visible />);
    expect(screen.getByTestId('tree-clusters-layer')).toHaveAttribute('data-visible', 'true');
    expect(screen.queryByText(/Zoom in to see Stem Mapping/)).not.toBeInTheDocument();
    expect(useVisibleTreeClusterTilesMock).toHaveBeenCalledWith(
      'calc-1', 0, [[10, 20], [11, 21]], 13, true,
    );
    mockMap.getZoom = () => 19;
  });

  it('at a mid zoom (z15): still renders the layer — the backend serves cluster bubbles here', () => {
    mockMap.getZoom = () => 15;
    render(<StemMappingClusters visible />);
    expect(screen.getByTestId('tree-clusters-layer')).toHaveAttribute('data-visible', 'true');
    expect(useVisibleTreeClusterTilesMock).toHaveBeenCalledWith(
      'calc-1', 0, [[10, 20], [11, 21]], 15, true,
    );
    mockMap.getZoom = () => 19;
  });

  it('still attaches viewport listeners while below the floor — zooming toward it is tracked', () => {
    mockMap.getZoom = () => 10;
    render(<StemMappingClusters visible />);
    expect(mockMap.on).toHaveBeenCalledWith('moveend', expect.any(Function));
    expect(mockMap.on).toHaveBeenCalledWith('zoomend', expect.any(Function));
    mockMap.getZoom = () => 19;
  });
});

describe('StemMappingClusters — P4.6 map filter, scoped to this layer', () => {
  beforeEach(() => {
    useVisibleTreeClusterTilesMock.mockReset().mockReturnValue({ tiles: new Map() });
    mockMap.on.mockClear();
    mockMap.off.mockClear();
    useWorkspaceStore.setState({ calculationId: 'calc-1', geometryVersion: 0, layerRenderers: {}, tableFilter: null });
  });

  it('passes the active filter through when it targets stem_mapping', () => {
    useWorkspaceStore.setState({
      tableFilter: { layerId: 'stem_mapping', field: 'dbh_cm', op: 'gt', value: '40' },
    });
    render(<StemMappingClusters visible />);
    expect(screen.getByTestId('tree-clusters-layer')).toHaveAttribute('data-filter-field', 'dbh_cm');
  });

  it('does not pass a filter scoped to a different layer', () => {
    useWorkspaceStore.setState({
      tableFilter: { layerId: 'blocks', field: 'area_ha', op: 'gt', value: '5' },
    });
    render(<StemMappingClusters visible />);
    expect(screen.getByTestId('tree-clusters-layer')).toHaveAttribute('data-filter-field', '');
  });

  it('below the floor with an active stem_mapping filter, the hint says the filter needs zoom 18+', () => {
    mockMap.getZoom = () => 12;
    useWorkspaceStore.setState({
      tableFilter: { layerId: 'stem_mapping', field: 'dbh_cm', op: 'gt', value: '40' },
    });
    render(<StemMappingClusters visible />);
    expect(screen.getByText(/table filter applies to individual trees — zoom in to 18\+/)).toBeInTheDocument();
    mockMap.getZoom = () => 19;
  });
});
