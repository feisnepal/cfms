import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import type L from 'leaflet';
import { TreeClusterMarker, TreeClustersLayer, MAX_INDIVIDUAL_MARKERS } from '../TreeClustersLayer';
import type { TreeClusterTileData } from '../../../hooks/useTreeClusters';
import { OTHER_COLOR, PRIME_SPECIES } from '../../../lib/primeSpecies';
import type { RendererSpec } from '../../../lib/layerRenderers';

vi.mock('react-leaflet', () => ({
  CircleMarker: (props: {
    radius: number; fillColor: string; interactive?: boolean; shape?: string;
    pathOptions?: { stroke?: boolean; fillOpacity?: number };
    eventHandlers?: { click?: (e: unknown) => void };
    children?: React.ReactNode;
  }) => (
    <div
      data-testid="circle-marker"
      data-radius={props.radius}
      data-fill={props.fillColor}
      data-shape={props.shape}
      data-stroke={String(props.pathOptions?.stroke)}
      data-fill-opacity={props.pathOptions?.fillOpacity}
      data-interactive={String(props.interactive)}
      onClick={() => props.eventHandlers?.click?.({ originalEvent: {} })}
    >
      {props.children}
    </div>
  ),
  // Real react-leaflet renders `icon` (an L.DivIcon) via Leaflet's own DOM
  // code; this stub never does, so it just surfaces the icon's own computed
  // HTML/size for assertions — L.divIcon() itself runs unmocked in the SUT.
  Marker: (props: { icon: L.DivIcon; children?: React.ReactNode }) => (
    <div
      data-testid="cluster-marker"
      data-html={props.icon.options.html as string}
      data-size={(props.icon.options.iconSize as [number, number])?.[0]}
    >
      {props.children}
    </div>
  ),
  Popup: ({ children }: { children: React.ReactNode }) => <div data-testid="popup">{children}</div>,
  useMap: () => ({}),
}));

function feature(props: Record<string, unknown>): GeoJSON.Feature<GeoJSON.Point> {
  return { type: 'Feature', geometry: { type: 'Point', coordinates: [83.5, 27.5] }, properties: props };
}

describe('TreeClusterMarker — cluster bubbles (the QGIS point-cluster look)', () => {
  it('a normal cluster shows its exact count on the bubble', () => {
    render(<TreeClusterMarker feature={feature({ point_count: 42, actual_count: 42, zoom_hint: false })} mapZoom={10} />);
    const el = screen.getByTestId('cluster-marker');
    expect(el.dataset.html).toContain('>42<');
    expect(el.dataset.html).toContain('#1890ff'); // blue = normal cluster
  });

  it('a dense (capped) cell shows the TRUE count, not the "500" cap, and reads red', () => {
    // Backend caps point_count at 500 but sends actual_count = 7437.
    render(
      <TreeClusterMarker
        feature={feature({ point_count: 500, actual_count: 7437, zoom_hint: true })}
        mapZoom={10}
      />,
    );
    const el = screen.getByTestId('cluster-marker');
    expect(el.dataset.html).toContain('>7.4k<');
    expect(el.dataset.html).not.toContain('500');
    expect(el.dataset.html).not.toContain('+<');
    expect(el.dataset.html).toContain('#ff4d4f');
    expect(Number(el.dataset.size)).toBe(52); // clusterRadius(*, true) = 26 -> diameter 52
  });

  it('the popup states the true count too', () => {
    render(
      <TreeClusterMarker
        feature={feature({ point_count: 500, actual_count: 7437, zoom_hint: true })}
        mapZoom={10}
      />,
    );
    expect(screen.getByTestId('popup').textContent).toBe('7,437 trees — click to zoom in');
  });

  it('bubble size grows with count (not a fixed size regardless of magnitude)', () => {
    render(<TreeClusterMarker feature={feature({ point_count: 4, actual_count: 4, zoom_hint: false })} mapZoom={10} />);
    const small = Number(screen.getByTestId('cluster-marker').dataset.size);

    render(<TreeClusterMarker feature={feature({ point_count: 400, actual_count: 400, zoom_hint: false })} mapZoom={10} />);
    const large = Number(screen.getAllByTestId('cluster-marker')[1].dataset.size);

    expect(large).toBeGreaterThan(small);
  });

  it('compacts thousands: 1,200 -> "1.2k", 12,000 -> "12k"', () => {
    render(<TreeClusterMarker feature={feature({ point_count: 500, actual_count: 1200, zoom_hint: true })} mapZoom={10} />);
    expect(screen.getAllByTestId('cluster-marker')[0].dataset.html).toContain('>1.2k<');

    render(<TreeClusterMarker feature={feature({ point_count: 500, actual_count: 12000, zoom_hint: true })} mapZoom={10} />);
    expect(screen.getAllByTestId('cluster-marker')[1].dataset.html).toContain('>12k<');
  });

  it('falls back to point_count when actual_count is absent (older cached tiles)', () => {
    render(<TreeClusterMarker feature={feature({ point_count: 42, zoom_hint: false })} mapZoom={10} />);
    expect(screen.getByTestId('cluster-marker').dataset.html).toContain('>42<');
  });
});

