import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Button, Drawer, Tabs, message } from 'antd';
import { useT } from '../../i18n/hooks';
import type { CatalogueActivity, RawPotentialActivity } from '../../lib/activitySearch';
import { yearlyActivitiesApi, yearlyPlanApi, type YearlyPlanLine } from '../../services/api';
import { ActivityPicker } from './ActivityPicker';
import { PlanTable } from './PlanTable';
import { ActivityWizard } from './wizard/ActivityWizard';
import { useActivityWizard } from './wizard/useActivityWizard';

interface Props {
  calculationId: string;
  /** bumped by the host to make the plan re-read (something else changed it) */
  refreshKey?: number | string;
  /** the plan was changed from here: the host re-reads what else shows it */
  onPlanChanged?: () => void;
  /** open the map workspace of the forest, where places are drawn */
  onEditOnMap?: () => void;
  /** a mappable line's location and drawn places (what the host offers for them) */
  onOpenDetails?: (line: YearlyPlanLine) => void;
  /** buttons after "Add activity" (the export menu) */
  toolbarExtra?: React.ReactNode;
  /** the host changes this number to open the add-activity questions (the guidance card's "add your first activity") */
  addSignal?: number;
  /** the Yearly Activities step: the table is a typed-into grid (see PlanTable) */
  gridMode?: boolean;
  /** a row's Draw button (grid mode): take the user to the map to draw that line's place */
  onDrawOnMap?: (line: YearlyPlanLine) => void;
}

/**
 * The yearly plan on the yearly-activities pages (plan §4.9, P5): one panel with two tabs — **Your plan**, the
 * editable table of what is planned (it opens here, D20), and **Browse all activities**, the finder — and the
 * add-activity questions in a side panel. The same components as the map: numbers save at once with a version
 * check and Undo. There is no "Save All" and nothing to lose by leaving.
 *
 * There is no map on these pages to draw on, so a place is drawn later in the map workspace ("Edit on map").
 */
export const PlanHome: React.FC<Props> = ({ calculationId, refreshKey = 0, onPlanChanged, onEditOnMap, onOpenDetails, toolbarExtra, addSignal = 0, gridMode = false, onDrawOnMap }) => {
  const t = useT();
  const controller = useActivityWizard();
  const [tab, setTab] = useState<'plan' | 'browse'>('plan');
  const [activities, setActivities] = useState<RawPotentialActivity[]>([]);
  const [lines, setLines] = useState<YearlyPlanLine[]>([]);
  const [tick, setTick] = useState(0);
  const [findFailed, setFindFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    yearlyActivitiesApi
      .listPotentialActivities({ is_active: true })
      .then((rows) => {
        if (!cancelled) setActivities(rows as RawPotentialActivity[]);
      })
      .catch(() => {
        if (!cancelled) setFindFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
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
  }, [calculationId, refreshKey, tick]);

  // The finder gets a NEW object only when the plan's contents change — a background re-read (window focus, another
  // edit) that finds the same plan must not reset the result someone is moving through with the arrow keys.
  const inPlanKey = lines.map((l) => `${l.potential_activity_id}:${l.planned_years.join('.')}`).join('|');
  const inPlan = useMemo(
    () => Object.fromEntries(lines.map((l) => [l.potential_activity_id, l.planned_years])) as Record<number, number[]>,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [inPlanKey],
  );

  // the host asked for the questions (never on the first render: a signal of 0 means "not asked")
  useEffect(() => {
    if (addSignal > 0) {
      setTab('plan');
      controller.openWizard();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [addSignal]);

  const changed = useCallback(() => {
    setTick((n) => n + 1);
    onPlanChanged?.();
  }, [onPlanChanged]);

  const startWizard = (activity?: CatalogueActivity) => {
    if (activity && lines.some((l) => l.potential_activity_id === activity.id)) {
      // already in the plan: nothing to add — its numbers are in the table
      message.info(t('yearlyPlan.wizard.what.inPlanBodyHere', { activity: activity.name }));
      setTab('plan');
      return;
    }
    controller.openWizard(activity ? { activity, existing: null } : undefined);
  };

  return (
    <div data-testid="plan-home">
      <Tabs
        activeKey={tab}
        onChange={(k) => setTab(k as 'plan' | 'browse')}
        items={[
          {
            key: 'plan',
            label: t('yearlyPlan.home.tabPlan'),
            children: (
              <div style={{ display: 'flex', flexDirection: 'column', minHeight: 320 }}>
                <PlanTable
                  calculationId={calculationId}
                  refreshKey={`${refreshKey}:${tick}`}
                  onAddActivity={() => startWizard()}
                  onPlanChanged={changed}
                  onOpenDetails={onOpenDetails}
                  noExpand
                  activities={activities}
                  gridMode={gridMode}
                  onDrawOnMap={onDrawOnMap}
                  extraToolbar={
                    <>
                      {toolbarExtra}
                      {onEditOnMap && (
                        <Button size="small" onClick={onEditOnMap} title={t('yearlyPlan.home.editOnMapTitle') as string} data-testid="plan-home-edit-on-map">
                          {t('yearlyPlan.home.editOnMap')}
                        </Button>
                      )}
                    </>
                  }
                />
              </div>
            ),
          },
          {
            key: 'browse',
            label: t('yearlyPlan.home.tabBrowse'),
            children: (
              <div className="activity-picker-wrap" data-testid="plan-home-browse">
                <ActivityPicker
                  activities={activities}
                  inPlan={inPlan}
                  onChoose={startWizard}
                  onOpen={() => setTab('plan')}
                  failed={findFailed}
                  loading={activities.length === 0 && !findFailed}
                />
              </div>
            ),
          },
        ]}
      />

      <Drawer
        open={controller.open}
        onClose={controller.close}
        placement="right"
        width="min(520px, 100vw)"
        title={t('yearlyPlan.home.wizardTitle') as string}
        destroyOnHidden
        styles={{ body: { padding: 12 } }}
      >
        <ActivityWizard
          embedded
          canDraw={false}
          controller={controller}
          calculationId={calculationId}
          activities={activities}
          lines={lines}
          onSaved={() => {
            changed();
            setTab('plan');
          }}
          onOpenPlan={() => {
            controller.close();
            setTab('plan');
          }}
          onEditOnMap={onEditOnMap}
        />
      </Drawer>
    </div>
  );
};

export default PlanHome;
