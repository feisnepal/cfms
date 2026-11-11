/**
 * The link between the wizard and the map (P3): the data behind the questions, and arming / putting away the
 * drawing tool as the wizard asks WHERE — plus the machine's drawing-shape rules.
 */
import { useState } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { toCatalogueActivity } from '../../../lib/activitySearch';
import { MASTER_LIST } from './masterList.fixture';
import { drawGeomOf, initialWizard, wizardReducer } from '../wizard/wizardMachine';

vi.mock('../../../services/api', () => ({
  yearlyActivitiesApi: { listPotentialActivities: vi.fn() },
  yearlyPlanApi: { getPlan: vi.fn() },
}));

import { yearlyActivitiesApi, yearlyPlanApi, type YearlyPlanLine } from '../../../services/api';
import { useWizardHost } from '../wizard/useWizardHost';

const listActivities = (yearlyActivitiesApi as unknown as { listPotentialActivities: ReturnType<typeof vi.fn> }).listPotentialActivities;
const getPlan = (yearlyPlanApi as unknown as { getPlan: ReturnType<typeof vi.fn> }).getPlan;

const byId = (id: number) => toCatalogueActivity(MASTER_LIST.find((a) => a.id === id)!);
const POINT: GeoJSON.Geometry = { type: 'Point', coordinates: [85, 27] };

const nurseryLine = {
  id: 'L1',
  potential_activity_id: 1,
  version: 3,
  planned_years: [1, 2],
  assign_to_all_blocks: false,
} as unknown as YearlyPlanLine;

/** A host with a small stateful stand-in for the workspace store. */
function useHostWithStore() {
  const [activeLayerId, setLayer] = useState<string | null>(null);
  const [toolbarMode, setMode] = useState<string | null>('select');
  const host = useWizardHost(
    'c1',
    { activeLayerId, toolbarMode, setActiveLayer: (id) => setLayer(id), setToolbarMode: (m) => setMode(m) },
    0,
  );
  return { host, activeLayerId, toolbarMode };
}

beforeEach(() => {
  vi.clearAllMocks();
  listActivities.mockResolvedValue(MASTER_LIST);
  getPlan.mockResolvedValue({ lines: [nurseryLine], total_budget: 0 });
});

describe('the drawing shape', () => {
  it('follows the activity\'s map symbol, else an area', () => {
    expect(drawGeomOf(byId(1))).toBe('point'); // nursery
    expect(drawGeomOf(byId(12))).toBe('line'); // fire line
    expect(drawGeomOf(byId(4))).toBe('polygon'); // plantation
    expect(drawGeomOf(byId(8))).toBe('polygon'); // no map symbol
    expect(drawGeomOf(null)).toBe('polygon');
  });

  it('is set when an activity is chosen and can be changed for one with no fixed shape', () => {
    let s = wizardReducer(initialWizard(), { type: 'chooseActivity', activity: byId(12), existing: null });
    expect(s.drawGeom).toBe('line');
    s = wizardReducer(initialWizard(), { type: 'chooseActivity', activity: byId(8), existing: null });
    s = wizardReducer(s, { type: 'setDrawGeom', geom: 'point' });
    expect(s.drawGeom).toBe('point');
  });

  it('a place drawn before the activity is chosen is kept for a mappable one and dropped for the others', () => {
    const drawn = wizardReducer(initialWizard(), { type: 'addPlace', place: { geometry: POINT } });
    expect(wizardReducer(drawn, { type: 'chooseActivity', activity: byId(1), existing: null })).toMatchObject({ places: [{ geometry: POINT }], where: 'map' });
    expect(wizardReducer(drawn, { type: 'chooseActivity', activity: byId(41), existing: null }).places).toEqual([]);
  });
});