const shorea = PRIME_SPECIES.find((x) => x.code === 18)!.color;
const albizia = PRIME_SPECIES.find((x) => x.code === 4)!.color;

describe('TreeClusterMarker — individual trees', () => {
  it('is coloured by prime species by default', () => {
    render(<TreeClusterMarker feature={feature({ dbh_cm: 15, prime_species_code: 18 })} mapZoom={19} />);
    expect(screen.getByTestId('circle-marker')).toHaveAttribute('data-fill', shorea);
  });

  it('every non-prime species gets the single default colour', () => {
    render(<TreeClusterMarker feature={feature({ dbh_cm: 15, prime_species_code: null })} mapZoom={19} />);
    expect(screen.getByTestId('circle-marker')).toHaveAttribute('data-fill', OTHER_COLOR);
  });

  it('size follows the DBH class (and the zoom), colour does not', () => {
    render(<TreeClusterMarker feature={feature({ dbh_cm: 5, prime_species_code: 18 })} mapZoom={19} />);
    render(<TreeClusterMarker feature={feature({ dbh_cm: 75, prime_species_code: 18 })} mapZoom={19} />);
    const [small, big] = screen.getAllByTestId('circle-marker');
    expect(Number(big.getAttribute('data-radius'))).toBeGreaterThan(Number(small.getAttribute('data-radius')));
    expect(small.getAttribute('data-fill')).toBe(big.getAttribute('data-fill'));

    render(<TreeClusterMarker feature={feature({ dbh_cm: 5, prime_species_code: 18 })} mapZoom={22} />);
    const zoomed = screen.getAllByTestId('circle-marker')[2];
    expect(Number(zoomed.getAttribute('data-radius'))).toBeGreaterThan(Number(small.getAttribute('data-radius')));
  });

  it('a mother tree is a star with an outline; a felling tree is a plain circle', () => {
    render(<TreeClusterMarker feature={feature({ dbh_cm: 45, prime_species_code: 4, tree_group: 'mother' })} mapZoom={19} />);
    render(<TreeClusterMarker feature={feature({ dbh_cm: 45, prime_species_code: 4, tree_group: 'felling' })} mapZoom={19} />);
    const [mother, felling] = screen.getAllByTestId('circle-marker');
    expect(mother).toHaveAttribute('data-shape', 'star');
    expect(mother).toHaveAttribute('data-stroke', 'true');
    expect(felling).toHaveAttribute('data-shape', 'circle');
    expect(felling).toHaveAttribute('data-stroke', 'false');
    // same species -> same colour; only the shape differs
    expect(mother.getAttribute('data-fill')).toBe(albizia);
    expect(felling.getAttribute('data-fill')).toBe(albizia);
  });

  it('a seedling is a small neutral dot, whatever its species', () => {
    render(<TreeClusterMarker feature={feature({ dbh_cm: 6, prime_species_code: 18, tree_group: 'seedling' })} mapZoom={19} />);
    expect(screen.getByTestId('circle-marker')).toHaveAttribute('data-fill', OTHER_COLOR);
  });

  it('has no popup — species is the colour, DBH the size, group the shape', () => {
    render(<TreeClusterMarker feature={feature({ id: 't1', dbh_cm: 15 })} mapZoom={19} />);
    expect(screen.queryByTestId('popup')).not.toBeInTheDocument();
  });

  it('clicking it selects that tree, and is inert (non-interactive) with no handler', () => {
    const onSelectTree = vi.fn();
    const { rerender } = render(
      <TreeClusterMarker feature={feature({ id: 't42', dbh_cm: 15 })} mapZoom={19} />,
    );
    // No handler wired → not interactive, nothing to click.
    expect(screen.getByTestId('circle-marker')).toHaveAttribute('data-interactive', 'false');

    rerender(
      <TreeClusterMarker
        feature={feature({ id: 't42', dbh_cm: 15 })}
        mapZoom={19}
        onSelectTree={onSelectTree}
      />,
    );
    const el = screen.getByTestId('circle-marker');
    expect(el).toHaveAttribute('data-interactive', 'true');
    fireEvent.click(el);
    expect(onSelectTree).toHaveBeenCalledWith('t42');
  });

  it('a dimmed (not-isolated) tree is faint and cannot be clicked', () => {
    const onSelectTree = vi.fn();
    render(
      <TreeClusterMarker feature={feature({ id: 't9', dbh_cm: 15, prime_species_code: 18 })} mapZoom={19} dimmed onSelectTree={onSelectTree} />,
    );
    const el = screen.getByTestId('circle-marker');
    expect(el).toHaveAttribute('data-interactive', 'false');
    expect(Number(el.getAttribute('data-fill-opacity'))).toBeLessThan(0.2);
  });

  it('honours a Style Layer override renderer (e.g. by species name)', () => {
    const bySpecies: RendererSpec = {
      mode: 'categorized',
      field: 'species',
      classes: [{ value: 'Sal', color: '#123456' }],
      otherColor: '#999999',
    };
    render(
      <TreeClusterMarker
        feature={feature({ dbh_cm: 15, species: 'Sal' })}
        mapZoom={19}
        renderer={bySpecies}
      />,
    );
    expect(screen.getByTestId('circle-marker')).toHaveAttribute('data-fill', '#123456');
  });
});

