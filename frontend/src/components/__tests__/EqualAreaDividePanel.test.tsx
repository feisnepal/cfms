import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { EqualAreaDividePanel } from '../EqualAreaDividePanel';

vi.mock('../../i18n/hooks', () => ({ useT: () => (k: string) => k }));

const dividePreview = vi.fn();
const divideEqualAreas = vi.fn();
vi.mock('../../services/api', () => ({
  forestApi: {
    dividePreview: (...a: unknown[]) => dividePreview(...a),
    divideEqualAreas: (...a: unknown[]) => divideEqualAreas(...a),
  },
}));

const layerFetch = vi.fn((_id?: string): Promise<unknown[]> => Promise.resolve([]));
vi.mock('../../lib/layerRegistry', () => ({
  getLayerConfig: () => ({ dataSource: { fetch: (id?: string) => layerFetch(id) } }),
}));

const STRUCTURED_DETAIL = {
  code: 'compartments.division_once_only',
  message: 'This area already has sub-divisions. Delete them first or select a different area.',
  message_np: 'यो क्षेत्रमा पहिले नै उप-विभाजनहरू छन्।',
};

describe('EqualAreaDividePanel — structured backend errors (compartment divide)', () => {
  beforeEach(() => {
    dividePreview.mockReset();
    divideEqualAreas.mockReset();
    layerFetch.mockReset();
    layerFetch.mockResolvedValue([]);
  });

  it('shows the real reason (not the generic axios message) when preview fails', async () => {
    dividePreview.mockRejectedValueOnce({
      message: 'Request failed with status code 400',
      response: { data: { detail: STRUCTURED_DETAIL } },
    });
    render(
      <EqualAreaDividePanel
        map={null}
        calculationId="c1"
        layerType="compartments"
        featureId="b1"
        onClose={vi.fn()}
        onCommitted={vi.fn()}
      />,
    );
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(STRUCTURED_DETAIL.message));
    expect(screen.queryByText('Request failed with status code 400')).not.toBeInTheDocument();
  });
});

// A ~90 ha + ~10 ha two-island block (rough degree boxes near Kathmandu).
const bigRing = [[[85.30, 27.70], [85.33, 27.70], [85.33, 27.73], [85.30, 27.73], [85.30, 27.70]]];
const smallRing = [[[85.40, 27.70], [85.41, 27.70], [85.41, 27.71], [85.40, 27.71], [85.40, 27.70]]];
const MULTI_BLOCK = {
  type: 'Feature',
  properties: { id: 'mirror-1', name: 'Block 1' },
  geometry: { type: 'MultiPolygon', coordinates: [bigRing, smallRing] },
};
const SINGLE_BLOCK = {
  type: 'Feature',
  properties: { id: 'b1', name: 'Block 1' },
  geometry: { type: 'Polygon', coordinates: bigRing },
};
// ~2.2 ha single polygon — small enough that a 0.5 ha piece is NOT also a
// "too many pieces" case (est = ceil(2.2/0.5) = 5 ≤ 20).
const SMALL_BLOCK = {
  type: 'Feature',
  properties: { id: 'b2', name: 'Small block' },
  geometry: {
    type: 'Polygon',
    coordinates: [[[85.300, 27.700], [85.301, 27.700], [85.301, 27.702], [85.300, 27.702], [85.300, 27.700]]],
  },
};

