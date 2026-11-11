import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AutoBlockDesigner } from '../AutoBlockDesigner';
import * as api from '../../services/api';

vi.mock('../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../services/api')>();
  return {
    ...actual,
    forestApi: {
      ...actual.forestApi,
      autoBlocksPreview: vi.fn(),
      autoBlocksCommit: vi.fn(),
      autoDividePreview: vi.fn(),
      autoDivideCommit: vi.fn(),
    },
  };
});

const mockPreview = api.forestApi.autoBlocksPreview as unknown as ReturnType<typeof vi.fn>;
const mockCommit = api.forestApi.autoBlocksCommit as unknown as ReturnType<typeof vi.fn>;
const mockDividePreview = api.forestApi.autoDividePreview as unknown as ReturnType<typeof vi.fn>;
const mockDivideCommit = api.forestApi.autoDivideCommit as unknown as ReturnType<typeof vi.fn>;

function piece(index: number, name: string, extra: Record<string, unknown> = {}) {
  return {
    type: 'Feature' as const,
    properties: {
      index,
      name,
      block_name: name,
      natural_name: null,
      area_hectares: 10 - index,
      ...extra,
    },
    geometry: { type: 'Polygon' as const, coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] },
  };
}

const MMU_RESPONSE = {
  ok: true,
  meta: {
    source_layer: 'base.mmu',
    basis: 'rivers & ridges',
    level: 'blocks',
    boundary_ha: 19,
    pieces_ha: 19,
    slivers_absorbed: 0,
    piece_count: 2,
    minimize_n: 1,
    adjacency_edge_count: 1,
    sliver_area_m2: 1000,
    // RS-2.9: the API reports the floor actually applied. It was a hardcoded 5
    // for every source until this row, so the fixture uses a real 0.1 ha value
    // -- with it at 5, a test could not tell a derived floor from the old lie.
    minimize_floor_ha: 0.1,
  },
  pieces: { type: 'FeatureCollection', features: [piece(1, 'Block-1'), piece(2, 'Block-2')] },
  edges: [],
};

const SLOPE_RESPONSE = {
  ok: true,
  meta: {
    ...MMU_RESPONSE.meta,
    source_layer: 'rasters.slope_regulation',
    basis: 'slope class (§15.2)',
  },
  pieces: {
    type: 'FeatureCollection',
    features: [
      piece(1, 'Block-1', { slope_band: 1, slope_band_label_en: '< 19°', slope_band_label_ne: '< १९°' }),
      piece(2, 'Block-2', { slope_band: 3, slope_band_label_en: '31–45°', slope_band_label_ne: '३१–४५°' }),
    ],
  },
  edges: [],
};

const ASPECT_RESPONSE = {
  ok: true,
  meta: {
    ...MMU_RESPONSE.meta,
    source_layer: 'rasters.aspect',
    basis: 'aspect (compass direction)',
  },
  pieces: {
    type: 'FeatureCollection',
    features: [
      piece(1, 'Block-1', { aspect_code: 1, aspect_label: 'N' }),
      piece(2, 'Block-2', { aspect_code: 5, aspect_label: 'S' }),
    ],
  },
  edges: [],
};

const CANOPY_RESPONSE = {
  ok: true,
  meta: {
    ...MMU_RESPONSE.meta,
    source_layer: 'canopy_height5m.tif',
    basis: 'canopy height structure',
  },
  pieces: {
    type: 'FeatureCollection',
    features: [
      piece(1, 'Block-1', { canopy_class: 1, canopy_class_label: 'non-forest' }),
      piece(2, 'Block-2', { canopy_class: 3, canopy_class_label: 'pole' }),
    ],
  },
  edges: [],
};

