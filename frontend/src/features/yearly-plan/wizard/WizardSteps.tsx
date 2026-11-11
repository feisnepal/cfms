import React, { useEffect, useMemo } from 'react';
import { Alert, Button, Input, Radio, Space, Typography } from 'antd';
import { DeleteOutlined } from '@ant-design/icons';
import { useT } from '../../../i18n/hooks';
import { formatNumber, parseLocaleNumber } from '../../../i18n/numberFormat';
import { formatYears } from '../../../lib/activityFeatureLabel';
import type { CatalogueActivity, RawPotentialActivity } from '../../../lib/activitySearch';
import { ActivityPicker } from '../ActivityPicker';
import { unitSlug } from '../activityCatalogue';
import { PLAN_YEARS, howMuchValid, yearsOfPreset, type WizardAction, type WizardState, type YearPreset } from './wizardMachine';
import { isUnusualAmount, measurePlaces, measuredText, peakBudgetOf, totalBudgetOf, yearAmounts } from './wizardNumbers';

const { Text } = Typography;

interface StepProps {
  state: WizardState;
  dispatch: (action: WizardAction) => void;
}

/** One question, one line of help, and the answer area. */
export const StepFrame: React.FC<{ question: string; help?: string; children: React.ReactNode; testId: string }> = ({
  question,
  help,
  children,
  testId,
}) => (
  <div data-testid={testId}>
    <div style={{ fontSize: 17, fontWeight: 600, lineHeight: 1.4, marginBottom: 4 }}>{question}</div>
    {help && <div style={{ color: '#595959', fontSize: 13, marginBottom: 12 }}>{help}</div>}
    {children}
  </div>
);

// ------------------------------------------------------------------------------------------------ WHAT
interface WhatProps {
  activities: RawPotentialActivity[];
  /** master-list id → the plan years it is planned in */
  inPlan: Record<number, number[]>;
  onPick: (activity: CatalogueActivity) => void;
  onOpenPlan: () => void;
  /** an activity that is in the plan and needs no map: nothing to add here */
  blocked: CatalogueActivity | null;
  /** false where there is no map to draw on (the yearly-plan pages): an activity already in the plan has nothing to add */
  canDraw?: boolean;
}

export const WhatStep: React.FC<WhatProps> = ({ activities, inPlan, onPick, onOpenPlan, blocked, canDraw = true }) => {
  const t = useT();
  return (
    <StepFrame testId="wizard-what" question={t('yearlyPlan.wizard.what.question')} help={t('yearlyPlan.wizard.what.help')}>
      {blocked && (
        <Alert
          data-testid="wizard-in-plan"
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message={t('yearlyPlan.wizard.what.inPlanTitle')}
          description={t(canDraw ? 'yearlyPlan.wizard.what.inPlanBody' : 'yearlyPlan.wizard.what.inPlanBodyHere', { activity: blocked.name })}
          action={
            <Button size="small" onClick={onOpenPlan}>
              {t(canDraw ? 'yearlyPlan.wizard.what.inPlanOpen' : 'yearlyPlan.wizard.what.inPlanShow')}
            </Button>
          }
        />
      )}
      <ActivityPicker activities={activities} inPlan={inPlan} onChoose={onPick} onOpen={onPick} />
    </StepFrame>
  );
};

// ----------------------------------------------------------------------------------------------- WHERE
const SHAPE_KEY: Record<string, string> = { Point: 'shapePoint', LineString: 'shapeLine', Polygon: 'shapePolygon' };

interface WhereProps extends StepProps {
  /** the activity is already in the plan: "decide later" would add nothing */
  existing: boolean;
  /** false where there is no map to draw on (the yearly-plan pages): the place is drawn later, in the map workspace */
  canDraw?: boolean;
  /** open the map workspace (offered next to the answers when nothing can be drawn here) */
  onEditOnMap?: () => void;
}

