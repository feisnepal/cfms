/**
 * CBASensitivityView — what-if sliders over a computed scenario
 * (CBA_MODULE_PLAN.md P6). Scales the year-wise benefit / cost totals and the
 * discount rate and shows the live NPV / IRR / B-C, recomputed client-side
 * (`lib/cbaMath`). Only the discount-rate slider maps to a real scenario field,
 * so "Apply discount rate" is the one persisting action; the ± multipliers are
 * exploration only.
 *
 * Per-source price sliders (timber / fuelwood / carbon) need the item-level
 * series rebuild — a later refinement; the aggregate benefit multiplier stands
 * in for a uniform price / harvest change for now.
 */
import React, { useMemo, useState } from 'react';
import { Slider, InputNumber, Button, Space, message } from 'antd';
import { useT } from '../../i18n/hooks';
import { cbaApi, type CbaScenario } from '../../services/api';
import { npv, irr, bcRatio } from '../../lib/cbaMath';

interface Props {
  calculationId: string;
  scenario: CbaScenario;
  onChanged: () => void;
}

const money = (v: number): string =>
  `₹${Math.round(v).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;

export const CBASensitivityView: React.FC<Props> = ({
  calculationId,
  scenario,
  onChanged,
}) => {
  const t = useT();
  const rows = scenario.result?.cash_flow_data ?? [];
  const baseRate = Number(scenario.discount_rate);

  const [benefitPct, setBenefitPct] = useState(0);
  const [costPct, setCostPct] = useState(0);
  const [rate, setRate] = useState(baseRate);
  const [applying, setApplying] = useState(false);

  const preview = useMemo(() => {
    const costs = rows.map((r) => r.cost * (1 + costPct / 100));
    const benefits = rows.map((r) => r.benefit * (1 + benefitPct / 100));
    const net = benefits.map((b, i) => b - costs[i]);
    return {
      npv: npv(net, rate),
      irr: irr(net),
      bc: bcRatio(costs, benefits, rate),
    };
  }, [rows, benefitPct, costPct, rate]);

  if (rows.length === 0) {
    return null;
  }

  const S: React.FC<{
    label: string;
    value: number;
    min: number;
    max: number;
    step?: number;
    suffix: string;
    onChange: (v: number) => void;
  }> = ({ label, value, min, max, step = 1, suffix, onChange }) => (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <span style={{ width: 150, fontSize: 13 }}>{label}</span>
      <Slider
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(v) => onChange(v as number)}
        style={{ flex: 1, minWidth: 180 }}
      />
      <span style={{ width: 64, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
        {value}
        {suffix}
      </span>
    </div>
  );

  const applyRate = async () => {
    setApplying(true);
    try {
      await cbaApi.updateScenario(calculationId, scenario.id, { discount_rate: rate });
      await cbaApi.compute(scenario.id);
      message.success(t('cba.sensitivity.applied'));
      onChanged();
    } catch {
      message.error(t('common.saveFailed'));
    } finally {
      setApplying(false);
    }
  };

  return (
    <div style={{ marginTop: 20, maxWidth: 640 }}>
      <h4 style={{ margin: '0 0 8px' }}>{t('cba.sensitivity.heading')}</h4>
      <Space direction="vertical" size={8} style={{ width: '100%' }}>
        <S
          label={t('cba.sensitivity.benefit')}
          value={benefitPct}
          min={-50}
          max={50}
          suffix="%"
          onChange={setBenefitPct}
        />
        <S
          label={t('cba.sensitivity.cost')}
          value={costPct}
          min={-50}
          max={50}
          suffix="%"
          onChange={setCostPct}
        />
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ width: 150, fontSize: 13 }}>{t('cba.editor.discountRate')}</span>
          <Slider
            min={1}
            max={25}
            step={0.5}
            value={rate}
            onChange={(v) => setRate(v as number)}
            style={{ flex: 1, minWidth: 180 }}
          />
          <InputNumber
            size="small"
            min={0}
            max={100}
            step={0.5}
            addonAfter="%"
            value={rate}
            onChange={(v) => setRate(Number(v ?? baseRate))}
            style={{ width: 96 }}
          />
        </div>
      </Space>

      <div
        style={{
          marginTop: 12,
          padding: 12,
          background: '#fafafa',
          border: '1px solid #f0f0f0',
          borderRadius: 8,
        }}
      >
        <Space size={28} wrap>
          <span>
            {t('cba.metric.npv')}: <b>{money(preview.npv)}</b>
          </span>
          <span>
            {t('cba.metric.irr')}:{' '}
            <b>{preview.irr == null ? t('common.notAvailable') : `${(preview.irr * 100).toFixed(1)}%`}</b>
          </span>
          <span>
            {t('cba.metric.bcRatio')}:{' '}
            <b>{preview.bc == null ? t('common.notAvailable') : preview.bc.toFixed(2)}</b>
          </span>
        </Space>
      </div>

      <Button
        size="small"
        style={{ marginTop: 10 }}
        loading={applying}
        disabled={rate === baseRate}
        onClick={applyRate}
      >
        {t('cba.sensitivity.applyRate')}
      </Button>
      <div style={{ fontSize: 11, color: '#999', marginTop: 4 }}>
        {t('cba.sensitivity.note')}
      </div>
    </div>
  );
};

export default CBASensitivityView;