describe('EqualAreaDividePanel — multi-island (MultiPolygon parent)', () => {
  beforeEach(() => {
    dividePreview.mockReset();
    divideEqualAreas.mockReset();
    layerFetch.mockReset();
    layerFetch.mockResolvedValue([MULTI_BLOCK]);
    dividePreview.mockResolvedValue({
      success: true,
      pieces: [
        { geometry: { type: 'Polygon', coordinates: bigRing }, name: 'C1', area_hectares: 10, area_sqm: 1e5, index: 1 },
        { geometry: { type: 'Polygon', coordinates: smallRing }, name: 'C2', area_hectares: 10, area_sqm: 1e5, index: 2 },
      ],
      warnings: [],
      total_pieces: 5,
      parent_id: 'mirror-1',
      islands: [
        { index: 0, area_ha: 90, suggested_count: 9, avg_piece_ha: 10, undersized: false },
        { index: 1, area_ha: 10, suggested_count: 1, avg_piece_ha: 10, undersized: false },
      ],
      target_area_ha: 10,
      n_effective: 10,
    });
    divideEqualAreas.mockResolvedValue({
      success: true, parent_id: 'mirror-1', children: ['a', 'b'],
      split_history_id: 'h', trees_reassigned: 0, warnings: [], n_children: 2,
      boundary_pieces_stored_as: 'compartments',
    });
  });

  const renderPanel = (onCommitted = vi.fn(), onClose = vi.fn()) =>
    render(
      <EqualAreaDividePanel
        map={null}
        calculationId="c1"
        layerType="compartments"
        featureId="mirror-1"
        onClose={onClose}
        onCommitted={onCommitted}
      />,
    );

  const islandInputs = async () => {
    await screen.findByTestId('divide-island-table');
    await waitFor(() =>
      expect(document.querySelectorAll('.divide-island-count').length).toBe(2),
    );
    return Array.from(
      document.querySelectorAll('.divide-island-count'),
    ) as HTMLInputElement[];
  };

  it('renders the per-island table with one row per part', async () => {
    renderPanel();
    await islandInputs();
    expect(
      screen.getByTestId('divide-island-table').querySelectorAll('tbody tr'),
    ).toHaveLength(2);
    expect(screen.getByTestId('divide-island-note')).toBeInTheDocument();
  });

  it('editing an island count updates the running total', async () => {
    renderPanel();
    const inputs = await islandInputs();
    fireEvent.change(inputs[0], { target: { value: '5' } });
    fireEvent.change(inputs[1], { target: { value: '2' } });
    await waitFor(() =>
      expect(screen.getByTestId('divide-island-table').querySelector('tfoot')?.textContent).toContain('7'),
    );
  });

  it('commit sends island_counts to the backend', async () => {
    renderPanel();
    const inputs = await islandInputs();
    fireEvent.change(inputs[0], { target: { value: '4' } });
    fireEvent.change(inputs[1], { target: { value: '1' } });

    const divideBtn = screen.getByRole('button', { name: 'editing.divide.divide' });
    await waitFor(() => expect(divideBtn).not.toBeDisabled());
    fireEvent.click(divideBtn);

    await waitFor(() => expect(divideEqualAreas).toHaveBeenCalled());
    const calls = divideEqualAreas.mock.calls;
    const req = calls[calls.length - 1]?.[1];
    expect(req.island_counts).toEqual([4, 1]);
    expect(req.count).toBe(5);
  });
});

const PREVIEW_OK = {
  success: true,
  pieces: [
    { geometry: { type: 'Polygon', coordinates: bigRing }, name: 'C1', area_hectares: 10, area_sqm: 1e5, index: 1 },
  ],
  warnings: [],
  total_pieces: 5,
  parent_id: 'b1',
  islands: [],
  target_area_ha: 10,
  n_effective: 5,
};

