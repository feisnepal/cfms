import { useCallback, useEffect, useRef, useState } from 'react';
import type { KindGeom } from '../../../lib/activityKinds';
import { toCatalogueActivity, type CatalogueActivity, type RawPotentialActivity } from '../../../lib/activitySearch';
import { yearlyActivitiesApi, yearlyPlanApi, type YearlyPlanLine } from '../../../services/api';
import type { StepView } from '../planMessages';
import { lineToExisting } from './existing';
import { useActivityWizard, type WizardController } from './useActivityWizard';

/** The slice of the workspace store the wizard needs (kept small so the hook is testable with a plain object). */
export interface WizardStoreLike {
  activeLayerId: string | null;
  toolbarMode: string | null;
  setActiveLayer: (id: 'activity_features') => void;
  setToolbarMode: (mode: 'select' | 'draw_point' | 'draw_line' | 'draw_polygon') => void;
}

const TOOL: Record<KindGeom, 'draw_point' | 'draw_line' | 'draw_polygon'> = {
  point: 'draw_point',
  line: 'draw_line',
  polygon: 'draw_polygon',
};

export interface WizardHost {
  controller: WizardController;
  /** the master list of activities (loaded the first time the wizard opens) */
  activities: RawPotentialActivity[];
  /** the plan as it is now (re-read when the wizard opens and after every save) */
  lines: YearlyPlanLine[];
  reload: () => void;
  /** open the wizard to fix what a "next step" asks for (the activity's place, or the first activity) */
  openForStep: (step: StepView | null) => Promise<void>;
}

/**
 * Everything the map workspace needs to host the add-activity wizard: the data behind its questions, and the
 * link between the wizard and the drawing tools — while WHERE is asking for a place the matching tool is armed on
 * the map, and when the wizard moves on the tool is put away again.
 */
export function useWizardHost(calculationId: string, store: WizardStoreLike, refreshKey: number | string = 0): WizardHost {
  const controller = useActivityWizard();
  const [activities, setActivities] = useState<RawPotentialActivity[]>([]);
  const [lines, setLines] = useState<YearlyPlanLine[]>([]);
  const [tick, setTick] = useState(0);
  const loadedList = useRef(false);

  const reload = useCallback(() => setTick((n) => n + 1), []);

  // the master list: once, the first time the wizard opens
  useEffect(() => {
    if (!controller.open || loadedList.current) return;
    loadedList.current = true;
    yearlyActivitiesApi
      .listPotentialActivities({ is_active: true })
      .then((rows) => setActivities(rows as RawPotentialActivity[]))
      .catch(() => {
        loadedList.current = false; // try again the next time it opens
      });
  }, [controller.open]);

  // the plan: whenever the wizard opens, after a save, and when the map's data changes
  useEffect(() => {
    if (!controller.open) return;
    let cancelled = false;
    yearlyPlanApi
      .getPlan(calculationId)
      .then((res) => {
        if (!cancelled) setLines(res.lines);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [controller.open, calculationId, tick, refreshKey]);

  // arm the drawing tool while WHERE asks for a place; put it away when the wizard moves on
  const armedByWizard = useRef(false);
  const { armedGeom, drawNonce } = controller;
  const { activeLayerId, toolbarMode, setActiveLayer, setToolbarMode } = store;
  useEffect(() => {
    if (armedGeom) {
      armedByWizard.current = true;
      if (activeLayerId !== 'activity_features') setActiveLayer('activity_features');
      if (toolbarMode !== TOOL[armedGeom]) setToolbarMode(TOOL[armedGeom]);
    } else if (armedByWizard.current) {
      armedByWizard.current = false;
      if (toolbarMode?.startsWith('draw_')) setToolbarMode('select');
    }
    // drawNonce: re-arm after each drawn place (the shape tool ends with its shape)
  }, [armedGeom, drawNonce, activeLayerId, toolbarMode, setActiveLayer, setToolbarMode]);

  const openForStep = useCallback(
    async (step: StepView | null) => {
      if (step?.action !== 'show_on_map' || !step.activityId) {
        controller.openWizard();
        return;
      }
      // the data may not be loaded yet (the wizard has not been opened before): fetch what is missing first
      try {
        const [rows, plan] = await Promise.all([
          activities.length > 0 ? Promise.resolve(activities) : (yearlyActivitiesApi.listPotentialActivities({ is_active: true }) as Promise<RawPotentialActivity[]>),
          yearlyPlanApi.getPlan(calculationId),
        ]);
        setActivities(rows);
        loadedList.current = true;
        setLines(plan.lines);
        const line = plan.lines.find((l) => l.id === step.activityId);
        const raw = line ? rows.find((r) => Number(r.id) === line.potential_activity_id) : undefined;
        if (line && raw) {
          const activity: CatalogueActivity = toCatalogueActivity(raw);
          controller.openWizard({ activity, existing: lineToExisting(line), step: 'where' });
          return;
        }
      } catch {
        /* fall through: the wizard still opens, at the first question */
      }
      controller.openWizard();
    },
    [activities, calculationId, controller],
  );

  return { controller, activities, lines, reload, openForStep };
}
