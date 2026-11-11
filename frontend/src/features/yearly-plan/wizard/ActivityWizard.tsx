import React, { useMemo, useState } from 'react';
import { Button, message } from 'antd';
import { CloseOutlined, DownOutlined, UpOutlined } from '@ant-design/icons';
import { useT } from '../../../i18n/hooks';
import { formatNumber, parseLocaleNumber } from '../../../i18n/numberFormat';
import type { CatalogueActivity, RawPotentialActivity } from '../../../lib/activitySearch';
import { yearlyPlanApi, type YearlyPlanLine } from '../../../services/api';
import { ConfirmStep, HowMuchStep, NameStep, WhatStep, WhenStep, WhereStep } from './WizardSteps';
import type { WizardController } from './useActivityWizard';
import { lineToExisting } from './existing';
import { canAdvance, stepsFor } from './wizardMachine';
import { buildWizardPlan, runWizardPlan, type WizardApi } from './wizardSave';

interface Props {
  controller: WizardController;
  calculationId: string;
  /** the master list of activities (as the API returns it) */
  activities: RawPotentialActivity[];
  /** the plan lines as they are now (for "already in the plan" and the unusual-amount hint) */
  lines: YearlyPlanLine[];
  /** the plan changed: re-read it and the map */
  onSaved: () => void;
  /** open the yearly-plan page (numbers of an activity that is already in the plan) */
  onOpenPlan: () => void;
  /** shown inside a page or panel instead of floating over the map: fills its container, cannot be folded away */
  embedded?: boolean;
  /** false where there is no map to draw on (the yearly-plan pages): "Show it on the map" is not offered */
  canDraw?: boolean;
  /** open the map workspace, where places are drawn (offered when nothing can be drawn here) */
  onEditOnMap?: () => void;
}

const peakBudget = (line: YearlyPlanLine): number =>
  line.years.filter((y) => y.planned).reduce((max, y) => Math.max(max, y.budget), 0);

/**
 * The card on the map that walks a person through adding an activity to the yearly plan, one question at a time
 * (plan §4.4). It is a card over the map, not a dialog: while it asks WHERE, the map stays live and armed.
 */