describe('EqualAreaDividePanel — 20-piece cap + by-area mode (single-polygon parent)', () => {
  beforeEach(() => {
    dividePreview.mockReset();
    divideEqualAreas.mockReset();
    layerFetch.mockReset();
    layerFetch.mockResolvedValue([SINGLE_BLOCK]);
    dividePreview.mockResolvedValue(PREVIEW_OK);
    divideEqualAreas.mockResolvedValue({
      success: true, parent_id: 'b1', children: ['a'],
      split_history_id: 'h', trees_reassigned: 0, warnings: [], n_children: 2,
      boundary_pieces_stored_as: 'compartments',
    });
  });

  const renderPanel = () =>
    render(
      <EqualAreaDividePanel
        map={null}
        calculationId="c1"
        layerType="compartments"
        featureId="b1"
        onClose={vi.fn()}
        onCommitted={vi.fn()}
      />,
    );

  const countInput = async () => {
    const input = (await screen.findByDisplayValue('8')) as HTMLInputElement;
    return input;
  };

  it('clamps the strips count at MAX_DIVIDE_PIECES and shows the max hint', async () => {
    renderPanel();
    const input = await countInput();
    fireEvent.change(input, { target: { value: '999' } });
    await waitFor(() => expect(dividePreview).toHaveBeenCalled());
    const calls = dividePreview.mock.calls;
    const req = calls[calls.length - 1]?.[1];
    expect(req.count).toBe(20);
    expect(screen.getByText('editing.divide.maxPiecesHint')).toBeInTheDocument();
  });

  it('count input is a native number spinner (mouse/keyboard arrows) bounded to 2..20', async () => {
    renderPanel();
    const input = (await countInput()) as HTMLInputElement & { type: string };
    expect(input.type).toBe('number');
    expect(input.step).toBe('1');
    expect(input.min).toBe('2');
    expect(input.max).toBe('20');
  });

  it("does not let a grid's rows × cols exceed MAX_DIVIDE_PIECES", async () => {
    renderPanel();
    fireEvent.click(screen.getByText('editing.divide.methodGrid'));
    const rows = (await screen.findByLabelText('editing.divide.rows')) as HTMLInputElement;
    const cols = screen.getByLabelText('editing.divide.cols') as HTMLInputElement;
    // rows 15 → cols must shrink to floor(20/15) = 1
    fireEvent.change(rows, { target: { value: '15' } });
    await waitFor(() => expect((cols as HTMLInputElement).value).toBe('1'));
    // cols 8 → rows must shrink to floor(20/8) = 2
    fireEvent.change(cols, { target: { value: '8' } });
    await waitFor(() => expect((rows as HTMLInputElement).value).toBe('2'));
  });

  it('by-area mode: warns when the piece area would produce more than 20 pieces', async () => {
    renderPanel();
    // wait for the initial count-mode preview so the parent fetch has resolved
    await waitFor(() => expect(dividePreview).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByText('editing.divide.modeArea'));
    // default 1 ha on a ~983 ha parent → ~983 pieces → local rejection, no API call
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('editing.divide.errPieceAreaTooMany'),
    );
    expect(dividePreview.mock.calls.length).toBe(1);
  });

  it('by-area mode: keeps partial decimal input alive so "1.5" can be typed', async () => {
    renderPanel();
    await waitFor(() => expect(dividePreview).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByText('editing.divide.modeArea'));
    const input = () => document.querySelector('#divide-piece-area') as HTMLInputElement;
    expect(input().value).toBe('1');
    // "1." must survive the keystroke — a number-backed input re-parses it to 1
    // and the trailing dot (and everything after it) is lost.
    fireEvent.change(input(), { target: { value: '1.' } });
    expect(input().value).toBe('1.');
    fireEvent.change(input(), { target: { value: '1.5' } });
    expect(input().value).toBe('1.5');
  });

  it('by-area mode: rejects a piece area under 1 ha locally', async () => {
    layerFetch.mockResolvedValue([SMALL_BLOCK]);
    renderPanel();
    await waitFor(() => expect(dividePreview).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByText('editing.divide.modeArea'));
    // 1 ha on the ~2.2 ha parent is still valid → a second (legit) preview runs
    await waitFor(() => expect(dividePreview).toHaveBeenCalledTimes(2));
    const callsAfterSwitch = dividePreview.mock.calls.length;
    const areaInput = document.querySelector('#divide-piece-area') as HTMLInputElement;
    fireEvent.change(areaInput, { target: { value: '0.5' } });
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('editing.divide.errPieceAreaTooSmall'),
    );
    // the invalid value is rejected locally — no additional API call
    expect(dividePreview.mock.calls.length).toBe(callsAfterSwitch);
  });

  it('by-area mode: hides the piece-count input (mutually exclusive with the area input)', async () => {
    renderPanel();
    // default count mode → the count input is present
    expect((await countInput()).value).toBe('8');
    await waitFor(() => expect(dividePreview).toHaveBeenCalledTimes(1));
    // switch to by-area → the count input must disappear, only the area input stays
    fireEvent.click(screen.getByText('editing.divide.modeArea'));
    await waitFor(() => expect(document.querySelector('#divide-piece-area')).toBeInTheDocument());
    expect(document.querySelector('#divide-count')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('editing.divide.pieceCount')).not.toBeInTheDocument();
    // switching back restores the count input
    fireEvent.click(screen.getByText('editing.divide.modeCount'));
    await waitFor(() => expect(document.querySelector('#divide-count')).toBeInTheDocument());
    expect(document.querySelector('#divide-piece-area')).not.toBeInTheDocument();
  });

  it('by-area mode: +/- buttons and arrow keys nudge the area by 0.1 ha', async () => {
    renderPanel();
    await waitFor(() => expect(dividePreview).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByText('editing.divide.modeArea'));
    const input = () => document.querySelector('#divide-piece-area') as HTMLInputElement;
    await waitFor(() => expect(input()).toBeInTheDocument());

    // + button: 1 → 1.1 (0.1 step)
    fireEvent.click(screen.getByLabelText('editing.divide.stepUp'));
    expect(input().value).toBe('1.1');
    // ArrowDown: 1.1 → 1
    fireEvent.keyDown(input(), { key: 'ArrowDown' });
    expect(input().value).toBe('1');
    // ArrowUp with Shift: 10× step → 1 + 1 = 2
    fireEvent.keyDown(input(), { key: 'ArrowUp', shiftKey: true });
    expect(input().value).toBe('2');
    // Shift+ArrowDown: → 2 − 1 = 1; then the down button is disabled at 1
    fireEvent.keyDown(input(), { key: 'ArrowDown', shiftKey: true });
    expect(input().value).toBe('1');
    expect((screen.getByLabelText('editing.divide.stepDown') as HTMLButtonElement).disabled).toBe(true);
  });

  it('by-area mode: sends target_area_sqm on preview and commit', async () => {
    renderPanel();
    await waitFor(() => expect(dividePreview).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByText('editing.divide.modeArea'));
    const areaInput = document.querySelector('#divide-piece-area') as HTMLInputElement;
    fireEvent.change(areaInput, { target: { value: '200' } });

    await waitFor(() => expect(dividePreview).toHaveBeenCalledTimes(2));
    const previewReq = dividePreview.mock.calls[1]?.[1];
    expect(previewReq.target_area_sqm).toBe(200 * 10000); // 200 ha → 2,000,000 m²
    expect(previewReq.method).toBe('strips');
    expect(previewReq.count).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'editing.divide.divide' }));
    await waitFor(() => expect(divideEqualAreas).toHaveBeenCalled());
    const calls = divideEqualAreas.mock.calls;
    const req = calls[calls.length - 1]?.[1];
    expect(req.target_area_sqm).toBe(200 * 10000);
  });
});