const NASA_RESPONSE = {
  ok: true,
  meta: {
    ...MMU_RESPONSE.meta,
    source_layer: 'rasters.nasa_forest_2020',
    basis: 'NASA 2020 forest quality',
  },
  pieces: {
    type: 'FeatureCollection',
    features: [
      piece(1, 'Block-1', { nasa_quality: 1, nasa_quality_label: 'Primary Forest' }),
      piece(2, 'Block-2', { nasa_quality: 3, nasa_quality_label: 'Old Secondary Forest' }),
    ],
  },
  edges: [],
};

// D41: a class-0-dominated piece is carved as geometry but is *anonymous* — the
// backend sends null for both code and label, never a stored 0.
const NASA_ANONYMOUS_RESPONSE = {
  ok: true,
  meta: { ...NASA_RESPONSE.meta },
  pieces: {
    type: 'FeatureCollection',
    features: [
      piece(1, 'Block-1', { nasa_quality: null, nasa_quality_label: null }),
      piece(2, 'Block-2', { nasa_quality: 2, nasa_quality_label: 'Young Secondary Forest' }),
    ],
  },
  edges: [],
};

beforeEach(() => {
  mockPreview.mockReset();
  mockPreview.mockResolvedValue(MMU_RESPONSE);
  mockCommit.mockReset();
  mockCommit.mockResolvedValue({ ok: true, blocks: [] });
});