export const ActivityWizard: React.FC<Props> = ({
  controller,
  calculationId,
  activities,
  lines,
  onSaved,
  onOpenPlan,
  embedded = false,
  canDraw = true,
  onEditOnMap,
}) => {
  const t = useT();
  const { state, dispatch } = controller;
  const [saving, setSaving] = useState(false);
  const [failedNote, setFailedNote] = useState<string | null>(null);
  const [failedPlaces, setFailedPlaces] = useState<number[] | null>(null);
  const [blocked, setBlocked] = useState<CatalogueActivity | null>(null);
  // folded to its header so the map can be drawn on without the card in the way
  const [minimized, setMinimized] = useState(false);

  const byActivity = useMemo(() => new Map(lines.map((l) => [l.potential_activity_id, l])), [lines]);
  const inPlan = useMemo(
    () => Object.fromEntries(lines.map((l) => [l.potential_activity_id, l.planned_years])) as Record<number, number[]>,
    [lines],
  );
  const othersMax = useMemo(
    () => lines.filter((l) => l.potential_activity_id !== state.activity?.id).map(peakBudget),
    [lines, state.activity],
  );

  if (!controller.open) return null;

  const steps = stepsFor(state);
  const at = steps.indexOf(state.step);
  const isLast = state.step === 'confirm';
  const canNext = canAdvance(state, parseLocaleNumber);

  const pick = (activity: CatalogueActivity) => {
    const line = byActivity.get(activity.id);
    // an activity that needs no map — or, where nothing can be drawn, any activity — that is already in the plan
    // has nothing to add here
    if (line && (!activity.requiresMap || !canDraw)) {
      setBlocked(activity);
      return;
    }
    setBlocked(null);
    dispatch({ type: 'chooseActivity', activity, existing: line ? lineToExisting(line) : null });
  };

  const api: WizardApi = {
    addLine: async (body) => (await yearlyPlanApi.addLine(calculationId, body as unknown as Record<string, unknown>)) as never,
    createFeature: async (body) =>
      (await yearlyPlanApi.createFeature(calculationId, body as unknown as Record<string, unknown>)) as never,
    updateLine: async (lineId, edit) =>
      (await yearlyPlanApi.updateLine(calculationId, lineId, {
        years: edit.years,
        expected_version: edit.expected_version,
      })) as never,
  };

  const save = async (addAnother: boolean) => {
    if (!state.activity) return;
    setSaving(true);
    setFailedNote(null);
    try {
      const plan = buildWizardPlan(state, parseLocaleNumber);
      const outcome = await runWizardPlan(plan, api, failedPlaces ?? undefined);
      if (!outcome.ok) {
        setFailedPlaces(outcome.failedPlaces.length > 0 ? outcome.failedPlaces : null);
        setFailedNote(
          outcome.failedPlaces.length > 0
            ? (t('yearlyPlan.wizard.error.somePlaces', { n: formatNumber(outcome.failedPlaces.length) }) as string)
            : (t('yearlyPlan.wizard.error.save') as string),
        );
        if (outcome.failedPlaces.length < plan.features.length || plan.features.length === 0) onSaved();
        return;
      }
      setFailedPlaces(null);
      message.success(
        state.existing && plan.features.length > 0
          ? t('yearlyPlan.wizard.done.placesSaved', { n: formatNumber(plan.features.length) })
          : t('yearlyPlan.wizard.done.saved', { activity: state.activity.name }),
      );
      onSaved();
      if (addAnother && state.activity.requiresMap && outcome.lineId) {
        dispatch({
          type: 'addAnotherPlace',
          existing: {
            id: outcome.lineId,
            version: outcome.version ?? 1,
            years: state.existing?.years.length ? state.existing.years : state.years,
            wholeForest: false,
          },
        });
      } else if (addAnother) {
        controller.openWizard();
      } else {
        controller.close();
      }
    } catch {
      // buildWizardPlan refuses an unfinished wizard; the buttons are disabled then, so this is a safety net
      setFailedNote(t('yearlyPlan.wizard.error.save') as string);
    } finally {
      setSaving(false);
    }
  };

  const renderStep = () => {
    switch (state.step) {
      case 'what':
        return <WhatStep activities={activities} inPlan={inPlan} onPick={pick} onOpenPlan={onOpenPlan} blocked={blocked} canDraw={canDraw} />;
      case 'where':
        return <WhereStep state={state} dispatch={dispatch} existing={state.existing !== null} canDraw={canDraw} onEditOnMap={onEditOnMap} />;
      case 'when':
        return <WhenStep state={state} dispatch={dispatch} />;
      case 'howMuch':
        return <HowMuchStep state={state} dispatch={dispatch} othersMax={othersMax} />;
      case 'name':
        return <NameStep state={state} dispatch={dispatch} />;
      default:
        return <ConfirmStep state={state} dispatch={dispatch} failedNote={failedNote} />;
    }
  };

  return (
    <div
      role="dialog"
      aria-label={t('yearlyPlan.wizard.title') as string}
      data-testid="activity-wizard"
      data-step={state.step}
      style={
        embedded
          ? {
              width: '100%',
              display: 'flex',
              flexDirection: 'column',
              background: '#ffffff',
              border: '1px solid #c6d8c8',
              borderLeft: '4px solid #2f7d32',
              borderRadius: 8,
            }
          : {
              position: 'absolute',
              top: 84,
              right: 12,
              zIndex: 460,
              width: 'min(360px, calc(100% - 24px))',
              maxHeight: 'calc(100% - 104px)',
              display: 'flex',
              flexDirection: 'column',
              background: '#ffffff',
              border: '1px solid #c6d8c8',
              borderLeft: '4px solid #2f7d32',
              borderRadius: 8,
              boxShadow: '0 6px 24px rgba(0,0,0,0.18)',
            }
      }
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 12px', borderBottom: '1px solid #f0f0f0' }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 600 }}>{t('yearlyPlan.wizard.title')}</div>
          {state.activity && (
            <div data-testid="wizard-progress" style={{ fontSize: 12, color: '#8c8c8c' }}>
              {t('yearlyPlan.wizard.stepOf', { n: formatNumber(at + 1), total: formatNumber(steps.length) })}
            </div>
          )}
        </div>
        {!embedded && (
        <Button
          type="text"
          icon={minimized ? <DownOutlined /> : <UpOutlined />}
          aria-label={(minimized ? t('yearlyPlan.wizard.restore') : t('yearlyPlan.wizard.minimize')) as string}
          title={(minimized ? t('yearlyPlan.wizard.restore') : t('yearlyPlan.wizard.minimize')) as string}
          aria-expanded={!minimized}
          data-testid="wizard-min"
          onClick={() => setMinimized((v) => !v)}
        />
        )}
        <Button
          type="text"
          icon={<CloseOutlined />}
          aria-label={t('yearlyPlan.wizard.close') as string}
          data-testid="wizard-close"
          onClick={controller.close}
        />
      </div>

      {!minimized && <div style={{ padding: 12, overflowY: 'auto', flex: 1 }}>{renderStep()}</div>}

      {!minimized && state.step !== 'what' && (
        <div style={{ display: 'flex', gap: 8, padding: '10px 12px', borderTop: '1px solid #f0f0f0', flexWrap: 'wrap' }}>
          <Button size="large" onClick={() => dispatch({ type: 'back' })} disabled={saving || at <= 0} data-testid="wizard-back">
            {t('yearlyPlan.wizard.back')}
          </Button>
          <div style={{ flex: 1 }} />
          {(state.step === 'where' || state.step === 'name') && (
            <Button size="large" type="text" onClick={() => dispatch({ type: 'skip' })} disabled={saving} data-testid="wizard-skip">
              {t('yearlyPlan.wizard.skip')}
            </Button>
          )}
          {isLast ? (
            <>
              {state.activity?.requiresMap && (
                <Button size="large" onClick={() => void save(true)} loading={saving} data-testid="wizard-save-add">
                  {t('yearlyPlan.wizard.saveAdd')}
                </Button>
              )}
              <Button size="large" type="primary" onClick={() => void save(false)} loading={saving} data-testid="wizard-save">
                {saving ? t('yearlyPlan.wizard.saving') : t('yearlyPlan.wizard.save')}
              </Button>
            </>
          ) : (
            <Button size="large" type="primary" onClick={() => dispatch({ type: 'next' })} disabled={!canNext} data-testid="wizard-next">
              {t('yearlyPlan.wizard.next')}
            </Button>
          )}
        </div>
      )}
    </div>
  );
};

export default ActivityWizard;