export const WhereStep: React.FC<WhereProps> = ({ state, dispatch, existing, canDraw = true, onEditOnMap }) => {
  const t = useT();
  const activity = state.activity as CatalogueActivity;
  const fixedShape = Boolean(activity.mapKind);
  const options: Array<{ value: 'map' | 'whole' | 'later'; label: string }> = [
    ...(canDraw ? [{ value: 'map' as const, label: t('yearlyPlan.wizard.where.map') as string }] : []),
    { value: 'whole', label: t('yearlyPlan.wizard.where.whole') },
    ...(existing ? [] : [{ value: 'later' as const, label: t('yearlyPlan.wizard.where.later') }]),
  ];
  const helpKey = state.drawGeom === 'point' ? 'helpPoint' : state.drawGeom === 'line' ? 'helpLine' : 'helpPolygon';
  return (
    <StepFrame testId="wizard-where" question={t('yearlyPlan.wizard.where.question')} help={t('yearlyPlan.wizard.where.help')}>
      <Radio.Group
        value={state.where}
        onChange={(e) => dispatch({ type: 'setWhere', where: e.target.value })}
        style={{ display: 'flex', flexDirection: 'column', gap: 8 }}
      >
        {options.map((o) => (
          <Radio.Button
            key={o.value}
            value={o.value}
            data-testid={`where-${o.value}`}
            style={{ height: 'auto', minHeight: 44, padding: '10px 14px', whiteSpace: 'normal', lineHeight: 1.4 }}
          >
            {o.label}
          </Radio.Button>
        ))}
      </Radio.Group>

      {!canDraw && (
        <div style={{ marginTop: 12 }} data-testid="wizard-no-draw">
          <Text type="secondary" style={{ fontSize: 12 }}>
            {t('yearlyPlan.wizard.where.noDrawHere')}
          </Text>
          {onEditOnMap && (
            <div>
              <Button type="link" size="small" onClick={onEditOnMap} style={{ padding: 0 }} data-testid="wizard-edit-on-map">
                {t('yearlyPlan.home.editOnMap')}
              </Button>
            </div>
          )}
        </div>
      )}

      {state.where === 'map' && (
        <div style={{ marginTop: 14 }} data-testid="wizard-draw">
          {!fixedShape && (
            <div style={{ marginBottom: 10 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {t('yearlyPlan.wizard.where.shape')}
              </Text>
              <div>
                <Radio.Group
                  size="small"
                  value={state.drawGeom}
                  onChange={(e) => dispatch({ type: 'setDrawGeom', geom: e.target.value })}
                >
                  <Radio.Button value="point" data-testid="shape-point">
                    {t('yearlyPlan.wizard.where.shapePoint')}
                  </Radio.Button>
                  <Radio.Button value="line" data-testid="shape-line">
                    {t('yearlyPlan.wizard.where.shapeLine')}
                  </Radio.Button>
                  <Radio.Button value="polygon" data-testid="shape-polygon">
                    {t('yearlyPlan.wizard.where.shapePolygon')}
                  </Radio.Button>
                </Radio.Group>
              </div>
            </div>
          )}
          <Alert type="info" showIcon message={t('yearlyPlan.wizard.where.drawing')} description={t(`yearlyPlan.wizard.where.${helpKey}`)} />
          <div style={{ marginTop: 10 }} data-testid="wizard-places">
            <Text strong>
              {state.places.length > 0
                ? t('yearlyPlan.wizard.where.drawn', { n: formatNumber(state.places.length) })
                : t('yearlyPlan.wizard.where.noneYet')}
            </Text>
            {state.places.map((place, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
                <span style={{ flex: 1 }}>
                  {formatNumber(i + 1)} · {t(`yearlyPlan.wizard.where.${SHAPE_KEY[place.geometry.type] ?? 'shapePolygon'}`)}
                </span>
                <Button
                  size="small"
                  type="text"
                  icon={<DeleteOutlined />}
                  aria-label={t('yearlyPlan.wizard.where.removePlace', { n: formatNumber(i + 1) }) as string}
                  data-testid={`remove-place-${i}`}
                  onClick={() => dispatch({ type: 'removePlace', index: i })}
                />
              </div>
            ))}
          </div>
        </div>
      )}
    </StepFrame>
  );
};

// ------------------------------------------------------------------------------------------------ WHEN
export const WhenStep: React.FC<StepProps> = ({ state, dispatch }) => {
  const t = useT();
  const toggle = (y: number) =>
    dispatch({
      type: 'setYears',
      years: state.years.includes(y) ? state.years.filter((x) => x !== y) : [...state.years, y],
    });
  const presets: Array<[YearPreset, string]> = [
    ['this', t('yearlyPlan.wizard.when.presetThis')],
    ['first5', t('yearlyPlan.wizard.when.presetFirst5')],
    ['every', t('yearlyPlan.wizard.when.presetEvery')],
  ];
  return (
    <StepFrame testId="wizard-when" question={t('yearlyPlan.wizard.when.question')} help={t('yearlyPlan.wizard.when.help')}>
      <Space wrap style={{ marginBottom: 10 }}>
        {presets.map(([preset, label]) => (
          <Button key={preset} data-testid={`preset-${preset}`} onClick={() => dispatch({ type: 'setYears', years: yearsOfPreset(preset) })}>
            {label}
          </Button>
        ))}
      </Space>
      <div role="group" aria-label={t('yearlyPlan.wizard.when.question') as string} style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        {PLAN_YEARS.map((y) => {
          const on = state.years.includes(y);
          return (
            <button
              key={y}
              type="button"
              aria-pressed={on}
              aria-label={t('yearlyPlan.table.yearLabel', { n: formatNumber(y) }) as string}
              data-testid={`when-year-${y}`}
              onClick={() => toggle(y)}
              style={{
                minWidth: 48,
                minHeight: 44,
                borderRadius: 22,
                border: `1px solid ${on ? '#1677ff' : '#d9d9d9'}`,
                background: on ? '#e6f4ff' : '#fff',
                color: on ? '#0958d9' : 'inherit',
                fontWeight: on ? 600 : 400,
                cursor: 'pointer',
                fontSize: 15,
              }}
            >
              {formatNumber(y)}
            </button>
          );
        })}
      </div>
    </StepFrame>
  );
};

// -------------------------------------------------------------------------------------------- HOW MUCH
interface HowMuchProps extends StepProps {
  /** each OTHER plan line's largest yearly budget, for the "unusual amount" hint */
  othersMax: number[];
}

const parse = parseLocaleNumber;

export const HowMuchStep: React.FC<HowMuchProps> = ({ state, dispatch, othersMax }) => {
  const t = useT();
  const activity = state.activity as CatalogueActivity;
  const unit = activity.unit;
  const slug = unitSlug(unit);
  const measured = useMemo(() => measurePlaces(state.places, unit), [state.places, unit]);
  const measuredKind = measured !== null && slug !== null;

  // pre-fill the quantity from the drawing, once, when the person has not typed one
  useEffect(() => {
    if (measured !== null && state.quantity === '') dispatch({ type: 'setNumbers', quantity: measuredText(measured) });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [measured]);

  const amounts = yearAmounts(state, parse);
  const total = totalBudgetOf(amounts);
  const peak = peakBudgetOf(amounts);
  const valid = howMuchValid(state, parse);
  const touched = state.quantity !== '' || state.budget !== '' || Object.keys(state.yearValues).length > 0;
  const anyZeroBudget = amounts.some((a) => a.budget === 0) && state.budget !== '';
  const unusual = valid && isUnusualAmount(peak, othersMax);

  const quantityLabel = unit ? t('yearlyPlan.wizard.howMuch.quantity', { unit }) : t('yearlyPlan.wizard.howMuch.quantityUnitless');

  return (
    <StepFrame testId="wizard-howmuch" question={t('yearlyPlan.wizard.howMuch.question')} help={t('yearlyPlan.wizard.howMuch.help')}>
      <Radio.Group
        value={state.same ? 'same' : 'different'}
        onChange={(e) => dispatch({ type: 'setSame', same: e.target.value === 'same' })}
        style={{ marginBottom: 12 }}
      >
        <Radio.Button value="same" data-testid="numbers-same">
          {t('yearlyPlan.wizard.howMuch.same')}
        </Radio.Button>
        <Radio.Button value="different" data-testid="numbers-different">
          {t('yearlyPlan.wizard.howMuch.different')}
        </Radio.Button>
      </Radio.Group>

      {state.same ? (
        <div style={{ display: 'grid', gap: 10 }}>
          <label>
            <div style={{ fontSize: 13, marginBottom: 2 }}>{quantityLabel}</div>
            <Input
              size="large"
              inputMode="decimal"
              data-testid="numbers-quantity"
              value={state.quantity}
              onChange={(e) => dispatch({ type: 'setNumbers', quantity: e.target.value })}
            />
          </label>
          {measuredKind && (
            <div data-testid="numbers-measured" style={{ fontSize: 13, color: '#595959' }}>
              {t('yearlyPlan.wizard.howMuch.measured', { value: measuredText(measured as number), unit })}{' '}
              <Button size="small" type="link" onClick={() => dispatch({ type: 'setNumbers', quantity: measuredText(measured as number) })}>
                {t('yearlyPlan.wizard.howMuch.useMeasured')}
              </Button>
            </div>
          )}
          <label>
            <div style={{ fontSize: 13, marginBottom: 2 }}>{t('yearlyPlan.wizard.howMuch.budget')}</div>
            <Input
              size="large"
              inputMode="decimal"
              prefix="NPR"
              data-testid="numbers-budget"
              value={state.budget}
              onChange={(e) => dispatch({ type: 'setNumbers', budget: e.target.value })}
            />
          </label>
        </div>
      ) : (
        <div data-testid="numbers-grid" style={{ display: 'grid', gap: 8 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '56px 1fr 1fr', gap: 8, fontSize: 12, color: '#595959' }}>
            <span>{t('yearlyPlan.wizard.howMuch.year')}</span>
            <span>{quantityLabel}</span>
            <span>{t('yearlyPlan.wizard.howMuch.budget')}</span>
          </div>
          {state.years.map((y) => {
            const row = state.yearValues[y] ?? { quantity: '', budget: '' };
            return (
              <div key={y} style={{ display: 'grid', gridTemplateColumns: '56px 1fr 1fr', gap: 8, alignItems: 'center' }}>
                <span>{formatNumber(y)}</span>
                <Input
                  inputMode="decimal"
                  data-testid={`grid-quantity-${y}`}
                  aria-label={`${t('yearlyPlan.wizard.howMuch.year')} ${formatNumber(y)}: ${quantityLabel}`}
                  value={row.quantity}
                  onChange={(e) => dispatch({ type: 'setYearValue', year: y, quantity: e.target.value })}
                />
                <Input
                  inputMode="decimal"
                  data-testid={`grid-budget-${y}`}
                  aria-label={`${t('yearlyPlan.wizard.howMuch.year')} ${formatNumber(y)}: ${t('yearlyPlan.wizard.howMuch.budget')}`}
                  value={row.budget}
                  onChange={(e) => dispatch({ type: 'setYearValue', year: y, budget: e.target.value })}
                />
              </div>
            );
          })}
        </div>
      )}

      {valid && (
        <div data-testid="numbers-total" style={{ marginTop: 12, fontWeight: 600 }}>
          {t('yearlyPlan.wizard.howMuch.total', { years: formatYears(state.years, formatNumber), total: formatNumber(total) })}
        </div>
      )}
      {anyZeroBudget && (
        <div data-testid="numbers-zero" style={{ marginTop: 6, fontSize: 13, color: '#595959' }}>
          {t('yearlyPlan.wizard.howMuch.zeroNote')}
        </div>
      )}
      {touched && !valid && (
        <div role="alert" data-testid="numbers-invalid" style={{ marginTop: 8, fontSize: 13, color: '#cf1322' }}>
          {t('yearlyPlan.wizard.howMuch.invalid')}
        </div>
      )}
      {unusual && (
        <Alert
          data-testid="numbers-unusual"
          type="warning"
          showIcon
          style={{ marginTop: 10 }}
          message={t('yearlyPlan.wizard.howMuch.unusual', { amount: formatNumber(peak) })}
        />
      )}
    </StepFrame>
  );
};

// ------------------------------------------------------------------------------------------------ NAME
export const NameStep: React.FC<StepProps> = ({ state, dispatch }) => {
  const t = useT();
  return (
    <StepFrame testId="wizard-name" question={t('yearlyPlan.wizard.name.question')} help={t('yearlyPlan.wizard.name.help')}>
      <Input
        size="large"
        data-testid="name-input"
        value={state.name}
        placeholder={state.activity?.name}
        onChange={(e) => dispatch({ type: 'setName', name: e.target.value })}
      />
    </StepFrame>
  );
};

// --------------------------------------------------------------------------------------------- CONFIRM
export const ConfirmStep: React.FC<StepProps & { failedNote?: string | null }> = ({ state, dispatch: _dispatch, failedNote }) => {
  const t = useT();
  const activity = state.activity as CatalogueActivity;
  const amounts = yearAmounts(state, parse);
  const total = totalBudgetOf(amounts);
  const yearlyAll = amounts.length > 0 && amounts.every((a) => a.budget === amounts[0].budget);
  const parts: string[] = [state.name.trim() || activity.name];

  if (state.existing) {
    parts.push(t('yearlyPlan.wizard.confirm.existing'));
    if (state.places.length > 0) parts.push(t('yearlyPlan.wizard.confirm.places', { n: formatNumber(state.places.length) }));
  } else {
    parts.push(t('yearlyPlan.wizard.confirm.years', { years: formatYears(state.years, formatNumber) }));
    if (activity.requiresMap) {
      if (state.where === 'map') parts.push(t('yearlyPlan.wizard.confirm.places', { n: formatNumber(state.places.length) }));
      else if (state.where === 'whole') parts.push(t('yearlyPlan.wizard.confirm.whole'));
      else parts.push(t('yearlyPlan.wizard.confirm.later'));
    }
    parts.push(
      state.same || yearlyAll
        ? t('yearlyPlan.wizard.confirm.moneySame', { yearly: formatNumber(amounts[0]?.budget ?? 0), total: formatNumber(total) })
        : t('yearlyPlan.wizard.confirm.moneyVaries', { total: formatNumber(total) }),
    );
  }
  return (
    <StepFrame testId="wizard-confirm" question={t('yearlyPlan.wizard.confirm.question')}>
      <div data-testid="confirm-sentence" style={{ fontSize: 15, lineHeight: 1.6, padding: '10px 12px', background: '#f6ffed', border: '1px solid #b7eb8f', borderRadius: 8 }}>
        {parts.join(' · ')}
      </div>
      {failedNote && (
        <Alert data-testid="confirm-failed" type="error" showIcon style={{ marginTop: 10 }} message={failedNote} />
      )}
    </StepFrame>
  );
};