describe('AutoBlockDesigner — source toggle', () => {
  it('defaults to the slope source', async () => {
    render(
      <AutoBlockDesigner
        map={null}
        calculationId="c1"
        initialLevel="blocks"
        onClose={vi.fn()}
        onCommitted={vi.fn()}
      />,
    );
    await waitFor(() =>
      expect(mockPreview).toHaveBeenCalledWith('c1', 'blocks', undefined, 50000, 'slope', true, undefined),
    );
  });

  it('switching to natural features re-fetches with source=mmu', async () => {
    mockPreview.mockImplementation((_id, _level, _n, _sliver, source) =>
      Promise.resolve(source === 'mmu' ? MMU_RESPONSE : SLOPE_RESPONSE),
    );
    render(
      <AutoBlockDesigner
        map={null}
        calculationId="c1"
        initialLevel="blocks"
        onClose={vi.fn()}
        onCommitted={vi.fn()}
      />,
    );
    await waitFor(() => expect(mockPreview).toHaveBeenCalledTimes(1));

    await userEvent.click(screen.getByLabelText(/natural features/i));

    await waitFor(() =>
      expect(mockPreview).toHaveBeenLastCalledWith('c1', 'blocks', undefined, 50000, 'mmu', true, undefined),
    );
  });

  it('shows the slope-band label instead of natural name (slope is the default source)', async () => {
    mockPreview.mockImplementation((_id, _level, _n, _sliver, source) =>
      Promise.resolve(source === 'slope' ? SLOPE_RESPONSE : MMU_RESPONSE),
    );
    render(
      <AutoBlockDesigner
        map={null}
        calculationId="c1"
        initialLevel="blocks"
        onClose={vi.fn()}
        onCommitted={vi.fn()}
      />,
    );
    await waitFor(() =>
      expect(mockPreview).toHaveBeenLastCalledWith('c1', 'blocks', undefined, 50000, 'slope', true, undefined),
    );
    expect(await screen.findByText('< 19°')).toBeInTheDocument();
    expect(screen.getByText('31–45°')).toBeInTheDocument();
  });

  it('commit carries each piece\'s dominant_slope_band through unmerged (source=slope)', async () => {
    mockPreview.mockResolvedValue(SLOPE_RESPONSE);
    render(
      <AutoBlockDesigner
        map={null}
        calculationId="c1"
        initialLevel="blocks"
        onClose={vi.fn()}
        onCommitted={vi.fn()}
      />,
    );
    await screen.findByText('< 19°'); // the default (slope) preview loaded, unmerged (N = piece count)

    await userEvent.click(screen.getByText('Create Blocks'));

    await waitFor(() => expect(mockCommit).toHaveBeenCalledTimes(1));
    const [, , blocks] = mockCommit.mock.calls[0];
    const bands = blocks.map((b: { dominant_slope_band?: number | null }) => b.dominant_slope_band);
    expect(bands.sort()).toEqual([1, 3]);
  });

  it('MMU commits never send a dominant_slope_band', async () => {
    mockPreview.mockResolvedValue(MMU_RESPONSE);
    render(
      <AutoBlockDesigner
        map={null}
        calculationId="c1"
        initialLevel="blocks"
        onClose={vi.fn()}
        onCommitted={vi.fn()}
      />,
    );
    await screen.findByText('Create Blocks');
    await waitFor(() => expect(mockPreview).toHaveBeenCalledTimes(1));
    await userEvent.click(screen.getByLabelText(/natural features/i)); // slope is the default
    await waitFor(() =>
      expect(mockPreview).toHaveBeenLastCalledWith('c1', 'blocks', undefined, 50000, 'mmu', true, undefined),
    );

    await userEvent.click(screen.getByText('Create Blocks'));

    await waitFor(() => expect(mockCommit).toHaveBeenCalledTimes(1));
    const [, , blocks] = mockCommit.mock.calls[0];
    const bands = blocks.map((b: { dominant_slope_band?: number | null }) => b.dominant_slope_band);
    expect(bands).toEqual([null, null]);
  });

  it('re-fetches with source=aspect and shows the direction label; commit carries dominant_aspect', async () => {
    mockPreview.mockImplementation((_id, _level, _n, _sliver, source) =>
      Promise.resolve(source === 'aspect' ? ASPECT_RESPONSE : MMU_RESPONSE),
    );
    render(
      <AutoBlockDesigner
        map={null}
        calculationId="c1"
        initialLevel="blocks"
        onClose={vi.fn()}
        onCommitted={vi.fn()}
      />,
    );
    await screen.findByText('Create Blocks');
    await userEvent.click(screen.getByLabelText(/aspect/i));

    await waitFor(() =>
      expect(mockPreview).toHaveBeenLastCalledWith('c1', 'blocks', undefined, 50000, 'aspect', true, undefined),
    );
    expect(await screen.findByText('N')).toBeInTheDocument();
    expect(screen.getByText('S')).toBeInTheDocument();

    await userEvent.click(screen.getByText('Create Blocks'));
    await waitFor(() => expect(mockCommit).toHaveBeenCalledTimes(1));
    const [, , blocks] = mockCommit.mock.calls[0];
    expect(
      blocks.map((b: { dominant_aspect?: number | null }) => b.dominant_aspect).sort(),
    ).toEqual([1, 5]);
    expect(
      blocks.map((b: { dominant_slope_band?: number | null }) => b.dominant_slope_band),
    ).toEqual([null, null]);
  });

  it('re-fetches with source=canopy and shows the structure-class label; commit carries dominant_canopy_class', async () => {
    mockPreview.mockImplementation((_id, _level, _n, _sliver, source) =>
      Promise.resolve(source === 'canopy' ? CANOPY_RESPONSE : MMU_RESPONSE),
    );
    render(
      <AutoBlockDesigner
        map={null}
        calculationId="c1"
        initialLevel="blocks"
        onClose={vi.fn()}
        onCommitted={vi.fn()}
      />,
    );
    await screen.findByText('Create Blocks');
    await userEvent.click(screen.getByLabelText(/canopy height structure/i));

    await waitFor(() =>
      expect(mockPreview).toHaveBeenLastCalledWith('c1', 'blocks', undefined, 50000, 'canopy', true, undefined),
    );
    expect(await screen.findByText('non-forest')).toBeInTheDocument();
    expect(screen.getByText('pole')).toBeInTheDocument();

    await userEvent.click(screen.getByText('Create Blocks'));
    await waitFor(() => expect(mockCommit).toHaveBeenCalledTimes(1));
    const [, , blocks] = mockCommit.mock.calls[0];
    expect(
      blocks.map((b: { dominant_canopy_class?: number | null }) => b.dominant_canopy_class).sort(),
    ).toEqual([1, 3]);
  });

  it('re-fetches with source=nasa_quality and commits dominant_nasa_quality', async () => {
    mockPreview.mockImplementation((_id, _level, _n, _sliver, source) =>
      Promise.resolve(source === 'nasa_quality' ? NASA_RESPONSE : MMU_RESPONSE),
    );
    render(
      <AutoBlockDesigner
        map={null}
        calculationId="c1"
        initialLevel="blocks"
        onClose={vi.fn()}
        onCommitted={vi.fn()}
      />,
    );
    await screen.findByText('Create Blocks');
    await userEvent.click(screen.getByLabelText(/NASA 2020/i));

    await waitFor(() =>
      expect(mockPreview).toHaveBeenLastCalledWith('c1', 'blocks', undefined, 50000, 'nasa_quality', true, undefined),
    );
    expect(await screen.findByText('Primary Forest')).toBeInTheDocument();
    expect(screen.getByText('Old Secondary Forest')).toBeInTheDocument();

    await userEvent.click(screen.getByText('Create Blocks'));
    await waitFor(() => expect(mockCommit).toHaveBeenCalledTimes(1));
    const [, , blocks] = mockCommit.mock.calls[0];
    expect(
      blocks.map((b: { dominant_nasa_quality?: number | null }) => b.dominant_nasa_quality).sort(),
    ).toEqual([1, 3]);
    // the sibling class columns must stay empty for a non-matching source
    for (const b of blocks) {
      expect(b.dominant_slope_band).toBeNull();
      expect(b.dominant_canopy_class).toBeNull();
    }
  });

  it('renders an anonymous NASA piece as a dash and commits null, never 0 (D41)', async () => {
    mockPreview.mockImplementation((_id, _level, _n, _sliver, source) =>
      Promise.resolve(source === 'nasa_quality' ? NASA_ANONYMOUS_RESPONSE : MMU_RESPONSE),
    );
    render(
      <AutoBlockDesigner
        map={null}
        calculationId="c1"
        initialLevel="blocks"
        onClose={vi.fn()}
        onCommitted={vi.fn()}
      />,
    );
    await screen.findByText('Create Blocks');
    await userEvent.click(screen.getByLabelText(/NASA 2020/i));

    expect(await screen.findByText('Young Secondary Forest')).toBeInTheDocument();
    // the anonymous piece shows the muted dash placeholder...
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
    // ...and must never render an invented label (the RS-2.5 "Class None" bug)
    expect(screen.queryByText(/class none/i)).not.toBeInTheDocument();
    expect(screen.queryByText('Non-forest')).not.toBeInTheDocument();

    await userEvent.click(screen.getByText('Create Blocks'));
    await waitFor(() => expect(mockCommit).toHaveBeenCalledTimes(1));
    const [, , blocks] = mockCommit.mock.calls[0];
    const codes = blocks
      .map((b: { dominant_nasa_quality?: number | null }) => b.dominant_nasa_quality)
      .sort();
    // null sorts last here; the point is that 0 is absent and null is present
    expect(codes).toContain(null);
    expect(codes).not.toContain(0);
  });

  it('RS-10.3b: union_fusion defaults to all attributes, and deselecting one re-fetches with the narrowed list', async () => {
    mockPreview.mockResolvedValue(MMU_RESPONSE);
    render(
      <AutoBlockDesigner
        map={null}
        calculationId="c1"
        initialLevel="blocks"
        onClose={vi.fn()}
        onCommitted={vi.fn()}
      />,
    );
    await screen.findByText('Create Blocks');
    await userEvent.click(screen.getByLabelText(/union \(fusion/i));

    await waitFor(() =>
      expect(mockPreview).toHaveBeenLastCalledWith(
        'c1', 'blocks', undefined, 50000, 'union_fusion', true,
        { sources: ['aspect', 'forest_type', 'nasa_quality', 'forest_health', 'landcover', 'dem'], includeCanopy: true },
      ),
    );

    // Deselect one attribute -- the next preview call must narrow the list,
    // not silently keep fusing everything.
    await userEvent.click(screen.getByLabelText(/^Aspect$/i));
    await waitFor(() =>
      expect(mockPreview).toHaveBeenLastCalledWith(
        'c1', 'blocks', undefined, 50000, 'union_fusion', true,
        { sources: ['forest_type', 'nasa_quality', 'forest_health', 'landcover', 'dem'], includeCanopy: true },
      ),
    );
  });
});

describe('AutoBlockDesigner — force-merge orphan toggle', () => {
  it('toggling the force-merge checkbox re-fetches the preview with forceAbsorbOrphans=false', async () => {
    mockPreview.mockResolvedValue(MMU_RESPONSE);
    render(
      <AutoBlockDesigner
        map={null}
        calculationId="c1"
        initialLevel="blocks"
        onClose={vi.fn()}
        onCommitted={vi.fn()}
      />,
    );
    await waitFor(() => expect(mockPreview).toHaveBeenCalledTimes(1));
    // Owner report 2026-10-01: default is now true (checkbox ticked by default).
    expect(mockPreview).toHaveBeenLastCalledWith('c1', 'blocks', undefined, 50000, 'slope', true, undefined);

    await userEvent.click(screen.getByLabelText(/force merge/i));

    await waitFor(() => expect(mockPreview).toHaveBeenCalledTimes(2));
    expect(mockPreview).toHaveBeenLastCalledWith('c1', 'blocks', undefined, 50000, 'slope', false, undefined);
  });

  it('commit forwards the min-area floor so the server can fold sub-floor parts', async () => {
    mockPreview.mockResolvedValue(MMU_RESPONSE);
    render(
      <AutoBlockDesigner
        map={null}
        calculationId="c1"
        initialLevel="blocks"
        onClose={vi.fn()}
        onCommitted={vi.fn()}
      />,
    );
    await screen.findByText('Create Blocks');
    await waitFor(() => expect(mockPreview).toHaveBeenCalledTimes(1));

    await userEvent.click(screen.getByText('Create Blocks'));

    await waitFor(() => expect(mockCommit).toHaveBeenCalledTimes(1));
    // 4th arg = sliver_area_m2 (minBlockHa default 5 ha, owner report 2026-10-01 * 10000 m²/ha)
    expect(mockCommit.mock.calls[0][3]).toBe(50000);
  });
});

describe('AutoBlockDesigner — error surfacing', () => {
  it('commit shows the bilingual detail message, not the generic axios string', async () => {
    mockCommit.mockRejectedValueOnce({
      response: { data: { detail: { code: 'invalid_geometry', message: 'Invalid geometry', message_np: 'अमान्य ज्यामिति' } } },
      message: 'Request failed with status code 400',
    });
    const onCommitted = vi.fn();
    render(
      <AutoBlockDesigner
        map={null}
        calculationId="c1"
        initialLevel="blocks"
        onClose={vi.fn()}
        onCommitted={onCommitted}
      />,
    );
    await screen.findByText('Create Blocks');
    await userEvent.click(screen.getByText('Create Blocks'));

    // The bilingual message must be shown (English in default locale)
    expect(await screen.findByText('Invalid geometry')).toBeInTheDocument();
    // The generic axios message must NOT be shown
    expect(screen.queryByText('Request failed with status code 400')).not.toBeInTheDocument();
    expect(onCommitted).not.toHaveBeenCalled();
  });
});

describe('AutoBlockDesigner — dividing ONE selected feature', () => {
  const DIVIDE_RESPONSE = {
    ...SLOPE_RESPONSE,
    meta: { ...SLOPE_RESPONSE.meta, parent_id: 'p1', parent_name: 'Block-1', child_layer: 'compartments' as const },
  };

  beforeEach(() => {
    mockDividePreview.mockReset();
    mockDividePreview.mockResolvedValue(DIVIDE_RESPONSE);
    mockDivideCommit.mockReset();
    mockDivideCommit.mockResolvedValue({ ok: true, children: ['a', 'b'], n_children: 2, child_layer: 'compartments' });
  });

  const renderDivide = () =>
    render(
      <AutoBlockDesigner
        map={null}
        calculationId="c1"
        initialLevel="compartments"
        parent={{ id: 'p1', name: 'Block-1' }}
        onClose={vi.fn()}
        onCommitted={vi.fn()}
      />,
    );

  it('previews inside the selected feature, never the whole forest', async () => {
    renderDivide();
    await waitFor(() =>
      expect(mockDividePreview).toHaveBeenCalledWith('c1', 'p1', { source: 'slope', sliverAreaM2: 50000, forceAbsorbOrphans: true }),
    );
    expect(mockPreview).not.toHaveBeenCalled();
  });

  it('names the feature being divided and hides the level choice (the parent fixes it)', async () => {
    renderDivide();
    await screen.findByText('< 19°');
    expect(screen.getByText(/Divide Block-1 by natural feature/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/^compartments$/i)).toBeNull();
  });

  it('switching the source re-fetches for the same feature', async () => {
    renderDivide();
    await waitFor(() => expect(mockDividePreview).toHaveBeenCalledTimes(1));
    await userEvent.click(screen.getByLabelText(/natural features/i));
    await waitFor(() =>
      expect(mockDividePreview).toHaveBeenLastCalledWith('c1', 'p1', { source: 'mmu', sliverAreaM2: 50000, forceAbsorbOrphans: true }),
    );
  });

  it('warns when other blocks still have no compartments (the analysis would leave them out)', async () => {
    mockDivideCommit.mockResolvedValue({ ok: true, children: ['a', 'b'], n_children: 2, child_layer: 'compartments', undivided_blocks: 2 });
    renderDivide();
    await screen.findByText('< 19°');
    await userEvent.click(screen.getByRole('button', { name: /create/i }));
    expect(await screen.findByText(/2 block\(s\) still have no compartments/i)).toBeInTheDocument();
  });

  it('commits as children of the feature — not through the whole-forest commit', async () => {
    renderDivide();
    await screen.findByText('< 19°');
    await userEvent.click(screen.getByRole('button', { name: /create/i }));

    await waitFor(() => expect(mockDivideCommit).toHaveBeenCalledTimes(1));
    const [calcId, parentId, source, blocks, sliver] = mockDivideCommit.mock.calls[0];
    expect([calcId, parentId, source, sliver]).toEqual(['c1', 'p1', 'slope', 50000]);
    expect(blocks.map((b: { dominant_slope_band?: number | null }) => b.dominant_slope_band).sort()).toEqual([1, 3]);
    expect(mockCommit).not.toHaveBeenCalled();
  });
  it('shows the floor the API reports, not a hardcoded 5 ha (RS-2.9)', async () => {
    renderDivide();
    await waitFor(() => expect(mockDividePreview).toHaveBeenCalled());
    // The fixture meta carries minimize_floor_ha: 0.1. Until RS-2.9 the label
    // interpolated a hardcoded 5 via `?? 5`, and the i18n string had no
    // {{floor}} placeholder at all, so the reported number never rendered.
    const btn = await screen.findByRole('button', { name: /minimize to smallest/i });
    expect(btn).toHaveTextContent(/0\.1/);
    expect(btn).not.toHaveTextContent(/\b5 ha/);
  });

  it('renders without inventing a floor when the API omits it (RS-2.9)', async () => {
    mockDividePreview.mockResolvedValue({
      ...MMU_RESPONSE,
      meta: { ...MMU_RESPONSE.meta, minimize_floor_ha: null },
    });
    renderDivide();
    await waitFor(() => expect(mockDividePreview).toHaveBeenCalled());
    const btn = await screen.findByRole('button', { name: /minimize to smallest/i });
    expect(btn).toBeInTheDocument();
    expect(btn).not.toHaveTextContent(/ha/);
  });

});