function tilesOf(...features: GeoJSON.Feature<GeoJSON.Point>[]): Map<string, { data: TreeClusterTileData | null; state: 'ready' }> {
  return new Map([['18:0:0', { data: { features, hasMore: false }, state: 'ready' as const }]]);
}

describe('TreeClustersLayer — P4.6 "show only matches on map" filter', () => {
  it('with no filter, every tile feature renders', () => {
    const tiles = tilesOf(feature({ dbh_cm: 15 }), feature({ dbh_cm: 55 }));
    render(<TreeClustersLayer tiles={tiles} mapZoom={19} />);
    expect(screen.getAllByTestId('circle-marker')).toHaveLength(2);
  });

  it('drops individual-tree features that fail the filter', () => {
    const tiles = tilesOf(
      feature({ dbh_cm: 15, prime_species_code: 4 }),
      feature({ dbh_cm: 55, prime_species_code: 18 }),
    );
    render(
      <TreeClustersLayer
        tiles={tiles}
        mapZoom={19}
        filter={{ layerId: 'stem_mapping', field: 'dbh_cm', op: 'gt', value: '40' }}
      />,
    );
    const markers = screen.getAllByTestId('circle-marker');
    expect(markers).toHaveLength(1);
    // The surviving marker is the Shorea dbh_cm=55 tree, not the Albizia dbh_cm=15 one
    // the filter (dbh_cm > 40) dropped.
    expect(markers[0]).toHaveAttribute('data-fill', shorea);
  });

  it('a cluster bubble always passes the filter -- it has no per-tree properties to test', () => {
    const tiles = tilesOf(feature({ point_count: 42, zoom_hint: false }), feature({ dbh_cm: 15 }));
    render(
      <TreeClustersLayer
        tiles={tiles}
        mapZoom={10}
        filter={{ layerId: 'stem_mapping', field: 'dbh_cm', op: 'gt', value: '40' }}
      />,
    );
    // The dbh_cm=15 individual fails the filter and is dropped; the cluster bubble
    // (no dbh_cm at all) is never subject to it and still renders.
    expect(screen.getAllByTestId('cluster-marker')).toHaveLength(1);
    expect(screen.queryByTestId('circle-marker')).not.toBeInTheDocument();
  });
});