describe('useWizardHost', () => {
  it('loads nothing until the wizard opens, then the master list once and the plan each time', async () => {
    const { result } = renderHook(() => useHostWithStore());
    expect(listActivities).not.toHaveBeenCalled();
    expect(getPlan).not.toHaveBeenCalled();

    act(() => result.current.host.controller.openWizard());
    await waitFor(() => expect(result.current.host.lines).toHaveLength(1));
    expect(result.current.host.activities).toHaveLength(135);
    expect(listActivities).toHaveBeenCalledTimes(1);

    act(() => result.current.host.controller.close());
    act(() => result.current.host.controller.openWizard());
    await waitFor(() => expect(getPlan).toHaveBeenCalledTimes(2));
    expect(listActivities).toHaveBeenCalledTimes(1); // the list is kept for the session
  });

  it('arms the matching drawing tool while WHERE asks for a place, and puts it away afterwards', async () => {
    const { result } = renderHook(() => useHostWithStore());
    act(() => result.current.host.controller.openWizard());
    act(() => result.current.host.controller.dispatch({ type: 'chooseActivity', activity: byId(12), existing: null }));
    expect(result.current.toolbarMode).toBe('select'); // WHERE not answered yet: nothing armed

    act(() => result.current.host.controller.dispatch({ type: 'setWhere', where: 'map' }));
    await waitFor(() => expect(result.current.toolbarMode).toBe('draw_line'));
    expect(result.current.activeLayerId).toBe('activity_features');

    act(() => result.current.host.controller.dispatch({ type: 'setWhere', where: 'whole' }));
    await waitFor(() => expect(result.current.toolbarMode).toBe('select'));
  });

  it('a different shape arms a different tool', async () => {
    const { result } = renderHook(() => useHostWithStore());
    act(() => result.current.host.controller.openWizard());
    act(() => result.current.host.controller.dispatch({ type: 'chooseActivity', activity: byId(8), existing: null }));
    act(() => result.current.host.controller.dispatch({ type: 'setWhere', where: 'map' }));
    await waitFor(() => expect(result.current.toolbarMode).toBe('draw_polygon'));
    act(() => result.current.host.controller.dispatch({ type: 'setDrawGeom', geom: 'point' }));
    await waitFor(() => expect(result.current.toolbarMode).toBe('draw_point'));
  });

  it('does not touch the toolbar when the person armed a tool themselves', async () => {
    const { result } = renderHook(() => useHostWithStore());
    act(() => result.current.host.controller.openWizard());
    await waitFor(() => expect(result.current.host.lines).toHaveLength(1));
    expect(result.current.toolbarMode).toBe('select');
  });

  it('a place drawn while the card is closed opens it', () => {
    const { result } = renderHook(() => useHostWithStore());
    act(() => result.current.host.controller.addPlace({ geometry: POINT }));
    expect(result.current.host.controller.open).toBe(true);
    expect(result.current.host.controller.state.places).toHaveLength(1);
  });

  it('a step "show it on the map" opens the wizard at WHERE for that activity, loading what it needs first', async () => {
    const { result } = renderHook(() => useHostWithStore());
    await act(async () => {
      await result.current.host.openForStep({
        key: 'NO_LOCATION',
        text: '',
        button: '',
        action: 'show_on_map',
        activityId: 'L1',
        confirmable: false,
      });
    });
    const { controller } = result.current.host;
    expect(controller.open).toBe(true);
    expect(controller.state.step).toBe('where');
    expect(controller.state.activity?.id).toBe(1);
    expect(controller.state.existing).toMatchObject({ id: 'L1', years: [1, 2] });
  });

  it('any other step (or nothing) just opens the wizard at the first question', async () => {
    const { result } = renderHook(() => useHostWithStore());
    await act(async () => {
      await result.current.host.openForStep(null);
    });
    expect(result.current.host.controller.open).toBe(true);
    expect(result.current.host.controller.state.step).toBe('what');
  });

  it('when what it needs cannot be loaded the wizard still opens', async () => {
    getPlan.mockRejectedValue(new Error('offline'));
    const { result } = renderHook(() => useHostWithStore());
    await act(async () => {
      await result.current.host.openForStep({
        key: 'NO_LOCATION',
        text: '',
        button: '',
        action: 'show_on_map',
        activityId: 'L1',
        confirmable: false,
      });
    });
    expect(result.current.host.controller.open).toBe(true);
    expect(result.current.host.controller.state.step).toBe('what');
  });
});
