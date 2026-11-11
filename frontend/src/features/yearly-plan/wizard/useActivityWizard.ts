import { useCallback, useReducer, useState } from 'react';
import type { KindGeom } from '../../../lib/activityKinds';
import type { CatalogueActivity } from '../../../lib/activitySearch';
import {
  initialWizard,
  wizardReducer,
  type ExistingLine,
  type Place,
  type WizardState,
  type WizardStep,
  type WizardAction,
} from './wizardMachine';

export interface OpenWizardOptions {
  /** start with this activity already chosen (editing / fixing an activity of the plan) */
  activity?: CatalogueActivity;
  existing?: ExistingLine | null;
  /** and at this step, when it exists for the activity */
  step?: WizardStep;
  /** a place the person drew before saying what it is */
  place?: Place;
}

export interface WizardController {
  open: boolean;
  state: WizardState;
  dispatch: (action: WizardAction) => void;
  openWizard: (options?: OpenWizardOptions) => void;
  close: () => void;
  /** a place was drawn on the map: it joins the wizard (opening it when it is closed) */
  addPlace: (place: Place) => void;
  /** the drawing shape the map should arm right now, or null when nothing should be drawn */
  armedGeom: KindGeom | null;
  /** changes each time a place is drawn, so the map can re-arm its tool for the next one */
  drawNonce: number;
}

/**
 * Where the add-activity wizard lives: its state, whether its card is open, and what the map should do for it.
 * Kept out of the card itself so the map workspace (which arms tools and receives drawn shapes) and the card
 * (which asks the questions) share one source of truth.
 */
export function useActivityWizard(): WizardController {
  const [open, setOpen] = useState(false);
  const [state, dispatch] = useReducer(wizardReducer, undefined, initialWizard);
  const [drawNonce, setDrawNonce] = useState(0);

  const openWizard = useCallback((options: OpenWizardOptions = {}) => {
    dispatch({ type: 'restart' });
    if (options.place) dispatch({ type: 'addPlace', place: options.place });
    if (options.activity) {
      dispatch({ type: 'chooseActivity', activity: options.activity, existing: options.existing ?? null });
      if (options.step) dispatch({ type: 'goto', step: options.step });
    }
    setOpen(true);
  }, []);

  const close = useCallback(() => {
    setOpen(false);
    dispatch({ type: 'restart' });
  }, []);

  const addPlace = useCallback(
    (place: Place) => {
      if (!open) {
        dispatch({ type: 'restart' });
        setOpen(true);
      }
      dispatch({ type: 'addPlace', place });
      setDrawNonce((n) => n + 1);
    },
    [open],
  );

  const armedGeom: KindGeom | null =
    open && state.activity?.requiresMap && state.step === 'where' && state.where === 'map' ? state.drawGeom : null;

  return { open, state, dispatch, openWizard, close, addPlace, armedGeom, drawNonce };
}