describe('TreeClustersLayer — individual-marker cap (the "page unresponsive" fix)', () => {
  const many = (n: number, over: (i: number) => Record<string, unknown> = () => ({})) =>
    Array.from({ length: n }, (_, i) => feature({ id: `t${i}`, dbh_cm: 10 + (i % 60), ...over(i) }));

  it('renders at most MAX_INDIVIDUAL_MARKERS individuals and shows a "showing N of M" notice', () => {
    const tiles = tilesOf(...many(MAX_INDIVIDUAL_MARKERS + 400));
    render(<TreeClustersLayer tiles={tiles} mapZoom={19} />);
    expect(screen.getAllByTestId('circle-marker')).toHaveLength(MAX_INDIVIDUAL_MARKERS);
    expect(
      screen.getByText(new RegExp(`of ${(MAX_INDIVIDUAL_MARKERS + 400).toLocaleString()} trees`)),
    ).toBeInTheDocument();
  });

  it('no notice when the feature count is within the cap', () => {
    const tiles = tilesOf(...many(50));
    render(<TreeClustersLayer tiles={tiles} mapZoom={19} />);
    expect(screen.getAllByTestId('circle-marker')).toHaveLength(50);
    expect(screen.queryByText(/trees — zoom in/)).not.toBeInTheDocument();
  });

  it('a filter that brings the match count under the cap clears the notice', () => {
    // 3000 trees, but only ~1/60 have dbh_cm exactly 15 → well under the cap.
    const tiles = tilesOf(...many(MAX_INDIVIDUAL_MARKERS + 500, (i) => ({ dbh_cm: i % 60 === 0 ? 15 : 100 })));
    render(
      <TreeClustersLayer
        tiles={tiles}
        mapZoom={19}
        filter={{ layerId: 'stem_mapping', field: 'dbh_cm', op: 'eq', value: '15' }}
      />,
    );
    const rendered = screen.getAllByTestId('circle-marker').length;
    expect(rendered).toBeLessThan(MAX_INDIVIDUAL_MARKERS);
    expect(screen.queryByText(/trees — zoom in/)).not.toBeInTheDocument();
  });
});

describe('TreeClustersLayer — species in view (reported to the layer panel) and isolation', () => {
  const mixed = () =>
    tilesOf(
      feature({ id: 'a', dbh_cm: 20, prime_species_code: 18 }),
      feature({ id: 'b', dbh_cm: 30, prime_species_code: 18 }),
      feature({ id: 'c', dbh_cm: 40, prime_species_code: 4 }),
      feature({ id: 'd', dbh_cm: 25, prime_species_code: null }),
    );

  it('reports the tree count per species on screen; non-prime species count as "other"', () => {
    const onSpeciesCounts = vi.fn();
    render(<TreeClustersLayer tiles={mixed()} mapZoom={19} onSpeciesCounts={onSpeciesCounts} />);
    const counts = onSpeciesCounts.mock.calls[onSpeciesCounts.mock.calls.length - 1][0] as Map<string, number>;
    expect(Object.fromEntries(counts)).toEqual({ '18': 2, '4': 1, other: 1 });
  });

  it('draws no legend on the map any more -- the layer panel owns it', () => {
    render(<TreeClustersLayer tiles={mixed()} mapZoom={19} onSpeciesCounts={() => {}} />);
    expect(screen.queryByTestId('stem-species-legend')).not.toBeInTheDocument();
  });

  it('with a species isolated, every other tree is dimmed and the isolated ones are not', () => {
    render(<TreeClustersLayer tiles={mixed()} mapZoom={19} isolated="18" />);
    const markers = screen.getAllByTestId('circle-marker');
    const faint = markers.filter((m) => Number(m.getAttribute('data-fill-opacity')) < 0.2);
    expect(markers).toHaveLength(4);
    expect(faint).toHaveLength(2); // Albizia + other; both Shorea stay bright
  });

  it('isolating "other" keeps only the non-prime trees bright', () => {
    render(<TreeClustersLayer tiles={mixed()} mapZoom={19} isolated="other" />);
    const bright = screen.getAllByTestId('circle-marker').filter((m) => Number(m.getAttribute('data-fill-opacity')) > 0.2);
    expect(bright).toHaveLength(1);
  });

  it('reports nothing when a user-chosen renderer replaced the species colouring (no species legend then)', () => {
    const bySpecies: RendererSpec = { mode: 'categorized', field: 'species', classes: [], otherColor: '#999' };
    const onSpeciesCounts = vi.fn();
    render(<TreeClustersLayer tiles={mixed()} mapZoom={19} renderer={bySpecies} isolated="18" onSpeciesCounts={onSpeciesCounts} />);
    expect((onSpeciesCounts.mock.calls[onSpeciesCounts.mock.calls.length - 1][0] as Map<string, number>).size).toBe(0);
    // ...and isolation must not dim anything under a renderer the species legend does not describe
    expect(screen.getAllByTestId('circle-marker').every((m) => Number(m.getAttribute('data-fill-opacity')) > 0.2)).toBe(true);
  });
});
